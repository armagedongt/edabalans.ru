import assert from "node:assert/strict";
import test from "node:test";

import {
  campaignIds,
  initialState,
  probe,
  runWatchdog,
  updateIncidentState,
} from "../src/logic.mjs";
import worker, { WatchdogCoordinator } from "../src/index.mjs";

class MemoryStorage {
  constructor(value = null) {
    this.value = value;
  }

  async get() {
    return structuredClone(this.value);
  }

  async put(_key, value) {
    this.value = structuredClone(value);
  }
}

function response(status, body) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function healthyChecks() {
  return {
    platform: { ok: true, status: 200, reasons: [], error: null },
    telegram: { ok: true, status: 200, reasons: [], error: null, route: "proxy" },
  };
}

test("campaign IDs reject the whole configuration when any value is invalid", () => {
  assert.deepEqual(campaignIds("12, 34"), [12, 34]);
  assert.throws(() => campaignIds("12, nope, 34, 5.5"), /некорректные ID/);
});

test("probe requires both HTTP success and an explicit ready payload", async () => {
  const good = await probe("https://example.test/ready", async () => response(200, { status: "ready" }));
  const wrong = await probe("https://example.test/ready", async () => response(200, { status: "ok" }));
  const failed = await probe("https://example.test/ready", async () => response(503, { status: "unavailable", reasons: ["polling_stale"] }));

  assert.equal(good.ok, true);
  assert.equal(wrong.ok, false);
  assert.equal(wrong.error, "unexpected_response");
  assert.equal(failed.ok, false);
  assert.deepEqual(failed.reasons, ["polling_stale"]);
});

test("three consecutive failures open one incident and recovery queues one message", () => {
  const failing = healthyChecks();
  failing.telegram = { ok: false, status: 503, reasons: ["polling_stale"], error: null, route: "proxy" };
  let state = initialState();
  state = updateIncidentState(state, failing, 0, 3);
  state = updateIncidentState(state, failing, 60_000, 3);
  assert.equal(state.incident, null);
  state = updateIncidentState(state, failing, 120_000, 3);
  assert.ok(state.incident);
  assert.equal(state.pendingAlerts.length, 1);

  state = updateIncidentState(state, healthyChecks(), 180_000, 3);
  assert.equal(state.incident, null);
  assert.equal(state.pendingAlerts.length, 2);
});

test("a changed failure boundary must earn its own consecutive failure streak", () => {
  const platformFailure = healthyChecks();
  platformFailure.platform = { ok: false, status: 503, reasons: [], error: "network_error" };
  const telegramFailure = healthyChecks();
  telegramFailure.telegram = { ok: false, status: 503, reasons: ["polling_stale"], error: null };
  let state = initialState();
  state = updateIncidentState(state, platformFailure, 0, 3);
  state = updateIncidentState(state, platformFailure, 60_000, 3);
  state = updateIncidentState(state, telegramFailure, 120_000, 3);
  assert.equal(state.incident, null);
  assert.equal(state.failureStreak, 1);
  state = updateIncidentState(state, telegramFailure, 180_000, 3);
  assert.equal(state.incident, null);
});

test("a healthy check breaks a pre-incident failure streak", () => {
  const failing = healthyChecks();
  failing.telegram = { ok: false, status: 503, reasons: ["polling_stale"], error: null };
  let state = initialState();
  state = updateIncidentState(state, failing, 0, 3);
  state = updateIncidentState(state, failing, 60_000, 3);
  state = updateIncidentState(state, healthyChecks(), 120_000, 3);
  state = updateIncidentState(state, failing, 180_000, 3);
  state = updateIncidentState(state, failing, 240_000, 3);
  assert.equal(state.incident, null);
  assert.equal(state.failureStreak, 2);
});

test("an open incident switches recovery boundary only after three matching checks", () => {
  const platformFailure = healthyChecks();
  platformFailure.platform = { ok: false, status: 503, reasons: [], error: "network_error" };
  const telegramFailure = healthyChecks();
  telegramFailure.telegram = { ok: false, status: 503, reasons: ["polling_stale"], error: null };
  let state = initialState();
  state = updateIncidentState(state, platformFailure, 0, 3);
  state = updateIncidentState(state, platformFailure, 60_000, 3);
  state = updateIncidentState(state, platformFailure, 120_000, 3);
  assert.deepEqual(state.incident.confirmedFailures, ["platform"]);
  state = updateIncidentState(state, telegramFailure, 180_000, 3);
  state = updateIncidentState(state, telegramFailure, 240_000, 3);
  assert.deepEqual(state.incident.confirmedFailures, ["platform"]);
  state = updateIncidentState(state, telegramFailure, 300_000, 3);
  assert.deepEqual(state.incident.confirmedFailures, ["telegram"]);
});

test("Telegram-only incident reboots EU first, RU after five minutes, then suspends ads", async () => {
  const calls = [];
  const fetchImpl = async (url, options = {}) => {
    calls.push({ url: String(url), options });
    if (String(url).includes("/ready") && !String(url).includes("/telegram/")) {
      return response(200, { status: "ready" });
    }
    if (String(url).includes("/telegram/ready")) {
      return response(503, { status: "unavailable", reasons: ["polling_stale"], telegram_route: "proxy" });
    }
    if (String(url).includes("api.telegram.org")) return response(200, { ok: true, result: {} });
    if (String(url).includes("api.timeweb.cloud")) return response(200, {});
    if (String(url).includes("api.direct.yandex.com")) {
      return response(200, { result: { SuspendResults: [{ Id: 101 }] } });
    }
    throw new Error(`Unexpected URL: ${url}`);
  };
  const env = {
    PLATFORM_READY_URL: "https://api.example/ready",
    TELEGRAM_READY_URL: "https://api.example/telegram/ready",
    FAILURES_BEFORE_INCIDENT: "3",
    ACTIONS_ENABLED: "true",
    TIMEWEB_API_TOKEN: "timeweb-secret",
    TIMEWEB_RU_SERVER_ID: "ru-id",
    TIMEWEB_EU_SERVER_ID: "eu-id",
    TELEGRAM_BOT_TOKEN: "telegram-secret",
    TELEGRAM_ALERT_CHAT_ID: "42",
    YANDEX_DIRECT_TOKEN: "direct-secret",
    YANDEX_CAMPAIGN_IDS: "101",
  };
  const storage = new MemoryStorage();

  await runWatchdog(env, storage, { fetchImpl, now: 0 });
  await runWatchdog(env, storage, { fetchImpl, now: 60_000 });
  await runWatchdog(env, storage, { fetchImpl, now: 120_000 });
  assert.equal(calls.filter((call) => call.url.endsWith("/servers/eu-id/reboot")).length, 1);
  assert.equal(calls.filter((call) => call.url.endsWith("/servers/ru-id/reboot")).length, 0);

  await runWatchdog(env, storage, { fetchImpl, now: 299_999 });
  assert.equal(calls.filter((call) => call.url.endsWith("/servers/ru-id/reboot")).length, 0);
  await runWatchdog(env, storage, { fetchImpl, now: 300_000 });
  assert.equal(calls.filter((call) => call.url.endsWith("/servers/ru-id/reboot")).length, 1);
  assert.equal(calls.filter((call) => call.url.includes("api.direct.yandex.com")).length, 0);

  await runWatchdog(env, storage, { fetchImpl, now: 599_999 });
  assert.equal(calls.filter((call) => call.url.includes("api.direct.yandex.com")).length, 0);
  await runWatchdog(env, storage, { fetchImpl, now: 600_000 });
  assert.equal(calls.filter((call) => call.url.endsWith("/servers/eu-id/reboot")).length, 1);
  assert.equal(calls.filter((call) => call.url.endsWith("/servers/ru-id/reboot")).length, 1);
  assert.equal(calls.filter((call) => call.url.includes("api.direct.yandex.com")).length, 1);
  const yandexCall = calls.find((call) => call.url.includes("api.direct.yandex.com"));
  assert.deepEqual(JSON.parse(yandexCall.options.body).params.SelectionCriteria.Ids, [101]);
  assert.equal(JSON.parse(yandexCall.options.body).method, "suspend");
  const alertTexts = calls
    .filter((call) => call.url.includes("api.telegram.org"))
    .map((call) => JSON.parse(call.options.body).text);
  assert.equal(alertTexts.length, 4);
  assert.ok(alertTexts.some((text) => text.includes("Бот не работает")));
  assert.ok(alertTexts.some((text) => text.includes("европейский сервер")));
  assert.ok(alertTexts.some((text) => text.includes("российский сервер")));
  assert.ok(alertTexts.some((text) => text.includes("Реклама в Яндекс.Директе остановлена")));
});

test("failed ad suspension keeps retrying, but an ambiguous reboot is never repeated", async () => {
  const calls = [];
  const fetchImpl = async (url) => {
    calls.push(String(url));
    if (String(url).includes("/telegram/ready")) return response(503, { status: "unavailable" });
    if (String(url).endsWith("/ready")) return response(200, { status: "ready" });
    if (String(url).includes("api.telegram.org")) return response(200, { ok: true });
    if (String(url).includes("api.timeweb.cloud")) return response(504, {});
    if (String(url).includes("api.direct.yandex.com")) return response(503, {});
    throw new Error(`Unexpected URL: ${url}`);
  };
  const env = {
    PLATFORM_READY_URL: "https://api.example/ready",
    TELEGRAM_READY_URL: "https://api.example/telegram/ready",
    FAILURES_BEFORE_INCIDENT: "1",
    ACTIONS_ENABLED: "true",
    ACTION_RETRY_SECONDS: "1",
    MAX_ACTION_ATTEMPTS: "3",
    TIMEWEB_API_TOKEN: "timeweb-secret",
    TIMEWEB_RU_SERVER_ID: "ru-id",
    TIMEWEB_EU_SERVER_ID: "eu-id",
    TELEGRAM_BOT_TOKEN: "telegram-secret",
    TELEGRAM_ALERT_CHAT_ID: "42",
    YANDEX_DIRECT_TOKEN: "direct-secret",
    YANDEX_CAMPAIGN_IDS: "101",
    ADS_PAUSE_AFTER_SECONDS: "1",
  };
  const storage = new MemoryStorage();
  for (const now of [1_000, 3_000, 5_000, 7_000, 9_000]) {
    await runWatchdog(env, storage, { fetchImpl, now });
  }
  assert.equal(calls.filter((url) => url.endsWith("/servers/eu-id/reboot")).length, 1);
  assert.equal(calls.filter((url) => url.includes("api.direct.yandex.com")).length, 4);
});

test("recovery after an ad suspension sends an alert and never resumes campaigns", async () => {
  let healthy = false;
  const telegramBodies = [];
  const yandexBodies = [];
  const fetchImpl = async (url, options = {}) => {
    if (String(url).includes("api.telegram.org")) {
      telegramBodies.push(JSON.parse(options.body));
      return response(200, { ok: true });
    }
    if (String(url).includes("api.timeweb.cloud")) return response(200, {});
    if (String(url).includes("api.direct.yandex.com")) {
      yandexBodies.push(JSON.parse(options.body));
      return response(200, { result: { SuspendResults: [{ Id: 101 }] } });
    }
    return healthy ? response(200, { status: "ready" }) : response(503, { status: "unavailable" });
  };
  const env = {
    PLATFORM_READY_URL: "https://api.example/ready",
    TELEGRAM_READY_URL: "https://api.example/telegram/ready",
    FAILURES_BEFORE_INCIDENT: "1",
    ADS_PAUSE_AFTER_SECONDS: "1",
    ACTIONS_ENABLED: "true",
    TIMEWEB_API_TOKEN: "timeweb-secret",
    TIMEWEB_RU_SERVER_ID: "ru-id",
    TELEGRAM_BOT_TOKEN: "telegram-secret",
    TELEGRAM_ALERT_CHAT_ID: "42",
    YANDEX_DIRECT_TOKEN: "direct-secret",
    YANDEX_CAMPAIGN_IDS: "101",
  };
  const storage = new MemoryStorage();
  await runWatchdog(env, storage, { fetchImpl, now: 1_000 });
  await runWatchdog(env, storage, { fetchImpl, now: 3_000 });
  healthy = true;
  await runWatchdog(env, storage, { fetchImpl, now: 4_000 });
  assert.deepEqual(yandexBodies.map((body) => body.method), ["suspend"]);
  assert.match(telegramBodies.at(-1).text, /снова работает/);
});

test("alerts remain queued after Telegram failure and are delivered once after retry", async () => {
  let alertAttempt = 0;
  const delivered = [];
  const fetchImpl = async (url, options = {}) => {
    if (String(url).includes("api.telegram.org")) {
      alertAttempt += 1;
      if (alertAttempt === 1) return response(503, {});
      delivered.push(JSON.parse(options.body).text);
      return response(200, { ok: true });
    }
    return response(503, { status: "unavailable" });
  };
  const env = {
    PLATFORM_READY_URL: "https://api.example/ready",
    TELEGRAM_READY_URL: "https://api.example/telegram/ready",
    FAILURES_BEFORE_INCIDENT: "1",
    ACTIONS_ENABLED: "false",
    TELEGRAM_BOT_TOKEN: "telegram-secret",
    TELEGRAM_ALERT_CHAT_ID: "42",
  };
  const storage = new MemoryStorage();
  await runWatchdog(env, storage, { fetchImpl, now: 1_000 });
  assert.ok(storage.value.pendingAlerts.length > 0);
  const queued = storage.value.pendingAlerts.length;
  await runWatchdog(env, storage, { fetchImpl, now: 2_000 });
  assert.equal(storage.value.pendingAlerts.length, 0);
  assert.equal(delivered.length, queued);
});

test("platform incident reboots only the Russian server immediately", async () => {
  const calls = [];
  const fetchImpl = async (url) => {
    calls.push(String(url));
    if (String(url).includes("api.telegram.org")) return response(200, { ok: true });
    if (String(url).includes("api.timeweb.cloud")) return response(200, {});
    return response(503, { status: "unavailable" });
  };
  const env = {
    PLATFORM_READY_URL: "https://api.example/ready",
    TELEGRAM_READY_URL: "https://api.example/telegram/ready",
    FAILURES_BEFORE_INCIDENT: "1",
    ACTIONS_ENABLED: "true",
    TIMEWEB_API_TOKEN: "timeweb-secret",
    TIMEWEB_RU_SERVER_ID: "ru-id",
    TIMEWEB_EU_SERVER_ID: "eu-id",
    TELEGRAM_BOT_TOKEN: "telegram-secret",
    TELEGRAM_ALERT_CHAT_ID: "42",
  };
  await runWatchdog(env, new MemoryStorage(), { fetchImpl, now: 1_000 });

  assert.equal(calls.filter((url) => url.endsWith("/servers/ru-id/reboot")).length, 1);
  assert.equal(calls.filter((url) => url.endsWith("/servers/eu-id/reboot")).length, 0);
});

test("actions stay disabled until secrets and the production switch are configured", async () => {
  const fetchImpl = async (url) => {
    if (String(url).includes("api.telegram.org")) return response(200, { ok: true });
    return response(503, { status: "unavailable" });
  };
  const storage = new MemoryStorage();
  await runWatchdog(
    {
      PLATFORM_READY_URL: "https://api.example/ready",
      TELEGRAM_READY_URL: "https://api.example/telegram/ready",
      FAILURES_BEFORE_INCIDENT: "1",
      TELEGRAM_BOT_TOKEN: "telegram-secret",
      TELEGRAM_ALERT_CHAT_ID: "42",
      ACTIONS_ENABLED: "false",
    },
    storage,
    { fetchImpl, now: 1_000 },
  );

  assert.equal(storage.value.incident.ruReboot.status, "pending");
  assert.match(storage.value.incident.missingConfigurationAlerts.ruReboot, /выключены/);
});

test("invalid campaign IDs block all Yandex calls and produce a configuration alert", async () => {
  const calls = [];
  const fetchImpl = async (url) => {
    calls.push(String(url));
    if (String(url).includes("api.telegram.org")) return response(200, { ok: true });
    return response(503, { status: "unavailable" });
  };
  const storage = new MemoryStorage();
  await runWatchdog({
    PLATFORM_READY_URL: "https://api.example/ready",
    TELEGRAM_READY_URL: "https://api.example/telegram/ready",
    FAILURES_BEFORE_INCIDENT: "1",
    ADS_PAUSE_AFTER_SECONDS: "1",
    ACTIONS_ENABLED: "true",
    TELEGRAM_BOT_TOKEN: "telegram-secret",
    TELEGRAM_ALERT_CHAT_ID: "42",
    YANDEX_DIRECT_TOKEN: "direct-secret",
    YANDEX_CAMPAIGN_IDS: "101, typo",
  }, storage, { fetchImpl, now: 1_000 });
  await runWatchdog({
    PLATFORM_READY_URL: "https://api.example/ready",
    TELEGRAM_READY_URL: "https://api.example/telegram/ready",
    FAILURES_BEFORE_INCIDENT: "1",
    ADS_PAUSE_AFTER_SECONDS: "1",
    ACTIONS_ENABLED: "true",
    TELEGRAM_BOT_TOKEN: "telegram-secret",
    TELEGRAM_ALERT_CHAT_ID: "42",
    YANDEX_DIRECT_TOKEN: "direct-secret",
    YANDEX_CAMPAIGN_IDS: "101, typo",
  }, storage, { fetchImpl, now: 3_000 });
  assert.equal(calls.filter((url) => url.includes("api.direct.yandex.com")).length, 0);
  assert.match(storage.value.incident.missingConfigurationAlerts.adsPause, /некорректные ID/);
});

test("enabled actions with missing Timeweb credentials never call Timeweb", async () => {
  const calls = [];
  const fetchImpl = async (url) => {
    calls.push(String(url));
    if (String(url).includes("api.telegram.org")) return response(200, { ok: true });
    return response(503, { status: "unavailable" });
  };
  const storage = new MemoryStorage();
  await runWatchdog({
    PLATFORM_READY_URL: "https://api.example/ready",
    TELEGRAM_READY_URL: "https://api.example/telegram/ready",
    FAILURES_BEFORE_INCIDENT: "1",
    ACTIONS_ENABLED: "true",
    TELEGRAM_BOT_TOKEN: "telegram-secret",
    TELEGRAM_ALERT_CHAT_ID: "42",
  }, storage, { fetchImpl, now: 1_000 });
  assert.equal(calls.filter((url) => url.includes("api.timeweb.cloud")).length, 0);
  assert.match(storage.value.incident.missingConfigurationAlerts.ruReboot, /не настроен Timeweb API/);
});

test("enabled actions require a configured Telegram alert route", async () => {
  const calls = [];
  const fetchImpl = async (url) => {
    calls.push(String(url));
    return response(503, { status: "unavailable" });
  };
  const storage = new MemoryStorage();
  await runWatchdog({
    PLATFORM_READY_URL: "https://api.example/ready",
    TELEGRAM_READY_URL: "https://api.example/telegram/ready",
    FAILURES_BEFORE_INCIDENT: "1",
    ACTIONS_ENABLED: "true",
    TIMEWEB_API_TOKEN: "timeweb-secret",
    TIMEWEB_RU_SERVER_ID: "ru-id",
  }, storage, { fetchImpl, now: 1_000 });
  assert.equal(calls.filter((url) => url.includes("api.timeweb.cloud")).length, 0);
  assert.match(storage.value.incident.missingConfigurationAlerts.ruReboot, /канал аварийных уведомлений/);
});

test("scheduled handler dispatches one serialized Durable Object run", async () => {
  const calls = [];
  let pending;
  const env = {
    WATCHDOG: {
      idFromName(name) { calls.push(["id", name]); return "object-id"; },
      get(id) {
        calls.push(["get", id]);
        return { fetch(url, options) { calls.push(["fetch", url, options.method]); return Promise.resolve(new Response("ok")); } };
      },
    },
  };
  await worker.scheduled({}, env, { waitUntil(value) { pending = value; } });
  await pending;
  assert.deepEqual(calls, [
    ["id", "production"],
    ["get", "object-id"],
    ["fetch", "https://watchdog.internal/run", "POST"],
  ]);
});

test("authenticated drill uses a separate Durable Object and cannot request actions", async () => {
  const calls = [];
  const env = {
    DRILL_TOKEN: "drill-secret",
    WATCHDOG: {
      idFromName(name) { calls.push(["id", name]); return `${name}-id`; },
      get(id) {
        return { fetch(url, options) {
          calls.push(["fetch", id, url, options.headers["X-Watchdog-Drill"]]);
          return Promise.resolve(response(503, { ok: false }));
        } };
      },
    },
  };
  const denied = await worker.fetch(new Request("https://worker.example/drill/fail"), env);
  assert.equal(denied.status, 404);
  const accepted = await worker.fetch(new Request("https://worker.example/drill/fail", {
    method: "POST",
    headers: { Authorization: "Bearer drill-secret" },
  }), env);
  assert.equal(accepted.status, 503);
  assert.deepEqual(calls, [
    ["id", "drill"],
    ["fetch", "drill-id", "https://watchdog.internal/run", "fail"],
  ]);
});

test("real drill coordinator sends alerts but hard-blocks Timeweb and Yandex actions", async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url: String(url), options });
    if (String(url).includes("api.telegram.org")) return response(200, { ok: true });
    if (String(url).includes("api.timeweb.cloud")) return response(200, {});
    if (String(url).includes("api.direct.yandex.com")) return response(200, { result: {} });
    throw new Error(`Unexpected URL: ${url}`);
  };
  try {
    const coordinator = new WatchdogCoordinator({ storage: new MemoryStorage() }, {
      ACTIONS_ENABLED: "true",
      TIMEWEB_API_TOKEN: "timeweb-secret",
      TIMEWEB_RU_SERVER_ID: "ru-id",
      TIMEWEB_EU_SERVER_ID: "eu-id",
      YANDEX_DIRECT_TOKEN: "direct-secret",
      YANDEX_CAMPAIGN_IDS: "101",
      TELEGRAM_BOT_TOKEN: "telegram-secret",
      TELEGRAM_ALERT_CHAT_ID: "42",
    });
    for (let index = 0; index < 4; index += 1) {
      await coordinator.fetch(new Request("https://watchdog.internal/run", {
        method: "POST",
        headers: { "X-Watchdog-Drill": "fail" },
      }));
    }
    await coordinator.fetch(new Request("https://watchdog.internal/run", {
      method: "POST",
      headers: { "X-Watchdog-Drill": "recover" },
    }));
    assert.equal(calls.filter((call) => call.url.includes("api.timeweb.cloud")).length, 0);
    assert.equal(calls.filter((call) => call.url.includes("api.direct.yandex.com")).length, 0);
    const messages = calls
      .filter((call) => call.url.includes("api.telegram.org"))
      .map((call) => JSON.parse(call.options.body).text);
    assert.equal(messages.length, 2);
    assert.match(messages[0], /Бот не работает/);
    assert.match(messages[1], /снова работает/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("Durable Object queues overlapping runs instead of executing them together", async () => {
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  let probeCount = 0;
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => {
    probeCount += 1;
    if (probeCount <= 2) await gate;
    return response(200, { status: "ready" });
  };
  try {
    const coordinator = new WatchdogCoordinator({ storage: new MemoryStorage() }, {
      PLATFORM_READY_URL: "https://api.example/ready",
      TELEGRAM_READY_URL: "https://api.example/telegram/ready",
    });
    const first = coordinator.fetch(new Request("https://watchdog.internal/run", { method: "POST" }));
    await new Promise((resolve) => setTimeout(resolve, 0));
    const second = coordinator.fetch(new Request("https://watchdog.internal/run", { method: "POST" }));
    await new Promise((resolve) => setTimeout(resolve, 0));
    assert.equal(probeCount, 2);
    release();
    await Promise.all([first, second]);
    assert.equal(probeCount, 4);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
