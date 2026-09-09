import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";
import path from "node:path";

const require = createRequire(import.meta.url);
const modulesRoot = process.env.CODEX_NODE_MODULES;
if (!modulesRoot) throw new Error("CODEX_NODE_MODULES is required");
const { chromium } = require(path.join(modulesRoot, "playwright"));

const appPath = path.resolve("app/static/apps/strength.html");
const screenshots = process.env.STRENGTH_EVIDENCE_DIR;
const browser = await chromium.launch({ headless: true });

function workout(type) {
  const names = [
    "Жим штанги лёжа", "Тяга верхнего блока", "Приседания со штангой",
    "Румынская тяга", "Ягодичный мост", "Разведение гантелей в стороны",
    "Жим лёжа узким хватом", "Жим гантелей", "Жим над головой",
    "Тяга горизонтального блока", "Подтягивания", "Тяга штанги в наклоне",
    "Жим ногами", "Выпады", "Болгарские сплит-приседания", "Становая тяга",
    "Сгибание ног", "Разгибание ног", "Сведение ног", "Разведение ног",
    "Подъёмы на носки", "Сгибание рук", "Разгибание рук", "Задняя дельта", "Планка",
  ];
  const catalog = names.map((name, index) => ({
    exercise_id: index === 0 ? "bench-press" : index === 1 ? "lat-pulldown" : `base-${index + 1}`,
    exercise_name: name,
    active: index === 0 || (index === 1 && type === 2),
    catalog_active: true,
    sort_order: index + 1,
    source: "base",
    muscles: "Основные работающие мышцы",
    tips: ["Первый ориентир", "Второй ориентир"],
  }));
  const exercises = catalog.filter((item) => item.active).map((item, index) => ({
    session_id: `session-${type}`,
    exercise_id: item.exercise_id,
    exercise_name: item.exercise_name,
    sort_order: index + 1,
    note: "",
  }));
  return {
    workout_types: [],
    exercise_catalog: catalog,
    sessions: [{ session_id: `session-${type}`, session_number: 1, date: "2026-09-10" }],
    session_exercises: exercises,
    sets: exercises.flatMap((exercise) => [1, 2, 3, 4].map((setNumber) => ({
      session_id: exercise.session_id,
      exercise_id: exercise.exercise_id,
      set_number: setNumber,
      plan_weight: "40",
      plan_reps: "10",
      fact_weight: "",
      fact_reps: "",
      rpe: "",
    }))),
  };
}

for (const width of [360, 430]) {
  const page = await browser.newPage({ viewport: { width, height: 900 } });
  await page.addInitScript(({ workouts }) => {
    window.EdabalansIdentity = { source: "native", email: "preview@example.test" };
    window.__saveActions = [];
    const payload = (value) => Promise.resolve(new Response(JSON.stringify(value), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }));
    window.__workouts = workouts;
    window.fetch = (url, options = {}) => {
      const parsed = new URL(String(url), "https://edabalans.ru");
      const body = options.body ? JSON.parse(options.body) : null;
      const action = body?.action || parsed.searchParams.get("action");
      if (action === "openUser") return payload({ ok: true, user: { user_id: "preview", email: "preview@example.test", display_name: "Предпросмотр" } });
      if (action === "getWorkout") {
        const type = Number(body?.type || parsed.searchParams.get("type") || 1);
        return payload({ ok: true, workout: window.__workouts[type] });
      }
      window.__saveActions.push(action);
      return payload({ ok: true, version: 2 });
    };
  }, { workouts: { 1: workout(1), 2: workout(2), 3: workout(3) } });
  await page.goto(pathToFileURL(appPath).href);
  await page.getByText("Редактировать шаблон", { exact: true }).waitFor();

  assert.equal(await page.getByText("Шаблон 1", { exact: true }).count(), 1);
  assert.equal(await page.getByText("Как пользоваться", { exact: true }).count(), 1);
  assert.ok(await page.locator("#strength-app").evaluate((node) => node.scrollWidth <= node.clientWidth));

  await page.getByText("Как пользоваться", { exact: true }).click();
  assert.equal(await page.getByText("Как пользоваться тренировками", { exact: true }).count(), 1);
  await page.getByText("Понятно", { exact: true }).click();

  await page.getByText("Редактировать шаблон", { exact: true }).click();
  assert.equal(await page.getByText("Редактировать шаблон 1", { exact: true }).count(), 1);
  assert.equal(await page.getByText("Добавить своё", { exact: true }).count(), 1);
  assert.equal(await page.getByText("Добавить", { exact: true }).count() > 0, true);
  assert.equal(await page.evaluate(() => document.body.style.overflow), "hidden");
  assert.equal(await page.locator(".st-manager-scroll").evaluate((node) => getComputedStyle(node).overflowY), "auto");
  assert.equal(await page.locator(".st-manager-scroll").evaluate((node) => node.scrollHeight > node.clientHeight), true);
  await page.locator(".st-manager-scroll").evaluate((node) => { node.scrollTop = 120; });
  assert.equal(await page.locator(".st-manager-scroll").evaluate((node) => node.scrollTop > 0), true);
  if (screenshots) await page.screenshot({ path: path.join(screenshots, `strength-manager-${width}.png`), fullPage: false });

  await page.getByText("Добавить", { exact: true }).first().click();
  await page.locator(".st-modal-bg").click({ position: { x: 2, y: 2 } });
  assert.equal(await page.locator(".st-modal-bg").count(), 0);
  assert.equal(await page.evaluate(() => document.body.style.overflow), "");
  assert.deepEqual(await page.evaluate(() => window.__saveActions), []);

  await page.getByText("Редактировать шаблон", { exact: true }).click();
  await page.getByText("Добавить", { exact: true }).first().click();
  await page.getByText("Готово", { exact: true }).click();
  await page.getByText("Редактировать шаблон", { exact: true }).waitFor();
  assert.equal((await page.evaluate(() => window.__saveActions)).includes("saveExerciseCatalog"), true);
  await page.close();
}

await browser.close();
console.log("strength editor mobile checks passed");
