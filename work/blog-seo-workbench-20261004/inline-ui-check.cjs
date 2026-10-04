const { createRequire } = require('node:module');
const { mkdirSync, writeFileSync } = require('node:fs');
const { chromium } = createRequire(process.env.NODE_PATH + '/package.json')('playwright');
const out = process.argv[2];
mkdirSync(out);
(async () => {
  const browser = await chromium.launch({ headless: true });
  const rows = [];
  for (const width of [360, 430, 768, 1440]) for (const theme of ['light', 'dark']) {
    for (const source of [true, false]) {
      const page = await browser.newPage({ viewport: { width, height: 900 }, deviceScaleFactor: 1 });
      const origin = source ? 'http://127.0.0.1:8771/articles/' : 'http://127.0.0.1:8784/blog/articles/';
      await page.goto(origin + 'pochemu-yapontsy-hudye-a-ty-net');
      await page.evaluate(value => { document.documentElement.dataset.theme = value; }, theme);
      if (source) await page.selectOption('#reader-visitor', 'subscribed');
      const card = page.locator('.reader-related').first();
      await card.scrollIntoViewIfNeeded();
      await page.evaluate(() => document.fonts.ready);
      const dimensions = await card.boundingBox();
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
      if (overflow || !dimensions || dimensions.width > width) throw Error('Inline overflow');
      const file = `${out}/${source ? 'source' : 'actual'}-${width}-${theme}.png`;
      await card.screenshot({ path: file });
      await page.screenshot({ path: file.replace('.png', '-context.png'), clip: { x: dimensions.x, y: Math.max(0, dimensions.y - 90), width: dimensions.width, height: dimensions.height + 180 } });
      const href = await card.locator('a').getAttribute('href');
      if (href !== '/articles/chto-vy-ne-ponimaete-o-formirovanii-privychek') throw Error('Wrong target');
      const before = await card.locator('.reader-related-arrow').evaluate(el => getComputedStyle(el).transform);
      await card.hover();
      await page.locator('body').evaluate(() => new Promise(resolve => setTimeout(resolve, 200)));
      const after = await card.locator('.reader-related-arrow').evaluate(el => getComputedStyle(el).transform);
      if (after !== 'matrix(1, 0, 0, 1, 2, -2)') throw Error('Wrong hover');
      if (!source) {
        await page.emulateMedia({ reducedMotion: 'reduce' });
        const reduced = await card.locator('.reader-related-arrow').evaluate(el => getComputedStyle(el).transform);
        if (reduced !== 'none') throw Error('Reduced-motion failure');
      }
      rows.push({ width, theme, source, file, dimensions, overflow, href, before, after });
      await page.close();
    }
  }
  await browser.close();
  writeFileSync(out + '/checks.json', JSON.stringify(rows, null, 2));
  console.log(JSON.stringify(rows.map(({ width, theme, source, dimensions }) => ({ width, theme, source, dimensions }))));
})().catch(error => { console.error(error); process.exitCode = 1; });
