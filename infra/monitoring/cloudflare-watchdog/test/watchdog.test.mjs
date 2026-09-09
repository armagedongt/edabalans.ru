import assert from "node:assert/strict";
import test from "node:test";

import {
  campaignIds,
  initialState,
  probe,
  runWatchdog,
  updateIncidentState,
} from "../src/logic.mjs";
import worker, { dispatchScheduledChecks, WatchdogCoordinator } from "../src/index.mjs";

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
    telegram: { ok: true, status: 200, reasons: [], error: null, route: "relay" },
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

test("three consecutive failures open one incident and the first recovery check keeps it open", () => {
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
  assert.ok(state.incident);
  assert.equal(state.incident.recoveryStreak, 1);
  assert.equal(state.incident.recoveryStartedAt, 180_000);
  assert.equal(state.pendingAlerts.length, 1);
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

test("Telegram-only incident suspends ads without rebooting either server", async () => {
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
      const method = JSON.parse(options.body).method;
      return method === "get"
        ? response(200, { result: { Campaigns: [
          { Id: 101, State: "ON", Status: "ACCEPTED" },
          { Id: 202, State: "ON", Status: "ACCEPTED" },
        ] } })
        : response(200, { result: { SuspendResults: [{ Id: 101 }, { Id: 202 }] } });
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
    YANDEX_CAMPAIGN_IDS: "101,202",
  };
  const storage = new MemoryStorage();

  await runWatchdog(env, storage, { fetchImpl, now: 0 });
  assert.equal(calls.filter((call) => call.url.includes("api.direct.yandex.com")).length, 0);
  await runWatchdog(env, storage, { fetchImpl, now: 30_000 });
  assert.equal(calls.filter((call) => call.url.includes("api.direct.yandex.com")).length, 0);
  await runWatchdog(env, storage, { fetchImpl, now: 60_000 });
  assert.equal(calls.filter((call) => call.url.includes("api.timeweb.cloud")).length, 0);
  assert.equal(calls.filter((call) => call.url.includes("api.direct.yandex.com")).length, 2);
  const yandexCall = calls.find((call) => call.url.includes("api.direct.yandex.com") && JSON.parse(call.options.body).method === "suspend");
  assert.deepEqual(JSON.parse(yandexCall.options.body).params.SelectionCriteria.Ids, [101, 202]);
  assert.equal(JSON.parse(yandexCall.options.body).method, "suspend");
  const alertTexts = calls
    .filter((call) => call.url.includes("api.telegram.org"))
    .map((call) => JSON.parse(call.options.body).text);
  assert.equal(alertTexts.length, 2);
  assert.ok(alertTexts.some((text) => text.includes("Бот не работает")));
  assert.ok(alertTexts.some((text) => text.includes("Реклама в Яндекс.Директе остановлена")));
});

test("Telegram probe rejects a ready response on the obsolete proxy route", async () => {
  const relay = await probe(
    "https://example.test/telegram/ready",
    async () => response(200, { status: "ready", telegram_route: "relay" }),
    10_000,
    "relay",
  );
  const proxy = await probe(
    "https://example.test/telegram/ready",
    async () => response(200, { status: "ready", telegram_route: "proxy" }),
    10_000,
    "relay",
  );

  assert.equal(relay.ok, true);
  assert.equal(proxy.ok, false);
  assert.equal(proxy.error, "unexpected_route");
});

test("failed ad suspension keeps retrying without rebooting a healthy platform", async () => {
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
  assert.equal(calls.filter((url) => url.includes("api.timeweb.cloud")).length, 0);
  assert.equal(calls.filter((url) => url.includes("api.direct.yandex.com")).length, 4);
});

test("five continuous healthy minutes resume both auto-paused campaigns but not a pre-paused campaign", async () => {
  let healthy = false;
  const telegramBodies = [];
  const yandexBodies = [];
  const campaignStates = new Map([[101, "ON"], [202, "ON"], [303, "SUSPENDED"]]);
  const fetchImpl = async (url, options = {}) => {
    if (String(url).includes("api.telegram.org")) {
      telegramBodies.push(JSON.parse(options.body));
      return response(200, { ok: true });
    }
    if (String(url).includes("api.timeweb.cloud")) return response(200, {});
    if (String(url).includes("api.direct.yandex.com")) {
      const body = JSON.parse(options.body);
      yandexBodies.push(body);
      if (body.method === "get") return response(200, { result: { Campaigns: [...campaignStates].map(([Id, State]) => ({ Id, State, Status: "ACCEPTED" })) } });
      if (body.method === "suspend") {
        for (const id of body.params.SelectionCriteria.Ids) campaignStates.set(id, "SUSPENDED");
        return response(200, { result: { SuspendResults: body.params.SelectionCriteria.Ids.map((Id) => ({ Id })) } });
      }
      if (body.method === "resume") {
        for (const id of body.params.SelectionCriteria.Ids) campaignStates.set(id, "ON");
        return response(200, { result: { ResumeResults: body.params.SelectionCriteria.Ids.map((Id) => ({ Id })) } });
      }
      throw new Error(`Unexpected Direct method: ${body.method}`);
    }
    return healthy
      ? response(200, { status: "ready", telegram_route: "relay" })
      : response(503, { status: "unavailable" });
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
    YANDEX_CAMPAIGN_IDS: "101,202,303",
    RECOVERY_STABLE_SECONDS: "300",
  };
  const storage = new MemoryStorage();
  await runWatchdog(env, storage, { fetchImpl, now: 1_000 });
  await runWatchdog(env, storage, { fetchImpl, now: 3_000 });
  healthy = true;
  for (const now of [33_000, 63_000, 93_000, 123_000, 153_000, 183_000, 213_000, 243_000, 273_000, 303_000]) {
    await runWatchdog(env, storage, { fetchImpl, now });
  }
  assert.deepEqual(yandexBodies.map((body) => body.method), ["get", "suspend"]);
  assert.ok(storage.value.incident);
  await runWatchdog(env, storage, { fetchImpl, now: 333_000 });
  assert.deepEqual(yandexBodies.map((body) => body.method), ["get", "suspend", "get", "resume"]);
  assert.deepEqual(yandexBodies.at(-1).params.SelectionCriteria.Ids, [101, 202]);
  assert.match(telegramBodies.at(-1).text, /стабильно работает 5 мин/);
  assert.equal(storage.value.incident, null);
});

test("partial ad suspension retains every auto-paused campaign across retry and recovery", async () => {
  let healthy = false;
  let suspendAttempt = 0;
  const methods = [];
  const campaignStates = new Map([[101, "ON"], [202, "ON"]]);
  const fetchImpl = async (url, options = {}) => {
    const value = String(url);
    if (value.includes("api.telegram.org")) return response(200, { ok: true });
    if (value.includes("api.direct.yandex.com")) {
      const body = JSON.parse(options.body);
      methods.push(body.method);
      if (body.method === "get") return response(200, { result: { Campaigns: [...campaignStates].map(([Id, State]) => ({ Id, State, Status: "ACCEPTED" })) } });
      if (body.method === "suspend") {
        suspendAttempt += 1;
        if (suspendAttempt === 1) {
          campaignStates.set(101, "SUSPENDED");
          return response(200, { result: { SuspendResults: [{ Id: 101 }, { Id: 202, Errors: [{ Code: 53 }] }] } });
        }
        campaignStates.set(202, "SUSPENDED");
        return response(200, { result: { SuspendResults: [{ Id: 202 }] } });
      }
      if (body.method === "resume") {
        for (const id of body.params.SelectionCriteria.Ids) campaignStates.set(id, "ON");
        return response(200, { result: { ResumeResults: body.params.SelectionCriteria.Ids.map((Id) => ({ Id })) } });
      }
    }
    return healthy
      ? response(200, { status: "ready", telegram_route: "relay" })
      : response(503, { status: "unavailable" });
  };
  const env = {
    PLATFORM_READY_URL: "https://api.example/ready",
    TELEGRAM_READY_URL: "https://api.example/telegram/ready",
    FAILURES_BEFORE_INCIDENT: "1",
    ADS_PAUSE_AFTER_SECONDS: "1",
    ACTION_RETRY_SECONDS: "1",
    RECOVERY_STABLE_SECONDS: "1",
    ACTIONS_ENABLED: "true",
    TELEGRAM_BOT_TOKEN: "telegram-secret",
    TELEGRAM_ALERT_CHAT_ID: "42",
    YANDEX_DIRECT_TOKEN: "direct-secret",
    YANDEX_CAMPAIGN_IDS: "101,202",
  };
  const storage = new MemoryStorage();
  await runWatchdog(env, storage, { fetchImpl, now: 1_000 });
  await runWatchdog(env, storage, { fetchImpl, now: 2_000 });
  assert.deepEqual(storage.value.incident.adsPause.campaignIds, [101, 202]);
  await runWatchdog(env, storage, { fetchImpl, now: 3_000 });
  assert.deepEqual(storage.value.incident.adsPause.campaignIds, [101, 202]);
  healthy = true;
  await runWatchdog(env, storage, { fetchImpl, now: 4_000 });
  assert.ok(storage.value.incident);
  await runWatchdog(env, storage, { fetchImpl, now: 5_000 });
  assert.deepEqual(methods, ["get", "suspend", "get", "suspend", "get", "resume"]);
  assert.equal(storage.value.incident, null);
});

test("a lost suspend response retains ownership and the campaign is resumed after recovery", async () => {
  let healthy = false;
  let campaignState = "ON";
  let suspendAttempt = 0;
  const resumeSelections = [];
  const fetchImpl = async (url, options = {}) => {
    const value = String(url);
    if (value.includes("api.telegram.org")) return response(200, { ok: true });
    if (value.includes("api.direct.yandex.com")) {
      const body = JSON.parse(options.body);
      if (body.method === "get") return response(200, { result: { Campaigns: [{ Id: 101, State: campaignState, Status: "ACCEPTED" }] } });
      if (body.method === "suspend") {
        suspendAttempt += 1;
        campaignState = "SUSPENDED";
        throw new Error("connection_lost_after_apply");
      }
      if (body.method === "resume") {
        resumeSelections.push(body.params.SelectionCriteria.Ids);
        campaignState = "ON";
        return response(200, { result: { ResumeResults: [{ Id: 101 }] } });
      }
    }
    return healthy
      ? response(200, { status: "ready", telegram_route: "relay" })
      : response(503, { status: "unavailable" });
  };
  const env = {
    PLATFORM_READY_URL: "https://api.example/ready",
    TELEGRAM_READY_URL: "https://api.example/telegram/ready",
    FAILURES_BEFORE_INCIDENT: "1",
    ADS_PAUSE_AFTER_SECONDS: "1",
    ACTION_RETRY_SECONDS: "1",
    RECOVERY_STABLE_SECONDS: "1",
    ACTIONS_ENABLED: "true",
    TELEGRAM_BOT_TOKEN: "telegram-secret",
    TELEGRAM_ALERT_CHAT_ID: "42",
    YANDEX_DIRECT_TOKEN: "direct-secret",
    YANDEX_CAMPAIGN_IDS: "101",
  };
  const storage = new MemoryStorage();
  await runWatchdog(env, storage, { fetchImpl, now: 1_000 });
  await runWatchdog(env, storage, { fetchImpl, now: 2_000 });
  assert.equal(storage.value.incident.adsPause.status, "failed");
  assert.deepEqual(storage.value.incident.adsPause.campaignIds, [101]);
  await runWatchdog(env, storage, { fetchImpl, now: 3_000 });
  assert.equal(suspendAttempt, 1);
  assert.equal(storage.value.incident.adsPause.status, "succeeded");
  healthy = true;
  await runWatchdog(env, storage, { fetchImpl, now: 4_000 });
  await runWatchdog(env, storage, { fetchImpl, now: 5_000 });
  assert.deepEqual(resumeSelections, [[101]]);
  assert.equal(storage.value.incident, null);
});

test("partial ad resume keeps the incident open and retries only what remains suspended", async () => {
  let healthy = false;
  let resumeAttempt = 0;
  const resumeSelections = [];
  const campaignStates = new Map([[101, "ON"], [202, "ON"]]);
  const fetchImpl = async (url, options = {}) => {
    const value = String(url);
    if (value.includes("api.telegram.org")) return response(200, { ok: true });
    if (value.includes("api.direct.yandex.com")) {
      const body = JSON.parse(options.body);
      if (body.method === "get") return response(200, { result: { Campaigns: [...campaignStates].map(([Id, State]) => ({ Id, State, Status: "ACCEPTED" })) } });
      if (body.method === "suspend") {
        for (const id of body.params.SelectionCriteria.Ids) campaignStates.set(id, "SUSPENDED");
        return response(200, { result: { SuspendResults: body.params.SelectionCriteria.Ids.map((Id) => ({ Id })) } });
      }
      if (body.method === "resume") {
        resumeAttempt += 1;
        resumeSelections.push(body.params.SelectionCriteria.Ids);
        if (resumeAttempt === 1) {
          campaignStates.set(101, "ON");
          return response(200, { result: { ResumeResults: [{ Id: 101 }, { Id: 202, Errors: [{ Code: 54 }] }] } });
        }
        campaignStates.set(202, "ON");
        return response(200, { result: { ResumeResults: [{ Id: 202 }] } });
      }
    }
    return healthy
      ? response(200, { status: "ready", telegram_route: "relay" })
      : response(503, { status: "unavailable" });
  };
  const env = {
    PLATFORM_READY_URL: "https://api.example/ready",
    TELEGRAM_READY_URL: "https://api.example/telegram/ready",
    FAILURES_BEFORE_INCIDENT: "1",
    ADS_PAUSE_AFTER_SECONDS: "1",
    ACTION_RETRY_SECONDS: "1",
    RECOVERY_STABLE_SECONDS: "1",
    ACTIONS_ENABLED: "true",
    TELEGRAM_BOT_TOKEN: "telegram-secret",
    TELEGRAM_ALERT_CHAT_ID: "42",
    YANDEX_DIRECT_TOKEN: "direct-secret",
    YANDEX_CAMPAIGN_IDS: "101,202",
  };
  const storage = new MemoryStorage();
  await runWatchdog(env, storage, { fetchImpl, now: 1_000 });
  await runWatchdog(env, storage, { fetchImpl, now: 2_000 });
  healthy = true;
  await runWatchdog(env, storage, { fetchImpl, now: 3_000 });
  assert.ok(storage.value.incident);
  await runWatchdog(env, storage, { fetchImpl, now: 4_000 });
  assert.ok(storage.value.incident);
  assert.equal(storage.value.incident.resumeAds.status, "failed");
  assert.deepEqual(storage.value.incident.resumeAds.campaignIds, [101]);
  await runWatchdog(env, storage, { fetchImpl, now: 5_000 });
  assert.deepEqual(resumeSelections, [[101, 202], [202]]);
  assert.equal(storage.value.incident, null);
});

test("a recovery failure resets the continuous healthy window", async () => {
  const storage = new MemoryStorage();
  const env = {
    FAILURES_BEFORE_INCIDENT: "1",
    RECOVERY_STABLE_SECONDS: "300",
  };
  await runWatchdog(env, storage, { checks: {
    platform: { ok: true, status: 200, reasons: [], error: null },
    telegram: { ok: false, status: 503, reasons: ["polling_stale"], error: null, route: "relay" },
  }, skipActions: true, now: 0 });
  for (const now of [30_000, 60_000, 90_000, 120_000, 150_000, 180_000, 210_000, 240_000, 270_000]) {
    await runWatchdog(env, storage, { checks: healthyChecks(), skipActions: true, now });
  }
  assert.equal(storage.value.incident.recoveryStreak, 9);
  await runWatchdog(env, storage, { checks: {
    platform: { ok: true, status: 200, reasons: [], error: null },
    telegram: { ok: false, status: 503, reasons: ["polling_stale"], error: null, route: "relay" },
  }, skipActions: true, now: 300_000 });
  assert.equal(storage.value.incident.recoveryStreak, 0);
  assert.equal(storage.value.incident.recoveryStartedAt, null);
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

test("daily report is generated, delivered as native rich tables after 06:00 Moscow, and never duplicated", async () => {
  const calls = [];
  const fetchImpl = async (url, options = {}) => {
    const value = String(url);
    calls.push({ url: value, body: options.body ? JSON.parse(options.body) : null });
    if (value.includes("api.telegram.org")) return response(200, { ok: true });
    if (value.includes("/daily-report/generate")) return response(200, { status: "pending" });
    if (value.includes("/daily-report/delivered")) return response(200, { status: "sent" });
    if (value.includes("/daily-report?")) return response(200, {
      messages: ["dry one", "dry two"],
      payload: {
        telegram_rich_messages: [
          { rich_message: { blocks: [{ type: "table", cells: [] }] }, fallback_text: "fallback" },
        ],
        demo_ai_message: "demo ai",
      },
    });
    return response(200, { status: "ready", telegram_route: "relay" });
  };
  const env = {
    PLATFORM_READY_URL: "https://api.example/ready",
    TELEGRAM_READY_URL: "https://api.example/telegram/ready",
    MARKETING_REPORT_URL: "https://api.example/daily-report",
    MARKETING_REPORT_TOKEN: "report-secret",
    TELEGRAM_BOT_TOKEN: "telegram-secret",
    TELEGRAM_ALERT_CHAT_ID: "42",
    SEND_REPORT_AI_DEMO_ONCE: "true",
  };
  const storage = new MemoryStorage();
  const atSixMoscow = Date.UTC(2026, 8, 8, 3, 0, 0);
  await runWatchdog(env, storage, { fetchImpl, now: atSixMoscow });
  await runWatchdog(env, storage, { fetchImpl, now: atSixMoscow + 60_000 });

  assert.equal(calls.filter((call) => call.url.includes("/generate?")).length, 1);
  assert.equal(calls.filter((call) => call.url.includes("/delivered?")).length, 1);
  const telegram = calls.filter((call) => call.url.includes("api.telegram.org"));
  assert.deepEqual(telegram.map((call) => call.url.split("/").at(-1)), ["sendRichMessage", "sendMessage"]);
  assert.equal(telegram[0].body.rich_message.blocks[0].type, "table");
  assert.equal(telegram[1].body.text, "demo ai");
  assert.equal(storage.value.report.sentDate, "2026-09-07");
  assert.equal(storage.value.report.demoSent, true);
  assert.equal(storage.value.report.richPreviewSent, true);
});

test("daily report snapshot waits for 03:00 Moscow and delivery waits for 06:00", async () => {
  const calls = [];
  const fetchImpl = async (url) => {
    const value = String(url);
    calls.push(value);
    if (value.includes("/daily-report/generate")) return response(200, { status: "pending" });
    if (value.includes("/daily-report/delivered")) return response(200, { status: "sent" });
    if (value.includes("/daily-report?")) return response(200, { messages: ["report"], payload: {} });
    if (value.includes("api.telegram.org")) return response(200, { ok: true });
    return response(200, { status: "ready", telegram_route: "relay" });
  };
  const env = {
    PLATFORM_READY_URL: "https://api.example/ready",
    TELEGRAM_READY_URL: "https://api.example/telegram/ready",
    MARKETING_REPORT_URL: "https://api.example/daily-report",
    MARKETING_REPORT_TOKEN: "report-secret",
    TELEGRAM_BOT_TOKEN: "telegram-secret",
    TELEGRAM_ALERT_CHAT_ID: "42",
  };
  const storage = new MemoryStorage();

  await runWatchdog(env, storage, { fetchImpl, now: Date.UTC(2026, 8, 7, 23, 59, 0) });
  assert.equal(calls.filter((url) => url.includes("/daily-report/")).length, 0);

  await runWatchdog(env, storage, { fetchImpl, now: Date.UTC(2026, 8, 8, 0, 0, 0) });
  assert.equal(calls.filter((url) => url.includes("/generate?")).length, 1);
  assert.equal(calls.filter((url) => url.includes("/delivered?")).length, 0);
  assert.equal(calls.filter((url) => url.includes("api.telegram.org")).length, 0);

  await runWatchdog(env, storage, { fetchImpl, now: Date.UTC(2026, 8, 8, 3, 0, 0) });
  assert.equal(calls.filter((url) => url.includes("/generate?")).length, 1);
  assert.equal(calls.filter((url) => url.includes("/delivered?")).length, 1);
  assert.equal(calls.filter((url) => url.includes("api.telegram.org")).length, 1);
  assert.equal(storage.value.report.generatedDate, "2026-09-07");
  assert.equal(storage.value.report.sentDate, "2026-09-07");
});

test("rich report falls back to readable cards when Telegram rejects native tables", async () => {
  const telegramCalls = [];
  const fetchImpl = async (url, options = {}) => {
    const value = String(url);
    if (value.endsWith("/sendRichMessage")) {
      telegramCalls.push(JSON.parse(options.body));
      return response(400, { ok: false });
    }
    if (value.endsWith("/sendMessage")) {
      telegramCalls.push(JSON.parse(options.body));
      return response(200, { ok: true });
    }
    if (value.includes("/daily-report/generate")) return response(200, { status: "pending" });
    if (value.includes("/daily-report/delivered")) return response(200, { status: "sent" });
    if (value.includes("/daily-report?")) return response(200, {
      messages: [],
      payload: {
        telegram_rich_messages: [
          { rich_message: { blocks: [{ type: "table", cells: [] }] }, fallback_text: "Readable fallback" },
        ],
      },
    });
    return response(200, { status: "ready", telegram_route: "relay" });
  };
  const env = {
    PLATFORM_READY_URL: "https://api.example/ready",
    TELEGRAM_READY_URL: "https://api.example/telegram/ready",
    MARKETING_REPORT_URL: "https://api.example/daily-report",
    MARKETING_REPORT_TOKEN: "report-secret",
    TELEGRAM_BOT_TOKEN: "telegram-secret",
    TELEGRAM_ALERT_CHAT_ID: "42",
    SEND_RICH_REPORT_PREVIEW_ONCE: "true",
  };
  const storage = new MemoryStorage();
  await runWatchdog(env, storage, { fetchImpl, now: Date.UTC(2026, 8, 8, 3, 0, 0) });
  assert.equal(telegramCalls.length, 2);
  assert.equal(telegramCalls[1].text, "Readable fallback");
});

test("platform incident delays reboot past the deploy window and reboots only the Russian server", async () => {
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
  const storage = new MemoryStorage();
  await runWatchdog(env, storage, { fetchImpl, now: 1_000 });
  assert.equal(calls.filter((url) => url.endsWith("/servers/ru-id/reboot")).length, 0);
  await runWatchdog(env, storage, { fetchImpl, now: 241_000 });

  assert.equal(calls.filter((url) => url.endsWith("/servers/ru-id/reboot")).length, 1);
  assert.equal(calls.filter((url) => url.endsWith("/servers/eu-id/reboot")).length, 0);
});

test("reboot delay measures the current continuous platform failure, not an older Telegram incident", async () => {
  const calls = [];
  const fetchImpl = async (url) => {
    calls.push(String(url));
    if (String(url).includes("api.telegram.org")) return response(200, { ok: true });
    if (String(url).includes("api.timeweb.cloud")) return response(200, {});
    throw new Error(`Unexpected URL: ${url}`);
  };
  const env = {
    FAILURES_BEFORE_INCIDENT: "1",
    ACTIONS_ENABLED: "true",
    RU_REBOOT_AFTER_SECONDS: "240",
    TIMEWEB_API_TOKEN: "timeweb-secret",
    TIMEWEB_RU_SERVER_ID: "ru-id",
    TELEGRAM_BOT_TOKEN: "telegram-secret",
    TELEGRAM_ALERT_CHAT_ID: "42",
  };
  const telegramOnly = {
    platform: { ok: true, status: 200, reasons: [], error: null },
    telegram: { ok: false, status: 503, reasons: ["polling_stale"], error: null, route: "relay" },
  };
  const bothFailed = {
    platform: { ok: false, status: 503, reasons: [], error: "network_error" },
    telegram: { ok: false, status: 503, reasons: ["polling_stale"], error: null, route: "relay" },
  };
  const storage = new MemoryStorage();
  await runWatchdog(env, storage, { fetchImpl, checks: telegramOnly, now: 0 });
  await runWatchdog(env, storage, { fetchImpl, checks: bothFailed, now: 180_000 });
  await runWatchdog(env, storage, { fetchImpl, checks: bothFailed, now: 241_000 });
  assert.equal(calls.filter((url) => url.endsWith("/servers/ru-id/reboot")).length, 0);
  await runWatchdog(env, storage, { fetchImpl, checks: bothFailed, now: 420_000 });
  assert.equal(calls.filter((url) => url.endsWith("/servers/ru-id/reboot")).length, 1);
});

test("platform recovery cancels a pending reboot while a Telegram incident remains open", async () => {
  const calls = [];
  const fetchImpl = async (url) => {
    calls.push(String(url));
    if (String(url).includes("api.telegram.org")) return response(200, { ok: true });
    if (String(url).includes("api.timeweb.cloud")) return response(200, {});
    throw new Error(`Unexpected URL: ${url}`);
  };
  const env = {
    FAILURES_BEFORE_INCIDENT: "1",
    ACTIONS_ENABLED: "true",
    RU_REBOOT_AFTER_SECONDS: "240",
    TIMEWEB_API_TOKEN: "timeweb-secret",
    TIMEWEB_RU_SERVER_ID: "ru-id",
    TELEGRAM_BOT_TOKEN: "telegram-secret",
    TELEGRAM_ALERT_CHAT_ID: "42",
  };
  const bothFailed = {
    platform: { ok: false, status: 503, reasons: [], error: "network_error" },
    telegram: { ok: false, status: 503, reasons: ["polling_stale"], error: null, route: "relay" },
  };
  const telegramOnly = {
    platform: { ok: true, status: 200, reasons: [], error: null },
    telegram: { ok: false, status: 503, reasons: ["polling_stale"], error: null, route: "relay" },
  };
  const storage = new MemoryStorage();
  await runWatchdog(env, storage, { fetchImpl, checks: bothFailed, now: 0 });
  await runWatchdog(env, storage, { fetchImpl, checks: telegramOnly, now: 240_000 });
  assert.equal(calls.filter((url) => url.endsWith("/servers/ru-id/reboot")).length, 0);
  assert.equal(storage.value.incident.platformFailureStartedAt, null);
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
      RU_REBOOT_AFTER_SECONDS: "1",
    },
    storage,
    { fetchImpl, now: 1_000 },
  );
  await runWatchdog(
    {
      PLATFORM_READY_URL: "https://api.example/ready",
      TELEGRAM_READY_URL: "https://api.example/telegram/ready",
      FAILURES_BEFORE_INCIDENT: "1",
      TELEGRAM_BOT_TOKEN: "telegram-secret",
      TELEGRAM_ALERT_CHAT_ID: "42",
      ACTIONS_ENABLED: "false",
      RU_REBOOT_AFTER_SECONDS: "1",
    },
    storage,
    { fetchImpl, now: 2_000 },
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
  const env = {
    PLATFORM_READY_URL: "https://api.example/ready",
    TELEGRAM_READY_URL: "https://api.example/telegram/ready",
    FAILURES_BEFORE_INCIDENT: "1",
    ADS_PAUSE_AFTER_SECONDS: "1",
    ACTIONS_ENABLED: "true",
    TELEGRAM_BOT_TOKEN: "telegram-secret",
    TELEGRAM_ALERT_CHAT_ID: "42",
    YANDEX_DIRECT_TOKEN: "direct-secret",
    YANDEX_CAMPAIGN_IDS: "101, typo",
  };
  await runWatchdog(env, storage, { fetchImpl, now: 1_000 });
  await runWatchdog(env, storage, { fetchImpl, now: 3_000 });
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
  const env = {
    PLATFORM_READY_URL: "https://api.example/ready",
    TELEGRAM_READY_URL: "https://api.example/telegram/ready",
    FAILURES_BEFORE_INCIDENT: "1",
    ACTIONS_ENABLED: "true",
    TELEGRAM_BOT_TOKEN: "telegram-secret",
    TELEGRAM_ALERT_CHAT_ID: "42",
    RU_REBOOT_AFTER_SECONDS: "1",
  };
  await runWatchdog(env, storage, { fetchImpl, now: 1_000 });
  await runWatchdog(env, storage, { fetchImpl, now: 2_000 });
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
  const env = {
    PLATFORM_READY_URL: "https://api.example/ready",
    TELEGRAM_READY_URL: "https://api.example/telegram/ready",
    FAILURES_BEFORE_INCIDENT: "1",
    ACTIONS_ENABLED: "true",
    TIMEWEB_API_TOKEN: "timeweb-secret",
    TIMEWEB_RU_SERVER_ID: "ru-id",
    RU_REBOOT_AFTER_SECONDS: "1",
  };
  await runWatchdog(env, storage, { fetchImpl, now: 1_000 });
  await runWatchdog(env, storage, { fetchImpl, now: 2_000 });
  assert.equal(calls.filter((url) => url.includes("api.timeweb.cloud")).length, 0);
  assert.match(storage.value.incident.missingConfigurationAlerts.ruReboot, /канал аварийных уведомлений/);
});

test("scheduled dispatcher runs immediately and again after thirty seconds", async () => {
  const calls = [];
  const stub = {
    fetch(url, options) {
      calls.push(["fetch", url, options.method]);
      return Promise.resolve(new Response("ok"));
    },
  };
  await dispatchScheduledChecks(stub, async (milliseconds) => {
    calls.push(["delay", milliseconds]);
  });
  assert.deepEqual(calls, [
    ["fetch", "https://watchdog.internal/run", "POST"],
    ["delay", 30_000],
    ["fetch", "https://watchdog.internal/run", "POST"],
  ]);
});

test("scheduled handler delegates the two-check cadence to the production object", async () => {
  let pending;
  let count = 0;
  const env = {
    WATCHDOG: {
      idFromName(name) { assert.equal(name, "production"); return "object-id"; },
      get(id) {
        assert.equal(id, "object-id");
        return { fetch() { count += 1; return Promise.resolve(new Response("ok")); } };
      },
    },
  };
  const originalTimeout = globalThis.setTimeout;
  globalThis.setTimeout = (callback, milliseconds) => {
    assert.equal(milliseconds, 30_000);
    callback();
    return 1;
  };
  try {
    await worker.scheduled({}, env, { waitUntil(value) { pending = value; } });
    await pending;
    assert.equal(count, 2);
  } finally {
    globalThis.setTimeout = originalTimeout;
  }
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
    for (let index = 0; index < 11; index += 1) {
      await coordinator.fetch(new Request("https://watchdog.internal/run", {
        method: "POST",
        headers: { "X-Watchdog-Drill": "recover" },
      }));
    }
    assert.equal(calls.filter((call) => call.url.includes("api.timeweb.cloud")).length, 0);
    assert.equal(calls.filter((call) => call.url.includes("api.direct.yandex.com")).length, 0);
    const messages = calls
      .filter((call) => call.url.includes("api.telegram.org"))
      .map((call) => JSON.parse(call.options.body).text);
    assert.equal(messages.length, 2);
    assert.match(messages[0], /Бот не работает/);
    assert.match(messages[1], /стабильно работает 5 мин/);
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
    return response(200, { status: "ready", telegram_route: "relay" });
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
