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
    for (const field of entry[1].matchAll(/(category|order|url|label|description|icon)\s*=\s*(?:"((?:\\.|[^"])*)"|(\d+))/g)) {
      item[field[1]] = field[3] == null ? JSON.parse(`"${field[2]}"`) : Number(field[3]);
    }
    return item;
  });
  return { id, admin_catalog };
}).filter((module) => module.id && module.admin_catalog.length) };
const userQueries = [];
const userAccessFilters = [];
const paymentOffsets = [];
const paymentSnapshots = [];
let errorAttempts = 0;
let libraryErrorAttempts = 0;
const sampleUser = { id:"u1", display_name:"Анна", email:"anna@example.com", telegram:"anna", purchase_count:2, ltv_rub:12000, estimated_ltv_rub:0, last_purchase_at:"2026-09-18T12:00:00Z", accesses:["MASTERCLASS"] };

function json(response, payload) {
  response.writeHead(200, { "Content-Type": "application/json; charset=utf-8" });
  response.end(JSON.stringify(payload));
}

async function assertDesktopGeometry(page, expectedOffset) {
  const padding = await page.locator("body").evaluate((node) => Number.parseFloat(getComputedStyle(node).paddingLeft));
  assert.ok(Math.abs(padding - expectedOffset) <= 1, JSON.stringify({ padding, expectedOffset }));
  const main = page.locator("main:visible").first();
  if (await main.count()) {
    const box = await main.boundingBox();
    if (box) assert.ok(box.x >= expectedOffset - 1, JSON.stringify({ box, expectedOffset }));
  }
}

const server = createServer((request, response) => {
  const url = new URL(request.url, "http://127.0.0.1");
  if (url.pathname === "/admin") {
    response.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
    return response.end(readFileSync(path.join(staticRoot, "crm.html")));
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
    "/admin/static/product-catalog-editor.css": "product-catalog-editor.css",
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
  if (url.pathname === "/admin/api/users") {
    const q = url.searchParams.get("q") || "";
    userQueries.push(q);
    userAccessFilters.push(url.searchParams.get("masterclass_access"));
    if (q === "error" && errorAttempts++ === 0) { response.writeHead(500, { "Content-Type": "application/json" }); return response.end(JSON.stringify({detail:"test error"})); }
    const delay = q === "a" ? 600 : q === "anna" ? 20 : 0;
    return setTimeout(() => json(response, [q === "a" ? {...sampleUser, display_name:"Устаревший ответ"} : sampleUser]), delay);
  }
  if (url.pathname === "/admin/api/payments") {
    const offset = Number(url.searchParams.get("offset") || 0);
    paymentOffsets.push(offset);
    paymentSnapshots.push(url.searchParams.get("snapshot_at"));
    const count = offset === 0 ? 100 : 1;
    return json(response, Array.from({length:count}, (_, index) => ({ id:`p${offset + index}`, user_id:"u1", display_name:offset === 0 ? `Первая оплата ${index + 1}` : "Оплата 101", email:"anna@example.com", product_name:"Мастер-класс", status:"paid", amount:12000, amount_is_estimated:false, paid_at:"2026-09-18T12:00:00Z", snapshot_at:"2026-09-19T12:00:00Z" })));
  }
  if (url.pathname === "/admin/api/access-reviews") return json(response, []);
  if (url.pathname === "/admin/api/content/authoring/summary") return json(response, { manifestations: 24, families: 18, candidate_groups: 2 });
  if (url.pathname === "/admin/api/content/authoring/groups") return json(response, { total: 0, groups: [] });
  if (url.pathname === "/admin/api/library/summary") return json(response, { library_resources: 42, published_manifestations: 17, repo_documents: 63, pending_reviews: 0 });
  if (url.pathname === "/admin/api/library/reviews") return json(response, []);
  if (url.pathname === "/admin/api/library/search") {
    if (url.searchParams.get("q") === "error" && libraryErrorAttempts++ === 0) { response.writeHead(500, { "Content-Type": "application/json" }); return response.end(JSON.stringify({detail:"test library error"})); }
    return json(response, { results: [] });
  }
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
  for (const category of ["Клиенты", "Приложения", "Маркетинг", "Курсы", "Коммерция", "Служебное", "База знаний"]) {
    assert.equal(await page.getByText(category, { exact: true }).count(), 1, category);
  }
  assert.equal(await page.locator('.admin-nav-disabled:has-text("Telegram-бот")').count(), 1);
  assert.equal(await page.locator('.admin-nav-disabled:has-text("Telegram-бот")').getAttribute("href"), null);
  assert.ok(await page.locator("body").evaluate((node) => node.scrollWidth <= node.clientWidth));
  assert.equal(await page.getByRole("link", { name: "CRM" }).locator(".admin-nav-icon").textContent(), "👥");
  assert.equal(await page.getByRole("link", { name: "DQS" }).locator(".admin-nav-icon").textContent(), "🥑");
  assert.equal(await page.getByRole("link", { name: "Силовые" }).locator(".admin-nav-icon").textContent(), "💪");
  assert.equal(await page.getByRole("link", { name: "Метаболизм" }).locator(".admin-nav-icon").textContent(), "🔥");
  assert.equal(await page.getByRole("link", { name: "Определитель допродаж" }).locator(".admin-nav-icon").textContent(), "🎯");
  const offerCategory = await page.getByRole("link", { name: "Определитель допродаж" }).evaluate((node) => { let current = node.previousElementSibling; while (current && current.tagName !== "SPAN") current = current.previousElementSibling; return current?.textContent.trim(); });
  const contentCategory = await page.getByRole("link", { name: "Каталог материалов" }).evaluate((node) => { let current = node.previousElementSibling; while (current && current.tagName !== "SPAN") current = current.previousElementSibling; return current?.textContent.trim(); });
  assert.equal(offerCategory, "Коммерция");
  assert.equal(contentCategory, "Маркетинг");

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
    await page.waitForTimeout(220);
    await assertDesktopGeometry(page, 252);
    await page.getByRole("button", { name: "Свернуть меню" }).click();
    assert.equal(await page.locator("body").evaluate((node) => node.classList.contains("admin-shell-collapsed")), true);
    await page.waitForTimeout(220);
    await assertDesktopGeometry(page, 72);
    const compactLabels = await page.locator(".admin-shell-nav .admin-nav-icon").allTextContents();
    assert.equal(new Set(compactLabels).size, compactLabels.length);
    assert.equal(await page.locator(".admin-shell-logout .admin-nav-icon").isVisible(), true);
    if (evidence && [768, 1440].includes(width)) await page.screenshot({ path: path.join(evidence, `admin-shell-collapsed-${width}.png`), fullPage: false });
    await page.getByRole("button", { name: "Раскрыть меню" }).click();
    assert.equal(await page.locator("body").evaluate((node) => node.classList.contains("admin-shell-collapsed")), false);
    await page.locator('[data-action="hide"]').click();
    assert.equal(await page.locator("body").evaluate((node) => node.classList.contains("admin-shell-hidden")), true);
    await page.waitForTimeout(220);
    await assertDesktopGeometry(page, 0);
    if (evidence && [768, 1440].includes(width)) await page.screenshot({ path: path.join(evidence, `admin-shell-hidden-${width}.png`), fullPage: false });
    await page.getByRole("button", { name: "Показать меню" }).click();
    assert.equal(await page.locator("body").evaluate((node) => node.classList.contains("admin-shell-hidden")), false);
    await page.waitForTimeout(220);
    await assertDesktopGeometry(page, 252);
  }
  if (evidence && [360, 430, 768, 1440].includes(width)) {
    await page.screenshot({ path: path.join(evidence, `admin-shell-${width}.png`), fullPage: true });
  }
  await page.close();
}

for (const width of [360, 430, 768, 1440]) {
  const page = await browser.newPage({ viewport: { width, height: 900 } });
  await page.goto(`http://127.0.0.1:${port}/finance`);
  await page.getByRole("link", { name: "Финансовая модель" }).waitFor();
  await page.getByRole("heading", { name: "Параметры" }).waitFor();
  const dimensions = await page.locator("body").evaluate((node) => ({scrollWidth:node.scrollWidth,clientWidth:node.clientWidth}));
  const columns = await page.locator("main > .grid").evaluate((node) => getComputedStyle(node).gridTemplateColumns.split(" ").filter(Boolean).length);
  assert.equal(columns, width >= 1280 ? 2 : 1, JSON.stringify({width,columns}));
  assert.match(await page.locator(".finance-mode-note").textContent(), /Сценарная модель/);
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
    await page.getByRole("link", { name: "CRM" }).waitFor();
    if (name === "crm" && width === 1440) {
      const search = page.locator("#crm-search");
      await search.click();
      await search.fill("a");
      await page.waitForTimeout(330);
      await search.fill("anna");
      await page.waitForTimeout(380);
      assert.equal(await search.evaluate((node) => document.activeElement === node), true);
      assert.match(await page.locator("#crm-user-results").textContent(), /Анна/);
      assert.doesNotMatch(await page.locator("#crm-user-results").textContent(), /Устаревший ответ/);
      assert.ok(userQueries.includes("a") && userQueries.includes("anna"));
      await search.fill("error");
      await page.waitForTimeout(380);
      assert.equal(await page.getByText("CRM", { exact:true }).count(), 2);
      assert.match(await page.locator("#crm-user-results").textContent(), /Люди не загрузились/);
      assert.equal(await search.inputValue(), "error");
      assert.equal(await search.evaluate((node) => document.activeElement === node), true);
      await page.getByRole("button", { name:"Повторить" }).click();
      await page.locator("#crm-user-results tbody tr[data-user-id]").waitFor();
      assert.equal(userQueries.filter((query) => query === "error").length, 2);
      await page.getByRole("button", { name:"Есть МК" }).click();
      await page.locator("#crm-user-results tbody tr[data-user-id]").waitFor();
      assert.equal(userAccessFilters.at(-1), "true");
      await page.locator(".crm-filters summary").click();
      assert.match(await page.locator(".crm-filter-help").textContent(), /Тег.*не подтверждает оплату/s);
      assert.match(await page.locator(".crm-filter-help").textContent(), /Проблемы доступа.*очередь/s);
      await page.getByRole("button", { name:"Оплаты" }).click();
      await page.locator("#payment-next:not([disabled])").waitFor();
      assert.match(await page.locator(".crm-table tbody").textContent(), /Первая оплата 1/);
      await page.locator("#payment-next").click();
      await page.waitForTimeout(80);
      assert.deepEqual(paymentOffsets.slice(-2), [0, 100]);
      assert.deepEqual(paymentSnapshots.slice(-2), [null, "2026-09-19T12:00:00Z"]);
      assert.match(await page.locator(".crm-table tbody").textContent(), /Оплата 101/);
      assert.doesNotMatch(await page.locator(".crm-table tbody").textContent(), /Первая оплата/);
      await page.getByRole("button", { name:"Люди" }).click();
      await page.locator("#crm-search").fill("");
      await page.locator("#crm-user-results tbody tr[data-user-id]").waitFor();
    }
    if (name === "library" && width === 1440) {
      assert.match(await page.locator("#results").textContent(), /Счётчик сверху показывает объём карты/);
      assert.match(await page.locator("#reviews").textContent(), /Очередь решений пуста/);
      await page.locator("#query").fill("ничего");
      await page.getByRole("button", { name:"Найти" }).click();
      await page.getByText("Ничего не найдено", { exact:true }).waitFor();
      await page.locator("#query").fill("error");
      await page.getByRole("button", { name:"Найти" }).click();
      await page.getByText("Поиск не загрузился", { exact:true }).waitFor();
      await page.getByRole("button", { name:"Повторить" }).click();
      await page.getByText("Ничего не найдено", { exact:true }).waitFor();
    }
    if (name === "products" && width === 1440) {
      await page.getByRole("heading", { name:"Продукты и описания" }).waitFor();
      assert.equal(await page.locator('[data-product="0"][data-field="shortName"]').evaluate((node) => node.tagName), "INPUT");
      assert.equal(await page.locator('[data-product="0"][data-field="marketing"]').evaluate((node) => node.tagName), "TEXTAREA");
      assert.match(await page.locator(".product-editor-item summary").first().textContent(), /Мастер-класс · active/);
    }
    if (width > 760) {
      await page.waitForTimeout(220);
      await assertDesktopGeometry(page, 252);
    }
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
