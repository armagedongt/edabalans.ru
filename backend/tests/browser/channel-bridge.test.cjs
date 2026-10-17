const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const vm = require('node:vm');
const source = readFileSync(join(__dirname, '../../app/static/channel-bridge/bridge.js'), 'utf8');
const target = 'https://t.me/Fitness_Talks/260';

async function run({ inTelegram = true, verify = 'ok', navigationError = false, platform = 'tdesktop' } = {}) {
  const calls = [];
  const status = {};
  const listeners = {};
  const button = {
    addEventListener: (name, callback) => { listeners[name] = callback; },
    removeEventListener: (name) => { delete listeners[name]; }
  };
  const elements = { destination: { textContent: JSON.stringify(target) }, status, 'open-post': button };
  const app = {
    platform,
    initData: inTelegram ? 'signed-input' : '',
    ready: () => calls.push('ready'),
    openTelegramLink: (url) => {
      calls.push(['open', url]);
      if (navigationError) throw new Error('Unsupported client');
    },
    close: () => calls.push('close')
  };
  const context = {
    document: { getElementById: id => elements[id] },
    window: { Telegram: { WebApp: app }, location: { replace: url => calls.push(['navigate', url]) } },
    AbortController,
    setTimeout,
    clearTimeout,
    fetch: async (url, options) => {
      calls.push(['verify', url, options]);
      if (verify === 'network') throw new Error('Offline');
      return { ok: verify !== 'unauthorized', json: async () => ({ destination: verify === 'wrong-target' ? 'https://example.com' : target }) };
    }
  };
  vm.runInNewContext(source, context);
  await new Promise(resolve => setImmediate(resolve));
  return { calls, status, button, listeners };
}

test('verifies before opening the fixed post, then closes the Mini App', async () => {
  const result = await run();
  assert.deepEqual(result.calls.map(x => Array.isArray(x) ? x[0] : x), ['ready', 'verify', 'open', 'close']);
  assert.equal(result.calls[2][1], target);
  const options = result.calls[1][2];
  assert.equal(options.credentials, 'omit');
  assert.equal(JSON.parse(options.body).init_data, 'signed-input');
  result.listeners.click({ preventDefault() {} });
  assert.equal(result.calls.filter(x => x === 'close').length, 2);
});

test('Android automatically uses native URL navigation after verification and never closes the fallback', async () => {
  const result = await run({ platform: 'android' });
  assert.deepEqual(result.calls.map(x => Array.isArray(x) ? x[0] : x), ['ready', 'verify', 'navigate']);
  assert.equal(result.calls.at(-1)[1], target);
  // A silently ignored native command must not disable the manual escape.
  result.listeners.click({ preventDefault() {} });
  assert.equal(result.calls.at(-1)[0], 'open');
  assert.equal(result.calls.includes('close'), false);
});

test('Android verification failure keeps a user-initiated SDK link without closing', async () => {
  const result = await run({ platform: 'android', verify: 'network' });
  assert.equal(result.calls.some(x => Array.isArray(x) && x[0] === 'navigate'), false);
  result.listeners.click({ preventDefault() {} });
  assert.equal(result.calls.at(-1)[0], 'open');
  assert.equal(result.calls.includes('close'), false);
});

test('iOS keeps automatic SDK navigation without an immediate close', async () => {
  const result = await run({ platform: 'ios' });
  assert.equal(result.calls.at(-1)[0], 'open');
  assert.equal(result.calls.includes('close'), false);
});

test('ordinary browser retains a direct link without identifying or navigating automatically', async () => {
  const result = await run({ inTelegram: false });
  assert.deepEqual(result.calls, []);
  assert.equal(result.button.href, target);
});

for (const verify of ['network', 'unauthorized', 'wrong-target']) {
  test(`${verify}: offers manual navigation without an automatic retry`, async () => {
    const result = await run({ verify });
    assert.equal(result.calls.some(x => Array.isArray(x) && x[0] === 'open'), false);
    assert.match(result.status.textContent, /Открыть канал/);
    result.listeners.click({ preventDefault() {} });
    assert.equal(result.calls.at(-1), 'close');
  });
}

test('SDK navigation failure keeps a usable ordinary link and does not close the screen', async () => {
  const result = await run({ navigationError: true });
  assert.equal(result.calls.includes('close'), false);
  assert.equal(result.listeners.click, undefined);
  assert.equal(result.button.href, target);
});
