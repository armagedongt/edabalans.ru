import assert from "node:assert/strict";
import fs from "node:fs";
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
const historyFunction = fs.readFileSync(appPath, "utf8").match(/function exerciseHistory[\s\S]*?function historySetText/)[0];
assert.doesNotMatch(historyFunction, /toLowerCase\(\).*String\(name\)/, "история упражнения не должна подменять ID совпавшим именем");

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
    sessions: empty ? [] : [{ session_id: `session-${type}-${sessionNumber}`, workout_type: type, session_number: sessionNumber, date: "2026-09-10" }],
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

function adminWorkout() {
  const base = workout(1, 1);
  const unsafeCustom = base.exercise_catalog.find((item) => item.exercise_id.startsWith("custom-"));
  unsafeCustom.active = true;
  const sessions = [];
  const sessionExercises = [];
  const sets = [];
  for (let sessionNumber = 1; sessionNumber <= 5; sessionNumber += 1) {
    const sessionId = `admin-session-${sessionNumber}`;
    sessions.push({ session_id: sessionId, workout_type: sessionNumber === 4 ? 2 : 1, session_number: sessionNumber, date: `2026-09-${String(sessionNumber).padStart(2, "0")}` });
    for (const exercise of base.session_exercises) {
      sessionExercises.push({ ...exercise, session_id: sessionId });
      for (const set of base.sets.filter((item) => item.exercise_id === exercise.exercise_id)) {
        sets.push({ ...set, session_id: sessionId, plan_weight: String(40 + sessionNumber), fact_weight: sessionNumber === 5 ? "" : String(35 + sessionNumber), fact_reps: sessionNumber === 5 ? "" : set.fact_reps, rpe: sessionNumber >= 4 ? "" : (set.set_number === 1 ? "9" : set.rpe) });
      }
    }
    sessionExercises.push({
      session_id: sessionId,
      exercise_id: unsafeCustom.exercise_id,
      exercise_name: unsafeCustom.exercise_name,
      sort_order: sessionExercises.length + 1,
      note: "",
    });
    sets.push({
      session_id: sessionId,
      exercise_id: unsafeCustom.exercise_id,
      set_number: 1,
      plan_weight: String(40 + sessionNumber),
      plan_reps: "10",
      fact_weight: sessionNumber === 5 ? "" : String(35 + sessionNumber),
      fact_reps: sessionNumber === 5 ? "" : "9",
      rpe: sessionNumber >= 4 ? "" : '<img src=x onerror="window.__strengthXss=1">',
    });
  }
  return {
    ...base,
    sessions,
    session_exercises: sessionExercises,
    sets,
  };
}

function globalWorkoutForType(workouts, type) {
  const selected = workouts[type];
  return {
    ...selected,
    version: 1,
    sessions: Object.entries(workouts).flatMap(([workoutType, item]) =>
      item.sessions.map((session) => ({ ...session, workout_type: Number(workoutType) }))),
    session_exercises: Object.values(workouts).flatMap((item) => item.session_exercises),
    sets: Object.values(workouts).flatMap((item) => item.sets),
  };
}

function addSameNamedCustomHistory(workout, exerciseId) {
  const session = workout.sessions[0];
  workout.session_exercises.push({
    session_id: session.session_id,
    exercise_id: exerciseId,
    exercise_name: "Одинаковое имя",
    sort_order: 99,
    note: "",
  });
  workout.sets.push({
    session_id: session.session_id,
    exercise_id: exerciseId,
    set_number: 1,
    plan_weight: "30",
    plan_reps: "10",
    fact_weight: "30",
    fact_reps: "10",
    rpe: "8",
  });
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
  }, (() => {
    const workouts = { 1: workout(1, 26), 2: workout(2, 25), 3: workout(3, 1, true) };
    addSameNamedCustomHistory(workouts[1], "custom-same-a");
    addSameNamedCustomHistory(workouts[2], "custom-same-b");
    workouts[1].sets
      .filter((set) => set.exercise_id === "bench-press")
      .forEach((set) => { set.fact_weight = "70"; set.fact_reps = "8"; set.rpe = "9"; });
    return { workouts: Object.fromEntries(Object.keys(workouts).map((type) => [type, globalWorkoutForType(workouts, Number(type))])) };
  })());
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
  assert.equal(savedSessions.length, 0, "Изменение будущего шаблона не переписывает прошлую сессию");
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
  await page.getByText("Шаблон 2", { exact: true }).click();
  await page.getByText("Редактировать", { exact: true }).click();
  await page.locator("#st-manager-save-state").getByText("Сохранено", { exact: true }).waitFor({ timeout: 5000 });
  const customRow = page.locator(".st-manager-row", { has: page.locator(".st-manager-name", { hasText: "Моё переименованное упражнение" }) });
  assert.equal(await customRow.count(), 1);
  assert.equal(await customRow.getByText("Добавить", { exact: true }).count(), 1);
  await page.evaluate(() => { window.__failNextSave = true; });
  await customRow.getByText("Добавить", { exact: true }).click();
  await page.getByText("Не удалось сохранить", { exact: true }).waitFor();
  if (screenshots) await page.screenshot({ path: path.join(screenshots, `strength-error-${width}.png`), fullPage: false });
  await page.locator("#st-manager-save-state").getByText("Сохранено", { exact: true }).waitFor({ timeout: 5000 });
  assert.ok((await page.evaluate(() => window.__saveActions.filter((action) => action === "saveExerciseCatalog").length)) >= 4);
  const retriedCatalogs = await page.evaluate(() => window.__saveBodies.filter((body) => body?.action === "saveExerciseCatalog"));
  assert.ok(retriedCatalogs.at(-1).exercises.some((item) => item.exercise_name === "Моё переименованное упражнение" && item.active));
  page.once("dialog", (dialog) => dialog.accept());
  await customRow.getByText("Удалить", { exact: true }).click();
  assert.equal(await page.locator(".st-manager-name", { hasText: "Моё переименованное упражнение" }).count(), 0);
  assert.equal(await page.getByText("Закрыть", { exact: true }).count(), 1);
  await page.getByText("Закрыть", { exact: true }).click();
  await page.locator("#st-save-state").getByText("Сохранено", { exact: true }).waitFor({ timeout: 5000 });
  await page.getByText("Редактировать", { exact: true }).waitFor();
  await page.getByText(/Тренировка №(25|26)/, { exact: true }).waitFor();
  const expectedDate = await page.evaluate(() => {
    const date = new Date();
    const pad = (value) => String(value).padStart(2, "0");
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
  });
  const catalogBeforeCreate = await page.evaluate(() => window.__saveBodies.filter((body) => body?.action === "saveExerciseCatalog" && body.workout_type === 2).at(-1));
  await page.getByText("Новая тренировка", { exact: false }).click();
  await page.getByText("Тренировка №27", { exact: true }).waitFor();
  if (screenshots) await page.screenshot({ path: path.join(screenshots, `strength-new-session-${width}.png`), fullPage: false });
  const createdSessions = await page.evaluate(() => window.__saveBodies.filter((body) => body?.action === "saveSession" && body.session?.session_number === 27));
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
  await page.waitForFunction(() => window.__saveBodies.some((body) => body?.action === "saveSession" && body.session?.session_number === 27 && body.session.exercises.some((exercise) => exercise.exercise_id === "bench-press" && String(exercise.sets[0].plan_weight) === "55")));
  await page.locator("#st-save-state").getByText("Сохранено", { exact: true }).waitFor({ timeout: 5000 });
  await page.getByRole("button", { name: "Отменить действие" }).click();
  assert.equal(await page.locator(".st-modern-set.edit input").first().inputValue(), "");
  await page.getByRole("button", { name: "Повторить действие" }).click();
  assert.equal(await page.locator(".st-modern-set.edit input").first().inputValue(), "55");
  await page.locator("#strength-app").click({ position: { x: 4, y: 4 } });
  await page.keyboard.press("Control+Z");
  assert.equal(await page.locator(".st-modern-set.edit input").first().inputValue(), "");
  await page.keyboard.press("Control+Shift+Z");
  assert.equal(await page.locator(".st-modern-set.edit input").first().inputValue(), "55");
  const savesBeforeNavigation = await page.evaluate(() => window.__saveBodies.filter((body) => body?.action === "saveSession").length);
  await page.getByRole("button", { name: "Предыдущая тренировка" }).click();
  await page.getByText("Тренировка №26", { exact: true }).waitFor();
  await page.locator(".st-modern-copy").first().click();
  await page.waitForFunction(() => window.__saveBodies.some((body) => body?.action === "saveSession" && body.session?.session_number === 27 && body.session.exercises.some((exercise) => exercise.exercise_id === "bench-press" && String(exercise.sets[0].plan_weight) === "40")));
  const copiedPlan = await page.evaluate(() => window.__saveBodies.filter((body) => body?.action === "saveSession" && body.session?.session_number === 27).at(-1));
  const destinationBench = copiedPlan.session.exercises.filter((exercise) => exercise.exercise_id === "bench-press");
  assert.equal(destinationBench.length, 1);
  const copiedSet = destinationBench[0].sets[0];
  assert.equal(String(copiedSet.plan_weight), "40");
  assert.equal(copiedSet.fact_weight, "");
  assert.equal(copiedSet.rpe, "");
  assert.ok(await page.evaluate(() => window.__saveBodies.filter((body) => body?.action === "saveSession").length) > savesBeforeNavigation);

  await page.getByText("Шаблон 3", { exact: true }).click();
  await page.getByText("Редактировать", { exact: true }).click();
  const firstExercise = page.locator(".st-manager-row").first();
  await firstExercise.getByText("Добавить", { exact: true }).click();
  await page.getByText("Закрыть", { exact: true }).click();
  if (screenshots) await page.screenshot({ path: path.join(screenshots, `strength-empty-template-${width}.png`), fullPage: false });
  await page.getByText("Новая тренировка", { exact: false }).click();
  await page.getByText("Тренировка №28", { exact: true }).waitFor();
  const firstSession = await page.evaluate(() => window.__saveBodies.find((body) => body?.action === "saveSession" && body.workout_type === 3));
  assert.equal(firstSession.session.session_number, 28);
  await page.close();
}

for (const width of [768, 1440]) {
  const page = await browser.newPage({ viewport: { width, height: 900 } });
  await page.addInitScript(({ workouts }) => {
    window.EdabalansAppContext = { mode: "admin", targetUserId: "managed-preview", accountUrl: "/admin/strength" };
    window.__saveBodies = [];
    window.__strengthXss = 0;
    const payload = (value) => Promise.resolve(new Response(JSON.stringify(value), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }));
    window.fetch = (url, options = {}) => {
      const parsed = new URL(String(url), "https://edabalans.ru");
      const body = options.body ? JSON.parse(options.body) : null;
      const action = body?.action || parsed.searchParams.get("action");
      if (action === "openUser") return payload({ ok: true, user: { user_id: "managed-preview", email: "preview@example.test", display_name: "Администраторский предпросмотр" } });
      if (action === "getWorkout") {
        const type = Number(body?.type || parsed.searchParams.get("type") || 1);
        return payload({ ok: true, workout: workouts[type] });
      }
      window.__saveBodies.push(body ? structuredClone(body) : null);
      return payload({
        ok: true,
        version: 2,
        session: action === "saveSession"
          ? { ...body.session, session_id: body.session.session_id || `server-${body.session.session_number}` }
          : undefined,
      });
    };
  }, (() => {
    const workouts = { 1: adminWorkout(), 2: workout(2, 1, true), 3: workout(3, 1, true) };
    return { workouts: Object.fromEntries(Object.keys(workouts).map((type) => [type, globalWorkoutForType(workouts, Number(type))])) };
  })());
  await page.goto(pathToFileURL(appPath).href);
  await page.getByText("План и факт по тренировкам", { exact: true }).waitFor();
  await page.waitForTimeout(100);
  assert.equal(await page.evaluate(() => window.__strengthXss), 0);

  assert.equal(await page.locator(".st-admin-sheet .st-day-head").count(), 3);
  assert.deepEqual(await page.locator(".st-admin-sheet .st-day-number").allTextContents(), ["№3", "№4", "№5"]);
  assert.ok(await page.locator(".st-admin-sheet .st-plan-field").count() > 0);
  assert.ok(await page.locator(".st-admin-sheet .st-fact-field").count() > 0);
  const planColor = await page.locator(".st-admin-sheet .st-plan-field").first().evaluate((node) => getComputedStyle(node).backgroundColor);
  const factColor = await page.locator(".st-admin-sheet .st-fact-field").first().evaluate((node) => getComputedStyle(node).backgroundColor);
  assert.notEqual(planColor, factColor);
  const firstExerciseDays = page.locator(".st-admin-sheet .st-ex-row").first().locator(".st-ex-day");
  const firstExerciseRow = page.locator(".st-admin-sheet .st-ex-row").first();
  assert.equal(await firstExerciseRow.locator(".st-ex-row-head").count(), 1, "у упражнения один общий заголовок на три дня");
  assert.equal(await firstExerciseRow.locator(".st-ex-row-name").count(), 1, "название упражнения не повторяется в дневных колонках");
  assert.equal(await firstExerciseRow.getByText("Жим штанги лёжа", { exact: true }).count(), 1, "видимое название упражнения встречается в строке только один раз");
  assert.equal(await firstExerciseRow.locator(".st-ex-name").count(), 0, "в дневных колонках нет отдельных заголовков упражнения");
  assert.equal(await firstExerciseRow.evaluate((node) => getComputedStyle(node).backgroundColor), "rgb(255, 255, 255)", "тело упражнения остаётся нейтральным");
  assert.notEqual(await firstExerciseRow.locator(".st-ex-row-head").evaluate((node) => getComputedStyle(node).backgroundColor), "rgb(255, 255, 255)", "цвет упражнения остаётся только в общей шапке");
  assert.equal(await firstExerciseRow.locator(".st-ex-row-days").evaluate((node) => getComputedStyle(node).backgroundColor), "rgba(0, 0, 0, 0)", "под шапкой нет отдельной цветной подложки");
  assert.equal(await firstExerciseDays.evaluateAll((nodes) => new Set(nodes.map((node) => getComputedStyle(node).backgroundColor)).size), 1, "три дневные области не получают разные фоны");
  assert.equal(await firstExerciseDays.evaluateAll((nodes) => nodes.every((node) => getComputedStyle(node).backgroundColor === "rgba(0, 0, 0, 0)")), true, "равномерный фон строки идёт от общего блока, а не от отдельных карточек");
  assert.equal(await page.locator(".st-admin-sheet .st-group-plan").first().evaluate((node) => getComputedStyle(node).backgroundColor), "rgba(0, 0, 0, 0)", "ярлык плана не получает отдельную заливку");
  assert.equal(await page.locator(".st-admin-sheet .st-group-fact").first().evaluate((node) => getComputedStyle(node).backgroundColor), "rgba(0, 0, 0, 0)", "ярлык факта не получает отдельную заливку");
  assert.equal(await firstExerciseRow.locator(".st-ex-day.current .st-fact-field.has-value").count(), 0, "пустые поля факта не подсвечиваются");
  assert.equal(await firstExerciseRow.locator(".st-ex-day.current .st-plan-field.has-value").count() > 0, true, "заполненные поля плана подсвечиваются");
  assert.equal(await firstExerciseRow.locator(".st-ex-day.current .st-admin-set-actions button").count(), 2, "в текущей незаполненной тренировке видны добавить и удалить подход");
  assert.ok(await page.locator(".st-admin-sheet .plan-up").count() > 0, "изменённый план сохраняет подсветку относительно прошлого факта");
  assert.ok(await page.locator(".st-admin-sheet .rpe9").count() > 0, "RPE сохраняет привычную шкалу цвета");
  assert.ok(await page.locator(".st-admin-sheet .st-divider").count() > 0);
  const unsafeId = "custom-x');window.__strengthXss=1;//";
  const unsafeHandlers = await page.locator(".st-admin-sheet").evaluate((sheet, exerciseId) => {
    const selectors = { hide: ".st-row-hide", plan: ".st-plan-field", fact: ".st-fact-field", rpe: ".st-fact-rpe", note: ".st-note" };
    return Object.fromEntries(Object.entries(selectors).map(([name, selector]) => [name, Array.from(sheet.querySelectorAll(selector))
      .filter((node) => node.dataset.exerciseId === exerciseId)
      .map((node) => `${node.getAttribute("onclick") || ""} ${node.getAttribute("onchange") || ""}`)]));
  }, unsafeId);
  const expectedHandlerCounts = { hide: 1, plan: 6, fact: 6, rpe: 3, note: 3 };
  for (const [name, handlers] of Object.entries(unsafeHandlers)) {
    assert.equal(handlers.length, expectedHandlerCounts[name]);
    handlers.forEach((handler) => {
      assert.ok(handler.includes("this.dataset.exerciseId"), `${name}: ${handler}`);
      assert.equal(handler.includes(unsafeId), false);
    });
  }
  assert.equal(await page.locator(".st-modern-list").count(), 0);
  assert.ok(await page.locator("#strength-app").evaluate((node) => node.scrollWidth <= node.clientWidth));
  if (screenshots) await page.screenshot({ path: path.join(screenshots, `strength-admin-sheet-${width}.png`), fullPage: false });

  await page.locator(".st-admin-sheet .st-fact-field").last().click();
  assert.equal(await page.evaluate(() => window.__strengthXss), 0);
  const factField = page.locator(".st-admin-sheet .st-fact-field").first();
  await factField.fill("37");
  await factField.blur();
  await page.waitForFunction(() => window.__saveBodies.some((body) => body?.action === "saveSession" && body.session?.session_number === 3 && body.session.exercises.some((exercise) => exercise.sets.some((set) => set.fact_weight === 37))));

  const customExerciseRow = page.locator(".st-admin-sheet .st-ex-row", { hasText: "Пользовательское упражнение" });
  await customExerciseRow.locator(".st-row-hide").click();
  await page.waitForFunction((exerciseId) => window.__saveBodies.some((body) => body?.action === "saveSession" && body.session?.session_number === 5 && !body.session.exercises.some((exercise) => exercise.exercise_id === exerciseId)), unsafeId);
  assert.equal(await customExerciseRow.locator(".st-ex-day").nth(0).locator(".st-set").count() > 0, true, "скрытие из №5 не затрагивает историческую №3");
  assert.equal(await customExerciseRow.locator(".st-ex-day").nth(1).locator(".st-set").count() > 0, true, "скрытие из №5 не затрагивает историческую №4");
  assert.equal(await customExerciseRow.locator(".st-ex-day").nth(2).locator(".st-set").count(), 0, "упражнение исчезает из выбранной №5 сразу после скрытия");
  await page.getByRole("button", { name: "Отменить действие" }).click();
  await page.waitForFunction((exerciseId) => window.__saveBodies.some((body) => body?.action === "saveSession" && body.session?.session_number === 5 && body.session.exercises.some((exercise) => exercise.exercise_id === exerciseId)), unsafeId);
  assert.ok(await customExerciseRow.locator(".st-ex-day").nth(2).locator(".st-set").count() > 0, "отмена сразу возвращает упражнение в выбранную №5");
  await page.getByRole("button", { name: "Предыдущая тренировка" }).click();
  await page.getByText("Тренировка №4", { exact: true }).waitFor();
  assert.equal(await page.locator(".st-admin-sheet .st-row-hide").count(), 0, "у заполненной тренировки нет кнопки скрытия");
  await page.getByRole("button", { name: "Следующая тренировка" }).click();
  await page.getByText("Тренировка №5", { exact: true }).waitFor();

  assert.equal(await page.locator(".st-admin-window-nav button").count(), 2);
  await page.getByText("← Предыдущие", { exact: true }).click();
  await page.locator(".st-admin-sheet .st-day-number").nth(2).getByText("№4", { exact: true }).waitFor();
  assert.deepEqual(await page.locator(".st-admin-sheet .st-day-number").allTextContents(), ["№2", "№3", "№4"]);
  await page.getByText("← Предыдущие", { exact: true }).click();
  assert.deepEqual(await page.locator(".st-admin-sheet .st-day-number").allTextContents(), ["№1", "№2", "№3"]);
  await page.getByText("← Предыдущие", { exact: true }).click();
  assert.deepEqual(await page.locator(".st-admin-sheet .st-day-number").allTextContents(), ["№1", "№2"]);
  await page.getByText("← Предыдущие", { exact: true }).click();
  assert.deepEqual(await page.locator(".st-admin-sheet .st-day-number").allTextContents(), ["№1"]);
  assert.equal(await page.getByText("← Предыдущие", { exact: true }).isDisabled(), true);
  for (let index = 0; index < 4; index += 1) {
    await page.getByText("Следующие →", { exact: true }).click();
  }
  assert.deepEqual(await page.locator(".st-admin-sheet .st-day-number").allTextContents(), ["№3", "№4", "№5"]);
  assert.equal(await page.getByText("Следующие →", { exact: true }).isDisabled(), true);

  const copyForward = page.locator(".st-admin-sheet .st-copy-forward").first();
  assert.equal(await copyForward.innerText(), "Копировать");
  assert.equal(await copyForward.getAttribute("aria-label"), "Скопировать план в ближайшую незавершённую тренировку");
  assert.equal(await copyForward.locator("xpath=..").getByText("План", { exact: true }).count(), 1, "кнопка стоит в области плана");
  await copyForward.click();
  await page.waitForFunction(() => window.__saveBodies.some((body) => body?.action === "saveSession" && body.session?.session_number === 5 && body.session.exercises.some((exercise) => exercise.exercise_id === "bench-press" && String(exercise.sets[0].plan_weight) === "43" && exercise.sets[0].fact_weight === "")));
  assert.deepEqual(await page.locator(".st-admin-sheet .st-day-number").allTextContents(), ["№3", "№4", "№5"]);

  await page.getByText("Новая тренировка", { exact: false }).click();
  await page.getByText("Тренировка №6", { exact: true }).waitFor();
  await page.locator(".st-admin-sheet .st-day-head").nth(2).waitFor();
  assert.equal(await page.locator(".st-admin-sheet .st-day-head").count(), 3);
  assert.deepEqual(await page.locator(".st-admin-sheet .st-day-number").allTextContents(), ["№4", "№5", "№6"]);
  assert.ok(await page.evaluate(() => window.__saveBodies.some((body) => body?.action === "saveSession" && body.session?.session_number === 6)));
  await page.getByRole("button", { name: "Предыдущая тренировка" }).click();
  await page.getByText("Тренировка №5", { exact: true }).waitFor();
  assert.ok(await page.locator(".st-admin-sheet .st-row-hide").count() > 0, "выбранная незаполненная тренировка сохраняет одну кнопку скрытия даже при существующей следующей");
  await page.getByRole("button", { name: "Следующая тренировка" }).click();
  await page.getByText("Тренировка №6", { exact: true }).waitFor();

  const filledLastSession = page.locator(".st-admin-sheet .st-ex-row").first().locator(".st-ex-day").nth(2).locator(".st-fact-field").first();
  await filledLastSession.fill("47");
  await filledLastSession.blur();
  await page.waitForFunction(() => window.__saveBodies.some((body) => body?.action === "saveSession" && body.session?.session_number === 6 && body.session.exercises.some((exercise) => exercise.exercise_id === "bench-press" && String(exercise.sets[0].fact_weight) === "47")));
  await page.locator(".st-admin-sheet .st-ex-row").first().locator(".st-ex-day").nth(1).locator(".st-copy-forward").click();
  await page.getByText("Тренировка №7", { exact: true }).waitFor();
  await page.waitForFunction((customExerciseId) => window.__saveBodies.some((body) => body?.action === "saveSession" && body.session?.session_number === 7 && body.session.exercises.some((exercise) => exercise.exercise_id === "bench-press" && String(exercise.sets[0].plan_weight) === "43" && exercise.sets[0].fact_weight === "") && body.session.exercises.some((exercise) => exercise.exercise_id === customExerciseId)), unsafeId);
  assert.deepEqual(await page.locator(".st-admin-sheet .st-day-number").allTextContents(), ["№5", "№6", "№7"]);
  await page.close();
}

await browser.close();
console.log("strength editor mobile checks passed");
