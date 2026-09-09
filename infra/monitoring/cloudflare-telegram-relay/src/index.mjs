const METHOD_PATTERN = /^[A-Za-z][A-Za-z0-9_]{0,63}$/;
const BOT_TOKEN_PATTERN = /^\d+:[A-Za-z0-9_-]{20,}$/;

function json(status, body) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8" },
  });
}

export async function handleRequest(request, env, fetchImpl = fetch) {
  const url = new URL(request.url);
  if (request.method === "GET" && url.pathname === "/health") {
    return json(200, { status: "ready" });
  }
  if (request.method !== "POST" || !url.pathname.startsWith("/telegram/")) {
    return json(404, { error: "not_found" });
  }
  const relayToken = request.headers.get("X-Edabalans-Relay-Token") || "";
  if (!env.RELAY_TOKEN || relayToken !== env.RELAY_TOKEN) {
    return json(401, { error: "unauthorized" });
  }
  const botToken = request.headers.get("X-Telegram-Bot-Token") || "";
  const method = url.pathname.slice("/telegram/".length);
  if (!BOT_TOKEN_PATTERN.test(botToken) || !METHOD_PATTERN.test(method)) {
    return json(400, { error: "invalid_request" });
  }

  const headers = new Headers();
  for (const name of ["Accept", "Content-Type"]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }

  return fetchImpl(`https://api.telegram.org/bot${botToken}/${method}`, {
    method: "POST",
    headers,
    body: request.body,
    redirect: "manual",
  });
}

export default {
  fetch(request, env) {
    return handleRequest(request, env);
  },
};
