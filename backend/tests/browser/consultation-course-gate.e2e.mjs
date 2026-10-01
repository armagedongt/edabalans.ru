import assert from 'node:assert/strict';
import {readFile, mkdir} from 'node:fs/promises';

const {chromium} = await import(process.env.PLAYWRIGHT_MODULE_URL || 'playwright');
const staticRoot = new URL('../../app/static/', import.meta.url);
const fragment = (await readFile(new URL('apps/account.html', staticRoot), 'utf8'))
  .replace(/<link\b[^>]*>/g, '')
  .replace(/<script\b[^>]*\bsrc=[^>]*><\/script>/g, '');
const css = await readFile(new URL('account-visual.css', staticRoot), 'utf8');
const browser = await chromium.launch({headless: true});
try {
  for (const direct of [false, true]) {
    const page = await browser.newPage({viewport: {width: 390, height: 844}});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.route('http://fixture.test/**', route => route.fulfill({contentType: 'text/html', body: '<html></html>'}));
    await page.goto('http://fixture.test/lk' + (direct ? '?open=calories:first' : ''));
    const data = {email: 'gate@example.test', state: 'ready', legal: {required: false}, applications: [], courses: [
      {code: 'calories', product_code: 'calories', title: 'Калорийный курс', summary: 'Описание курса', owned: true, ready: true, state: 'consultation_locked', app: null},
    ]};
    const setup = `<script>
      window.EdabalansIdentity={email:'gate@example.test'};
      window.EdabalansAccountPayload=${JSON.stringify(data)};
      window.EdabalansEmbed={waitUntilReady:function(){},load:function(){throw new Error('Locked course loaded')}};
      window.fetch=function(){return Promise.resolve(new Response(JSON.stringify({action:'locked',reason_code:'consultation_required',title:'Курс откроется после консультации',explanation:'Напишите мне — после консультации я открою вам курс.'}),{status:200}))};
    </script>`;
    await page.setContent(`<meta charset="utf-8"><style>${css}</style>${setup}${fragment}`);
    const contact = page.getByRole('link', {name: 'Напишите мне', exact: true});
    await contact.waitFor();
    assert.equal(await contact.getAttribute('href'), 'https://t.me/FitnessSergey');
    assert.equal(await page.locator('[data-app="calories-course"]').count(), 0);
    assert.equal(await page.locator('[data-offer-product]').count(), 0);
    for (const width of [390, 1440]) {
      await page.setViewportSize({width, height: 900});
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
      if (process.env.QA_OUT) {
        await mkdir(process.env.QA_OUT, {recursive: true});
        await page.screenshot({path: `${process.env.QA_OUT}/gate-${direct ? 'link' : 'card'}-${width}.png`});
      }
    }
    assert.deepEqual(errors, []);
    await page.close();
  }
  console.log('Consultation card and direct-link gate: passed at 390/1440px');
} finally {
  await browser.close();
}
