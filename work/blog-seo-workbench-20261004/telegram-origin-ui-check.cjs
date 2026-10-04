const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const {createRequire} = require('node:module');
const {chromium} = createRequire(process.env.NODE_PATH + '/package.json')('playwright');
(async () => {
  const out = process.argv[2], root = process.cwd(), rows = [];
  const browser = await chromium.launch({headless: true});
  try {
    for (const width of [360,430,768,1440]) for (const theme of ['light','dark']) {
      const page = await browser.newPage({viewport: {width,height:900}, reducedMotion:'reduce'});
      const errors = [];
      page.on('pageerror', e => errors.push(e.message));
      await page.route('**/*', async route => {
        const url = new URL(route.request().url());
        if (url.hostname !== 'fixture.test') return route.fulfill({body:'', contentType:'text/javascript'});
        const file = url.pathname === '/article' ? path.join(out,'article.html') :
          url.pathname.startsWith('/blog/assets/') ? path.join(root,'backend/app/static/blog/assets',url.pathname.slice('/blog/assets/'.length)) :
          url.pathname.startsWith('/assets/') ? path.join(root,'backend/app/static',url.pathname.slice('/assets/'.length)) :
          url.pathname.startsWith('/media/') ? path.join(root,'content/blog/media',url.pathname.slice('/media/'.length)) : null;
        if (!file || !fs.existsSync(file)) return route.fulfill({status:404,body:''});
        const ext = path.extname(file);
        const types = {'.css':'text/css','.js':'text/javascript','.html':'text/html','.webp':'image/webp','.woff2':'font/woff2'};
        return route.fulfill({body:fs.readFileSync(file),contentType:types[ext] || 'application/octet-stream'});
      });
      await page.goto('http://fixture.test/article');
      await page.evaluate(t => document.documentElement.dataset.theme = t, theme);
      const plaque = page.locator('.reader-telegram-source');
      await plaque.scrollIntoViewIfNeeded();
      await page.evaluate(() => document.fonts.ready);
      assert.equal(await plaque.count(),1);
      assert.equal(await plaque.locator('a').count(),3);
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
      assert.deepEqual(errors,[]);
      await plaque.screenshot({path:path.join(out,`${width}-${theme}-plaque.png`)});
      await page.screenshot({path:path.join(out,`${width}-${theme}-context.png`)});
      rows.push({width,theme,overflow:false,pageErrors:errors});
      await page.close();
    }
    fs.writeFileSync(path.join(out,'browser.json'), JSON.stringify(rows,null,2));
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode=1; });
