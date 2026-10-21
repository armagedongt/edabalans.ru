import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const {chromium} = await import(process.env.PLAYWRIGHT_MODULE_URL || 'playwright');
const asset = path => readFileSync(new URL('../../app/static/'+path, import.meta.url),'utf8');
const browser = await chromium.launch({headless:true});
try {
  const page = await browser.newPage();
  const maxEvents=[];
  await page.addInitScript(() => {window.WebApp={initData:'signed-MAX-U-AbCd',initDataUnsafe:{start_param:'U-AbCd'},ready(){},openMaxLink(url){window.openedMax=url;}};});
  await page.route('**/*', async route => {
    const path=new URL(route.request().url()).pathname;
    if(path==='/max-app') return route.fulfill({contentType:'text/html',body:asset('max-app.html')});
    if(path==='/apps/channel-bridge/max.js') return route.fulfill({contentType:'text/javascript',body:asset('channel-bridge/max.js')});
    if(path==='/apps/channel-bridge/card') return route.fulfill({contentType:'text/html',body:asset('channel-bridge/index.html')});
    if(path.endsWith('/max/verify')) {maxEvents.push(route.request().postDataJSON()); return route.fulfill({json:{destination:'https://max.ru/id230409966750_biz',request_write_access:false}});}
    if(path.endsWith('/max/event')) {maxEvents.push(route.request().postDataJSON());return route.fulfill({status:204});}
    return route.fulfill({body:''});
  });
  await page.goto('https://example.test/max-app');
  await page.waitForFunction(()=>window.openedMax);
  assert.equal(await page.evaluate(()=>window.openedMax),'https://max.ru/id230409966750_biz');
  assert.equal(await page.locator('h1').textContent(),'Сергей Воронцов');
  assert.equal(await page.locator('#open-post').getAttribute('href'),'https://max.ru/id230409966750_biz');
  assert(maxEvents.every(e=>e.init_data==='signed-MAX-U-AbCd'));
  await page.close();

  const homepage=asset('homepage-preview/release-candidate.html');
  const start=homepage.indexOf("      const endpoint = '/api/public/homepage-analytics';");
  const end=homepage.indexOf('</script>',start);
  const tracker='(() => {\n'+homepage.slice(start,end);
  const observed=[];
  const home=await browser.newPage({viewport:{width:390,height:700}});
  await home.route('**/*', async route => {
    const path=new URL(route.request().url()).pathname;
    if(path==='/browser-journey.js') {await new Promise(r=>setTimeout(r,120));return route.fulfill({contentType:'text/javascript',body:asset('browser-journey.js')});}
    if(path==='/cookie-notice.js')return route.fulfill({contentType:'text/javascript',body:asset('site-cookie-notice.js')});
    if(path==='/api/public/browser-journey') return route.fulfill({json:{context:'verified-visitor',transfer:'signed-transfer',accepted:false}});
    if(path==='/api/public/homepage-analytics') {observed.push(route.request().postDataJSON());return route.fulfill({json:{ok:true}});}
    return route.fulfill({contentType:'text/html',body:'<!doctype html><script src="/cookie-notice.js" defer></script><section data-analytics-section="hero_intro" style="height:400px">Hero</section><section style="height:3500px">Middle</section><section data-analytics-section="pricing" style="height:2000px">Pricing</section><script>'+tracker+'</script>'});
  });
  await home.goto('https://похудение-это-есть.рф/');
  await home.waitForFunction(()=>window.EdabalansBrowserJourney?.context());
  await home.waitForTimeout(250);
  assert(observed.some(e=>e.event==='page_open'&&e.context==='verified-visitor'));
  assert(observed.some(e=>e.section_id==='hero_intro'&&e.context==='verified-visitor'));
  await home.evaluate(()=>window.scrollTo(0,document.documentElement.scrollHeight));
  await home.waitForTimeout(400);
  assert(observed.some(e=>e.event==='scroll_depth'&&e.scroll_percent===100));
  assert(observed.filter(e=>e.event==='section_seen').every(e=>['hero_intro','pricing'].includes(e.section_id)));
  console.log('MAX shared card/native SDK dispatch; fresh homepage observer context and bottom depth PASS');
} finally {await browser.close();}
