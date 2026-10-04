const { createRequire } = require('node:module');
const { mkdirSync, readFileSync, statSync, writeFileSync } = require('node:fs');
const { chromium } = createRequire(process.env.NODE_PATH + '/package.json')('playwright');
const out = process.argv[2];
mkdirSync(out);
(async () => {
  const browser = await chromium.launch({ headless: true });
  const rows = [];
  for (const width of [360, 1440]) for (const dpr of [1, 2]) {
    const page = await browser.newPage({ viewport: { width, height: 1000 }, deviceScaleFactor: dpr });
    for (const path of ['/blog', '/blog/articles/pochemu-yapontsy-hudye-a-ty-net']) {
      await page.goto('http://127.0.0.1:8784' + path);
      const selected = page.locator('img[srcset]').first();
      await selected.scrollIntoViewIfNeeded();
      await selected.evaluate(img => img.decode());
      const image = await selected.evaluate(img => ({ src: img.getAttribute('src'), currentSrc: new URL(img.currentSrc).pathname, srcset: img.srcset, width: img.getBoundingClientRect().width, loaded: img.complete && img.naturalWidth > 0 }));
      const original = process.cwd() + '/content/blog/media/' + image.src.replace('/blog/media/', '');
      const chosen = process.cwd() + '/content/blog/media/' + image.currentSrc.replace('/blog/media/', '');
      image.originalBytes = statSync(original).size;
      image.selectedBytes = statSync(chosen).size;
      if (!image.loaded || !image.currentSrc.startsWith('/blog/media/') || image.width > width) throw Error('Image selection failure');
      const dimensions = await page.evaluate(() => ({ viewport: innerWidth, document: document.documentElement.scrollWidth }));
      if (dimensions.document > width) throw Error('Horizontal overflow');
      rows.push({ width, dpr, path, image, dimensions });
      if (path === '/blog') await selected.screenshot({ path: out + '/card-' + width + '-dpr' + dpr + '.png' });
    }
    await page.close();
  }
  await browser.close();
  writeFileSync(out + '/checks.json', JSON.stringify(rows, null, 2));
  console.log(JSON.stringify(rows.map(row => ({ width: row.width, dpr: row.dpr, path: row.path, selectedBytes: row.image.selectedBytes, originalBytes: row.image.originalBytes, currentSrc: row.image.currentSrc }))));
})().catch(error => { console.error(error); process.exitCode = 1; });
