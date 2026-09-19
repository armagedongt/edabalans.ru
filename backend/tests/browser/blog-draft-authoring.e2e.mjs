import assert from 'node:assert/strict';
import { mkdir, readFile } from 'node:fs/promises';
import path from 'node:path';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const modulesRoot = process.env.CODEX_NODE_MODULES;
const { chromium } = modulesRoot ? require(path.join(modulesRoot, 'playwright')) : await import('playwright');
const baseURL = process.env.BLOG_QA_BASE_URL || 'http://127.0.0.1:8765';
const output = process.env.QA_OUT;
const slug = 'vse-znayut-nikto-ne-delaet';
const internalSlug = 'vse-znayut-nikto-ne-delaet-internal';

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
  if (output) await mkdir(output, { recursive: true });
  const fixtureRoot = new URL('../fixtures/blog-draft-real/', import.meta.url);
  const metadata = JSON.parse(await readFile(new URL('real-article.metadata.json', fixtureRoot), 'utf8'));
  const markdown = await readFile(new URL('real-article.md', fixtureRoot), 'utf8');
  const media = await Promise.all(metadata.media.map(async item => ({
    ...item,
    alt: '',
    content_base64: (await readFile(new URL(`media/${item.name}`, fixtureRoot))).toString('base64'),
  })));
  const internalResponse = await context.request.put(`${baseURL}/admin/api/blog/articles/${internalSlug}`, {
    data: {
      expected_version: 0,
      title: `${metadata.title} · служебная копия`,
      excerpt: '',
      category: metadata.category,
      markdown,
      visibility: 'internal',
      editorial_status: 'moderation',
      cta: metadata.cta,
      sources: metadata.sources,
      source_id: metadata.source_id,
      hero: metadata.hero,
      media,
      metadata: { e2e_fixture: true },
    },
  });
  assert.ok([200, 409].includes(internalResponse.status()), `internal fixture HTTP ${internalResponse.status()}`);
  for (const width of [360, 430, 768, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto(`${baseURL}/blog`, { waitUntil: 'networkidle' });
    await page.locator('#owner-title').waitFor();
    assert.equal(await page.locator('.owner-card').count(), 2);
    for (const [filter, expected] of Object.entries({ all: 2, public: 1, internal: 1, moderation: 2 })) {
      const button = page.locator(`[data-owner-filter="${filter}"]`);
      await button.click();
      assert.equal(await button.getAttribute('aria-pressed'), 'true');
      assert.equal(await page.locator('.owner-card:not([hidden])').count(), expected, `${filter} at ${width}px`);
    }
    await page.evaluate(async () => {
      const images = Array.from(document.querySelectorAll('img'));
      images.forEach(image => { image.loading = 'eager'; });
      await Promise.all(images.map(image => image.complete ? Promise.resolve() : new Promise(resolve => {
        image.addEventListener('load', resolve, { once: true });
        image.addEventListener('error', resolve, { once: true });
      })));
    });
    const catalogImages = page.locator('img');
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
    assert.match(await page.locator('#draft-meta').innerText(), /На модерации/);
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
  await page.locator('#draft-preview').click();
  await page.locator('#article').getByText(successfulMarker, { exact: true }).waitFor();
  await page.locator('#draft-notice').getByText('Предпросмотр обновлён. Изменения пока не сохранены.', { exact: true }).waitFor();
  await page.locator('#draft-save').click();
  await page.locator('#draft-notice').waitFor();
  await page.waitForFunction(() => /Версия \d+ сохранена/.test(document.querySelector('#draft-status')?.textContent || ''));
  assert.equal(await textarea.inputValue(), successfulEdit);

  await page.route(`**/admin/api/blog/articles/${slug}/text`, route => route.fulfill({
    status: 409,
    contentType: 'application/json',
    body: JSON.stringify({ detail: 'Версия уже изменилась' }),
  }));
  const edited = `${await textarea.inputValue()}\n\nЛокальная несохранённая правка.`;
  await textarea.fill(edited);
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
