import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
import path from 'node:path';

const require = createRequire(import.meta.url);
const { chromium } = require(path.join(process.env.CODEX_NODE_MODULES, 'playwright'));
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  await page.addInitScript(() => {
    window.EdabalansAppContext = { mode: 'admin', targetUserId: 'synthetic-profile' };
    window.__writes = [];
    window.__serverVersion = 1;
    window.__activeWrites = 0;
    window.__overlap = false;
    window.__conflicts = 0;
    const sessions = [1, 2, 3].map(number => ({ session_id: `s${number}`, workout_type: 1, session_number: number, date: '2026-09-21' }));
    const catalog = ['bench', 'row', 'old', 'custom'].map((id, i) => ({ exercise_id: id, exercise_name: ['Жим', 'Тяга', 'Старое упражнение', 'Своё упражнение'][i], active: id === 'bench', sort_order: i + 1, source: id === 'custom' ? 'custom' : 'base' }));
    window.fetch = async (url, options = {}) => {
      const parsed = new URL(String(url), 'https://edabalans.ru');
      const body = options.body ? JSON.parse(options.body) : null;
      const action = body?.action || parsed.searchParams.get('action');
      let response = { ok: true, version: window.__serverVersion };
      if (action === 'openUser') response.user = { user_id: 'synthetic-profile', email: 'synthetic@example.test', display_name: 'Тестовый профиль' };
      if (action === 'getWorkout') {
        const exercises = sessions.flatMap(session => ['bench', 'old'].map(id => ({ session_id: session.session_id, exercise_id: id, exercise_name: catalog.find(item => item.exercise_id === id).exercise_name, sort_order: id === 'bench' ? 1 : 2 })));
        response.workout = { version: window.__serverVersion, exercise_catalog: Number(parsed.searchParams.get('type')) === 1 ? catalog : catalog.map(item => ({ ...item, active: false })), sessions, session_exercises: exercises, sets: exercises.flatMap(exercise => [1, 2, 3, 4].map(number => ({ ...exercise, set_number: number, plan_weight: '40', plan_reps: '10', fact_weight: exercise.session_id === 's1' && exercise.exercise_id === 'old' ? '15' : '', fact_reps: '', rpe: '' }))) };
      }
      if (action === 'saveSession' || action === 'saveExerciseCatalog') {
        window.__writes.push(body);
        window.__activeWrites++;
        if (window.__activeWrites > 1) window.__overlap = true;
        if (window.__writes.length === 1) await new Promise(resolve => { window.__releaseFirst = resolve; });
        if (body.version !== window.__serverVersion) {
          response = { ok: false, error: 'STRENGTH_STATE_CONFLICT' };
          window.__conflicts++;
        } else {
          response = { ok: true, version: ++window.__serverVersion, session: body.session };
        }
        window.__activeWrites--;
      }
      return new Response(JSON.stringify(response), { headers: { 'Content-Type': 'application/json' } });
    };
  });
  await page.goto(pathToFileURL(path.resolve('app/static/apps/strength.html')).href);
  await page.getByText('Тренировка №3', { exact: true }).waitFor();
  assert.equal(await page.locator('.st-ex-row', { hasText: 'Старое упражнение' }).locator('.st-ex-day').count(), 1, 'Факт старого упражнения виден только в его прошлой тренировке');
  await page.getByRole('button', { name: 'Редактировать шаблон 1', exact: true }).click();
  const row = page.locator('.st-manager-row', { hasText: 'Тяга' });
  await row.getByText('Добавить', { exact: true }).click();
  await page.waitForFunction(() => !!window.__releaseFirst);
  await row.getByText('Убрать', { exact: true }).click();
  await page.getByText('Закрыть', { exact: true }).click();
  await page.getByRole('button', { name: 'Редактировать шаблон 2', exact: true }).click();
  await page.locator('.st-manager-row', { hasText: 'Своё упражнение' }).getByText('Добавить', { exact: true }).click();
  await page.getByText('Закрыть', { exact: true }).click();
  await page.getByRole('button', { name: 'Редактировать шаблон 1', exact: true }).click();
  page.once('dialog', dialog => dialog.accept('Новое название'));
  await page.locator('.st-manager-row', { hasText: 'Своё упражнение' }).getByText('Изменить', { exact: true }).click();
  await page.getByText('Закрыть', { exact: true }).click();
  for (const [number, weight] of [[3, '43'], [2, '42'], [1, '41']]) {
    await page.getByText(`Тренировка №${number}`, { exact: true }).waitFor();
    const input = page.locator('.st-ex-row', { hasText: 'Жим' }).locator('.st-ex-day.current .st-plan-field').first();
    await input.fill(weight);
    await input.blur();
    // Allow each session's debounce to enqueue while the first request is held.
    await page.waitForTimeout(500);
    if (number > 1) await page.getByRole('button', { name: 'Предыдущая тренировка', exact: true }).click();
  }
  assert.equal(await page.evaluate(() => window.__writes.length), 1, 'Запросы ожидают завершения первого сохранения');
  await page.evaluate(() => window.__releaseFirst());
  await page.waitForFunction(() => window.__serverVersion === 7);
  const result = await page.evaluate(() => ({ writes: window.__writes, overlap: window.__overlap, conflicts: window.__conflicts }));
  assert.equal(result.overlap, false);
  assert.equal(result.conflicts, 0);
  assert.deepEqual(result.writes.map(body => body.version), [1, 2, 3, 4, 5, 6]);
  assert.equal(result.writes[2].workout_type, 2);
  assert.equal(result.writes[2].exercises.find(item => item.exercise_id === 'custom').exercise_name, 'Новое название', 'Ожидающий другой шаблон не возвращает старое общее название');
  assert.equal(result.writes[1].exercises.find(item => item.exercise_id === 'row').active, false, 'Сохраняется последняя правка шаблона');
  assert.deepEqual(result.writes.filter(body => body.action === 'saveSession').map(body => [body.session.session_id, body.session.exercises[0].sets[0].plan_weight]), [['s3', 43], ['s2', 42], ['s1', 41]], 'Правки разных тренировок не вытесняются');

  await page.evaluate(() => { window.__serverVersion++; });
  const input = () => page.locator('.st-ex-row', { hasText: 'Жим' }).locator('.st-ex-day.current .st-plan-field').first();
  await input().fill('51');
  await input().blur();
  await page.getByText('Загрузить актуальное', { exact: true }).waitFor();
  assert.equal(await page.getByText('Повторить', { exact: true }).count(), 0);
  await input().fill('52');
  await input().blur();
  await page.waitForTimeout(800);
  assert.equal(await page.evaluate(() => window.__writes.length), 7, 'Конфликт другой вкладки блокирует дальнейшую отправку');
  await page.getByText('Загрузить актуальное', { exact: true }).click();
  await page.getByText('Тренировка №3', { exact: true }).waitFor();
  await input().fill('53');
  await input().blur();
  await page.waitForFunction(() => window.__serverVersion === 9);
  assert.equal(await page.evaluate(() => window.__writes.at(-1).version), 8);
  assert.equal(await page.evaluate(() => window.__writes.length), 8, 'После загрузки не отправляются старые несохранённые правки');

  await page.evaluate(() => { window.__serverVersion++; });
  await page.getByRole('button', { name: 'Редактировать шаблон 1', exact: true }).click();
  await row.getByText('Добавить', { exact: true }).click();
  await page.getByText('Не удалось сохранить', { exact: true }).waitFor();
  await page.waitForTimeout(1700);
  assert.equal(await page.evaluate(() => window.__writes.length), 9, 'Версионный конфликт каталога не повторяется автоматически');
  await browser.close();
} finally {
  await browser.close();
}
console.log('strength save queue checks passed');
