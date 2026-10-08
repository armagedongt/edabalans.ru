import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const {chromium} = await import(process.env.PLAYWRIGHT_MODULE_URL || 'playwright');
const sdk = readFileSync(new URL('../../app/static/browser-journey.js', import.meta.url), 'utf8');
const root = new URL('https://похудение-это-есть.рф').hostname;
const browser = await chromium.launch({headless:true});
const context = await browser.newContext();
const calls = [];
const preparedCalls = [];
const baseUrl = process.env.BROWSER_JOURNEY_BASE_URL || process.env.HOMEPAGE_BASE_URL || 'http://127.0.0.1:8790';
let concurrent = 0, maximum = 0;
try {
  await context.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.pathname.startsWith('/preview/direct-intensive')) {
      const upstream=await fetch(baseUrl+url.pathname+url.search);
      return route.fulfill({status:upstream.status,headers:{...Object.fromEntries(upstream.headers),'access-control-allow-origin':'*'},body:Buffer.from(await upstream.arrayBuffer())});
    }
    if (url.pathname === '/api/messaging/start-link') {
      const headers={'access-control-allow-origin':'*','access-control-allow-methods':'POST, OPTIONS','access-control-allow-headers':'Content-Type'};
      if(route.request().method()==='OPTIONS') return route.fulfill({status:200,headers});
      const body=route.request().postDataJSON();preparedCalls.push(body);
      const payload='U'+body.messenger+body.entry;
      const deep=body.messenger==='tg'?'https://t.me/Fitness_Talks_bot?start='+payload:'https://max.ru/id230409966750_bot?start='+payload;
      return route.fulfill({headers,contentType:'application/json',body:JSON.stringify({messenger:body.messenger,entry:body.entry,payload,deep_link:deep,qr_url:'https://edabalans.ru/q/'+payload,click_url:'https://edabalans.ru/api/messaging/start-link/click'})});
    }
    if(url.pathname==='/direct-entry') return route.fulfill({contentType:'text/html; charset=utf-8',body:'<!doctype html><meta charset="utf-8"><div id="edb-direct-intensive-host"></div><script src="https://edabalans.ru/preview/direct-intensive/loader.js?variant=topics"></script>'});
    if (url.pathname === '/browser-journey.js') return route.fulfill({contentType:'application/javascript',body:sdk});
    if (url.pathname === '/api/public/browser-journey') {
      const origin = route.request().headers()['origin'] || url.origin;
      const headers = {'access-control-allow-origin':origin,'access-control-allow-methods':'POST, OPTIONS','access-control-allow-headers':'Content-Type'};
      if (route.request().method()==='OPTIONS') return route.fulfill({status:200,headers});
      concurrent++; maximum=Math.max(maximum,concurrent);
      const body=route.request().postDataJSON(); calls.push(body);
      await new Promise(resolve=>setTimeout(resolve,80));
      concurrent--;
      const id=body.transfer?.replace('handoff-', '') || body.context?.replace('visitor-', '') || 'one';
      return route.fulfill({contentType:'application/json',headers,body:JSON.stringify({context:'visitor-'+id,transfer:'handoff-'+id})});
    }
    return route.fulfill({contentType:'text/html',body:`<!doctype html><html><head><meta charset="utf-8"><script src="https://edabalans.ru/browser-journey.js"></script></head><body><a id="bridge" href="https://${url.hostname==='edabalans.ru'?root:'edabalans.ru'}/next">Продолжить</a><button id="accept" onclick="document.cookie='edabalans_cookie_notice=accepted-v1; Path=/';document.dispatchEvent(new Event('edabalans:cookie-accepted'))">Приемлемо</button></body></html>`});
  });
  const page=await context.newPage(); const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('https://edabalans.ru/intensive?i=personal-fixture');
  await page.waitForFunction(()=>window.EdabalansBrowserJourney?.context());
  assert.deepEqual(calls.map(c=>c.event),['init']);
  assert.equal(calls[0].personal_token,'personal-fixture');
  assert.equal(calls[0].accepted,false);
  assert((await context.cookies('https://edabalans.ru')).some(c=>c.name==='edabalans_visitor'&&c.expires>Date.now()/1000+364*86400));
  assert(!(await context.cookies('https://'+root)).some(c=>c.name==='edabalans_visitor'));
  await page.click('#accept');
  await page.waitForFunction(()=>window.EdabalansBrowserJourney.ready);
  await new Promise(resolve=>setTimeout(resolve,180));
  assert(calls.some(c=>c.event==='page'&&c.accepted));
  assert(calls.filter(c=>c.event!=='init').every(c=>!c.personal_token));
  assert.equal(maximum,1);
  await page.click('#bridge');
  await page.waitForFunction(()=>window.EdabalansBrowserJourney?.context());
  assert.equal(await page.evaluate(()=>window.EdabalansBrowserJourney.context()),'visitor-one');
  assert(!page.url().includes('visitor_transfer'));
  const target=(await context.cookies('https://'+root)).find(c=>c.name==='edabalans_visitor');
  assert.equal(target.value,'visitor-one');
  assert.equal(target.domain,'.'+root);
  assert.deepEqual(errors,[]);
  await page.goto('https://'+root+'/direct-entry?utm_source=yandex');
  await page.waitForFunction(()=>document.querySelector('#edb-direct-intensive-v1'));
  await page.waitForTimeout(600);
  assert.equal(preparedCalls.length,4);
  assert(preparedCalls.every(call=>call.browser_context==='visitor-one'));
  assert.deepEqual(new Set(preparedCalls.map(call=>call.messenger)),new Set(['tg','max']));
  console.log('browser journey: pre-acceptance identity, gated events, serialized requests, two-root handoff PASS');
} finally { await browser.close(); }
