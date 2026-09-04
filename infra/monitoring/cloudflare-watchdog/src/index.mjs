import { runWatchdog } from "./logic.mjs";

export class WatchdogCoordinator {
  constructor(ctx, env) {
    this.ctx = ctx;
    this.env = env;
    this.runQueue = Promise.resolve();
  }

  async fetch(request) {
    if (request.method !== "POST") return new Response("Method Not Allowed", { status: 405 });
    const drillState = request.headers.get("X-Watchdog-Drill");
    const options = drillState ? {
      checks: drillState === "recover" ? healthyDrillChecks() : failingDrillChecks(),
      skipActions: true,
    } : {};
    const runEnv = drillState ? { ...this.env, FAILURES_BEFORE_INCIDENT: "3" } : this.env;
    const currentRun = this.runQueue.then(() => runWatchdog(runEnv, this.ctx.storage, options));
    this.runQueue = currentRun.catch(() => undefined);
    try {
      const result = await currentRun;
      return Response.json(result, { status: result.ok ? 200 : 503 });
    } catch (error) {
      console.error("Watchdog run failed", String(error?.message || error));
      return Response.json({ ok: false, error: "watchdog_run_failed" }, { status: 500 });
    }
  }
}

export default {
  async scheduled(_controller, env, ctx) {
    const id = env.WATCHDOG.idFromName("production");
    const stub = env.WATCHDOG.get(id);
    ctx.waitUntil(stub.fetch("https://watchdog.internal/run", { method: "POST" }));
  },

  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/drill/fail" || url.pathname === "/drill/recover") {
      if (request.method !== "POST" || !env.DRILL_TOKEN || request.headers.get("Authorization") !== `Bearer ${env.DRILL_TOKEN}`) {
        return new Response("Not Found", { status: 404 });
      }
      const id = env.WATCHDOG.idFromName("drill");
      const stub = env.WATCHDOG.get(id);
      return stub.fetch("https://watchdog.internal/run", {
        method: "POST",
        headers: { "X-Watchdog-Drill": url.pathname.endsWith("recover") ? "recover" : "fail" },
      });
    }
    return Response.json({ status: "ok", service: "edabalans-watchdog" });
  },
};

function healthyDrillChecks() {
  return {
    platform: { ok: true, status: 200, reasons: [], route: null, error: null },
    telegram: { ok: true, status: 200, reasons: [], route: "drill", error: null },
  };
}

function failingDrillChecks() {
  return {
    platform: { ok: true, status: 200, reasons: [], route: null, error: null },
    telegram: { ok: false, status: 503, reasons: ["isolated_drill"], route: "drill", error: null },
  };
}
