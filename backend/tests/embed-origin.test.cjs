const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const { test } = require('node:test');
const vm = require('node:vm');

const source = readFileSync(join(__dirname, '../app/static/embed.js'), 'utf8');
const brand = 'xn-----jlceacr3bggd8ajed5a6kl.xn--p1ai';

for (const host of [brand, 'www.' + brand, 'admin.' + brand, 'localhost', 'edabalans.ru', 'app.edabalans.ru', 'future.example']) {
  test(`application assets stay on ${host}`, async () => {
    const requests = [];
    const origin = 'https://' + host;
    const context = {
      URL,
      window: {},
      location: { hostname: host, origin, href: origin + '/lk' },
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


test('external embedding loads assets from the script owner, not the embedding page', async () => {
  const requests = [];
  const context = {
    URL,
    window: {},
    location: { hostname: 'archive.example', origin: 'https://archive.example', href: 'https://archive.example/course' },
    document: { currentScript: { src: 'https://future.example/embed.js', getAttribute: () => 'true' } },
    fetch: async url => { requests.push(url); return { ok: true, text: async () => '<main></main>' }; },
  };
  vm.runInNewContext(source, context);
  await context.window.EdabalansEmbed.prefetch('account');
  assert.deepEqual(requests, ['https://future.example/apps/account.html']);
});

test('selected account stays in its tab and scopes only same-site account APIs', async () => {
  function tab(query) {
    const requests = [], origin = 'https://' + brand;
    const context = {URL, Headers, Request, location:{hostname:brand,origin,href:origin+'/lk'+query},
      document:{currentScript:{src:origin+'/embed.js',getAttribute:()=> 'true'}},
      fetch:async (input,options)=>{requests.push({input,options});return {ok:true}}};
    context.window=context;
    vm.runInNewContext(source,context);
    return {context,requests};
  }
  const selected=tab('?account_user=00000000-0000-0000-0000-000000000002'), own=tab('');
  const request=new Request('https://'+brand+'/api/masterclass/course',{method:'POST',headers:{'Content-Type':'application/json'},body:'{"answer":"unchanged"}'});
  await selected.context.fetch(request);
  assert.equal(selected.requests[0].options.headers.get('X-Edabalans-Account-User'),'00000000-0000-0000-0000-000000000002');
  assert.equal(selected.requests[0].options.headers.get('Content-Type'),'application/json');
  assert.equal(await selected.requests[0].input.clone().text(),'{"answer":"unchanged"}');
  for(const course of ['calories','recipes']){
    await selected.context.fetch('/api/'+course+'/course');
    assert.equal(selected.requests.at(-1).options.headers.get('X-Edabalans-Account-User'),'00000000-0000-0000-0000-000000000002');
  }
  await own.context.fetch('/api/account-auth/account');
  assert.equal(own.requests[0].options,undefined);
  for(const path of ['https://other.example/api/account-auth/account','/api/public/browser-journey','/api/account-auth/login','/api/account-auth/logout']){
    await selected.context.fetch(path);
    assert.equal(selected.requests.at(-1).options,undefined);
  }
});
