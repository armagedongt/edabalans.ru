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
const userAccompanimentFilters = [];
const paymentOffsets = [];
const paymentSnapshots = [];
const paymentQueries = [];
let failNextPaymentRequest = false;
let errorAttempts = 0;
let libraryErrorAttempts = 0;
const sampleUser = { id:"u1", display_name:"Анна", email:"anna@example.com", telegram:"anna", purchase_count:2, ltv_rub:12000, estimated_ltv_rub:0, first_seen_at:"2026-08-01T12:00:00Z", first_purchase_at:"2026-08-02T12:00:00Z", last_purchase_at:"2026-09-18T12:00:00Z", first_source:"telegram", accompaniment_status:"active", initial_tariff:"Стандарт", accesses:["ACCESS_MASTERCLASS", "ACCESS_DQS"], note_count:1, messengers:[{platform:"telegram",platform_user_id:"101",username:"anna",first_seen_at:"2026-08-01T12:00:00Z",main_scenario_seen_at:"2026-08-01T12:00:00Z",subscription_status:"subscribed"},{platform:"max",platform_user_id:"max-202",username:"maxanna",first_seen_at:"2026-08-04T12:00:00Z",main_scenario_seen_at:"2026-08-04T12:00:00Z",subscription_status:"active"}] };
const sampleUsers = [
  sampleUser,
  { id:"u2", display_name:"Ирина Лебедева", email:"irina.lebedeva@example.org", purchase_count:1, ltv_rub:8900, estimated_ltv_rub:0, first_seen_at:"2026-08-11T12:00:00Z", first_purchase_at:"2026-08-14T12:00:00Z", first_source:"pikabu", initial_tariff:"Минимальный", accesses:["ACCESS_MASTERCLASS"], note_count:0, messengers:[{platform:"telegram",platform_user_id:"102",username:"irina_example",first_seen_at:"2026-08-11T12:00:00Z",main_scenario_seen_at:"2026-08-11T12:00:00Z",subscription_status:"subscribed"}] },
  { id:"u3", display_name:"Дмитрий", email:"dmitry.sokolov.long-mailbox@example.net", purchase_count:0, ltv_rub:0, estimated_ltv_rub:0, first_seen_at:"2026-09-02T12:00:00Z", first_source:"yandex_direct", initial_tariff:null, accesses:[], note_count:2, messengers:[{platform:"max",platform_user_id:"max-303",username:"",first_seen_at:"2026-09-02T12:00:00Z",main_scenario_seen_at:null,subscription_status:"unknown"}] },
  { id:"u4", display_name:"Николай Сергеевич Петров", email:"nikolay@example.ru", purchase_count:1, ltv_rub:19900, estimated_ltv_rub:0, first_seen_at:"2026-07-03T12:00:00Z", first_purchase_at:"2026-07-20T12:00:00Z", first_source:"website", accompaniment_status:"active", initial_tariff:"Основной", accesses:["ACCESS_COACHING"], note_count:4, messengers:[{platform:"telegram",platform_user_id:"104",username:"nikolay_example",first_seen_at:"2026-07-03T12:00:00Z",main_scenario_seen_at:"2026-07-04T12:00:00Z",subscription_status:"active"},{platform:"max",platform_user_id:"max-404",username:"",first_seen_at:"2026-07-05T12:00:00Z",main_scenario_seen_at:"2026-07-05T12:00:00Z",subscription_status:"active"}] },
  { id:"u5", display_name:"", email:"maria@example.com", purchase_count:0, ltv_rub:0, estimated_ltv_rub:0, first_seen_at:"2026-09-10T12:00:00Z", first_source:"telegram", initial_tariff:null, accesses:[], note_count:0, messengers:[] },
  { id:"u6", display_name:"Ольга В.", email:"olga.v@example.com", purchase_count:1, ltv_rub:3000, estimated_ltv_rub:0, first_seen_at:"2026-06-01T12:00:00Z", first_purchase_at:"2026-06-04T12:00:00Z", first_source:"tilda", initial_tariff:"Дополнение", accesses:["ACCESS_DQS"], note_count:1, messengers:[{platform:"telegram",platform_user_id:"106",username:"olga_example",first_seen_at:"2026-06-01T12:00:00Z",main_scenario_seen_at:null,subscription_status:"unsubscribed"}] }
];
const sampleUserDetail = {
  id:"u1", display_name:"Анна", status:"active", data_origin:"native", accompaniment_status:"active", first_seen_at:"2026-08-01T12:00:00Z",
  access_review_status:"not_required", access_review_note:"", tilda_access_status:"not_required", tilda_membership:null,
  emails:[{email:"anna@example.com",primary:true,verification_status:"verified"}],
  credential:{exists:false,password_available:false,password_version:null,issued_via:null,updated_at:null},
  messengers:[{platform:"telegram",platform_user_id:"101",username:"anna",first_name:"Анна",subscription_status:"active",main_scenario_seen_at:null},{platform:"max",platform_user_id:"max-202",username:"maxanna",first_name:"Анна",subscription_status:"active",main_scenario_seen_at:"2026-08-04T12:00:00Z"}], phones:[],
  purchase_count:2, ltv_rub:12000, estimated_ltv_rub:0, total_ltv_rub:12000,
  payments:[
    {id:"p2",product_code:"DQS",product_name:"Diet Quality Score",product_name_raw:"DQS",tariff:"Дополнение",amount:3000,amount_is_estimated:false,currency:"RUB",status:"paid",review_status:"ok",source:"robokassa",payment_system:"Robokassa",external_order_id:"2",paid_at:"2026-09-18T12:00:00Z",source_event_at:"2026-09-18T12:00:00Z"},
    {id:"p1",product_code:"MASTERCLASS_STANDARD",product_name:"Мастер-класс",product_name_raw:"Мастер-класс",tariff:"Стандарт",amount:9000,amount_is_estimated:false,currency:"RUB",status:"paid",review_status:"ok",source:"robokassa",payment_system:"Robokassa",external_order_id:"1",paid_at:"2026-08-02T12:00:00Z",source_event_at:"2026-08-02T12:00:00Z"}
  ],
  purchased_products:[
    {product_code:"DQS",product_name:"Diet Quality Score",tariff:"Дополнение",purchased_at:"2026-09-18T12:00:00Z"},
    {product_code:"MASTERCLASS_STANDARD",product_name:"Мастер-класс",tariff:"Стандарт",purchased_at:"2026-08-02T12:00:00Z"}
  ],
  accesses:[
    {code:"ACCESS_MASTERCLASS",name:"Мастер-класс",granted_at:"2026-08-02T12:00:00Z",expires_at:null,revoked_at:null,paused_at:null},
    {code:"ACCESS_DQS",name:"Diet Quality Score",granted_at:"2026-09-18T12:00:00Z",expires_at:null,revoked_at:null,paused_at:null}
  ],
  attribution:[{event_type:"first_seen",source:"telegram",utm_source:null,utm_campaign:null,landing_url:null,occurred_at:"2026-08-01T12:00:00Z"}],
  product_progress:[
    {code:"masterclass",name:"Мастер-класс",completed:12,total:20,percent:60,legacy_assumed_complete:false},
    {code:"dqs",name:"Diet Quality Score",completed:8,total:30,percent:27,legacy_assumed_complete:false}
  ],
  tags:[{id:"t1",name:"Мастер-класс",category:"purchase"}], notes:[{body:"Обсудить следующий этап",author:"Сергей",created_at:"2026-09-19T12:00:00Z"}],
  masterclass:{questionnaires:[],events:[],offers:[]}
};
const sampleModules = {
  dqs:{exists:true,has_access:true,has_direct_access:true},
  strength:{exists:false,has_access:false,has_direct_access:false},
  metabolism:{exists:false,has_access:false,has_direct_access:false},
  telegram:{exists:true,has_access:true}
};

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
  if (url.pathname === "/favicon.png") {
    response.writeHead(200, { "Content-Type": "image/png" });
    return response.end(readFileSync(path.join(staticRoot, "brand/favicon.png")));
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
    "/admin/courses/masterclass-21/materials/day-01-article-02/editor": "course-material-editor.html",
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
    "/admin/static/course-material-editor.css": "course-material-editor.css",
    "/admin/static/course-material-editor.js": "course-material-editor.js",
    "/admin/static/product-catalog-editor.js": "product-catalog-editor.js",
    "/admin/static/product-catalog-editor.css": "product-catalog-editor.css",
    "/crm/crm.css": "crm.css",
    "/crm/crm.js": "crm.js",
    "/assets/max-logo.png": "max-logo.png",
  };
  if (assets[url.pathname]) {
    const name = assets[url.pathname];
    response.writeHead(200, { "Content-Type": name.endsWith(".css") ? "text/css" : name.endsWith(".png") ? "image/png" : "text/javascript" });
    return response.end(readFileSync(path.join(staticRoot, name)));
  }
  if (["/assets/article-typography.css", "/assets/article-note.css", "/assets/course-visual.css", "/course-assets/masterclass/article-components.css"].includes(url.pathname)) {
    response.writeHead(200, { "Content-Type": "text/css" });
    return response.end("");
  }
  if (url.pathname === "/course-assets/masterclass/article-components.js") {
    response.writeHead(200, { "Content-Type": "text/javascript" });
    return response.end("");
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
    userAccompanimentFilters.push(url.searchParams.get("accompaniment_status"));
    if (q === "error" && errorAttempts++ === 0) { response.writeHead(500, { "Content-Type": "application/json" }); return response.end(JSON.stringify({detail:"test error"})); }
    const delay = q === "a" ? 600 : q === "anna" ? 20 : 0;
    const users = q === "a"
      ? [{...sampleUser, display_name:"Устаревший ответ"}]
      : q === "anna" ? [sampleUser] : sampleUsers;
    return setTimeout(() => json(response, users), delay);
  }
  if (url.pathname === "/admin/api/users/u1") return json(response, sampleUserDetail);
  if (url.pathname === "/admin/api/users/u1/course-accesses") return json(response, {courses: [
    {resource_code:"ACCESS_MASTERCLASS",name:"Мастер-класс",entitled:true,start_open:true,all_lessons_open:false,available:true},
    {resource_code:"ACCESS_CALORIES",name:"Курс о калориях",entitled:false,start_open:false,all_lessons_open:false,available:true}
  ]});
  if (url.pathname === "/admin/api/resources") return json(response, [
    {code:"ACCESS_MASTERCLASS",name:"Мастер-класс"},
    {code:"ACCESS_DQS",name:"Diet Quality Score"},
    {code:"ACCESS_RECIPES",name:"Рецепты"},
    {code:"ACCESS_CALORIES",name:"Курс о калориях"},
    {code:"ACCESS_STRENGTH",name:"Приложение тренировок"},
    {code:"ACCESS_CONSULTATION",name:"Консультация"},
    {code:"ACCESS_COACHING",name:"Сопровождение"}
  ]);
  if (url.pathname.startsWith("/admin/api/users/u1/app-accesses/") && request.method === "PUT") {
    const code = url.pathname.split("/").at(-1);
    sampleModules[code].has_direct_access = true;
    sampleModules[code].has_access = true;
    return json(response, {enabled: true});
  }
  if (url.pathname === "/admin/api/users/u1/modules") return json(response, {modules:sampleModules});
  if (url.pathname === "/admin/api/users/u1/personal-access-links") return json(response, {links:[]});
  if (url.pathname === "/admin/api/payments") {
    paymentQueries.push(new URLSearchParams(url.searchParams));
    if (failNextPaymentRequest) {
      failNextPaymentRequest = false;
      response.writeHead(500, { "Content-Type": "application/json" });
      return response.end(JSON.stringify({detail:"test payment error"}));
    }
    const offset = Number(url.searchParams.get("offset") || 0);
    paymentOffsets.push(offset);
    paymentSnapshots.push(url.searchParams.get("snapshot_at"));
    const count = offset === 0 ? 100 : 1;
    return json(response, Array.from({length:count}, (_, index) => ({ id:`p${offset + index}`, user_id:"u1", display_name:offset === 0 ? `Первая оплата ${index + 1}` : "Оплата 101", email:"anna@example.com", product_name:"Мастер-класс", status:"paid", source:"robokassa", payment_system:"Robokassa", external_order_id:String(offset + index + 1), amount:12000, amount_is_estimated:false, paid_at:"2026-09-18T12:00:00Z", snapshot_at:"2026-09-19T12:00:00Z" })));
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
  if (url.pathname === "/admin/api/editorial/masterclass/materials/day-01-article-02" && request.method === "GET") return json(response, { ok:true, step_id:"day-01-article-02", day:1, title:"Как вести дневник питания", path:"content/masterclass/editorial/materials/01-02.md", connected:true, main:{sha:"a".repeat(40),content:"# Как вести дневник питания\n\n## Зачем нужен дневник?\n\nТекст материала.\n"}, draft:null, draft_base_main_sha:null });
  if (url.pathname === "/admin/api/editorial/masterclass/materials/day-01-article-02/preview") return json(response, { ok:true, html:"<h2>Зачем нужен дневник?</h2><p>Текст материала.</p>", diff:"Изменений нет" });
  if (url.pathname === "/admin/api/editorial/masterclass/materials/day-01-article-02/history") return json(response, { ok:true, history:[{sha:"a".repeat(40),message:"content: source",author:"Admin",date:"2026-09-19T12:00:00Z",active:true}] });
  if (url.pathname === "/admin/api/product-catalog") return json(response, { active: { version: 3, manifest: { products: [{ shortName: "Мастер-класс", fullName: "Мастер-класс по похудению", descriptor: "Как выстроить питание", status: "active", marketing: "" }], tariffs: [] } }, history: [] });
  if (url.pathname === "/admin/api/logout") return json(response, { ok: true });
  response.writeHead(404);
  response.end("not found");
});

const requestedPort = Number(process.env.ADMIN_SHELL_PREVIEW_PORT || 0);
await new Promise((resolve) => server.listen(requestedPort, "127.0.0.1", resolve));
const { port } = server.address();
if (process.env.ADMIN_SHELL_PREVIEW_ONLY === "1") {
  console.log(`admin shell preview: http://127.0.0.1:${port}/crm`);
  await new Promise(() => {});
}
const browser = await chromium.launch({ headless: true });
const evidence = process.env.ADMIN_SHELL_EVIDENCE_DIR;

for (const width of [360, 430, 759, 761, 768, 1440]) {
  const page = await browser.newPage({ viewport: { width, height: 900 } });
  await page.goto(`http://127.0.0.1:${port}/admin`);
  await page.getByRole("link", { name: "Финансовая модель" }).waitFor();
  assert.ok(await page.locator(".admin-brand img").evaluate((node) => node.complete && node.naturalWidth > 0));
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
    await assertDesktopGeometry(page, 270);
    await page.getByRole("button", { name: "Свернуть меню" }).click();
    assert.equal(await page.locator("body").evaluate((node) => node.classList.contains("admin-shell-collapsed")), true);
    await page.waitForTimeout(220);
    await assertDesktopGeometry(page, 74);
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
    await assertDesktopGeometry(page, 270);
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
  // The shared shell animates its desktop offset for 180 ms. Measure the
  // settled layout, not an intermediate frame where body padding can add a
  // few transient pixels to scrollWidth.
  await page.waitForTimeout(220);
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
  materialEditor: "/admin/courses/masterclass-21/materials/day-01-article-02/editor",
  products: "/admin/products",
};
for (const [name, route] of Object.entries(integratedPages)) {
  for (const width of [360, 430, 768, 1440]) {
    const page = await browser.newPage({ viewport: { width, height: 900 } });
    await page.goto(`http://127.0.0.1:${port}${route}`);
    await page.getByRole("link", { name: "CRM" }).waitFor();
    if (name === "crm" && width === 1440) {
      await page.locator(".crm-people-table tbody tr[data-user-id='u3']").waitFor();
      assert.equal(await page.locator(".crm-people-table tbody tr[data-user-id='u3'] .crm-table-messenger-slot--telegram .crm-contact-button").count(), 0);
      assert.equal(await page.locator(".crm-people-table tbody tr[data-user-id='u3'] .crm-table-messenger-slot--max .crm-contact-button--max").count(), 1);
      assert.match(await page.locator(".crm-people-table tbody tr[data-user-id='u5'] .crm-person-name").textContent(), /maria@example\.com/);
      const search = page.locator("#crm-search");
      await search.click();
      await search.fill("a");
      await page.waitForTimeout(330);
      await search.fill("anna");
      await page.waitForTimeout(380);
      assert.equal(await search.evaluate((node) => document.activeElement === node), true);
      assert.match(await page.locator("#crm-user-results").textContent(), /Анна/);
      assert.doesNotMatch(await page.locator("#crm-user-results").textContent(), /Устаревший ответ/);
      assert.equal(await page.locator(".crm-head > .crm-tabs").count(), 1);
      assert.deepEqual(await page.locator(".crm-people-table th").allTextContents(), ["Имя", "Мессенджеры", "Источник", "Тариф", "Итого", "Статус", "В боте", "Подписка"]);
      assert.equal(await page.locator(".crm-people-table tbody tr[data-user-id='u1'] .crm-contact-cell .crm-contact-button").count(), 2);
      assert.equal(await page.locator(".crm-people-table tbody tr[data-user-id='u1'] .crm-table-messenger-slot").count(), 2);
      await page.locator(".crm-people-table tbody tr[data-user-id='u1'] .crm-preview-trigger.email").hover();
      await page.getByText("Нажмите значок копирования справа от имени, чтобы скопировать адрес.").waitFor();
      assert.match(await page.locator(".crm-popover:visible").textContent(), /anna@example\.com/);
      assert.equal(await page.locator(".crm-people-table tbody tr[data-user-id='u1'] .crm-copy-email").count(), 1);
      await page.locator(".crm-people-table tbody tr[data-user-id='u1'] .crm-copy-email").click();
      await page.locator(".crm-people-table tbody tr[data-user-id='u1'] .crm-copy-email[aria-label='Email скопирован']").waitFor();
      assert.equal(await page.locator(".crm-people-table tbody tr[data-user-id='u1'] .crm-copy-email").getAttribute("aria-label"), "Email скопирован");
      assert.equal(await page.locator(".crm-table-wrap").evaluate((node) => node.scrollWidth > node.clientWidth), true);
      assert.equal(await page.locator(".crm-table-scrollbar").evaluate((node) => node.scrollWidth > node.clientWidth), true);
      assert.match(await page.locator(".crm-people-table tbody").textContent(), /с 01\.08\.2026.*первая покупка 02\.08\.2026.*Подписан/s);
      await page.getByRole("button", { name:"Показать тариф и доступы: Анна" }).hover();
      await page.getByText("Доступно", { exact:true }).waitFor();
      assert.match(await page.locator(".crm-popover:visible").textContent(), /Мастер-класс.*Стандарт.*02\.08\.2026.*Доступно.*Diet Quality Score.*Прогресс курсов.*12 из 20/s);
      assert.doesNotMatch(await page.locator(".crm-popover:visible").textContent(), /Позже куплено/);
      await page.getByRole("button", { name:"Показать оплаты: Анна" }).hover();
      await page.locator(".crm-popover:visible .crm-popover-title", { hasText:"Оплаты" }).waitFor();
      assert.match(await page.locator(".crm-popover:visible").textContent(), /3\s000 ₽.*Diet Quality Score.*9\s000 ₽.*Мастер-класс.*Прогресс курсов.*12 из 20/s);
      assert.doesNotMatch(await page.locator(".crm-popover:visible").textContent(), /Robokassa/);
      await page.getByRole("button", { name:"Показать статус и прогресс: Анна" }).hover();
      await page.getByText(/Покупатель · прогресс/).waitFor();
      assert.match(await page.locator(".crm-popover:visible").textContent(), /Мастер-класс.*12 из 20/s);
      assert.ok(userQueries.includes("a") && userQueries.includes("anna"));
      await search.fill("error");
      await page.waitForTimeout(380);
      assert.equal(await page.getByText("CRM", { exact:true }).count(), 2);
      assert.match(await page.locator("#crm-user-results").textContent(), /Люди не загрузились/);
      assert.equal(await search.inputValue(), "error");
      assert.equal(await search.evaluate((node) => document.activeElement === node), true);
      await page.getByRole("button", { name:"Повторить" }).click();
      await page.locator("#crm-user-results tbody tr[data-user-id]").first().waitFor();
      assert.equal(userQueries.filter((query) => query === "error").length, 2);
      await page.getByRole("button", { name:"Лиды", exact:true }).click();
      await page.locator("#crm-user-results tbody tr[data-user-id]").first().waitFor();
      assert.deepEqual(await page.locator(".crm-people-table th").allTextContents(), ["Имя", "Мессенджеры", "Источник", "В боте", "Подписка", "Статус", "Заметки"]);
      assert.match(await page.locator(".crm-people-table tbody").textContent(), /Подписан/);
      await page.getByRole("button", { name:"Есть МК" }).click();
      await page.locator("#crm-user-results tbody tr[data-user-id]").first().waitFor();
      assert.equal(userAccessFilters.at(-1), "true");
      await page.getByRole("button", { name:"Сопровождение", exact:true }).click();
      await page.locator("#crm-user-results tbody tr[data-user-id]").first().waitFor();
      assert.equal(userAccompanimentFilters.at(-1), "active");
      assert.deepEqual(await page.locator(".crm-people-table th").allTextContents(), ["Имя", "Мессенджеры", "Источник", "Итого", "Подписка", "Статус", "Заметки"]);
      await page.locator(".crm-filters summary").click();
      assert.match(await page.locator(".crm-filter-help").textContent(), /Тег.*не подтверждает оплату/s);
      assert.match(await page.locator(".crm-filter-help").textContent(), /Проблемы доступа.*очередь/s);
      await page.getByRole("button", { name:"Показать оплаты: Анна" }).hover();
      await page.locator(".crm-popover:visible .crm-popover-title", { hasText:"Оплаты" }).waitFor();
      assert.match(await page.locator(".crm-popover:visible").textContent(), /Мастер-класс/);
      await page.locator(".crm-people-table tbody tr[data-user-id='u1'] .crm-person-name").click();
      await page.locator(".crm-profile-head").waitFor();
      assert.match(await page.locator(".crm-profile-head").textContent(), /Анна/);
      assert.equal(await page.getByText("Курсы и доступы", { exact:true }).count(), 1);
      assert.equal(new URL(page.url()).searchParams.get("user"), "u1");
      assert.equal(await page.getByText("Купленные продукты и тарифы", { exact:true }).count(), 0);
      assert.equal(await page.getByText("История покупок", { exact:true }).count(), 1);
      assert.equal(await page.locator(".crm-purchase-item").count(), 2);
      assert.equal(await page.locator(".crm-profile-contacts").count(), 0);
      assert.equal(await page.locator(".crm-profile-messengers .crm-contact-button--telegram").count(), 1);
      assert.equal(await page.locator(".crm-profile-messengers .crm-contact-button--max").count(), 1);
      assert.equal(await page.locator(".crm-profile-messengers a.crm-contact-button--telegram[href='https://t.me/anna']").count(), 1);
      assert.equal(await page.locator(".crm-profile-messengers a.crm-contact-button--max").count(), 0);
      assert.match(await page.locator(".crm-note-card").textContent(), /Обсудить следующий этап/);
      assert.ok((await page.locator(".crm-apps-card").boundingBox()).y < (await page.locator(".crm-note-card").boundingBox()).y);
      assert.equal(await page.locator(".crm-foot").count(), 0);
      assert.equal(await page.getByText("Tilda Members Area", { exact:true }).count(), 0);
      assert.equal(await page.locator("#review-form").count(), 0);
      assert.equal(await page.locator("#course-access-preview [data-course-code='ACCESS_CALORIES']").count(), 1);
      assert.equal(await page.locator("#course-access-preview [data-course-code='ACCESS_MASTERCLASS'] .is-right").count(), 1);
      assert.equal(await page.locator("#course-access-preview [data-course-setting]").count(), 0);
      await page.getByRole("button", { name:"Настроить доступ к курсу Курс о калориях" }).click();
      assert.equal(await page.getByRole("button", { name:"Скрыть доступ к курсу Курс о калориях" }).getAttribute("aria-expanded"), "true");
      assert.equal(await page.locator("#course-access-preview [data-course-code='ACCESS_CALORIES'] [data-course-setting='start-open']").isDisabled(), true);
      assert.equal(await page.locator(".crm-access-applications", { hasText:"Дневник силовых тренировок" }).count(), 1);
      assert.equal(await page.getByRole("checkbox", { name:"DQS" }).isChecked(), true);
      await page.getByRole("checkbox", { name:"Дневник силовых тренировок" }).check();
      await page.getByRole("checkbox", { name:"Дневник силовых тренировок" }).waitFor({state:"attached"});
      assert.equal(await page.getByRole("checkbox", { name:"Дневник силовых тренировок" }).isChecked(), true);
      assert.equal(await page.locator(".crm-card-title", { hasText:"Этапы рассылки" }).count(), 1);
      assert.equal(await page.locator(".crm-avatar").count(), 0);
      assert.match(await page.locator(".crm-profile-summary").textContent(), /Первая оплата.*02\.08\.2026.*через 1 дн\. после старта бота/s);
      assert.equal(await page.locator(".crm-course-access-card").count(), 1);
      assert.equal(await page.locator(".crm-course-progress-card").count(), 0);
      assert.equal(await page.locator(".crm-purchases-card .crm-inline-personal").count(), 1);
      assert.equal(await page.locator(".crm-purchases-card .crm-inline-personal").getAttribute("open"), null);
      assert.doesNotMatch(await page.locator("body").textContent(), /Просмотр и смена записываются в журнал админки/);
      await page.getByRole("button", { name:"Показать прогресс: Diet Quality Score" }).hover();
      await page.getByText(/Покупатель · прогресс/).waitFor();
      assert.match(await page.locator(".crm-popover:visible").textContent(), /Мастер-класс.*12 из 20/s);
      if (evidence) await page.screenshot({ path: path.join(evidence, "admin-crm-profile-1440.png"), fullPage:true });
      await page.getByRole("button", { name:"← Назад" }).click();
      await page.locator("#crm-user-results tbody tr[data-user-id]").first().waitFor();
      assert.equal(new URL(page.url()).searchParams.has("user"), false);
      failNextPaymentRequest = true;
      await page.getByRole("button", { name:"Оплаты", exact:true }).click();
      await page.getByText("CRM не загрузилась", { exact:true }).waitFor();
      assert.match(await page.locator(".crm-error").textContent(), /test payment error/);
      await page.getByRole("button", { name:"Повторить" }).click();
      await page.locator("#payment-next:not([disabled])").waitFor();
      assert.equal(paymentQueries.at(-1).has("date_from"), false);
      assert.equal(paymentQueries.at(-1).has("date_to"), false);
      assert.equal(paymentQueries.at(-1).has("product_code"), false);
      assert.equal(paymentQueries.at(-1).get("amount_kind"), "all");
      assert.match(await page.locator(".crm-table tbody").textContent(), /Первая оплата 1/);
      assert.deepEqual(await page.locator(".crm-table th").allTextContents(), ["Дата", "Человек", "Что куплено", "Сумма"]);
      assert.doesNotMatch(await page.locator(".crm-table tbody").textContent(), /Robokassa/);
      await page.locator("#payment-next").click();
      await page.waitForTimeout(80);
      assert.deepEqual(paymentOffsets.slice(-2), [0, 100]);
      assert.deepEqual(paymentSnapshots.slice(-2), [null, "2026-09-19T12:00:00Z"]);
      assert.match(await page.locator(".crm-table tbody").textContent(), /Оплата 101/);
      assert.doesNotMatch(await page.locator(".crm-table tbody").textContent(), /Первая оплата/);
      await page.getByRole("button", { name:"Люди" }).click();
      await page.locator("#crm-search").fill("");
      await page.locator("#crm-user-results tbody tr[data-user-id]").first().waitFor();
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
      await assertDesktopGeometry(page, 270);
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

{
  const page = await browser.newPage({ viewport: { width: 1440, height: 560 } });
  await page.goto(`http://127.0.0.1:${port}/crm`);
  await page.getByRole("link", { name: "Продукты и описания" }).waitFor();
  await page.locator(".admin-shell-nav").evaluate((node) => { node.scrollTop = 220; });
  await page.waitForTimeout(30);
  const before = await page.locator(".admin-shell-nav").evaluate((node) => node.scrollTop);
  await page.goto(`http://127.0.0.1:${port}/admin/products`);
  await page.getByRole("heading", { name: "Продукты и описания" }).waitFor();
  const after = await page.locator(".admin-shell-nav").evaluate((node) => node.scrollTop);
  assert.ok(before > 100 && Math.abs(after - before) <= 2, JSON.stringify({before,after}));
  await page.close();
}

{
  const page = await browser.newPage({ viewport: { width: 1440, height: 560 } });
  await page.goto(`http://127.0.0.1:${port}/crm?user=u1`);
  await page.locator(".admin-shell-nav").getByRole("link", { name: "DQS", exact: true }).waitFor();
  assert.equal(await page.getByRole("link", { name: "CRM" }).getAttribute("href"), "/crm?user=u1");
  assert.equal(await page.locator(".admin-shell-nav").getByRole("link", { name: "DQS", exact: true }).getAttribute("href"), "/admin/dqs?user=u1");
  assert.equal(await page.locator(".admin-shell-nav").getByRole("link", { name: "Силовые", exact: true }).getAttribute("href"), "/admin/strength?user=u1");
  assert.equal(await page.locator(".admin-shell-nav").getByRole("link", { name: "Метаболизм", exact: true }).getAttribute("href"), "/admin/metabolism?user=u1");
  assert.equal(await page.locator(".admin-shell-nav").getByRole("link", { name: "Продукты и описания", exact: true }).getAttribute("href"), "/admin/products?user=u1");
  assert.equal(await page.getByRole("link", { name: "Личный кабинет" }).getAttribute("href"), "/lk");
  await page.close();
}

await browser.close();
await new Promise((resolve) => server.close(resolve));
console.log("admin shell e2e: ok");
