import assert from "node:assert/strict";
import {createServer} from "node:http";
import {createRequire} from "node:module";
import {readFileSync} from "node:fs";
import path from "node:path";
import {fileURLToPath} from "node:url";

const require = createRequire(import.meta.url);
const {chromium} = process.env.CODEX_NODE_MODULES
  ? require(path.join(process.env.CODEX_NODE_MODULES, "playwright")) : await import("playwright");
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
const staticRoot = path.join(root, "backend/app/static");
const navigation = {modules: [{id: "platform.crm", admin_catalog: [
  {category: "clients", order: 10, url: "/crm", label: "CRM", icon: "👥"}
]}]};
const server = createServer((req, res) => {
  const url = new URL(req.url, "http://localhost");
  if (url.pathname === "/admin") {
    res.setHeader("Content-Type", "text/html");
    return res.end('<main id="test-login">Вход</main>');
  }
  if (url.pathname.startsWith("/admin/api/")) {
    res.setHeader("Content-Type", "application/json");
    return res.end(JSON.stringify(url.pathname === "/admin/api/navigation" ? navigation : []));
  }
  const name = url.pathname === "/crm" ? "crm.html" : path.basename(url.pathname);
  try {
    const file = readFileSync(path.join(staticRoot, name));
    res.setHeader("Content-Type", name.endsWith(".js") ? "text/javascript" : name.endsWith(".css") ? "text/css" : "text/html");
    res.end(file);
  } catch { res.writeHead(404).end(); }
});
await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
const origin = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch({headless: true});
const pages = [];
try {
  const page = await browser.newPage(); pages.push(page);
  const requests = [];
  page.on("request", request => requests.push(new URL(request.url()).pathname));
  let releaseMenu;
  const menuGate = new Promise(resolve => { releaseMenu = resolve; });
  await page.route("**/admin/api/navigation", async route => {
    await menuGate;
    await route.fulfill({json: navigation});
  });
  await page.goto(origin + "/crm");
  await page.waitForSelector("#crm-user-results table");
  assert(!requests.includes("/admin/api/project-map"));
  assert(!requests.includes("/admin/api/summary"));
  const search = page.locator("#crm-search");
  await search.fill("не потерять ввод");
  await search.focus();
  releaseMenu();
  await page.waitForSelector('.admin-shell-nav a[href="/crm"]');
  assert.equal(await search.inputValue(), "не потерять ввод");
  assert.equal(await page.evaluate(() => document.activeElement.id), "crm-search");

  const errors = await browser.newPage(); pages.push(errors);
  let menuAttempts = 0;
  await errors.route("**/admin/api/navigation", route => ++menuAttempts === 1
    ? route.fulfill({status: 503, json: {detail: "unavailable"}})
    : route.fulfill({json: navigation}));
  await errors.goto(origin + "/crm");
  await errors.waitForSelector("#crm-user-results table");
  await errors.getByRole("button", {name: "Меню не загрузилось. Повторить"}).click();
  await errors.waitForSelector('.admin-shell-nav a[href="/crm"]');
  assert.equal(await errors.locator("#crm-user-results table").count(), 1);

  const direct = await browser.newPage(); pages.push(direct);
  let cardRequested = false;
  const directRequests = [];
  direct.on("request", request => directRequests.push(new URL(request.url()).pathname));
  await direct.route("**/admin/api/users/direct-user", route => {
    cardRequested = true;
    return route.fulfill({status: 404, json: {detail: "Synthetic missing user"}});
  });
  await direct.goto(origin + "/crm?user=direct-user");
  await direct.waitForFunction(() => document.querySelector(".crm-error")?.textContent.includes("Synthetic missing user"));
  assert(cardRequested, "Direct client request must start without summary");
  assert(!directRequests.includes("/admin/api/summary"));

  const expired = await browser.newPage(); pages.push(expired);
  await expired.route("**/admin/api/navigation", route => route.fulfill({status: 401, json: {detail: "expired"}}));
  await expired.goto(origin + "/crm?q=preserve");
  await expired.waitForURL(url => url.pathname === "/admin" && url.searchParams.get("next") === "/crm?q=preserve");
  await expired.waitForSelector("#test-login");
  console.log("PASS: clients and direct profile skip unused summary; menu recovers independently; no full map requested");
} finally {
  for (const page of pages) await page.close();
  await browser.close();
  await new Promise(resolve => server.close(resolve));
}
