import assert from 'node:assert/strict';
import {readFile, mkdir, writeFile} from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';

const {chromium} = await import(process.env.PLAYWRIGHT_MODULE_URL ||
  pathToFileURL(path.join(process.env.CODEX_NODE_MODULES, 'playwright/index.mjs')).href);
const staticRoot = new URL('../../app/static/', import.meta.url);
const appHtml = await readFile(new URL('apps/strength.html', staticRoot), 'utf8');
const guide = JSON.parse(await readFile(new URL('../../app/strength_exercise_guides.json', import.meta.url), 'utf8'))[0];
const content = JSON.parse(await readFile(new URL('strength-tutorial/content.json', staticRoot), 'utf8'));
const expectedImageCounts = [1,1,2,2,2,2,4];
const output = process.env.QA_OUT;
assert(output, 'Set QA_OUT for browser evidence');
await mkdir(output, {recursive:true});
const base = 'http://127.0.0.1:8838';
const workout = {
  version:1, selected_type:1,
  workout_types:[{workout_type:1, title:'Верх', active:true, sort_order:1}],
  exercise_catalog:[{exercise_id:guide.code, exercise_name:guide.name, short_name:guide.short_name,
    full_name:guide.full_name, source:'base', active:true, sort_order:1}],
  sessions:[{session_id:'tutorial-test', workout_type:1, session_number:1, date:'2026-10-22'}],
  session_exercises:[{session_id:'tutorial-test', exercise_id:guide.code, exercise_name:guide.name, sort_order:1}],
  sets:[{session_id:'tutorial-test', exercise_id:guide.code, set_number:1, role:'work',
    plan_weight:20, plan_reps:10, fact_weight:20, fact_reps:10, rpe:8}]
};
const types = {'.html':'text/html; charset=utf-8', '.css':'text/css', '.js':'text/javascript',
  '.json':'application/json', '.png':'image/png', '.woff2':'font/woff2'};
const browser = await chromium.launch(), evidence = [];
try {
  for (const width of [360,380,381,430,768,1440]) {
    const height = width <= 381 ? 780 : 900;
    const page = await browser.newPage({viewport:{width,height}}), errors = [], writes = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.route(base + '/**', async route => {
      const url = new URL(route.request().url());
      if (url.pathname === '/tutorial-app') return route.fulfill({contentType:'text/html; charset=utf-8',
        body:'<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1"><script>window.EdabalansIdentity={source:"native",email:"synthetic@example.test"};' +
          'window.EdabalansAppContext={accountUrl:"/lk"};</script>' + appHtml});
      if (url.pathname === '/api/apps/strength') {
        const request = route.request();
        const data = request.method() === 'POST' ? request.postDataJSON() : Object.fromEntries(url.searchParams);
        if (!['getWorkout', 'openUser'].includes(data.action)) writes.push(data.action);
        return route.fulfill({json:{ok:true, version:1, user:{user_id:'synthetic', email:'synthetic@example.test'},
          ...(data.action === 'getWorkout' ? {workout} : {})}});
      }
      if (url.pathname.startsWith('/assets/')) {
        const relative = url.pathname.slice('/assets/'.length);
        if (relative.split('/').includes('..')) return route.fulfill({status:400});
        try { return route.fulfill({body:await readFile(new URL(relative, staticRoot)),
          contentType:types[path.extname(relative)] || 'application/octet-stream'}); }
        catch { return route.fulfill({status:404}); }
      }
      return route.fulfill({status:404});
    });
    await page.goto(base + '/tutorial-app');
    await page.locator('article').first().waitFor();
    const before = await page.locator('article [data-field="planWeight"]').first().inputValue();
    await page.getByRole('button', {name:'Как пользоваться', exact:true}).click();
    const iframe = page.frameLocator('.st-tutorial-frame iframe');
    await iframe.locator('#lesson-title').filter({hasText:content.screens[0].title}).waitFor();
    assert.equal(await iframe.locator('select').count(), 0);
    assert(await iframe.locator('#close-tutorial').isVisible());
    for (let index = 0; index < content.screens.length; index++) {
      assert.equal(await iframe.locator('#counter').textContent(), `${index + 1} / ${content.screens.length}`);
      assert.equal(await iframe.locator('h1').textContent(), content.screens[index].title);
      assert.equal(await iframe.locator('#previous-top').isDisabled(), index === 0);
      assert.equal(await iframe.locator('#previous').isDisabled(), index === 0);
      assert.equal(await iframe.locator('#next-top').isDisabled(), index === content.screens.length - 1);
      assert.equal(await iframe.locator('#next').isDisabled(), index === content.screens.length - 1);
      assert.equal(await iframe.locator('#screenshots img').count(), expectedImageCounts[index]);
      await iframe.locator('#screenshots img').evaluateAll(images => Promise.all(images.map(image => image.decode())));
      if (index === 0 || index === 2) assert(await iframe.locator('#lesson-lead').isVisible());
      if (index === 5) assert.equal(await iframe.locator('#lesson-text li').nth(1).locator('p').count(), 3);
      const metrics = await iframe.locator('html').evaluate(el => ({width:innerWidth, height:innerHeight,
        scrollWidth:el.scrollWidth, scrollHeight:el.scrollHeight,
        minDpr:Math.min(...[...document.querySelectorAll('#screenshots img')].map(img => img.naturalWidth / img.getBoundingClientRect().width))}));
      assert(metrics.scrollWidth <= metrics.width, 'No horizontal overflow');
      assert(metrics.minDpr >= 2.99);
      await page.screenshot({path:path.join(output, `${width}-${index + 1}.png`)});
      if (metrics.scrollHeight > metrics.height) {
        await iframe.locator('body').evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
        await page.screenshot({path:path.join(output, `${width}-${index + 1}-bottom.png`)});
      }
      evidence.push({width, index:index + 1, ...metrics});
      if (index < content.screens.length - 1) {
        await iframe.locator(index % 2 ? '#next' : '#next-top').click();
      }
    }
    for (let index = content.screens.length - 2; index >= 0; index--) {
      await iframe.locator(index % 2 ? '#previous-top' : '#previous').click();
      assert.equal(await iframe.locator('h1').textContent(), content.screens[index].title);
    }
    await iframe.locator('#close-tutorial').click();
    await page.locator('.st-tutorial-frame').waitFor({state:'detached'});
    assert.equal(await page.locator('article [data-field="planWeight"]').first().inputValue(), before);
    await page.waitForFunction(() => document.activeElement?.matches('.st-help'));
    assert(await page.getByRole('button', {name:'Как пользоваться', exact:true}).evaluate(el => el === document.activeElement));
    await page.getByRole('button', {name:'Как пользоваться', exact:true}).click();
    await page.locator('.st-tutorial-frame').waitFor();
    await page.keyboard.press('Escape');
    await page.locator('.st-tutorial-frame').waitFor({state:'detached'});
    await page.getByRole('button', {name:'Как пользоваться', exact:true}).click();
    await iframe.locator('#next-top').click();
    await page.keyboard.press('Escape');
    await page.locator('.st-tutorial-frame').waitFor({state:'detached'});
    await page.getByRole('button', {name:'Как пользоваться', exact:true}).click();
    await iframe.locator('#next-top').click();
    await page.goBack();
    await page.locator('.st-tutorial-frame').waitFor({state:'detached'});
    if (width === 430) {
      await page.route(base + '/assets/strength-tutorial/content.json*', route => route.fulfill({status:503}));
      await page.getByRole('button', {name:'Как пользоваться', exact:true}).click();
      await iframe.locator('#tutorial-error').filter({hasText:'Не удалось загрузить'}).waitFor();
      assert(await iframe.locator('#next-top').isDisabled());
      await iframe.locator('#close-tutorial').click();
      await page.locator('.st-tutorial-frame').waitFor({state:'detached'});
    }
    assert.equal(await page.evaluate(() => document.body.style.overflow), '');
    assert.deepEqual(writes, [], 'Reading help never writes workouts or sends messages');
    assert.deepEqual(errors, []);
    await page.close();
  }
  await writeFile(path.join(output, 'report.json'), JSON.stringify(evidence, null, 2));
  console.log(JSON.stringify({cases:evidence.length, widths:6, writes:0}));
} finally { await browser.close(); }
