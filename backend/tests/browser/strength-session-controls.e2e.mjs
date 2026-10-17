import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
import path from 'node:path';

const require = createRequire(import.meta.url);
const { chromium } = require(path.join(process.env.CODEX_NODE_MODULES, 'playwright'));
const browser = await chromium.launch({ headless: true });
const screenshots = process.env.STRENGTH_EVIDENCE_DIR;

const sampleNote = 'Сохранённая заметка.\nНамеренно не стала доделывать 20 повторений.\nСледующий подход выполнила по плану.\nПоследняя строка длинного комментария.';

function fixture(type) {
  const catalog = [
    { exercise_id: 'bench', exercise_name: 'Жим штанги', active: true, sort_order: 2 },
    { exercise_id: 'triceps', exercise_name: 'Верхний блок на трицепс', active: type === 1, sort_order: 1 },
    { exercise_id: 'row', exercise_name: 'Тяга в тренажёре', active: type === 2, sort_order: 3 },
    { exercise_id: 'bridge', exercise_name: 'Ягодичный мост', active: false, sort_order: 4 },
  ];
  const sessions = Array.from({ length: 6 }, (_, i) => ({ session_id: `s${i + 1}`, workout_type: i % 2 + 1, session_number: i + 1, date: '2026-09-21' }));
  const exercises = sessions.flatMap((session) => ['bench', 'triceps', 'row', 'history-only'].map((id, i) => ({ session_id: session.session_id, exercise_id: id, exercise_name: catalog.find((item) => item.exercise_id === id)?.exercise_name || 'Историческое упражнение', sort_order: i + 1, note: session.session_id === 's3' ? '' : sampleNote })));
  return { version: 1, exercise_catalog: type === 3 ? catalog.map((item) => ({ ...item, active: false })) : catalog, sessions, session_exercises: exercises, sets: exercises.flatMap((exercise) => Array.from({ length: 4 }, (_, i) => ({ ...exercise, set_number: i + 1, plan_weight: '40', plan_reps: '10', fact_weight: exercise.session_id === 's1' && ['bench', 'triceps'].includes(exercise.exercise_id) && !(exercise.exercise_id === 'triceps' && i === 3) ? '35' : '', fact_reps: '', rpe: exercise.session_id === 's1' && exercise.exercise_id === 'triceps' ? (i === 0 ? '7' : i === 3 ? '8' : '') : '' }))) };
}

try {
for (const width of [360,430,700,701,768,1440]) {
const page=await browser.newPage({viewport:{width,height:900}});
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

const date=page.locator('.st-session-date input');
assert.ok(await date.isVisible());
await date.fill('2026-10-17'); await date.dispatchEvent('change');
await page.waitForFunction(()=>window.__saveBodies.some(b=>b.action==='saveSession' && b.session.date==='2026-10-17'));
await page.getByRole('button',{name:'Предыдущая тренировка',exact:true}).click();
await page.getByText('Тренировка №3',{exact:true}).waitFor();
if(width<=700){
assert.ok(await page.locator('.st-modern-labels .st-plan-copy-label').first().isVisible());
assert.ok(await page.locator('.st-modern-labels .st-fact-copy-label').first().isVisible());
}
await page.getByRole('button',{name:'Начать тренировку',exact:true}).click();
await page.getByRole('button',{name:'Новая тренировка',exact:true}).click();
await page.getByText('Тренировка №7',{exact:true}).waitFor();
await page.waitForFunction(()=>window.__saveBodies.some(b=>b.action==='saveSession' && b.session.session_number===7));
await page.getByRole('button',{name:'Новая тренировка',exact:true}).waitFor({state:'visible'});
await page.waitForFunction(()=>!document.querySelector('#strength-app').textContent.includes('Создаю тренировку'));
if(screenshots) await page.screenshot({path:path.join(screenshots,`session-controls-${width}.png`)});
page.once('dialog',d=>d.dismiss());
await page.getByRole('button',{name:'Удалить тренировку',exact:true}).click();
assert.ok(await page.getByText('Тренировка №7',{exact:true}).isVisible());
page.once('dialog',d=>d.accept());
await page.getByRole('button',{name:'Удалить тренировку',exact:true}).click();
await page.waitForFunction(()=>window.__saveBodies.some(b=>b.action==='saveSession' && b.session.deleted===true));
await page.getByText('Тренировка №5',{exact:true}).waitFor();
await page.keyboard.press('Control+z');
await page.getByText('Тренировка №7',{exact:true}).waitFor();
await page.waitForFunction(()=>window.__saveBodies.filter(b=>b.action==='saveSession').at(-1)?.session.session_number===7);
await page.getByRole('button',{name:'Предыдущая тренировка',exact:true}).click();
await page.getByRole('button',{name:'Предыдущая тренировка',exact:true}).click();
await page.getByRole('button',{name:'Предыдущая тренировка',exact:true}).click();
await page.getByText('Тренировка №1',{exact:true}).waitFor();
await page.locator('.st-session-date input').fill('2026-10-16');
await page.locator('.st-session-date input').dispatchEvent('change');
await page.waitForFunction(()=>window.__saveBodies.some(b=>b.action==='saveSession' && b.session.session_id==='s1'));
const original=await page.evaluate(()=>window.__saveBodies.filter(b=>b.action==='saveSession' && b.session.session_id==='s1').at(-1).session);
page.once('dialog',d=>d.accept());
await page.getByRole('button',{name:'Удалить тренировку',exact:true}).click();
await page.waitForFunction(()=>window.__saveBodies.some(b=>b.session?.session_id==='s1' && b.session.deleted));
await page.keyboard.press('Control+z');
await page.getByText('Тренировка №1',{exact:true}).waitFor();
await page.waitForFunction(()=>window.__saveBodies.filter(b=>b.action==='saveSession').at(-1)?.session.session_id==='s1' && !window.__saveBodies.filter(b=>b.action==='saveSession').at(-1)?.session.deleted);
assert.deepEqual(await page.evaluate(()=>window.__saveBodies.filter(b=>b.action==='saveSession').at(-1).session),original,'Undo restores date, exercises, plan and fact');
assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
for(let remaining=4;remaining>0;remaining--){
page.once('dialog',d=>d.accept());
await page.getByRole('button',{name:'Удалить тренировку',exact:true}).click();
}
assert.equal(await page.locator('.st-nav-title').count(),0);
assert.equal(await page.locator('#st-save-state').count(),1);
await page.getByRole('button',{name:'↶ Отменить',exact:true}).click();
await page.getByText('Тренировка №3',{exact:true}).waitFor();
await page.close();
}
}finally{await browser.close();}
console.log('strength session controls passed');
