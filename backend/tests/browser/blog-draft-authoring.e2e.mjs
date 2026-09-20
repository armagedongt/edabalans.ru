import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import path from 'node:path';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const modulesRoot = process.env.CODEX_NODE_MODULES;
const { chromium } = modulesRoot ? require(path.join(modulesRoot, 'playwright')) : await import('playwright');
const baseURL = process.env.BLOG_QA_BASE_URL || 'http://127.0.0.1:8765';
const output = process.env.QA_OUT;
const slug = 'skolko-vremeni-nuzhno-na-pohudenie';

const browser = await chromium.launch({ headless: true });
const username = process.env.BLOG_QA_USER || 'qa-owner';
const password = process.env.BLOG_QA_PASSWORD || 'qa-password';
const context = await browser.newContext({
  extraHTTPHeaders: {
    Authorization: `Basic ${Buffer.from(`${username}:${password}`).toString('base64')}`,
  },
});
const page = await context.newPage();

try {
  const inventoryResponse = await context.request.get(`${baseURL}/admin/api/blog/articles`);
  assert.equal(inventoryResponse.status(), 200);
  const inventory = (await inventoryResponse.json()).articles;
  const expectedCounts = {
    all: inventory.length,
    public: inventory.filter(article => article.visibility === 'public').length,
    internal: inventory.filter(article => article.visibility === 'internal').length,
    moderation: inventory.filter(article => article.editorial_status === 'moderation').length,
  };
  if (output) await mkdir(output, { recursive: true });
  for (const width of [360, 430, 768, 899, 901, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto(`${baseURL}/blog`, { waitUntil: 'networkidle' });
    await page.locator('#owner-title').waitFor();
    assert.equal(await page.locator('.owner-card').count(), expectedCounts.all);
    for (const [filter, expected] of Object.entries(expectedCounts)) {
      const button = page.locator(`[data-owner-filter="${filter}"]`);
      await button.click();
      assert.equal(await button.getAttribute('aria-pressed'), 'true');
      assert.equal(await page.locator('.owner-card:not([hidden])').count(), expected, `${filter} at ${width}px`);
    }
    await page.locator('[data-owner-filter="all"]').click();
    await page.evaluate(async () => {
      const images = Array.from(document.querySelectorAll('img'));
      images.forEach(image => { image.loading = 'eager'; });
      await Promise.all(images.map(image => image.complete ? Promise.resolve() : new Promise(resolve => {
        image.addEventListener('load', resolve, { once: true });
        image.addEventListener('error', resolve, { once: true });
      })));
    });
    const catalogImages = page.locator('img:visible');
    for (let index = 0; index < await catalogImages.count(); index += 1) {
      await catalogImages.nth(index).scrollIntoViewIfNeeded();
      await catalogImages.nth(index).evaluate(image => image.decode().catch(() => {}));
    }
    await page.evaluate(() => window.scrollTo(0, 0));
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
    assert.equal(overflow, false, `owner catalog overflows at ${width}px`);
    if (output) await page.screenshot({ path: path.join(output, `owner-catalog-${width}.png`), fullPage: true });

    await page.goto(`${baseURL}/blog/drafts/${slug}/edit`, { waitUntil: 'networkidle' });
    await page.locator('#draft-markdown').waitFor();
    assert.match(await page.locator('#draft-meta').innerText(), /Опубликована/);
    if (width > 900) {
      const columns = await page.evaluate(() => {
        const result = document.querySelector('.draft-result').getBoundingClientRect();
        const source = document.querySelector('.draft-source').getBoundingClientRect();
        return { resultLeft: result.left, sourceLeft: source.left };
      });
      assert.ok(columns.resultLeft < columns.sourceLeft, `preview must be left of Markdown at ${width}px`);
    }
    const editorOverflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
    assert.equal(editorOverflow, false, `draft editor overflows at ${width}px`);
    assert.ok(await page.locator('.draft-cover-option').count() > 1, `cover choices at ${width}px`);
    assert.equal(await page.locator('#draft-cover-preview').isVisible(), true);
    if (output) await page.screenshot({ path: path.join(output, `draft-editor-${width}.png`), fullPage: true });
    await page.locator('#draft-preview').click();
    await page.locator('#draft-notice').getByText('Предпросмотр обновлён по сохранённой версии.', { exact: true }).waitFor();
    if (output) await page.screenshot({ path: path.join(output, `draft-editor-feedback-${width}.png`), fullPage: true });
  }

  await page.locator('#draft-markdown').focus();
  assert.equal(await page.evaluate(() => document.activeElement?.id), 'draft-markdown');
  assert.notEqual(await page.locator('#draft-markdown').evaluate(element => getComputedStyle(element).outlineStyle), 'none');

  const textarea = page.locator('#draft-markdown');
  const successfulMarker = `Успешная E2E-правка ${Date.now()}.`;
  const successfulEdit = `${await textarea.inputValue()}\n\n${successfulMarker}`;
  await textarea.fill(successfulEdit);
  const alternativeCover = page.locator('.draft-cover-option').nth(1);
  const alternativeName = await alternativeCover.getAttribute('data-card-name');
  await alternativeCover.click();
  assert.match(await page.locator('#draft-cover-preview').getAttribute('src'), new RegExp(alternativeName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  const previewRatio = await page.locator('.draft-cover-frame').evaluate(frame => frame.clientWidth / frame.clientHeight);
  assert.ok(Math.abs(previewRatio - (16 / 9)) < 0.02, `cover preview ratio is ${previewRatio}`);
  await page.locator('input[name="card-fit"][value="contain"]').check();
  assert.equal(await page.locator('#draft-cover-preview').evaluate(image => getComputedStyle(image).objectFit), 'contain');
  await page.locator('#draft-preview').click();
  await page.locator('#article').getByText(successfulMarker, { exact: true }).waitFor();
  await page.locator('#draft-notice').getByText('Предпросмотр обновлён. Изменения пока не сохранены.', { exact: true }).waitFor();
  await page.locator('#draft-save').click();
  await page.locator('#draft-notice').waitFor();
  await page.waitForFunction(() => /Версия \d+ сохранена/.test(document.querySelector('#draft-status')?.textContent || ''));
  assert.equal(await textarea.inputValue(), successfulEdit);
  assert.match(await page.locator('#draft-meta').innerText(), /На модерации/);

  page.once('dialog', dialog => dialog.dismiss());
  await page.locator('#draft-publish').click();
  assert.match(await page.locator('#draft-meta').innerText(), /На модерации/);
  const beforeConfirmation = await context.request.get(`${baseURL}/blog/articles/${slug}`);
  assert.doesNotMatch(await beforeConfirmation.text(), new RegExp(successfulMarker));

  page.once('dialog', dialog => dialog.accept());
  await page.locator('#draft-publish').click();
  await page.locator('#draft-notice').getByText('Статья опубликована. Публичная страница обновлена без deploy.', { exact: true }).waitFor();
  assert.match(await page.locator('#draft-meta').innerText(), /Опубликована/);
  const publicResponse = await context.request.get(`${baseURL}/blog/articles/${slug}`);
  assert.equal(publicResponse.status(), 200);
  assert.match(await publicResponse.text(), new RegExp(successfulMarker));
  const publicCatalog = await context.request.get(`${baseURL}/blog`);
  const publicCatalogHtml = await publicCatalog.text();
  assert.match(publicCatalogHtml, new RegExp(`card-image card-image--contain[^>]+${alternativeName}`));
  await page.goto(`${baseURL}/blog`, { waitUntil: 'networkidle' });
  const publishedCard = page.locator(`img.card-image--contain[src$="${alternativeName}"]`);
  await publishedCard.waitFor({ state: 'attached' });
  assert.equal(await publishedCard.evaluate(image => getComputedStyle(image).objectFit), 'contain');
  await page.goto(`${baseURL}/blog/drafts/${slug}/edit`, { waitUntil: 'networkidle' });
  await textarea.waitFor();

  await page.route(`**/admin/api/blog/articles/${slug}/text`, route => route.fulfill({
    status: 409,
    contentType: 'application/json',
    body: JSON.stringify({ detail: 'Версия уже изменилась' }),
  }));
  const edited = `${await textarea.inputValue()}\n\nЛокальная несохранённая правка.`;
  await textarea.fill(edited);
  assert.equal(await page.locator('#draft-publish').isDisabled(), true);
  await page.locator('#draft-save').click();
  await page.locator('#draft-error').waitFor();
  assert.equal(await textarea.inputValue(), edited);
  assert.match(await page.locator('#draft-status').innerText(), /текст сохранён в поле/);

  await page.unroute(`**/admin/api/blog/articles/${slug}/text`);
  await page.route(`**/admin/api/blog/articles/${slug}/text`, route => route.abort('failed'));
  const offlineEdit = `${edited}\nЕщё одна несохранённая строка.`;
  await textarea.fill(offlineEdit);
  await page.locator('#draft-save').click();
  await page.waitForFunction(() => document.querySelector('#draft-status')?.textContent.includes('Не удалось сохранить'));
  assert.equal(await textarea.inputValue(), offlineEdit);
  assert.equal(await page.evaluate(() => {
    const event = new Event('beforeunload', { cancelable: true });
    window.dispatchEvent(event);
    return event.defaultPrevented;
  }), true);
  console.log('blog draft authoring e2e: ok');
} finally {
  await browser.close();
}
