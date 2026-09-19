import assert from "node:assert/strict";
import { createServer } from "node:http";
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const modulesRoot = process.env.CODEX_NODE_MODULES;
const { chromium } = modulesRoot ? require(path.join(modulesRoot, "playwright")) : await import("playwright");
const testRoot = path.dirname(fileURLToPath(import.meta.url));
const repositoryRoot = path.resolve(testRoot, "../../..");
const staticRoot = path.join(repositoryRoot, "backend/app/static");
const modulesToml = readFileSync(path.join(repositoryRoot, "docs/modules.toml"), "utf8");
const projectMap = { modules: modulesToml.split(/\r?\n(?=\[\[modules\]\])/).map((block) => {
  const id = block.match(/^id\s*=\s*"([^"]+)"/m)?.[1];
  const catalog = block.match(/^admin_catalog\s*=\s*\[(.*)\]$/m)?.[1] || "";
  const admin_catalog = [...catalog.matchAll(/\{([^{}]+)\}/g)].map((entry) => {
    const item = {};
    for (const field of entry[1].matchAll(/(category|order|url|label|description)\s*=\s*(?:"((?:\\.|[^"])*)"|(\d+))/g)) {
      item[field[1]] = field[3] == null ? JSON.parse(`"${field[2]}"`) : Number(field[3]);
    }
    return item;
  });
  return { id, admin_catalog };
}).filter((module) => module.id && module.admin_catalog.length) };

function json(response, payload) {
  response.writeHead(200, { "Content-Type": "application/json; charset=utf-8" });
  response.end(JSON.stringify(payload));
}

const server = createServer((request, response) => {
  const url = new URL(request.url, "http://127.0.0.1");
  if (url.pathname === "/admin") {
    response.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
    return response.end(readFileSync(path.join(staticRoot, "admin.html")));
  }
  if (url.pathname === "/finance") {
    response.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
    return response.end(readFileSync(path.join(staticRoot, "eda-finance.html")));
  }
  const pages = {
    "/crm": "crm.html",
    "/admin/content": "content-catalog.html",
    "/admin/library": "knowledge-library.html",
    "/admin/knowledge-base": "knowledge-base.html",
    "/admin/courses": "course-editors.html",
    "/admin/courses/masterclass-21/structure": "course-structure-editor.html",
    "/admin/products": "product-catalog-editor.html",
  };
  if (pages[url.pathname]) {
    response.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
    return response.end(readFileSync(path.join(staticRoot, pages[url.pathname])));
  }
  const assets = {
    "/admin/static/admin.css": "admin.css",
    "/admin/static/admin-shell.css": "admin-shell.css",
    "/admin/static/admin-shell.js": "admin-shell.js",
    "/admin/static/admin.js": "admin.js",
    "/admin/static/marketing.css": "marketing.css",
    "/admin/static/admin-session.css": "admin-session.css",
    "/admin/static/content-catalog.css": "content-catalog.css",
    "/admin/static/content-catalog.js": "content-catalog.js",
    "/admin/static/knowledge-library.css": "knowledge-library.css",
    "/admin/static/knowledge-library.js": "knowledge-library.js",
    "/admin/static/knowledge-base.css": "knowledge-base.css",
    "/admin/static/knowledge-base.js": "knowledge-base.js",
    "/admin/static/course-structure-editor.css": "course-structure-editor.css",
    "/admin/static/course-structure-editor.js": "course-structure-editor.js",
    "/admin/static/product-catalog-editor.js": "product-catalog-editor.js",
    "/crm/crm.css": "crm.css",
    "/crm/crm.js": "crm.js",
  };
  if (assets[url.pathname]) {
    const name = assets[url.pathname];
    response.writeHead(200, { "Content-Type": name.endsWith(".css") ? "text/css" : "text/javascript" });
    return response.end(readFileSync(path.join(staticRoot, name)));
  }
  if (url.pathname === "/embed.js") {
    response.writeHead(200, { "Content-Type": "text/javascript" });
    return response.end("");
  }
  if (url.pathname === "/admin/api/project-map") return json(response, projectMap);
  if (url.pathname === "/admin/api/summary") return json(response, { users: 321, buyers: 87, paid_payments: 112, revenue_rub: 950000, access_reviews: 4 });
  if (url.pathname === "/admin/api/payment-products" || url.pathname === "/admin/api/tags") return json(response, []);
  if (url.pathname === "/admin/api/users") return json(response, []);
  if (url.pathname === "/admin/api/content/authoring/summary") return json(response, { manifestations: 24, families: 18, candidate_groups: 2 });
  if (url.pathname === "/admin/api/content/authoring/groups") return json(response, { total: 0, groups: [] });
  if (url.pathname === "/admin/api/library/summary") return json(response, { library_resources: 42, published_manifestations: 17, repo_documents: 63, pending_reviews: 0 });
  if (url.pathname === "/admin/api/library/reviews") return json(response, []);
  if (url.pathname === "/admin/api/courses") return json(response, { courses: [{ name: "Мастер-класс", units: 21, unit_name: "день", version: 7, materials_total: 42, materials_published: 42, ready: true, editor_url: "/admin/courses/masterclass-21/structure" }] });
  if (url.pathname === "/admin/api/courses/masterclass-21/structure") return json(response, { course: { name: "Мастер-класс", unit_name: "день" }, active: { version: 7, created_at: "2026-09-19T12:00:00Z", manifest: { days: [{ number: 1, title: "Начало работы", tocSummary: "Первый день", lead: "", videoId: "", image: "", timings: [], intro: "", afterLead: "", afterTitle: "", afterText: "", steps: [], checks: [] }] } }, history: [] });
  if (url.pathname === "/admin/api/product-catalog") return json(response, { active: { version: 3, manifest: { products: [{ shortName: "Мастер-класс", fullName: "Мастер-класс по похудению", descriptor: "Как выстроить питание", status: "active", marketing: "" }], tariffs: [] } }, history: [] });
  if (url.pathname === "/admin/api/logout") return json(response, { ok: true });
  response.writeHead(404);
  response.end("not found");
});

await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const { port } = server.address();
const browser = await chromium.launch({ headless: true });
const evidence = process.env.ADMIN_SHELL_EVIDENCE_DIR;

for (const width of [360, 430, 759, 761, 768, 1440]) {
  const page = await browser.newPage({ viewport: { width, height: 900 } });
  await page.goto(`http://127.0.0.1:${port}/admin`);
  await page.getByRole("link", { name: "Финансовая модель" }).waitFor();
  assert.equal(await page.getByText("Служебное", { exact: true }).count(), 1);
  assert.equal(await page.getByText("База знаний", { exact: true }).count(), 1);
  for (const category of ["Клиенты", "Приложения", "Маркетинг", "Контент", "Коммерция", "Служебное", "База знаний"]) {
    assert.equal(await page.getByText(category, { exact: true }).count(), 1, category);
  }
  assert.equal(await page.locator('.admin-nav-disabled:has-text("Telegram-бот")').count(), 1);
  assert.equal(await page.locator('.admin-nav-disabled:has-text("Telegram-бот")').getAttribute("href"), null);
  assert.ok(await page.locator("body").evaluate((node) => node.scrollWidth <= node.clientWidth));

  if (width <= 760) {
    const burger = page.getByRole("button", { name: "Открыть меню" });
    await burger.click();
    assert.equal(await page.locator("body").evaluate((node) => node.classList.contains("admin-shell-mobile-opened")), true);
    await page.waitForTimeout(220);
    const openBurgerBox = await burger.boundingBox();
    const brandBox = await page.locator(".admin-brand").boundingBox();
    if (openBurgerBox && brandBox) assert.ok(openBurgerBox.x >= brandBox.x + brandBox.width || brandBox.x >= openBurgerBox.x + openBurgerBox.width);
    if (evidence && [360, 430].includes(width)) await page.screenshot({ path: path.join(evidence, `admin-shell-open-${width}.png`), fullPage: false });
    await page.locator(".admin-shell-backdrop").click({ position: { x: width - 5, y: 400 } });
    assert.equal(await page.locator("body").evaluate((node) => node.classList.contains("admin-shell-mobile-opened")), false);
    await page.waitForTimeout(220);
    const sidebarBox = await page.locator(".admin-sidebar").boundingBox();
    assert.ok(sidebarBox.x + sidebarBox.width <= 1, JSON.stringify(sidebarBox));
  } else {
    await page.getByRole("button", { name: "Свернуть меню" }).click();
    assert.equal(await page.locator("body").evaluate((node) => node.classList.contains("admin-shell-collapsed")), true);
    await page.waitForTimeout(220);
    const compactLabels = await page.locator(".admin-shell-nav .admin-nav-icon").allTextContents();
    assert.equal(new Set(compactLabels).size, compactLabels.length);
    assert.equal(await page.locator(".admin-shell-logout .admin-nav-icon").isVisible(), true);
    if (evidence && [768, 1440].includes(width)) await page.screenshot({ path: path.join(evidence, `admin-shell-collapsed-${width}.png`), fullPage: false });
    await page.getByRole("button", { name: "Раскрыть меню" }).click();
    assert.equal(await page.locator("body").evaluate((node) => node.classList.contains("admin-shell-collapsed")), false);
    await page.locator('[data-action="hide"]').click();
    assert.equal(await page.locator("body").evaluate((node) => node.classList.contains("admin-shell-hidden")), true);
    await page.waitForTimeout(220);
    if (evidence && [768, 1440].includes(width)) await page.screenshot({ path: path.join(evidence, `admin-shell-hidden-${width}.png`), fullPage: false });
    await page.getByRole("button", { name: "Показать меню" }).click();
    assert.equal(await page.locator("body").evaluate((node) => node.classList.contains("admin-shell-hidden")), false);
    await page.waitForTimeout(220);
  }
  if (evidence && [360, 430, 768, 1440].includes(width)) {
    await page.screenshot({ path: path.join(evidence, `admin-shell-${width}.png`), fullPage: true });
  }
  await page.close();
}

for (const width of [360, 1440]) {
  const page = await browser.newPage({ viewport: { width, height: 900 } });
  await page.goto(`http://127.0.0.1:${port}/finance`);
  await page.getByRole("link", { name: "Финансовая модель" }).waitFor();
  await page.getByRole("heading", { name: "Параметры" }).waitFor();
  const dimensions = await page.locator("body").evaluate((node) => ({scrollWidth:node.scrollWidth,clientWidth:node.clientWidth}));
  if (evidence) await page.screenshot({ path: path.join(evidence, `admin-finance-${width}.png`), fullPage: true });
  assert.ok(dimensions.scrollWidth <= dimensions.clientWidth, JSON.stringify({width,dimensions}));
  await page.close();
}

const integratedPages = {
  crm: "/crm",
  content: "/admin/content",
  library: "/admin/library",
  knowledge: "/admin/knowledge-base",
  courses: "/admin/courses",
  course: "/admin/courses/masterclass-21/structure",
  products: "/admin/products",
};
for (const [name, route] of Object.entries(integratedPages)) {
  for (const width of [360, 1440]) {
    const page = await browser.newPage({ viewport: { width, height: 900 } });
    await page.goto(`http://127.0.0.1:${port}${route}`);
    await page.getByRole("link", { name: "Главное" }).waitFor();
    if (width <= 760) {
      const burgerBox = await page.getByRole("button", { name: "Открыть меню" }).boundingBox();
      const protectedContent = name === "knowledge"
        ? await page.locator(".wiki-back").boundingBox()
        : await page.locator("body > :not(.admin-sidebar):not(.admin-shell-backdrop):not(.admin-shell-open):not(.admin-shell-mobile-open)").first().boundingBox();
      if (burgerBox && protectedContent) {
        const separated = name === "knowledge"
          ? protectedContent.x >= burgerBox.x + burgerBox.width
          : protectedContent.y >= burgerBox.y + burgerBox.height;
        assert.ok(separated, JSON.stringify({name,width,burgerBox,protectedContent}));
      }
      const heading = page.locator("h1:visible").first();
      if (burgerBox && await heading.count()) {
        const headingBox = await heading.boundingBox();
        if (headingBox) assert.ok(headingBox.y >= burgerBox.y + burgerBox.height, JSON.stringify({name,width,burgerBox,headingBox}));
      }
    }
    if (evidence) await page.screenshot({ path: path.join(evidence, `admin-${name}-${width}.png`), fullPage: false });
    await page.close();
  }
}

await browser.close();
await new Promise((resolve) => server.close(resolve));
console.log("admin shell e2e: ok");
