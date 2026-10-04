// Verify the new server-rendered author UI without unrelated client animations.
const { createRequire } = require('node:module');
const { mkdirSync, writeFileSync } = require('node:fs');
const { chromium } = createRequire(process.env.NODE_PATH + '/package.json')('playwright');
const out = process.argv[2];
mkdirSync(out);
(async () => {
  const browser = await chromium.launch({ headless: true });
  const rows = [];
  for (const width of [360, 430, 619, 621, 639, 641, 768, 1440]) {
    const page = await browser.newPage({ viewport: { width, height: 1000 }, javaScriptEnabled: false });
    await page.goto('http://127.0.0.1:8784/blog/articles/pochemu-yapontsy-hudye-a-ty-net');
    const avatar = await page.locator('.author-byline img').boundingBox();
    const breadcrumb = await page.locator('.breadcrumbs').boundingBox();
    const imageLoaded = await page.locator('.author-byline img').evaluate(img => img.complete && img.naturalWidth > 0);
    const dimensions = await page.evaluate(() => ({ viewport: innerWidth, document: document.documentElement.scrollWidth }));
    if (!imageLoaded || avatar.width !== 32 || avatar.height !== 32 || breadcrumb.y < 0 || dimensions.document > width) throw Error('Author UI check failed at ' + width);
    await page.screenshot({ path: out + '/article-' + width + '.png' });
    rows.push({ width, avatar, breadcrumb, dimensions, imageLoaded });
    await page.close();
  }
  await browser.close();
  writeFileSync(out + '/checks.json', JSON.stringify(rows, null, 2));
  console.log('8 widths PASS: visible breadcrumbs, 32px loaded avatar, no document overflow; no JavaScript required');
})().catch(error => { console.error(error); process.exitCode = 1; });
