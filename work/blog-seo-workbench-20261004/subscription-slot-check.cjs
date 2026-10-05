// Run against an isolated local app. NODE_PATH points to the installed Playwright package.
const {createRequire} = require('node:module');
const {chromium} = createRequire(process.env.NODE_PATH+'/package.json')('./');
const assert = require('node:assert/strict');
const base = process.env.BLOG_CHECK_URL || 'http://127.0.0.1:8789';
const path = '/blog/articles/pochemu-yapontsy-hudye-a-ty-net';
const anchor = 'принцип-no4-контролировать-окружение';
(async () => {
  const browser = await chromium.launch({channel:'msedge', headless:true});
  try {
    for (const width of [360,1440]) {
      for (const missing of [false,true]) {
        const context = await browser.newContext({viewport:{width,height:900}});
        const page = await context.newPage();
        const errors=[];
        page.on('pageerror', e=>errors.push(e.message));
        await page.route('https://edabalans.ru/**', async route=> {
          const url=new URL(route.request().url());
          const response=await context.request.get(base+url.pathname+url.search);
          await route.fulfill({response});
        });
        if (missing) await page.route(base+path, async route=> {
          const response=await route.fetch();
          const html=(await response.text()).replace('data-subscription-before-heading="'+anchor+'"','data-subscription-before-heading="missing-heading"');
          await route.fulfill({response,body:html});
        });
        const ready=page.waitForResponse(r=>r.url().endsWith('/blog/reader/context'));
        await page.goto(base+path,{waitUntil:'load'});
        await ready;
        if (!missing) {
          await page.waitForSelector('#reader-channel-inline');
          assert.equal(await page.locator('#reader-channel-inline').count(),1);
          assert.equal(await page.locator('#reader-channel-inline').evaluate(n=>n.nextElementSibling.id),anchor);
        }
        await page.evaluate(()=>window.scrollTo(0,document.body.scrollHeight));
        await page.waitForSelector('#reader-popup[open]');
        if (missing) assert.equal(await page.locator('#reader-channel-inline').count(),0);
        await page.keyboard.press('Escape');
        await page.waitForSelector('#reader-popup[open]',{state:'hidden'});
        assert.deepEqual(errors,[]);
        console.log(JSON.stringify({width,missing,inline:!missing,popup:true,errors:0}));
        await context.close();
      }
    }
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
