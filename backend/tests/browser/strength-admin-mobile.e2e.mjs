import assert from "node:assert/strict";
import { createServer } from "node:http";
import { createRequire } from "node:module";
import { existsSync, mkdirSync, readFileSync } from "node:fs";
import path from "node:path";

const require = createRequire(import.meta.url);
const modulesRoot = process.env.CODEX_NODE_MODULES;
if (!modulesRoot) throw new Error("CODEX_NODE_MODULES is required");
const { chromium } = require(path.join(modulesRoot, "playwright"));

const staticRoot = path.resolve("app/static");
const newbieId = "00000000-0000-4000-8000-000000000001";
const people = {
  owner: { id: "owner", display_name: "Сергей", email: "owner@example.test" },
  valentina: { id: "valentina", display_name: "Валентина Капитанова", email: "valentina@example.test" },
  [newbieId]: { id: newbieId, display_name: "Новый участник", email: "newbie@example.test" },
};
const appRequests = [];
const userListRequests = [];
const managedRuntimeRequests = [];
const openedProfiles = new Set();

function hasState(appCode, userId) {
  return userId !== newbieId || openedProfiles.has(`${appCode}:${userId}`);
}

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
  if (["/admin/dqs", "/admin/strength", "/admin/metabolism", "/admin/client-diary"].includes(url.pathname)) {
    response.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
    return response.end(readFileSync(path.join(staticRoot, "admin.html")));
  }
  const assets = {
    "/admin/static/admin.css": "admin.css",
    "/admin/static/admin.js": "admin.js",
    "/admin/static/admin-shell.css": "admin-shell.css",
    "/admin/static/admin-shell.js": "admin-shell.js",
    "/admin/static/admin-session.css": "admin-session.css",
    "/admin/static/marketing.css": "marketing.css",
    "/embed.js": "embed.js",
    "/apps/strength.html": "apps/strength.html",
    "/apps/dqs.html": "apps/dqs.html",
    "/apps/dqs-category-rules.js": "apps/dqs-category-rules.js",
    "/apps/metabolism.html": "apps/metabolism.html",
    "/assets/app-client-picker.mjs": "app-client-picker.mjs",
  };
  if (assets[url.pathname]) {
    const name = assets[url.pathname];
    response.writeHead(200, { "Content-Type": name.endsWith(".css") ? "text/css" : /\.m?js$/.test(name) ? "text/javascript" : "text/html; charset=utf-8" });
    return response.end(readFileSync(path.join(staticRoot, name)));
  }
  if (/^\/assets\/[\w.-]+\.(css|m?js)$/.test(url.pathname)) {
    const asset = path.join(staticRoot, path.basename(url.pathname));
    if (existsSync(asset)) {
      response.writeHead(200, { "Content-Type": asset.endsWith(".css") ? "text/css" : "text/javascript" });
      return response.end(readFileSync(asset));
    }
  }
  if (["/admin/api/project-map", "/admin/api/navigation"].includes(url.pathname)) {
    return json(response, { ok: true, modules: [{ id: "products.strength", admin_catalog: [{ category: "applications", order: 20, url: "/admin/strength", label: "Силовые", icon: "💪", description: "Тренировки" }] }] });
  }
  if (url.pathname === "/admin/api/apps/users") {
    userListRequests.push(Object.fromEntries(url.searchParams));
    const q = String(url.searchParams.get("q") || "").toLowerCase();
    const users = Object.values(people).filter((user) => !q || `${user.display_name} ${user.email}`.toLowerCase().includes(q));
    return json(response, { ok: true, users: users.map((user) => ({ user_id: user.id, display_name: user.display_name, email: user.email, has_access: true, has_state: hasState(url.searchParams.get("app_code"), user.id), summary: { sessions: 1, filled_sessions: 1 } })) });
  }
  if (url.pathname === "/admin/api/apps/client-directory") {
    userListRequests.push(Object.fromEntries(url.searchParams));
    const q = String(url.searchParams.get("q") || "").toLowerCase();
    const favorites = url.searchParams.getAll("favorite_ids");
    const active = url.searchParams.get("scope") === "active";
    return json(response, { ok: true, users: Object.values(people)
      .filter(user => user.email.includes(q) && (!active || user.id !== newbieId || favorites.includes(user.id)))
      .map(user => ({ ...user, user_id: user.id, has_opened_app: user.id !== newbieId })) });
  }
  if (/^\/admin\/api\/users\/[^/]+\/modules$/.test(url.pathname)) {
    return json(response, { ok: true, modules: { dqs: { exists: false, has_access: false }, strength: { exists: true, has_access: true }, metabolism: { exists: false, has_access: false }, telegram: { exists: true } } });
  }
  if (/^\/admin\/api\/apps\/strength\/users\/[^/]+$/.test(url.pathname)) {
    const id = url.pathname.split("/").at(-1);
    const user = people[id] || people.owner;
    const state = hasState("strength", id);
    return json(response, { ok: true, user, has_access: true, has_state: state, state: state ? { summary: { sessions: 1 } } : null });
  }
  if (/^\/admin\/api\/apps\/(dqs|metabolism)\/users\/[^/]+$/.test(url.pathname)) {
    const code = url.pathname.split("/")[4];
    const id = url.pathname.split("/").at(-1);
    const user = people[id] || people.owner;
    const state = hasState(code, id);
    return json(response, { ok: true, app_code: code, user, has_access: true, has_state: state, state: state ? { summary: {}, version: 1 } : null });
  }
  const openMatch = url.pathname.match(/^\/admin\/api\/apps\/(dqs|strength|metabolism)\/users\/([^/]+)\/open$/);
  if (openMatch && request.method === "POST") {
    openedProfiles.add(`${openMatch[1]}:${openMatch[2]}`);
    return json(response, { ok: true, created: true, app_code: openMatch[1], user_id: openMatch[2], version: 1 });
  }
  if (/^\/admin\/api\/apps\/dqs\/users\/[^/]+\/runtime$/.test(url.pathname)) {
    managedRuntimeRequests.push({ app_code: "dqs", user_id: url.pathname.split("/")[6], method: request.method });
    return json(response, { ok: true, email: selected.email, startDate: "2026-09-01", needsStartDate: false, days: Array(30).fill(null), version: 1 });
  }
  if (/^\/admin\/api\/apps\/metabolism\/users\/[^/]+\/runtime$/.test(url.pathname)) {
    managedRuntimeRequests.push({ app_code: "metabolism", user_id: url.pathname.split("/")[6], method: request.method });
    if (request.method === "PUT") return json(response, { ok: true, version: 2 });
    return json(response, { ok: true, variants: {}, activeVariant: 1, version: 1, name: selected.display_name, email: selected.email });
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
    const user = { user_id: managed.id, display_name: managed.display_name, email: managed.email, can_coach: true };
    if (resolvedAction === "openUser") return json(response, { ok: true, user });
    if (resolvedAction === "getWorkout") return json(response, { ok: true, user, workout: workout() });
    return json(response, { ok: true, version: 2 });
  }
  response.writeHead(404);
  response.end("not found");
});

await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const { port } = server.address();
const browser = await chromium.launch({ headless: true });
const screenshots = process.env.STRENGTH_ADMIN_EVIDENCE_DIR;
if (screenshots) mkdirSync(screenshots, { recursive: true });

for (const width of [360, 430, 759, 761, 768, 1440]) {
  const page = await browser.newPage({ viewport: { width, height: 900 } });
  await page.goto(`http://127.0.0.1:${port}/admin/strength?mobile=1&user=owner`);
  await page.getByText("Жим штанги лёжа", { exact: true }).first().waitFor();
  assert.equal(await page.locator(".admin-sidebar:visible").count(), 0);
  assert.ok(await page.locator("body").evaluate((node) => node.scrollWidth <= node.clientWidth));
  assert.equal(await page.locator(".admin-managed-toolbar").count(), 1);
  assert.equal(await page.locator(".st-client-head:visible").count(), 0);
  if (screenshots) await page.screenshot({ path: path.join(screenshots, `strength-admin-direct-${width}.png`), fullPage: false });
  await page.locator("#admin-managed-person").click();
  const picker = page.getByRole("dialog", { name: "Выбрать клиента" });
  await picker.waitFor();
  await picker.getByRole("button", { name: /Валентина Капитанова/, exact: false }).first().waitFor();
  assert.ok(userListRequests.some((item) => item.app_code === "strength" && item.scope === "active"));
  await picker.getByRole("searchbox").fill("valentina@example");
  await page.waitForFunction(() => document.querySelectorAll(".ed-client-row").length === 1);
  if (screenshots) await page.screenshot({ path: path.join(screenshots, `strength-admin-picker-${width}.png`), fullPage: false });
  await picker.locator(".ed-client-row").click();
  await page.locator("#admin-managed-person").getByText(people.valentina.email).waitFor();
  assert.equal(new URL(page.url()).searchParams.get("user"), "valentina");
  await page.waitForFunction(() => document.body.textContent.includes("Жим штанги лёжа"));
  assert.ok(appRequests.some((item) => item.action === "getWorkout" && item.target_user_id === "valentina"));
  if (width === 360) {
    await page.getByRole("button", {name: "Управление шаблонами"}).click();
    await page.getByRole("dialog", {name: "Шаблоны"}).waitFor();
  }
  await page.close();
}

const desktop = await browser.newPage({ viewport: { width: 1440, height: 900 } });
await desktop.goto(`http://127.0.0.1:${port}/admin/strength?user=owner`);
await desktop.getByText("Жим штанги лёжа", { exact: true }).first().waitFor();
assert.equal(await desktop.locator(".admin-sidebar:visible").count(), 1);
assert.equal(await desktop.locator(".admin-managed-toolbar").count(), 1);
await desktop.locator("#admin-managed-app").click();
const apps = desktop.getByRole("dialog", {name: "Приложения"});
if (screenshots) await desktop.screenshot({ path: path.join(screenshots, "apps-drawer-1440.png") });
assert.deepEqual((await apps.getByRole("link").allTextContents()).slice(0, 4), ["Дашборд", "DQS", "Силовые", "Калькулятор метаболизма"]);
assert.equal(await desktop.locator(".admin-profile-head").count(), 0);
assert.equal(await desktop.getByText("Быстрые переходы", { exact: true }).count(), 0);
assert.equal(await desktop.locator(".st-client-head:visible").count(), 0);
if (screenshots) await desktop.screenshot({ path: path.join(screenshots, "strength-admin-direct-1440.png"), fullPage: false });
await apps.getByRole("link", {name: "DQS", exact: true}).click();
await desktop.waitForURL(/\/admin\/dqs\?user=owner/);
assert.equal(new URL(desktop.url()).searchParams.get("user"), "owner");
await desktop.locator("#dqs-app").waitFor();
await desktop.getByRole("button", {name: "Выбрать клиента"}).click();
const dqsPicker = desktop.getByRole("dialog", {name: "Выбрать клиента"});
await dqsPicker.getByRole("button", {name: "Все клиенты"}).click();
await dqsPicker.getByRole("searchbox").fill("newbie");
await dqsPicker.getByRole("button", {name: "Добавить в избранное: Новый участник"}).click();
await dqsPicker.getByRole("button", {name: "Активные · 30 дней"}).click();
await dqsPicker.getByRole("searchbox").clear();
await dqsPicker.getByRole("button", {name: "Убрать из избранного: Новый участник"}).waitFor();
assert.ok(userListRequests.some(item => item.app_code === "dqs" && item.scope === "active" && item.favorite_ids === newbieId));
await desktop.close();

for (const appCode of ["dqs", "metabolism"]) {
  for (const width of [360, 430, 768, 1440]) {
    const page = await browser.newPage({ viewport: { width, height: 900 } });
    await page.goto(`http://127.0.0.1:${port}/admin/${appCode}?user=valentina`);
    await page.locator(".admin-managed-toolbar").waitFor();
    await page.waitForFunction((code) => {
      const mount = document.getElementById(code === "dqs" ? "dqs-app" : "metabolism-app");
      return Boolean(mount && !mount.querySelector(":scope > .admin-empty"));
    }, appCode);
    assert.ok(await page.locator("body").evaluate((node) => node.scrollWidth <= node.clientWidth));
    assert.equal(await page.locator(".admin-profile-head").count(), 0);
    assert.equal(await page.getByText("Быстрые переходы", { exact: true }).count(), 0);
    assert.ok(managedRuntimeRequests.some((item) => item.app_code === appCode && item.user_id === "valentina" && item.method !== "PUT"));
    if (appCode === "metabolism") assert.equal(await page.locator("[data-account-name]:visible").count(), 0);
    if (appCode === "metabolism" && width === 430) {
      await page.locator('[data-field="weight"]').first().fill("79");
      await page.waitForFunction(() => document.querySelector('[data-status]')?.textContent === 'Изменения сохранены');
      assert.ok(managedRuntimeRequests.some((item) => item.app_code === "metabolism" && item.user_id === "valentina" && item.method === "PUT"));
    }
    if (screenshots) await page.screenshot({ path: path.join(screenshots, `${appCode}-admin-direct-${width}.png`), fullPage: false });
    await page.close();
  }
}

const unopened = await browser.newPage({ viewport: { width: 430, height: 900 } });
await unopened.goto(`http://127.0.0.1:${port}/admin/dqs?user=${newbieId}`);
await unopened.getByRole("button", { name: "Открыть приложение", exact: true }).waitFor();
assert.equal(await unopened.locator("#dqs-app").count(), 0);
await unopened.getByRole("button", { name: "Открыть приложение", exact: true }).click();
await unopened.locator("#dqs-app").waitFor();
assert.equal(openedProfiles.has(`dqs:${newbieId}`), true);
await unopened.close();

await browser.close();
await new Promise((resolve) => server.close(resolve));
console.log("strength mobile admin checks passed");
