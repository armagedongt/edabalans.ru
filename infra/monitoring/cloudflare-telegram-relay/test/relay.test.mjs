import assert from "node:assert/strict";
import test from "node:test";

import { handleRequest } from "../src/index.mjs";

test("health is public and contains no Telegram details", async () => {
  const response = await handleRequest(new Request("https://relay.test/health"), {});
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { status: "ready" });
});

test("relay rejects requests without its shared secret", async () => {
  const missing = await handleRequest(
    new Request("https://relay.test/telegram/getMe", { method: "POST" }),
    { RELAY_TOKEN: "expected" },
  );
  const wrong = await handleRequest(
    new Request("https://relay.test/telegram/getMe", {
      method: "POST",
      headers: { "X-Edabalans-Relay-Token": "not-the-expected-secret" },
    }),
    { RELAY_TOKEN: "expected" },
  );
  assert.equal(missing.status, 401);
  assert.equal(wrong.status, 401);
});

test("relay strips private headers and forwards the body to Telegram", async () => {
  const calls = [];
  const request = new Request("https://relay.test/telegram/getUpdates", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Edabalans-Relay-Token": "relay-secret",
      "X-Telegram-Bot-Token": "123456:abcdefghijklmnopqrstuvwxyz",
      "X-Untrusted-Forwarded-Header": "must-not-reach-telegram",
    },
    body: JSON.stringify({ timeout: 25 }),
  });
  const response = await handleRequest(request, { RELAY_TOKEN: "relay-secret" }, async (url, options) => {
    calls.push({ url, options, body: await new Response(options.body).text() });
    return new Response(JSON.stringify({ ok: true, result: [] }), {
      headers: { "Content-Type": "application/json" },
    });
  });

  assert.equal(response.status, 200);
  assert.equal(calls[0].url, "https://api.telegram.org/bot123456:abcdefghijklmnopqrstuvwxyz/getUpdates");
  assert.equal(calls[0].options.method, "POST");
  assert.equal(calls[0].options.headers.has("X-Edabalans-Relay-Token"), false);
  assert.equal(calls[0].options.headers.has("X-Telegram-Bot-Token"), false);
  assert.equal(calls[0].options.headers.has("X-Untrusted-Forwarded-Header"), false);
  assert.equal(calls[0].body, JSON.stringify({ timeout: 25 }));
});
