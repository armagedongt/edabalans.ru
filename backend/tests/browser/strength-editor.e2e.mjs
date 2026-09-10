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

function workout(type, sessionNumber = 1, empty = false) {
  const names = [
    "Жим штанги лёжа", "Жим лёжа узким хватом", "Жим гантелей на наклонной скамье",
    "Подтягивания в гравитроне", "Тяга верхнего блока сидя", "Тяга горизонтального блока",
    "Подтягивания", "Тяга гантели в наклоне", "Тяга штанги в наклоне", "Приседания со штангой", "Жим ногами",
    "Выпады", "Румынская тяга", "Становая тяга",
    "Ягодичный мост", "Сгибание ног в тренажёре", "Разгибание ног в тренажёре",
    "Сведение ног в тренажёре", "Разведение ног в тренажёре", "Подъёмы на носки",
    "Сгибание рук с гантелями", "Тяга верхнего блока на трицепс",
    "Разведение гантелей в стороны", "Разведение рук на заднюю дельту",
    "Подъём гантелей на бицепс сидя на наклонной скамье",
  ];
  const catalog = names.map((name, index) => ({
    exercise_id: index === 0 ? "bench-press" : index === 1 ? "lat-pulldown" : `base-${index + 1}`,
    exercise_name: name,
    active: !empty && (index === 0 || (index === 1 && type === 2)),
    catalog_active: true,
    sort_order: index + 1,
    source: "base",
    muscles: "Основные работающие мышцы",
    tips: ["Первый ориентир", "Второй ориентир"],
  }));
  catalog.push({
    exercise_id: "custom-x');window.__strengthXss=1;//",
    exercise_name: "Пользовательское упражнение",
    active: false,
    catalog_active: true,
    sort_order: catalog.length + 1,
    source: "custom",
    muscles: "",
    tips: [],
  });
  const exercises = catalog.filter((item) => item.active).map((item, index) => ({
    session_id: `session-${type}-${sessionNumber}`,
    exercise_id: item.exercise_id,
    exercise_name: item.exercise_name,
    sort_order: index + 1,
    note: "",
  }));
  return {
    workout_types: [],
    exercise_catalog: catalog,
    sessions: empty ? [] : [{ session_id: `session-${type}-${sessionNumber}`, session_number: sessionNumber, date: "2026-09-10" }],
    session_exercises: empty ? [] : exercises,
    sets: empty ? [] : exercises.flatMap((exercise) => [1, 2, 3, 4].map((setNumber) => ({
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

for (const width of [360, 430, 768, 1440]) {
  const page = await browser.newPage({ viewport: { width, height: 900 } });
  await page.addInitScript(({ workouts }) => {
    window.EdabalansIdentity = { source: "native", email: "preview@example.test" };
    window.__saveActions = [];
    window.__saveBodies = [];
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
      window.__saveBodies.push(body ? structuredClone(body) : null);
      if (window.__failNextSave && action === "saveExerciseCatalog") {
        window.__failNextSave = false;
        return payload({ ok: false, error: "Сеть недоступна" });
      }
      const responseBody = action === "saveSession"
        ? {
            ok: true,
            version: 2,
            session: {
              ...body.session,
              session_id: body.session.session_id || `server-${body.workout_type}-${body.session.session_number}`,
            },
          }
        : { ok: true, version: 2 };
      return new Promise((resolve) => setTimeout(() => resolve(new Response(JSON.stringify(responseBody), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })), 120));
    };
  }, { workouts: { 1: workout(1, 26), 2: workout(2, 4), 3: workout(3, 1, true) } });
  await page.goto(pathToFileURL(appPath).href);
  await page.getByText("Редактировать", { exact: true }).waitFor();

  assert.equal(await page.getByText("Шаблон 1", { exact: true }).count(), 1);
  assert.equal(await page.getByText("Как пользоваться", { exact: true }).count(), 1);
  assert.ok(await page.locator("#strength-app").evaluate((node) => node.scrollWidth <= node.clientWidth));
  if (screenshots) await page.screenshot({ path: path.join(screenshots, `strength-closed-${width}.png`), fullPage: false });

  await page.getByText("Как пользоваться", { exact: true }).click();
  assert.equal(await page.getByText("Как пользоваться тренировками", { exact: true }).count(), 1);
  if (screenshots) await page.screenshot({ path: path.join(screenshots, `strength-tutorial-${width}.png`), fullPage: false });
  await page.getByText("Понятно", { exact: true }).click();

  await page.getByText("Редактировать", { exact: true }).click();
  assert.equal(await page.getByText("Редактировать · Шаблон 1", { exact: true }).count(), 1);
  assert.equal(await page.getByText("Добавить своё", { exact: true }).count(), 1);
  assert.equal(await page.getByText("Добавить", { exact: true }).count() > 0, true);
  assert.equal(await page.getByText("Изменения применяются сразу.", { exact: false }).count(), 1);
  assert.equal(await page.getByText("Готово", { exact: true }).count(), 0);
  assert.equal(await page.getByText("Отменить", { exact: false }).isDisabled(), true);
  assert.equal(await page.evaluate(() => document.body.style.overflow), "hidden");
  assert.equal(await page.locator(".st-manager-scroll").evaluate((node) => getComputedStyle(node).overflowY), "auto");
  assert.equal(await page.locator(".st-manager-scroll").evaluate((node) => node.scrollHeight > node.clientHeight), true);
  if (width === 360) {
    await page.evaluate(() => { window.__strengthXss = 0; });
    page.once("dialog", (dialog) => dialog.dismiss());
    await page.locator(".st-manager-row", { hasText: "Пользовательское упражнение" }).getByText("Изменить", { exact: true }).click();
    assert.equal(await page.evaluate(() => window.__strengthXss), 0);
    await page.locator(".st-manager-row", { hasText: "Пользовательское упражнение" }).getByText("Добавить", { exact: true }).click();
  }
  await page.locator(".st-manager-scroll").evaluate((node) => { node.scrollTop = 120; });
  assert.equal(await page.locator(".st-manager-scroll").evaluate((node) => node.scrollTop > 0), true);
  if (screenshots) await page.screenshot({ path: path.join(screenshots, `strength-manager-${width}.png`), fullPage: false });

  const undoProbeRow = page.locator(".st-manager-row", { hasText: "Жим лёжа узким хватом" });
  await undoProbeRow.getByText("Добавить", { exact: true }).click();
  await page.getByText("Отменить", { exact: false }).click();
  assert.equal(await undoProbeRow.getByText("Добавить", { exact: true }).count(), 1);
  await page.waitForFunction(() => {
    const saved = window.__saveBodies.filter((body) => body?.action === "saveExerciseCatalog" && body.workout_type === 1).at(-1);
    return saved?.exercises.find((item) => item.exercise_id === "lat-pulldown")?.active === false;
  });
  const undoCatalogs = await page.evaluate(() => window.__saveBodies.filter((body) => body?.action === "saveExerciseCatalog" && body.workout_type === 1));
  assert.equal(undoCatalogs.at(-1).exercises.find((item) => item.exercise_id === "lat-pulldown").active, false);
  assert.equal(await page.getByText("Отменить", { exact: false }).isDisabled(), width !== 360);
  await undoProbeRow.getByText("Добавить", { exact: true }).click();
  await page.waitForFunction(() => window.__saveActions.includes("saveExerciseCatalog"));
  if (screenshots) await page.screenshot({ path: path.join(screenshots, `strength-saving-${width}.png`), fullPage: false });
  await page.locator("#st-new-exercise").fill("Моё упражнение");
  await page.getByText("Добавить своё", { exact: true }).click();
  await page.locator(".st-manager-name", { hasText: "Моё упражнение" }).waitFor();
  await page.locator("#st-manager-save-state").getByText("Сохранено", { exact: true }).waitFor();
  const savedCatalogs = await page.evaluate(() => window.__saveBodies.filter((body) => body?.action === "saveExerciseCatalog"));
  assert.ok(savedCatalogs.length >= 2);
  assert.ok(savedCatalogs.at(-1).exercises.some((item) => item.exercise_name === "Моё упражнение" && item.catalog_active));
  assert.ok(savedCatalogs.at(-1).exercises.some((item) => item.exercise_name === "Жим лёжа узким хватом" && item.active));
  const savedSessions = await page.evaluate(() => window.__saveBodies.filter((body) => body?.action === "saveSession"));
  assert.ok(savedSessions.length >= 1);
  assert.ok(savedSessions.at(-1).session.exercises.some((item) => item.exercise_name === "Моё упражнение"));
  const customRowBeforeRename = page.locator(".st-manager-row", { has: page.locator(".st-manager-name", { hasText: "Моё упражнение" }) });
  page.once("dialog", (dialog) => dialog.accept("Моё переименованное упражнение"));
  await customRowBeforeRename.getByText("Изменить", { exact: true }).click();
  await page.locator(".st-manager-name", { hasText: "Моё переименованное упражнение" }).waitFor();
  const renamedRow = page.locator(".st-manager-row", { has: page.locator(".st-manager-name", { hasText: "Моё переименованное упражнение" }) });
  await renamedRow.getByRole("button", { name: "Выше" }).click();
  await page.locator(".st-modal-bg").click({ position: { x: 2, y: 2 } });
  assert.equal(await page.locator(".st-modal-bg").count(), 0);
  assert.equal(await page.evaluate(() => document.body.style.overflow), "");
  assert.equal((await page.evaluate(() => window.__saveActions)).includes("saveExerciseCatalog"), true);
  if (width === 360) {
    const maliciousExercise = page.locator("article.st-modern-exercise", { hasText: "Пользовательское упражнение" });
    await maliciousExercise.getByRole("button", { name: "Открыть историю упражнения" }).click();
    assert.equal(await page.evaluate(() => window.__strengthXss), 0);
    await page.locator(".st-modal-bg").click({ position: { x: 2, y: 2 } });
  }

  await page.getByText("Шаблон 2", { exact: true }).click();
  await page.getByText("Редактировать", { exact: true }).click();
  const customRow = page.locator(".st-manager-row", { has: page.locator(".st-manager-name", { hasText: "Моё переименованное упражнение" }) });
  assert.equal(await customRow.count(), 1);
  assert.equal(await customRow.getByText("Добавить", { exact: true }).count(), 1);
  await page.evaluate(() => { window.__failNextSave = true; });
  await page.getByText("Добавить", { exact: true }).first().click();
  await page.getByText("Не удалось сохранить", { exact: true }).waitFor();
  if (screenshots) await page.screenshot({ path: path.join(screenshots, `strength-error-${width}.png`), fullPage: false });
  await page.locator("#st-manager-save-state").getByText("Сохранено", { exact: true }).waitFor({ timeout: 5000 });
  assert.ok((await page.evaluate(() => window.__saveActions.filter((action) => action === "saveExerciseCatalog").length)) >= 4);
  const retriedCatalogs = await page.evaluate(() => window.__saveBodies.filter((body) => body?.action === "saveExerciseCatalog"));
  assert.ok(retriedCatalogs.at(-1).exercises.some((item) => item.exercise_name === "Жим гантелей на наклонной скамье" && item.active));
  page.once("dialog", (dialog) => dialog.accept());
  await customRow.getByText("Удалить", { exact: true }).click();
  assert.equal(await page.locator(".st-manager-name", { hasText: "Моё переименованное упражнение" }).count(), 0);
  assert.equal(await page.getByText("Закрыть", { exact: true }).count(), 1);
  await page.getByText("Закрыть", { exact: true }).click();
  await page.locator("#st-save-state").getByText("Сохранено", { exact: true }).waitFor({ timeout: 5000 });
  await page.getByText("Редактировать", { exact: true }).waitFor();
  assert.equal(await page.getByText("Тренировка №4", { exact: true }).count(), 1);
  const expectedDate = await page.evaluate(() => {
    const date = new Date();
    const pad = (value) => String(value).padStart(2, "0");
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
  });
  const catalogBeforeCreate = await page.evaluate(() => window.__saveBodies.filter((body) => body?.action === "saveExerciseCatalog" && body.workout_type === 2).at(-1));
  await page.getByText("Новая тренировка", { exact: false }).click();
  await page.getByText("Тренировка №5", { exact: true }).waitFor();
  if (screenshots) await page.screenshot({ path: path.join(screenshots, `strength-new-session-${width}.png`), fullPage: false });
  const createdSessions = await page.evaluate(() => window.__saveBodies.filter((body) => body?.action === "saveSession" && body.session?.session_number === 5));
  assert.equal(createdSessions.length, 1);
  assert.equal(createdSessions[0].workout_type, 2);
  assert.equal(createdSessions[0].session.date, expectedDate);
  assert.deepEqual(
    createdSessions[0].session.exercises.map((item) => item.exercise_id),
    catalogBeforeCreate.exercises.filter((item) => item.active && item.catalog_active !== false).map((item) => item.exercise_id),
  );
  assert.equal(await page.getByRole("button", { name: "Предыдущая тренировка" }).isEnabled(), true);
  assert.equal(await page.getByRole("button", { name: "Следующая тренировка" }).isDisabled(), true);
  const firstPlanInput = page.locator(".st-modern-set.edit input").first();
  await firstPlanInput.fill("55");
  await firstPlanInput.blur();
  await page.waitForFunction(() => window.__saveBodies.some((body) => body?.action === "saveSession" && body.session?.session_id === "server-2-5"));
  const savesBeforeNavigation = await page.evaluate(() => window.__saveBodies.filter((body) => body?.action === "saveSession").length);
  await page.getByRole("button", { name: "Предыдущая тренировка" }).click();
  await page.getByText("Тренировка №4", { exact: true }).waitFor();
  await page.getByRole("button", { name: "Следующая тренировка" }).click();
  await page.getByText("Тренировка №5", { exact: true }).waitFor();
  assert.equal(await page.evaluate(() => window.__saveBodies.filter((body) => body?.action === "saveSession").length), savesBeforeNavigation);

  await page.getByText("Шаблон 3", { exact: true }).click();
  await page.getByText("Редактировать", { exact: true }).click();
  const firstExercise = page.locator(".st-manager-row").first();
  await firstExercise.getByText("Добавить", { exact: true }).click();
  await page.getByText("Закрыть", { exact: true }).click();
  if (screenshots) await page.screenshot({ path: path.join(screenshots, `strength-empty-template-${width}.png`), fullPage: false });
  await page.getByText("Создать первую тренировку", { exact: false }).click();
  await page.getByText("Тренировка №1", { exact: true }).waitFor();
  const firstSession = await page.evaluate(() => window.__saveBodies.find((body) => body?.action === "saveSession" && body.workout_type === 3));
  assert.equal(firstSession.session.session_number, 1);
  await page.close();
}

await browser.close();
console.log("strength editor mobile checks passed");
