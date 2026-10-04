// Local UI verification only: no production requests or analytics.
import { createRequire } from 'node:module';
import path from 'node:path';
import assert from 'node:assert/strict';
const require = createRequire(import.meta.url);
const { chromium } = require(path.join(process.env.NODE_PATH, 'playwright'));
const browser = await chromium.launch({ headless: true });
try {
  for (const javaScriptEnabled of [false, true]) {
    const context = await browser.newContext({ javaScriptEnabled, viewport: { width: 360, height: 800 } });
    // Common third-party footer/cookie assets are outside this selected-area test.
    await context.route('https://**/*', route => route.abort());
    const page = await context.newPage();
    await page.goto('http://127.0.0.1:8782/blog');
    assert.equal(await page.locator('.article-grid .article-card').count(), 15);
    const first = await page.locator('.card-link').first().getAttribute('href');
    await page.locator('.pagination a.next').click();
    await page.waitForURL('**/blog?page=2#articles');
    assert.equal(await page.locator('.article-grid .article-card').count(), 15);
    assert.notEqual(await page.locator('.card-link').first().getAttribute('href'), first);
    await page.locator('[data-category-filter="Похудение"]').click();
    assert.equal(new URL(page.url()).searchParams.get('category'), 'Похудение');
    assert.equal(new URL(page.url()).searchParams.get('page'), null);
    assert.ok(await page.locator('.article-card').evaluateAll(nodes => nodes.every(node => node.dataset.category === 'Похудение')));
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    await context.close();
  }
  console.log('PASS: mobile page/category links with JavaScript disabled and enabled; no horizontal overflow.');
} finally {
  await browser.close();
}
