import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { initialState, runWatchdog, updateIncidentState } from "../src/logic.mjs";

const { vars } = JSON.parse(await readFile(new URL("../wrangler.jsonc", import.meta.url), "utf8"));
const healthy = {
  platform: { ok: true, status: 200, reasons: [], error: null },
  telegram: { ok: true, status: 200, reasons: [], error: null, route: "relay" },
};
const failing = { ...healthy, telegram: { ...healthy.telegram, ok: false, status: 503 } };

function incidentStorage() {
  let state = updateIncidentState(initialState(), failing, 0, 1);
  state.incident.adsPause.status = "succeeded";
  state.incident.adsPause.campaignIds = [101];
  return {
    async get() { return structuredClone(state); },
    async put(_key, value) { state = structuredClone(value); },
  };
}

function recoveryHarness() {
  const methods = [];
  const storage = incidentStorage();
  const env = {
    ...vars,
    ACTIONS_ENABLED: "true",
    TELEGRAM_BOT_TOKEN: "test-token",
    TELEGRAM_ALERT_CHAT_ID: "test-chat",
    YANDEX_DIRECT_TOKEN: "test-token",
  };
  const fetchImpl = async (url, options) => {
    let body = { ok: true };
    if (String(url).includes("api.direct.yandex.com")) {
      const request = JSON.parse(options.body);
      methods.push(request.method);
      assert.deepEqual(request.params.SelectionCriteria.Ids, [101]);
      body = request.method === "get"
        ? { result: { Campaigns: [{ Id: 101, State: "SUSPENDED" }] } }
        : { result: { ResumeResults: [{ Id: 101 }] } };
    } else {
      assert.ok(String(url).includes("api.telegram.org"));
    }
    return new Response(JSON.stringify(body), { status: 200 });
  };
  const run = (now, checks = healthy) => runWatchdog(env, storage, {
    checks, now, fetchImpl, skipReport: true,
  });
  return { methods, storage, run };
}

test("production recovery waits two full minutes, then resumes only owned campaigns", async () => {
  const { run, storage, methods } = recoveryHarness();
  for (const now of [30_000, 60_000, 90_000, 120_000]) await run(now);
  assert.ok((await storage.get()).incident);
  assert.deepEqual(methods, []);
  await run(149_999);
  assert.deepEqual(methods, []);
  await run(150_000);
  assert.deepEqual(methods, ["get", "resume"]);
  assert.equal((await storage.get()).incident, null);
});

test("production recovery needs observations as well as elapsed time", async () => {
  const { run, storage, methods } = recoveryHarness();
  await run(30_000);
  await run(150_000);
  assert.ok((await storage.get()).incident);
  assert.deepEqual(methods, []);
  await run(180_000);
  assert.deepEqual(methods, []);
  await run(210_000);
  assert.deepEqual(methods, ["get", "resume"]);
});

test("a new failure restarts the production recovery window", async () => {
  const { run, storage, methods } = recoveryHarness();
  for (const now of [30_000, 60_000, 90_000, 120_000]) await run(now);
  // This incident already owns its suspended campaign; do not issue a new pause.
  await runWatchdog(vars, storage, { checks: failing, now: 150_000, skipActions: true, skipReport: true });
  for (const now of [180_000, 210_000, 240_000, 270_000]) await run(now);
  assert.deepEqual(methods, []);
  assert.ok((await storage.get()).incident);
  await run(300_000);
  assert.deepEqual(methods, ["get", "resume"]);
});
