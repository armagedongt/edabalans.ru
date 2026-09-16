import assert from "node:assert/strict";
import test from "node:test";
import { initialState, probe, runWatchdog, updateIncidentState } from "../src/logic.mjs";
import worker, { WatchdogCoordinator } from "../src/index.mjs";

const good = { ok: true, status: 200, reasons: [], error: null };
const healthy = { platform: good, telegram: good, max: good };
const failed = { ...healthy, max: { ...good, ok: false, status: 503, reasons: ["max_api_unreachable"] } };

function harness({ resumeFailure = null, campaignStates = [[101, "ON"], [102, "SUSPENDED"]] } = {}) {
  let state = initialState();
  const storage = {
    async get() { return structuredClone(state); },
    async put(key, value) { state = structuredClone(value); },
  };
  const methods = [], alerts = [];
  const campaigns = new Map(campaignStates);
  let resumeAttempts = 0;
  const env = {
    ACTIONS_ENABLED: "true", TELEGRAM_BOT_TOKEN: "test-token", TELEGRAM_ALERT_CHAT_ID: "test-chat",
    YANDEX_DIRECT_TOKEN: "test-token", YANDEX_CAMPAIGN_IDS: [...campaigns.keys()].join(","),
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
    if (request.method === "resume" && ++resumeAttempts === 1 && resumeFailure) {
      if (resumeFailure === "lost") {
        for (const id of ids) campaigns.set(id, "ON");
        throw new Error("resume response lost after applying request");
      }
      campaigns.set(ids[0], "ON");
      return Response.json({ result: { ResumeResults: ids.map((Id, index) => index === 0
        ? { Id } : { Id, Errors: [{ Code: 999 }] }) } });
    }
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

for (const persistent of ["max", "telegram", "platform"]) {
  test(`persistent ${persistent} failure is confirmed despite another flapping boundary`, async () => {
    const h = harness();
    const flapping = persistent === "telegram" ? "max" : "telegram";
    for (let i = 0; i < 3; i++) await h.run(i * 30_000, {
      ...healthy, [persistent]: { ...good, ok: false },
      [flapping]: { ...good, ok: i % 2 === 1 },
    });
    const state = await h.storage.get();
    assert.ok(state.incident);
    assert.deepEqual(state.incident.confirmedFailures, [persistent]);
    assert.equal(state.incident.startedAt, 0);
    assert.deepEqual(h.methods.filter(item => item.method === "suspend"), [{ method: "suspend", ids: [101] }]);
    assert.equal(h.alerts.filter(text => text.includes("🚨")).length, 1);
  });
}

for (const persistent of ["max", "telegram"]) {
  test(`outage alert diagnoses confirmed ${persistent}, not a single platform failure`, () => {
    let state = initialState();
    for (let i = 0; i < 3; i++) state = updateIncidentState(state, {
      ...healthy, [persistent]: { ...good, ok: false }, platform: { ...good, ok: i < 2 },
    }, i * 30_000, 3);
    assert.deepEqual(state.incident.confirmedFailures, [persistent]);
    assert.ok(state.pendingAlerts[0].includes(persistent === "max" ? "MAX-бот" : "Telegram-бот"));
    assert.ok(!state.pendingAlerts[0].includes("основной российский сервер/API"));
  });
}

test("alternating unrelated failures do not become three failures of one boundary", () => {
  let state = initialState();
  for (let i = 0; i < 12; i++) state = updateIncidentState(state, {
    ...healthy, [i % 2 ? "max" : "telegram"]: { ...good, ok: false },
  }, i * 30_000, 3);
  assert.equal(state.incident, null);
});

test("legacy durable streak survives upgrade without confirming a new boundary", () => {
  const old = initialState();
  delete old.failureChecks;
  old.failureStreak = 2;
  old.firstFailureAt = 0;
  old.candidateFailureKey = "telegram";
  const state = updateIncidentState(old, { ...failed, telegram: { ...good, ok: false } }, 60_000, 3);
  assert.deepEqual(state.incident.confirmedFailures, ["telegram"]);
  assert.equal(state.incident.startedAt, 0);
  assert.equal(state.failureChecks.max.streak, 1);
});

for (const resumeFailure of ["partial", "lost"]) {
  for (const boundary of ["max", "telegram"]) {
    test(`${boundary} relapse re-pauses owned campaigns after ${resumeFailure} resume response`, async () => {
      const h = harness({ resumeFailure, campaignStates: [[101, "ON"], [102, "ON"], [103, "SUSPENDED"]] });
      for (const now of [0, 30_000, 60_000]) await h.run(now, failed);
      for (const now of [90_000, 120_000, 150_000, 180_000, 210_000]) await h.run(now, healthy);
      assert.equal((await h.storage.get()).incident.resumeAds.status, "failed");
      assert.equal(h.campaigns.get(101), "ON");
      await h.run(240_000, { ...healthy, [boundary]: { ...good, ok: false } });
      assert.deepEqual(h.methods.filter(item => item.method === "suspend").map(item => item.ids),
        [[101, 102], resumeFailure === "partial" ? [101] : [101, 102]]);
      assert.deepEqual([...h.campaigns.values()], ["SUSPENDED", "SUSPENDED", "SUSPENDED"]);
      const incident = (await h.storage.get()).incident;
      assert.deepEqual(incident.adsPause.campaignIds, [101, 102]);
      assert.equal(incident.resumeAds.attempts, 0);
      for (const now of [270_000, 300_000, 330_000, 360_000]) await h.run(now, healthy);
      assert.equal(h.campaigns.get(101), "SUSPENDED");
      await h.run(390_000, healthy);
      assert.equal((await h.storage.get()).incident, null);
      assert.deepEqual([...h.campaigns.values()], ["ON", "ON", "SUSPENDED"]);
      assert.equal(h.alerts.filter(text => text.includes("🚨")).length, 1);
    });
  }
}

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
