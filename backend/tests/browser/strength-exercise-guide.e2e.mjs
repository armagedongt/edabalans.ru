import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import fs from 'node:fs';
import path from 'node:path';

const require = createRequire(import.meta.url);
const { chromium } = require(path.join(process.env.CODEX_NODE_MODULES, 'playwright'));
const guides = JSON.parse(fs.readFileSync('app/strength_exercise_guides.json', 'utf8'));
const base = process.env.STRENGTH_QA_BASE_URL || 'http://127.0.0.1:8794';
const screenshots = process.env.QA_SCREENSHOTS_DIR;
if (screenshots) fs.mkdirSync(screenshots, { recursive: true });
const catalog = guides.map((item, i) => ({ exercise_id: item.code, exercise_name: item.name, source: 'base', active: true, sort_order: i + 1, media_url: item.media_url, guide: item.guide }));
const workout = {
  version: 1, exercise_catalog: catalog,
  sessions: [{ session_id: 'qa-session', session_number: 1, workout_type: 1, date: '2026-10-08' }],
  session_exercises: catalog.map((item, i) => ({ session_id: 'qa-session', exercise_id: item.exercise_id, exercise_name: item.exercise_name, sort_order: i + 1 })),
  sets: catalog.map((item) => ({ session_id: 'qa-session', exercise_id: item.exercise_id, set_number: 1, plan_weight: '20', plan_reps: '10' })),
};
const browser = await chromium.launch({ headless: true });
try {
  for (const width of [360, 430, 767, 768, 1440]) {
    const page = await browser.newPage({ viewport: { width, height: 900 } });
    const errors = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.addInitScript(({ workout }) => {
      window.EdabalansAppContext = { mode: 'admin', targetUserId: 'synthetic-profile' };
      window.fetch = async (url, options = {}) => {
        const parsed = new URL(String(url), location.href);
        const body = options.body ? JSON.parse(options.body) : null;
        const action = body?.action || parsed.searchParams.get('action');
        const response = { ok: true, version: 1 };
        if (action === 'openUser') response.user = { user_id: 'synthetic-profile', display_name: 'Тестовый профиль', email: 'synthetic@example.test' };
        if (action === 'getWorkout') response.workout = workout;
        return new Response(JSON.stringify(response), { headers: { 'Content-Type': 'application/json' } });
      };
    }, { workout });
    await page.goto(base + '/apps/strength.html');
    const infoButton = page.getByRole('button', { name: width <= 700 ? 'Как выполнять упражнение' : 'Информация об упражнении', exact: true });
    await infoButton.first().click();
    const dialog = page.getByRole('dialog');
    await dialog.waitFor();
    assert.deepEqual(await dialog.boundingBox(), { x: 0, y: 0, width, height: 900 });
    assert.equal(await dialog.locator('h2').textContent(), guides[0].guide.title);
    assert.deepEqual(await dialog.locator('h3').allTextContents(), ['Положение', 'Движение', 'Детали']);
    assert.equal(await page.evaluate(() => document.body.style.overflow), 'hidden');
    for (const image of await dialog.locator('img').all()) {
      await image.evaluate((el) => el.decode());
      assert.ok(await image.evaluate((el) => el.naturalWidth > 0));
    }
    assert.equal(await dialog.locator('.st-guide-body').evaluate((el) => el.scrollWidth > el.clientWidth), false);
    await page.keyboard.press('Tab');
    assert.equal(await page.locator('.st-guide-body').evaluate((el) => el === document.activeElement), true);
    await page.keyboard.press('Shift+Tab');
    assert.equal(await page.locator('.st-guide-close').evaluate((el) => el === document.activeElement), true);
    {
      const sources = [
        { name: 'BurnFit', url: 'https://burnfit.io/' },
        { name: 'FitnessProgramer', url: 'https://fitnessprogramer.com/' },
      ];
      assert.deepEqual(await dialog.locator('.st-guide-credit a').allTextContents(), sources.map((item) => item.name));
      assert.equal(await dialog.locator('.st-guide-copy > :last-child').getAttribute('class'), 'st-guide-credit');
      for (const source of sources) {
        const link = dialog.getByRole('link', { name: source.name, exact: true });
        assert.equal(await link.getAttribute('href'), source.url);
        assert.equal(await link.getAttribute('rel'), 'noopener noreferrer');
      }
      await page.keyboard.press('Tab');
      for (const source of sources) {
        await page.keyboard.press('Tab');
        assert.equal(await dialog.getByRole('link', { name: source.name, exact: true }).evaluate((el) => el === document.activeElement), true);
      }
      await page.keyboard.press('Tab');
      assert.equal(await page.locator('.st-guide-close').evaluate((el) => el === document.activeElement), true);
    }
    if (screenshots) await page.screenshot({ path: path.join(screenshots, `guide-${width}-top.png`) });
    await dialog.locator('.st-guide-body').evaluate((el) => { el.scrollTop = el.scrollHeight; });
    if (screenshots) await page.screenshot({ path: path.join(screenshots, `guide-${width}-bottom.png`) });
    await page.keyboard.press('Escape');
    assert.equal(await dialog.count(), 0);
    assert.notEqual(await page.evaluate(() => document.body.style.overflow), 'hidden');
    assert.equal(await infoButton.first().evaluate((el) => el === document.activeElement), true);
    // Every approved card reaches the popup through its real exercise identity.
    if (width === 360) {
      for (let i = 0; i < guides.length; i++) {
        await infoButton.nth(i).click();
        assert.equal(await dialog.locator('h2').textContent(), guides[i].guide.title);
        assert.equal(await dialog.locator('.st-guide-copy p').first().textContent(), guides[i].guide.position);
        await dialog.locator('.st-guide-demo').evaluate((el) => el.decode());
        await dialog.locator('.st-guide-muscles').evaluate((el) => el.decode());
        await page.getByRole('button', { name: 'Закрыть информацию об упражнении' }).click();
      }
    }
    // Template edits retain the guide when the client copies its catalogue.
    await page.getByRole('button', { name: 'Редактировать шаблон 1', exact: true }).click();
    await page.locator('.st-manager-row').filter({ has: page.getByText(guides[0].name, { exact: true }) }).getByRole('button', { name: 'Ниже', exact: true }).click();
    await page.getByText('Закрыть', { exact: true }).click();
    const movedInfo = page.locator(`.st-exercise-info[data-exercise-id="${guides[0].code}"]`);
    await movedInfo.click();
    assert.equal(await dialog.locator('.st-guide-copy p').first().textContent(), guides[0].guide.position);
    assert.deepEqual(errors, []);
    await page.close();
  }
} finally {
  await browser.close();
}
console.log('All 50 exercise guides and fullscreen popup checks passed');
