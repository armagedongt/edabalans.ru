const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const { test } = require('node:test');
const vm = require('node:vm');

const source = readFileSync(join(__dirname, '../app/static/embed.js'), 'utf8');
const brand = 'xn-----jlceacr3bggd8ajed5a6kl.xn--p1ai';

for (const host of [brand, 'www.' + brand, 'admin.' + brand, 'localhost', 'edabalans.ru']) {
  test(`application assets stay on ${host}`, async () => {
    const requests = [];
    const origin = 'https://' + host;
    const context = {
      window: {},
      location: { hostname: host, origin },
      document: { currentScript: { getAttribute: () => 'true' } },
      fetch: async url => {
        requests.push(url);
        return { ok: true, text: async () => '<main></main>' };
      },
    };
    vm.runInNewContext(source, context);
    await context.window.EdabalansEmbed.prefetch('account');
    assert.deepEqual(requests, [origin + '/apps/account.html']);
  });
}
