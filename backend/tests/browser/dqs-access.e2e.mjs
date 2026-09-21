import assert from 'node:assert/strict';
const {chromium} = await import(process.env.PLAYWRIGHT_MODULE_URL || 'playwright');

const origin = process.env.QA_BASE_URL || 'http://127.0.0.1:8798';
const accountToken = process.env.QA_ACCOUNT_TOKEN;
assert(/^(localhost|127\.0\.0\.1)$/.test(new URL(origin).hostname), 'Use a synthetic local fixture');
assert(accountToken, 'QA_ACCOUNT_TOKEN must belong to the synthetic local fixture');

const browser = await chromium.launch({headless:true,args:['--disable-gpu']});
const context = await browser.newContext({viewport:{width:1440,height:1000}});
await context.addCookies([{
  name:'edabalans_account_session',value:accountToken,
  url:origin,httpOnly:true,secure:false,sameSite:'Lax',
}]);
await context.grantPermissions(['clipboard-read','clipboard-write'], {origin});
await context.route('**/api/**', async route => {
  const requested = new URL(route.request().url());
  if (requested.origin === origin) return route.continue();
  const local = new URL(requested.pathname + requested.search, origin).toString();
  const response = await route.fetch({url:local});
  return route.fulfill({response});
});

const page = await context.newPage();
try {
  await page.goto(origin+'/lk?course_day=4&course_material=day-04-dqs');
  await page.locator('#dqs-open-app').waitFor();
  assert.deepEqual(
    await page.locator('.dqs-material-buttons > *').allTextContents(),
    ['Скачать печатный вариант', 'Открыть приложение'],
  );
  assert.equal(await page.locator('#dqs-copy-link').count(), 0);
  assert.equal(
    await page.locator('#dqs-print').getAttribute('href'),
    'https://storage.yandexcloud.net/workcloud1/table_images/DQS_for_print.png',
  );
  assert.match(
    await page.locator('.dqs-material-note').textContent(),
    /Ссылка продублируется вам в подключённый мессенджер/,
  );

  let releaseReveal;
  let revealRequested = false;
  const revealGate = new Promise(resolve => { releaseReveal = resolve; });
  await page.route(origin+'/api/masterclass/apps/dqs/reveal', async route => {
    revealRequested = true;
    await revealGate;
    await route.fulfill({json:{ok:true,app_url:'https://edabalans.ru/dqs',telegram_link_status:'queued'}});
  });
  await page.route(origin+'/api/masterclass/events', route => route.fulfill({json:{ok:true,created:true}}));

  await page.locator('#dqs-open-app').click();
  await page.waitForFunction(() => document.querySelector('#dqs-open-app')?.disabled === true);
  assert(revealRequested,'DQS click must request the guarded reveal');
  assert(await page.locator('#dqs-panel').isHidden(),'DQS must stay closed until reveal succeeds');
  releaseReveal();
  await page.locator('#dqs-panel').waitFor({state:'visible'});
  assert.equal(
    await page.locator('#dqs-material-status').textContent(),
    'Постоянная ссылка отправлена в подключённый мессенджер. Закрепите сообщение, чтобы DQS всегда был под рукой.',
  );
  console.log('PASS: DQS print action and guarded reveal-before-open interaction.');
} finally {
  await browser.close();
}
