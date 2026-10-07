import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
import path from 'node:path';

const require = createRequire(import.meta.url);
const { chromium } = require(path.join(process.env.CODEX_NODE_MODULES, 'playwright'));
const browser = await chromium.launch({ headless: true });
const screenshots = process.env.STRENGTH_EVIDENCE_DIR;

function fixture(type) {
  const catalog = [
    { exercise_id: 'bench', exercise_name: 'Жим штанги', active: true, sort_order: 2 },
    { exercise_id: 'triceps', exercise_name: 'Верхний блок на трицепс', active: type === 1, sort_order: 1 },
    { exercise_id: 'row', exercise_name: 'Тяга в тренажёре', active: type === 2, sort_order: 3 },
  ];
  const sessions = Array.from({ length: 6 }, (_, i) => ({ session_id: `s${i + 1}`, workout_type: i % 2 + 1, session_number: i + 1, date: '2026-09-21' }));
  const exercises = sessions.flatMap((session) => ['bench', 'triceps', 'row', 'history-only'].map((id, i) => ({ session_id: session.session_id, exercise_id: id, exercise_name: catalog.find((item) => item.exercise_id === id)?.exercise_name || 'Историческое упражнение', sort_order: i + 1, note: 'Сохранённая заметка' })));
  return { version: 1, exercise_catalog: type === 3 ? catalog.map((item) => ({ ...item, active: false })) : catalog, sessions, session_exercises: exercises, sets: exercises.flatMap((exercise) => Array.from({ length: 4 }, (_, i) => ({ ...exercise, set_number: i + 1, plan_weight: '40', plan_reps: '10', fact_weight: exercise.session_id === 's1' ? '35' : '', fact_reps: '', rpe: '' }))) };
}

try {
  for (const width of [360, 430, 700, 701, 768, 1412, 1440, 1480]) {
    const page = await browser.newPage({ viewport: { width, height: 900 } });
    await page.addInitScript(({ workouts }) => {
      window.EdabalansAppContext = { mode: 'admin', targetUserId: 'synthetic-profile' };
      window.__saveBodies = [];
      window.fetch = async (url, options = {}) => {
        const parsed = new URL(String(url), 'https://edabalans.ru');
        const body = options.body ? JSON.parse(options.body) : null;
        const action = body?.action || parsed.searchParams.get('action');
        const response = { ok: true, version: 2 };
        if (action === 'openUser') response.user = { user_id: 'synthetic-profile', email: 'synthetic@example.test', display_name: 'Тестовый профиль' };
        if (action === 'getWorkout') response.workout = workouts[Number(parsed.searchParams.get('type') || 1)];
        if (body) window.__saveBodies.push(structuredClone(body));
        if (action === 'saveSession') response.session = body.session;
        return new Response(JSON.stringify(response), { headers: { 'Content-Type': 'application/json' } });
      };
    }, { workouts: { 1: fixture(1), 2: fixture(2), 3: fixture(3) } });
    await page.goto(pathToFileURL(path.resolve('app/static/apps/strength.html')).href);
    await page.getByText('Тренировка №5', { exact: true }).waitFor();
    const names = () => page.locator(width > 700 ? '.st-ex-row-name' : '.st-modern-title strong').allTextContents();
    assert.deepEqual(await names(), ['Верхний блок на трицепс', 'Жим штанги']);
    if (width > 700) assert.deepEqual(await page.locator('.st-day-number').allTextContents(), ['№1', '№3', '№5']);
    const planWeight = () => page.locator(width > 700 ? '.st-ex-row:first-of-type .st-ex-day.current .st-plan-field' : '.st-modern-exercise:first-child .st-plan-inputs input').first();
    const factWeight = () => page.locator(width > 700 ? '.st-ex-row:first-of-type .st-ex-day.current .st-fact-field' : '.st-modern-exercise:first-child .st-fact-inputs input').first();
    async function enterWeight(locator, value, field, expected) {
      await locator().fill(value);
      await locator().blur();
      assert.equal(await locator().inputValue(), String(expected));
      await page.waitForFunction(({ field, expected }) => {
        const saved = window.__saveBodies.filter((body) => body.action === 'saveSession').at(-1);
        return saved?.session.exercises.find((exercise) => exercise.exercise_id === 'triceps')?.sets[0][field] === expected;
      }, { field, expected });
    }
    assert.equal(await planWeight().getAttribute('inputmode'), 'decimal');
    assert.equal(await factWeight().getAttribute('inputmode'), 'decimal');
    await enterWeight(planWeight, '12,5', 'plan_weight', 12.5);
    await enterWeight(factWeight, '7.25', 'fact_weight', 7.25);
    await enterWeight(planWeight, '17.75', 'plan_weight', 17.75);
    await enterWeight(factWeight, '8,5', 'fact_weight', 8.5);
    await enterWeight(factWeight, '0', 'fact_weight', 0);
    await enterWeight(factWeight, '', 'fact_weight', '');
    await enterWeight(planWeight, '40', 'plan_weight', 40);
    if (width <= 700) {
      await page.getByRole('button', { name: 'Начать тренировку', exact: true }).click();
      await enterWeight(factWeight, '3,75', 'fact_weight', 3.75);
      await enterWeight(factWeight, '', 'fact_weight', '');
      await page.getByRole('button', { name: 'Редактировать план', exact: true }).click();
    }
    await page.evaluate(() => { window.__saveBodies = []; });
    await page.getByRole('button', { name: 'Предыдущая тренировка', exact: true }).click();
    await page.getByText('Тренировка №3', { exact: true }).waitFor();
    const copyButton = page.locator(width > 700 ? '.st-ex-row' : '.st-modern-exercise', { hasText: 'Жим штанги' }).locator(width > 700 ? '.st-ex-day.current .st-copy-forward' : '.st-modern-copy');
    await copyButton.click();
    await page.getByText('Тренировка №5', { exact: true }).waitFor();
    await page.waitForFunction(() => window.__saveBodies.some((body) => body.action === 'saveSession'));
    const copied = await page.evaluate(() => window.__saveBodies.filter((body) => body.action === 'saveSession'));
    assert.deepEqual(copied.map((body) => body.session.session_id), ['s5'], 'Пустая №4 другого шаблона пропускается при копировании');
    await page.evaluate(() => { window.__saveBodies = []; });
    await page.getByRole('button', { name: 'Предыдущая тренировка', exact: true }).click();
    await page.getByText('Тренировка №3', { exact: true }).waitFor();
    await page.getByRole('button', { name: 'Предыдущая тренировка', exact: true }).click();
    await page.getByText('Тренировка №1', { exact: true }).waitFor();
    assert.equal(await page.getByRole('button', { name: 'Предыдущая тренировка', exact: true }).isDisabled(), true);
    await page.getByRole('button', { name: 'Шаблон 2', exact: true }).click();
    await page.getByText('Тренировка №6', { exact: true }).waitFor();
    assert.deepEqual(await names(), ['Жим штанги', 'Тяга в тренажёре']);
    if (width > 700) assert.deepEqual(await page.locator('.st-day-number').allTextContents(), ['№2', '№4', '№6']);
    await page.getByRole('button', { name: 'Шаблон 1', exact: true }).click();
    await page.getByText('Тренировка №5', { exact: true }).waitFor();
    if (screenshots) await page.screenshot({ path: path.join(screenshots, `strength-template-${width}.png`), fullPage: true });
    await page.getByRole('button', { name: 'Редактировать шаблон 1', exact: true }).click();
    await page.locator('.st-manager-row', { hasText: 'Верхний блок на трицепс' }).getByText('Убрать', { exact: true }).click();
    await page.getByText('Закрыть', { exact: true }).click();
    assert.deepEqual(await names(), ['Жим штанги']);
    assert.equal(await page.evaluate(() => window.__saveBodies.some((body) => body.action === 'saveSession')), false);
    await page.locator('.st-top-stats').click();
    await page.getByRole('button', { name: 'Анализ', exact: true }).click();
    assert.equal(await page.locator('.st-analysis-controls option[value="triceps"]').count(), 1, 'Исключённое упражнение доступно в общей статистике');
    await page.getByText('← К тренировкам', { exact: true }).click();
    await page.getByRole('button', { name: 'Предыдущая тренировка', exact: true }).click();
    await page.getByRole('button', { name: 'Предыдущая тренировка', exact: true }).click();
    await page.getByText('Тренировка №1', { exact: true }).waitFor();
    const field = page.locator(width > 700 ? '.st-ex-day.current .st-plan-field' : '.st-modern-set.edit input').first();
    await field.fill('42');
    await field.blur();
    await page.waitForFunction(() => window.__saveBodies.some((body) => body.action === 'saveSession'));
    const saved = await page.evaluate(() => window.__saveBodies.find((body) => body.action === 'saveSession'));
    assert.equal(saved.session.session_id, 's1');
    assert.deepEqual(saved.session.exercises.map((exercise) => exercise.exercise_id), ['bench', 'triceps', 'row', 'history-only']);
    assert.equal(saved.session.exercises.find((exercise) => exercise.exercise_id === 'triceps').note, 'Сохранённая заметка');
    assert.deepEqual(saved.session.exercises.find((exercise) => exercise.exercise_id === 'triceps').sets.map((set) => [String(set.plan_weight), String(set.plan_reps), String(set.fact_weight), set.rpe]), Array.from({ length: 4 }, () => ['40', '10', '35', '']));
    await page.getByRole('button', { name: 'Следующая тренировка', exact: true }).click();
    await page.getByRole('button', { name: 'Следующая тренировка', exact: true }).click();
    await page.getByText('Тренировка №5', { exact: true }).waitFor();
    await page.getByText('Новая тренировка', { exact: false }).click();
    await page.getByText('Тренировка №7', { exact: true }).waitFor();
    const created = await page.evaluate(() => window.__saveBodies.find((body) => body.action === 'saveSession' && body.session.session_number === 7));
    assert.equal(created.workout_type, 1);
    assert.deepEqual(created.session.exercises.map((exercise) => exercise.exercise_id), ['bench']);
    await page.getByRole('button', { name: 'Шаблон 3', exact: true }).click();
    assert.equal(await page.locator('.st-nav-title').count(), 0);
    assert.deepEqual(await names(), []);
    assert.equal(await page.getByRole('button', { name: 'Начать тренировку', exact: true }).isDisabled(), true);
    await page.close();
  }
} finally {
  await browser.close();
}
console.log('strength template navigation checks passed');
