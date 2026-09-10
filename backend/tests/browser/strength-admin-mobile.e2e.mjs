import assert from "node:assert/strict";
import { createServer } from "node:http";
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import path from "node:path";

const require = createRequire(import.meta.url);
const modulesRoot = process.env.CODEX_NODE_MODULES;
if (!modulesRoot) throw new Error("CODEX_NODE_MODULES is required");
const { chromium } = require(path.join(modulesRoot, "playwright"));

const staticRoot = path.resolve("app/static");
const people = {
  owner: { id: "owner", display_name: "Сергей", email: "owner@example.test" },
  valentina: { id: "valentina", display_name: "Валентина Капитанова", email: "valentina@example.test" },
};
const appRequests = [];
const userListRequests = [];

function json(response, body) {
  response.writeHead(200, { "Content-Type": "application/json" });
  response.end(JSON.stringify(body));
}

function workout() {
  return {
    workout_types: [],
    exercise_catalog: [{
      exercise_id: "bench-press", exercise_name: "Жим штанги лёжа", active: true,
      catalog_active: true, sort_order: 1, source: "base", muscles: "Грудные мышцы",
      tips: ["Сведите лопатки", "Контролируйте движение"],
    }],
    sessions: [{ session_id: "one", session_number: 1, date: "2026-09-10" }],
    session_exercises: [{ session_id: "one", exercise_id: "bench-press", exercise_name: "Жим штанги лёжа", sort_order: 1, note: "" }],
    sets: [1, 2, 3, 4].map((set_number) => ({ session_id: "one", exercise_id: "bench-press", set_number, plan_weight: "40", plan_reps: "10", fact_weight: "", fact_reps: "", rpe: "" })),
  };
}

const server = createServer(async (request, response) => {
  const url = new URL(request.url, "http://127.0.0.1");
  const selected = people[url.searchParams.get("user")] || people.owner;
  if (url.pathname === "/admin/strength") {
    response.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
    return response.end(readFileSync(path.join(staticRoot, "admin.html")));
  }
  const assets = {
    "/admin/static/admin.css": "admin.css",
    "/admin/static/admin.js": "admin.js",
    "/admin/static/admin-session.css": "admin-session.css",
    "/admin/static/marketing.css": "marketing.css",
    "/embed.js": "embed.js",
    "/apps/strength.html": "apps/strength.html",
  };
  if (assets[url.pathname]) {
    const name = assets[url.pathname];
    response.writeHead(200, { "Content-Type": name.endsWith(".css") ? "text/css" : name.endsWith(".js") ? "text/javascript" : "text/html; charset=utf-8" });
    return response.end(readFileSync(path.join(staticRoot, name)));
  }
  if (url.pathname === "/admin/api/apps/users") {
    userListRequests.push(Object.fromEntries(url.searchParams));
    return json(response, { ok: true, users: Object.values(people).map((user) => ({ user_id: user.id, display_name: user.display_name, email: user.email, has_state: true, summary: { sessions: 1, filled_sessions: 1 } })) });
  }
  if (/^\/admin\/api\/users\/[^/]+\/modules$/.test(url.pathname)) {
    return json(response, { ok: true, modules: { dqs: { exists: false, has_access: false }, strength: { exists: true, has_access: true }, metabolism: { exists: false, has_access: false }, telegram: { exists: true } } });
  }
  if (/^\/admin\/api\/apps\/strength\/users\/[^/]+$/.test(url.pathname)) {
    const id = url.pathname.split("/").at(-1);
    const user = people[id] || people.owner;
    return json(response, { ok: true, user, has_access: true, has_state: true, state: { summary: { sessions: 1 } } });
  }
  if (url.pathname === "/api/apps/strength") {
    const body = request.method === "POST"
      ? await new Promise((resolve) => {
          let raw = "";
          request.on("data", (chunk) => { raw += chunk; });
          request.on("end", () => resolve(raw ? JSON.parse(raw) : {}));
        })
      : {};
    const targetUserId = body.target_user_id || url.searchParams.get("target_user_id");
    const managed = people[targetUserId] || selected;
    const action = url.searchParams.get("action");
    const resolvedAction = body.action || action;
    appRequests.push({ action: resolvedAction, target_user_id: targetUserId });
    if (resolvedAction === "openUser") return json(response, { ok: true, user: { user_id: managed.id, display_name: managed.display_name, email: managed.email } });
    if (resolvedAction === "getWorkout") return json(response, { ok: true, user: managed, workout: workout() });
    return json(response, { ok: true, version: 2 });
  }
  response.writeHead(404);
  response.end("not found");
});

await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const { port } = server.address();
const browser = await chromium.launch({ headless: true });
const screenshots = process.env.STRENGTH_ADMIN_EVIDENCE_DIR;

for (const width of [360, 430, 768, 1440]) {
  const page = await browser.newPage({ viewport: { width, height: 900 } });
  await page.goto(`http://127.0.0.1:${port}/admin/strength?mobile=1&user=owner`);
  await page.getByText("Жим штанги лёжа", { exact: true }).first().waitFor();
  assert.equal(await page.locator(".admin-sidebar:visible").count(), 0);
  assert.ok(await page.locator("body").evaluate((node) => node.scrollWidth <= node.clientWidth));
  await page.getByRole("button", { name: /Сергей/ }).click();
  await page.getByRole("dialog", { name: "Выберите клиента" }).waitFor();
  assert.ok(userListRequests.some((item) => item.app_code === "strength" && item.with_records === "true"));
  assert.equal(await page.evaluate(() => document.body.classList.contains("strength-mobile-picker-open")), true);
  await page.getByPlaceholder("Например, anna@mail.ru").fill("valentina@example");
  assert.equal(await page.locator(".strength-mobile-person").count(), 1);
  if (screenshots) await page.screenshot({ path: path.join(screenshots, `strength-admin-picker-${width}.png`), fullPage: false });
  await page.getByRole("button", { name: /Валентина Капитанова/ }).click();
  await page.getByRole("button", { name: /Валентина Капитанова/ }).waitFor();
  assert.equal(new URL(page.url()).searchParams.get("user"), "valentina");
  await page.waitForFunction(() => document.body.textContent.includes("Жим штанги лёжа"));
  assert.ok(appRequests.some((item) => item.action === "getWorkout" && item.target_user_id === "valentina"));
  if (width === 360) {
    await page.getByText("Редактировать", { exact: true }).click();
    await page.getByText("Убрать", { exact: true }).click();
    await page.waitForFunction(() => document.querySelector("#st-manager-save-state")?.textContent.includes("Сохранено"));
    assert.ok(appRequests.some((item) => item.action === "saveExerciseCatalog" && item.target_user_id === "valentina"));
  }
  await page.close();
}

await browser.close();
await new Promise((resolve) => server.close(resolve));
console.log("strength mobile admin checks passed");
