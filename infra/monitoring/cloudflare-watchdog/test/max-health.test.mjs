import assert from "node:assert/strict";
import test from "node:test";
import { initialState, probe, runWatchdog } from "../src/logic.mjs";
import worker, { WatchdogCoordinator } from "../src/index.mjs";

const good = { ok: true, status: 200, reasons: [], error: null };
const healthy = { platform: good, telegram: good, max: good };
const failed = { ...healthy, max: { ...good, ok: false, status: 503, reasons: ["max_api_unreachable"] } };

function harness() {
  let state = initialState();
  const storage = {
    async get() { return structuredClone(state); },
    async put(key, value) { state = structuredClone(value); },
  };
  const methods = [], alerts = [];
  const campaigns = new Map([[101, "ON"], [102, "SUSPENDED"]]);
  const env = {
    ACTIONS_ENABLED: "true", TELEGRAM_BOT_TOKEN: "test-token", TELEGRAM_ALERT_CHAT_ID: "test-chat",
    YANDEX_DIRECT_TOKEN: "test-token", YANDEX_CAMPAIGN_IDS: "101,102",
    RECOVERY_STABLE_SECONDS: "120", RECOVERY_SUCCESSES_BEFORE_RESUME: "4",
    TIMEWEB_API_TOKEN: "test-token", TIMEWEB_RU_SERVER_ID: "test-server",
  };
  const fetchImpl = async (url, options) => {
    const request = JSON.parse(options.body);
    if (String(url).includes("api.telegram.org")) {
      alerts.push(request.text);
      return Response.json({ ok: true });
    }
    assert.ok(String(url).includes("api.direct.yandex.com"), "MAX-only failure must not reboot VM");
    const ids = request.params.SelectionCriteria.Ids;
    methods.push({ method: request.method, ids });
    if (request.method === "get") return Response.json({ result: { Campaigns: ids.map(Id => ({ Id, State: campaigns.get(Id) })) } });
    for (const id of ids) campaigns.set(id, request.method === "suspend" ? "SUSPENDED" : "ON");
    return Response.json({ result: { [request.method === "suspend" ? "SuspendResults" : "ResumeResults"]: ids.map(Id => ({ Id })) } });
  };
  const run = (now, checks) => runWatchdog(env, storage, { now, checks, fetchImpl, skipReport: true });
  return { run, storage, methods, alerts, campaigns };
}

test("MAX-only outage alerts once, pauses only active campaigns and never reboots VM", async () => {
  const h = harness();
  for (const now of [0, 30_000, 60_000, 90_000, 300_000]) await h.run(now, failed);
  assert.equal(h.alerts.filter(text => text.includes("🚨")).length, 1);
  assert.ok(h.alerts[0].includes("MAX"));
  assert.deepEqual(h.methods.filter(item => item.method === "suspend"), [{ method: "suspend", ids: [101] }]);
  assert.equal(h.campaigns.get(102), "SUSPENDED");
});

test("advertising recovers only after both Telegram and MAX are continuously healthy", async () => {
  const h = harness();
  for (const now of [0, 30_000, 60_000]) await h.run(now, failed);
  for (const now of [90_000, 120_000, 150_000]) await h.run(now, healthy);
  await h.run(180_000, { ...healthy, telegram: { ...good, ok: false } });
  for (const now of [210_000, 240_000, 270_000, 300_000]) await h.run(now, healthy);
  assert.equal(h.campaigns.get(101), "SUSPENDED");
  await h.run(330_000, healthy);
  assert.deepEqual(h.methods.filter(item => item.method === "resume"), [{ method: "resume", ids: [101] }]);
  assert.equal(h.campaigns.get(102), "SUSPENDED");
  assert.equal((await h.storage.get()).incident, null);
});

test("MAX probe rejects unrelated ready JSON", async () => {
  const wrong = await probe("https://example.test/max", async () => Response.json({ status: "ready" }), 1000, null, "max");
  assert.equal(wrong.ok, false);
  assert.equal(wrong.error, "unexpected_messenger");
});

test("production sampling actually calls the separate MAX endpoint", async () => {
  const urls = [];
  const env = { PLATFORM_READY_URL: "https://example.test/ready", TELEGRAM_READY_URL: "https://example.test/tg", MAX_READY_URL: "https://example.test/max" };
  const storage = { async get() { return initialState(); }, async put() {} };
  const result = await runWatchdog(env, storage, { skipActions: true, skipReport: true, fetchImpl: async url => {
    urls.push(url);
    return Response.json(url.endsWith("/max") ? { status: "unavailable", messenger: "max" } : { status: "ready", telegram_route: "relay" });
  } });
  assert.equal(result.ok, false);
  assert.equal(result.checks.max.ok, false);
  assert.ok(urls.includes(env.MAX_READY_URL));
});

test("MAX drill uses isolated state and sends alerts without touching advertising or servers", async () => {
  const messages = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, options) => {
    assert.ok(String(url).includes("api.telegram.org"));
    messages.push(JSON.parse(options.body).text);
    return Response.json({ ok: true });
  };
  try {
    let state = initialState();
    const coordinator = new WatchdogCoordinator({ storage: {
      async get() { return structuredClone(state); }, async put(key, value) { state = structuredClone(value); },
    } }, {
      ACTIONS_ENABLED: "true", TELEGRAM_BOT_TOKEN: "test-token", TELEGRAM_ALERT_CHAT_ID: "test-chat",
      YANDEX_DIRECT_TOKEN: "test-token", YANDEX_CAMPAIGN_IDS: "101", TIMEWEB_API_TOKEN: "test-token", TIMEWEB_RU_SERVER_ID: "test-server",
      RECOVERY_STABLE_SECONDS: "120", RECOVERY_SUCCESSES_BEFORE_RESUME: "4",
    });
    const env = { DRILL_TOKEN: "test-drill", WATCHDOG: {
      idFromName(name) { assert.equal(name, "drill-max"); return name; },
      get() { return { fetch(url, options) { return coordinator.fetch(new Request(url, options)); } }; },
    } };
    const request = action => new Request(`https://example.test/drill/max/${action}`, {
      method: "POST", headers: { Authorization: "Bearer test-drill" },
    });
    for (let i = 0; i < 4; i++) assert.equal((await worker.fetch(request("fail"), env)).status, 503);
    for (let i = 0; i < 5; i++) assert.equal((await worker.fetch(request("recover"), env)).status, 200);
    assert.equal(messages.length, 2);
    assert.ok(messages[0].includes("MAX"));
    assert.equal(state.incident, null);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
