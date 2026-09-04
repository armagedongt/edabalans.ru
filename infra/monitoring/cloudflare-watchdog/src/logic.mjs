const DEFAULT_TIMEOUT_MS = 10_000;
const DEFAULT_FAILURES_BEFORE_INCIDENT = 3;
const DEFAULT_RU_REBOOT_DELAY_SECONDS = 300;
const DEFAULT_ADS_PAUSE_DELAY_SECONDS = 600;
const DEFAULT_ACTION_RETRY_SECONDS = 120;
const DEFAULT_MAX_ACTION_ATTEMPTS = 3;

export function initialState() {
  return {
    version: 1,
    failureStreak: 0,
    candidateFailureKey: null,
    firstFailureAt: null,
    incident: null,
    pendingAlerts: [],
  };
}

export function parsePositiveInteger(value, fallback) {
  const parsed = Number.parseInt(String(value ?? ""), 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

export function parseBoolean(value, fallback = false) {
  if (value == null || value === "") return fallback;
  return String(value).toLowerCase() === "true";
}

export function campaignIds(value) {
  const items = String(value ?? "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  const invalid = items.filter((item) => !/^\d+$/.test(item));
  if (invalid.length) {
    throw new Error(`некорректные ID кампаний: ${invalid.join(", ")}`);
  }
  return items.map((item) => Number(item));
}

export function normalizeState(value) {
  if (!value || value.version !== 1) return initialState();
  return {
    ...initialState(),
    ...value,
    pendingAlerts: Array.isArray(value.pendingAlerts) ? value.pendingAlerts.slice(-20) : [],
  };
}

export async function probe(url, fetchImpl, timeoutMs = DEFAULT_TIMEOUT_MS) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetchImpl(url, {
      headers: { Accept: "application/json", "User-Agent": "edabalans-watchdog/1" },
      redirect: "follow",
      signal: controller.signal,
    });
    let body = null;
    try {
      body = await response.json();
    } catch {
      body = null;
    }
    const declaredReady = body?.status === "ready";
    return {
      ok: response.ok && declaredReady,
      status: response.status,
      reasons: Array.isArray(body?.reasons) ? body.reasons.map(String).slice(0, 8) : [],
      route: typeof body?.telegram_route === "string" ? body.telegram_route : null,
      error: response.ok && !declaredReady ? "unexpected_response" : null,
    };
  } catch (error) {
    return {
      ok: false,
      status: null,
      reasons: [],
      route: null,
      error: error?.name === "AbortError" ? "timeout" : "network_error",
    };
  } finally {
    clearTimeout(timer);
  }
}

function actionState() {
  return {
    status: "pending",
    attempts: 0,
    attemptedAt: null,
    retryAt: null,
    lastError: null,
  };
}

function failedChecks(checks) {
  return Object.entries(checks)
    .filter(([, result]) => !result.ok)
    .map(([name]) => name);
}

function checkDetails(checks) {
  return Object.entries(checks)
    .filter(([, result]) => !result.ok)
    .map(([name, result]) => {
      const suffix = result.reasons.length
        ? result.reasons.join(", ")
        : result.error || `HTTP ${result.status ?? "?"}`;
      return `${name}: ${suffix}`;
    })
    .join("; ");
}

function queueAlert(state, text) {
  if (!text) return;
  state.pendingAlerts.push(text);
  state.pendingAlerts = state.pendingAlerts.slice(-20);
}

function incidentLabel(checks) {
  if (!checks.platform.ok) return "основной российский сервер/API";
  return "Telegram-бот или европейский Telegram-шлюз";
}

export function updateIncidentState(stateInput, checks, now, failuresBeforeIncident) {
  const state = normalizeState(stateInput);
  const failures = failedChecks(checks);

  if (failures.length === 0) {
    if (state.incident) {
      const durationMinutes = Math.max(1, Math.round((now - state.incident.startedAt) / 60_000));
      queueAlert(
        state,
        `✅ Бот снова работает. Авария закрыта, длительность около ${durationMinutes} мин. Рекламу автоматически не запускаю.`,
      );
    }
    state.failureStreak = 0;
    state.candidateFailureKey = null;
    state.firstFailureAt = null;
    state.incident = null;
    return state;
  }

  const failureKey = failures.slice().sort().join(",");
  if (!state.incident && state.candidateFailureKey !== failureKey) {
    state.failureStreak = 0;
    state.firstFailureAt = now;
    state.candidateFailureKey = failureKey;
  }
  state.failureStreak += 1;
  state.firstFailureAt ??= now;

  if (!state.incident && state.failureStreak >= failuresBeforeIncident) {
    state.incident = {
      id: String(state.firstFailureAt),
      startedAt: state.firstFailureAt,
      openedAt: now,
      lastFailures: failures,
      confirmedFailures: failures,
      boundaryCandidateKey: failureKey,
      boundaryStreak: state.failureStreak,
      ruReboot: actionState(),
      euReboot: actionState(),
      adsPause: actionState(),
      missingConfigurationAlerts: {},
    };
    queueAlert(
      state,
      `🚨 Бот не работает: ${incidentLabel(checks)}. Ошибка подтверждена ${state.failureStreak} проверками. ${checkDetails(checks)}`,
    );
  } else if (state.incident) {
    state.incident.lastFailures = failures;
    if (state.incident.boundaryCandidateKey === failureKey) {
      state.incident.boundaryStreak = (state.incident.boundaryStreak || 0) + 1;
    } else {
      state.incident.boundaryCandidateKey = failureKey;
      state.incident.boundaryStreak = 1;
    }
    if (state.incident.boundaryStreak >= failuresBeforeIncident) {
      state.incident.confirmedFailures = failures;
    }
  }

  return state;
}

function canAttempt(action, target, now) {
  if (target.status === "succeeded") return false;
  // A reboot has an ambiguous outcome if the provider accepts it but the response
  // is lost. Never send a second disruptive reboot in the same incident.
  if (action.kind === "reboot" && target.attempts > 0) return false;
  if (target.status === "in_progress" && target.retryAt && now < target.retryAt) return false;
  if (target.status === "failed" && target.retryAt && now < target.retryAt) return false;
  return true;
}

function actionPlan(state, checks, now, env) {
  if (!state.incident) return [];
  const ageSeconds = Math.max(0, (now - state.incident.startedAt) / 1000);
  const ruDelay = parsePositiveInteger(
    env.RU_REBOOT_AFTER_TELEGRAM_FAILURE_SECONDS,
    DEFAULT_RU_REBOOT_DELAY_SECONDS,
  );
  const adsDelay = parsePositiveInteger(env.ADS_PAUSE_AFTER_SECONDS, DEFAULT_ADS_PAUSE_DELAY_SECONDS);
  const actions = [];

  const confirmed = new Set(state.incident.confirmedFailures || state.incident.lastFailures || []);
  if (confirmed.has("platform")) {
    actions.push({ key: "ruReboot", kind: "reboot", server: "RU", serverId: env.TIMEWEB_RU_SERVER_ID });
  }
  if (!confirmed.has("platform") && confirmed.has("telegram")) {
    actions.push({ key: "euReboot", kind: "reboot", server: "EU", serverId: env.TIMEWEB_EU_SERVER_ID });
    if (ageSeconds >= ruDelay) {
      actions.push({ key: "ruReboot", kind: "reboot", server: "RU", serverId: env.TIMEWEB_RU_SERVER_ID });
    }
  }
  if (ageSeconds >= adsDelay) {
    actions.push({ key: "adsPause", kind: "pause_ads" });
  }
  return actions;
}

function configurationFor(action, env) {
  if (!parseBoolean(env.ACTIONS_ENABLED, false)) {
    return { ok: false, reason: "автоматические действия пока выключены" };
  }
  if (!env.TELEGRAM_BOT_TOKEN || !env.TELEGRAM_ALERT_CHAT_ID) {
    return { ok: false, reason: "не настроен канал аварийных уведомлений Telegram" };
  }
  if (action.kind === "reboot") {
    if (!env.TIMEWEB_API_TOKEN || !action.serverId) {
      return { ok: false, reason: `не настроен Timeweb API для ${action.server}` };
    }
    return { ok: true };
  }
  let ids;
  try {
    ids = campaignIds(env.YANDEX_CAMPAIGN_IDS);
  } catch (error) {
    return { ok: false, reason: String(error?.message || error) };
  }
  if (!env.YANDEX_DIRECT_TOKEN || ids.length === 0) {
    return { ok: false, reason: "не настроены токен и ID кампаний Яндекс.Директа" };
  }
  return { ok: true, ids };
}

async function rebootServer(action, env, fetchImpl) {
  const base = String(env.TIMEWEB_API_BASE_URL || "https://api.timeweb.cloud/api/v1").replace(/\/$/, "");
  const response = await fetchWithTimeout(`${base}/servers/${encodeURIComponent(action.serverId)}/reboot`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.TIMEWEB_API_TOKEN}`,
      "Content-Type": "application/json",
    },
  }, fetchImpl, parsePositiveInteger(env.ACTION_TIMEOUT_MS, DEFAULT_TIMEOUT_MS));
  if (!response.ok) throw new Error(`Timeweb HTTP ${response.status}`);
}

async function pauseAds(ids, env, fetchImpl) {
  const headers = {
    Authorization: `Bearer ${env.YANDEX_DIRECT_TOKEN}`,
    "Accept-Language": "ru",
    "Content-Type": "application/json; charset=utf-8",
  };
  if (env.YANDEX_DIRECT_CLIENT_LOGIN) headers["Client-Login"] = env.YANDEX_DIRECT_CLIENT_LOGIN;
  const response = await fetchWithTimeout("https://api.direct.yandex.com/json/v501/campaigns", {
    method: "POST",
    headers,
    body: JSON.stringify({ method: "suspend", params: { SelectionCriteria: { Ids: ids } } }),
  }, fetchImpl, parsePositiveInteger(env.ACTION_TIMEOUT_MS, DEFAULT_TIMEOUT_MS));
  if (!response.ok) throw new Error(`Яндекс.Директ HTTP ${response.status}`);
  const body = await response.json();
  if (body.error) throw new Error(`Яндекс.Директ API ${body.error.error_code ?? "error"}`);
  const errors = (body.result?.SuspendResults || []).flatMap((item) => item.Errors || []);
  if (errors.length) throw new Error(`Яндекс.Директ: ${errors[0].Code ?? "ошибка"}`);
}

async function sendTelegramAlert(text, env, fetchImpl) {
  if (!env.TELEGRAM_BOT_TOKEN || !env.TELEGRAM_ALERT_CHAT_ID) {
    throw new Error("Telegram alert route is not configured");
  }
  const response = await fetchWithTimeout(
    `https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        chat_id: env.TELEGRAM_ALERT_CHAT_ID,
        text,
        disable_web_page_preview: true,
      }),
    },
    fetchImpl,
    parsePositiveInteger(env.ACTION_TIMEOUT_MS, DEFAULT_TIMEOUT_MS),
  );
  if (!response.ok) throw new Error(`Telegram HTTP ${response.status}`);
  const body = await response.json();
  if (!body.ok) throw new Error("Telegram rejected the alert");
}

async function fetchWithTimeout(url, options, fetchImpl, timeoutMs) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetchImpl(url, { ...options, signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
}

async function persist(storage, state) {
  await storage.put("state", state);
}

async function markMissingConfiguration(state, action, reason, storage) {
  const incident = state.incident;
  if (!incident || incident.missingConfigurationAlerts[action.key] === reason) return;
  incident.missingConfigurationAlerts[action.key] = reason;
  queueAlert(state, `⚠️ Автовосстановление не выполнено: ${reason}.`);
  await persist(storage, state);
}

async function executeAction(state, action, env, fetchImpl, storage, now) {
  const incident = state.incident;
  if (!incident) return;
  const target = incident[action.key];
  const alertAfterAttempts = parsePositiveInteger(env.MAX_ACTION_ATTEMPTS, DEFAULT_MAX_ACTION_ATTEMPTS);
  if (!canAttempt(action, target, now)) return;

  const configuration = configurationFor(action, env);
  if (!configuration.ok) {
    await markMissingConfiguration(state, action, configuration.reason, storage);
    return;
  }

  delete incident.missingConfigurationAlerts[action.key];
  const retrySeconds = parsePositiveInteger(env.ACTION_RETRY_SECONDS, DEFAULT_ACTION_RETRY_SECONDS);
  target.status = "in_progress";
  target.attempts += 1;
  target.attemptedAt = now;
  target.retryAt = now + retrySeconds * 1000;
  target.lastError = null;
  await persist(storage, state);

  try {
    if (action.kind === "reboot") {
      await rebootServer(action, env, fetchImpl);
      queueAlert(state, `🔄 Отправлена команда перезагрузить ${action.server === "RU" ? "российский" : "европейский"} сервер.`);
    } else {
      await pauseAds(configuration.ids, env, fetchImpl);
      queueAlert(state, `⛔ Реклама в Яндекс.Директе остановлена: ${configuration.ids.length} камп.`);
    }
    target.status = "succeeded";
    target.retryAt = null;
  } catch (error) {
    target.status = "failed";
    target.lastError = String(error?.message || "unknown_error").slice(0, 160);
    if (action.kind === "reboot" || target.attempts === alertAfterAttempts) {
      queueAlert(state, `❌ Автоматическое действие не удалось после ${target.attempts} попыток: ${target.lastError}.`);
    }
  }
  await persist(storage, state);
}

async function flushAlerts(state, env, fetchImpl, storage) {
  while (state.pendingAlerts.length) {
    try {
      await sendTelegramAlert(state.pendingAlerts[0], env, fetchImpl);
    } catch (error) {
      console.error("Telegram alert delivery failed", String(error?.message || error));
      return;
    }
    state.pendingAlerts.shift();
    await persist(storage, state);
  }
}

export async function runWatchdog(env, storage, options = {}) {
  const fetchImpl = options.fetchImpl || fetch;
  const now = options.now ?? Date.now();
  let checks = options.checks;
  if (!checks) {
    const timeoutMs = parsePositiveInteger(env.CHECK_TIMEOUT_MS, DEFAULT_TIMEOUT_MS);
    const [platform, telegram] = await Promise.all([
      probe(env.PLATFORM_READY_URL, fetchImpl, timeoutMs),
      probe(env.TELEGRAM_READY_URL, fetchImpl, timeoutMs),
    ]);
    checks = { platform, telegram };
  }
  const { platform, telegram } = checks;
  const previous = normalizeState(await storage.get("state"));
  const failuresBeforeIncident = parsePositiveInteger(
    env.FAILURES_BEFORE_INCIDENT,
    DEFAULT_FAILURES_BEFORE_INCIDENT,
  );
  const state = updateIncidentState(previous, checks, now, failuresBeforeIncident);
  await persist(storage, state);

  if (state.incident && !options.skipActions) {
    for (const action of actionPlan(state, checks, now, env)) {
      await executeAction(state, action, env, fetchImpl, storage, now);
    }
  }
  await flushAlerts(state, env, fetchImpl, storage);

  return {
    ok: platform.ok && telegram.ok,
    checks,
    incident: state.incident?.id ?? null,
    failureStreak: state.failureStreak,
  };
}

export const testing = {
  actionPlan,
  configurationFor,
};
