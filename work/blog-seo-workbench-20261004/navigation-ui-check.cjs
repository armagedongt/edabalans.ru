const {createRequire} = require('node:module');
const {chromium} = createRequire(process.env.NODE_PATH + '/package.json')('playwright');
const fs = require('node:fs');
const assert = require('node:assert/strict');
(async () => {
  const out = process.argv[2];
  fs.mkdirSync(out, {recursive: false});
  const browser = await chromium.launch({headless: true});
  const rows = [];
  for (const width of [360,430,768,900,901,1360,1361,1440]) {
    for (const theme of ['light','dark']) {
      const page = await browser.newPage({viewport: {width, height: 900}, deviceScaleFactor: 1, reducedMotion: 'reduce'});
      const errors = [];
      page.on('pageerror', e => errors.push(e.message));
      await page.route('https://edabalans.ru/**', r => r.fulfill({body: '', contentType: 'text/javascript'}));
      await page.goto(process.argv[3] || 'http://127.0.0.1:8784/blog/articles/pochemu-yapontsy-hudye-a-ty-net');
      if (await page.locator('#reader-visitor').count()) await page.locator('#reader-visitor').selectOption('subscribed');
      await page.evaluate(t => document.documentElement.dataset.theme = t, theme);
      await page.evaluate(() => window.scrollTo(0, 800));
      await page.waitForFunction(() => document.querySelector('.reader-bottom').classList.contains('reader-scrolled'));
      assert.equal(await page.locator('#reader-menu').isVisible(), width <= 900);
      assert.equal(await page.locator('.reader-sidebar').isVisible(), width > 1360);
      const centered = await page.locator('#reader-top').evaluate(b => {
        const a=b.getBoundingClientRect(), s=b.querySelector('svg').getBoundingClientRect();
        return Math.abs((a.top+a.bottom-s.top-s.bottom)/2)<.1 && Math.abs((a.left+a.right-s.left-s.right)/2)<.1;
      });
      assert.ok(centered);
      await page.locator('.reader-bottom').screenshot({path: `${out}/${width}-${theme}-buttons.png`});
      await page.screenshot({path: `${out}/${width}-${theme}-context.png`});
      if (width > 1360) await page.locator('.reader-sidebar').screenshot({path: `${out}/${width}-${theme}-sidebar.png`});
      const firstAnchor = await page.locator('#reader-sheet ol a').first().getAttribute('href');
      const thirdAnchor = await page.locator('#reader-sheet ol a').nth(2).getAttribute('href');
      await page.evaluate(hash => document.getElementById(hash.slice(1)).scrollIntoView(), thirdAnchor);
      await page.waitForFunction(hash => document.querySelector('.reader-sidebar a[aria-current]')?.getAttribute('href') === hash, thirdAnchor);
      await page.evaluate(hash => document.getElementById(hash.slice(1)).scrollIntoView(), firstAnchor);
      await page.waitForFunction(hash => document.querySelector('.reader-sidebar a[aria-current]')?.getAttribute('href') === hash, firstAnchor);
      if (width <= 900) {
        await page.locator('#reader-menu').click();
        assert.ok(await page.locator('#reader-sheet').evaluate(s => s.open && s.matches(':modal')));
        const labels = await page.locator('.reader-site-menu > a, .reader-site-menu summary').allTextContents();
        assert.deepEqual(labels, ['Мастер-класс','Бесплатный интенсив','Личный кабинет','Контакты']);
        const menuProductLinks = await page.locator('.reader-site-menu > a').evaluateAll(a => a.map(x => x.href));
        const headerProductLinks = await page.locator('#public-blog-nav > a').evaluateAll(a => a.slice(1).map(x => x.href));
        assert.deepEqual(menuProductLinks, headerProductLinks);
        const menuContactLinks = await page.locator('#reader-sheet .reader-account').nth(1).locator('a').evaluateAll(a => a.map(x => x.href));
        const headerContactLinks = await page.locator('.nav-contact-panel a').evaluateAll(a => a.map(x => x.href));
        assert.deepEqual(menuContactLinks, headerContactLinks);
        const accountLinks = await page.locator('#reader-sheet .reader-account').first().locator('a').evaluateAll(a => a.map(x => x.href));
        assert.deepEqual(accountLinks, ['https://похудение-это-есть.рф/lk','https://похудение-это-есть.рф/lk?mode=register'].map(x => new URL(x).href));
        const rect = await page.locator('#reader-sheet').boundingBox();
        assert.equal(rect.width, width); assert.equal(rect.height, 900);
        await page.locator('#reader-sheet').screenshot({path: `${out}/${width}-${theme}-sheet.png`});
        const before = await page.evaluate(() => scrollY);
        await page.mouse.move(5, 300); await page.mouse.wheel(0, 500);
        assert.equal(await page.evaluate(() => scrollY), before);
        await page.locator('#reader-sheet').evaluate(s => s.scrollTop = 0);
        await page.locator('#reader-sheet .reader-account summary').first().click();
        await page.locator('#reader-sheet .reader-account summary').nth(1).click();
        assert.equal(await page.locator('#reader-sheet .reader-account').nth(1).locator('a').count(), 4);
        assert.equal(await page.locator('.reader-account').first().locator('a').count(), 2);
        await page.locator('#reader-sheet').screenshot({path: `${out}/${width}-${theme}-expanded.png`});
        await page.keyboard.press('Escape');
        assert.equal(await page.locator('#reader-sheet').evaluate(s => s.open), false);
        assert.equal(await page.evaluate(() => document.activeElement.id), 'reader-menu');
        await page.locator('#reader-menu').click();
        await page.locator('#reader-sheet .reader-close').click();
        assert.equal(await page.locator('#reader-sheet').evaluate(s => s.open), false);
        assert.equal(await page.evaluate(() => document.activeElement.id), 'reader-menu');
        await page.locator('#reader-menu').click();
        await page.locator('#reader-sheet ol a').nth(2).click();
        assert.equal(await page.locator('#reader-sheet').evaluate(s => s.open), false);
        assert.ok(await page.evaluate(() => location.hash.length > 1));
      }
      await page.locator('#reader-top').click();
      await page.waitForFunction(() => scrollY === 0);
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
      assert.deepEqual(errors, []);
      rows.push({width, theme, menu: width<=900, sidebar: width>1360, passed:true});
      await page.close();
    }
  }
  await browser.close();
  fs.writeFileSync(`${out}/results.json`, JSON.stringify(rows, null, 2));
  console.log(JSON.stringify(rows));
})().catch(e => { console.error(e); process.exit(1); });
