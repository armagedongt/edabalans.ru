import assert from 'node:assert/strict';
import {readFile, writeFile, mkdir} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
import {execFileSync} from 'node:child_process';
const {chromium} = await import(process.env.PLAYWRIGHT_MODULE_URL || 'playwright');
const out = process.env.QA_OUT;
assert(out, 'QA_OUT must be an external evidence path');
await mkdir(out, {recursive:true});
// Use the same test-only database fixture as the backend access tests.
const fixtureData = JSON.parse(execFileSync(process.env.PYTHON || 'python', ['-c', `
import json, logging
logging.disable(logging.CRITICAL)
from test_legacy_courses import legacy_setup
client, factory = legacy_setup()
print(json.dumps({name:client.get(path).json() for name,path in [
 ('manifest','/api/masterclass/course/manifest?email=member@example.test'),
 ('course','/api/masterclass/course?email=member@example.test')]}))
`], {cwd:new URL('../..',import.meta.url),env:{...process.env,PYTHONPATH:'tests'},encoding:'utf8'}));
for (const name of ['manifest','course']) await writeFile(`${out}/${name}.json`,JSON.stringify(fixtureData[name]));
const root = new URL('../../app/static/', import.meta.url);
const fragment = (await readFile(new URL('apps/account.html',root),'utf8')).replace(/<link\b[^>]*>/g,'').replace(/<script\b[^>]*\bsrc=[^>]*><\/script>/g,'');
const css = await readFile(new URL('account-visual.css',root),'utf8');
const js = await readFile(new URL('account-legacy-offer.js',root),'utf8');
const font = (await readFile(new URL('blog/fonts/manrope-cyrillic.woff2',root))).toString('base64');
const account = {email:'member@example.test',state:'ready',legal:{required:false},legacy_portal:{available:true},
  courses:[{code:'masterclass',product_code:'masterclass',title:'Мастер-класс по изменению питания и пищевых привычек',summary:'Программа по питанию.',owned:true,ready:true,app:'masterclass-course',access_edition:'non_updating'}],applications:[]};
function fixture(stage) {
  const now=Date.now(), amount=stage==='first'?1990:stage==='day'?2500:2990;
  const offer={available:true,stage,server_now:new Date(now).toISOString(),expires_at:stage==='standard'?null:new Date(now+(stage==='first'?600000:86400000)).toISOString(),
    current:[{name:'Мастер-класс по изменению питания и пищевых привычек',edition:'non_updating'}],
    offers:[{code:'legacy-upgrade',price:amount,regular_price:2990,details:[{name:'Мастер-класс по изменению питания и пищевых привычек'},{name:'Мини-курс «Калорийный»'},{name:'Система рецептов'}]}]};
  return `<!doctype html><meta charset="utf-8"><style>@font-face{font-family:Manrope;src:url(data:font/woff2;base64,${font})}body{margin:0}${css}</style><script>
    window.EdabalansIdentity={email:'member@example.test',source:'native'};
    window.EdabalansAccountPayload=${JSON.stringify(account)};
    window.EdabalansAppHost='http://fixture.test';
    window.EdabalansEmbed={waitUntilReady:function(){},load:function(){return Promise.resolve()}};
    window.EdabalansProductPopup={show:function(){}};
    window.__checkoutBodies=[]; window.__submitted=0;
    HTMLFormElement.prototype.submit=function(){window.__submitted++};
    window.fetch=function(url,options){var payload={};
      if(String(url).includes('/legacy-offer/show'))payload=${JSON.stringify(offer)};
      if(String(url).includes('/account-offers/checkout')){window.__checkoutBodies.push(JSON.parse(options.body));payload={amount:${amount},payment_form:{method:'POST',action:'https://auth.robokassa.ru/Merchant/Index.aspx',fields:{InvId:'fixture'}}};}
      return Promise.resolve(new Response(JSON.stringify(payload),{status:200,headers:{'Content-Type':'application/json'}}));
    };
  </script><script>${js}</script>${fragment}`;
}
const browser=await chromium.launch({headless:true});
try {
  for(const stage of ['first','day','standard']) {
    const html=fixture(stage);
    await writeFile(`${out}/${stage}.html`,html);
    const page=await browser.newPage();
    await page.setContent(html,{waitUntil:'domcontentloaded'});
    await page.locator('[data-legacy-buy]').waitFor();
    assert(await page.locator('[data-legacy-buy]').isDisabled());
    for(const width of [360,430,520,521,768,1440]) {
      await page.setViewportSize({width,height:1000});
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`${stage} overflow at ${width}`);
      await page.screenshot({path:`${out}/${stage}-${width}.png`,fullPage:true,animations:'disabled'});
    }
    await page.locator('[data-legacy-consent]').check();
    await page.locator('[data-legacy-buy]').click();
    await page.waitForFunction(()=>window.__submitted===1);
    const bodies=await page.evaluate(()=>window.__checkoutBodies);
    assert.equal(bodies.length,1);
    assert.equal(bodies[0].expected_price,stage==='first'?1990:stage==='day'?2500:2990);
    await page.close();
  }
  const manifest = JSON.parse(await readFile(`${out}/manifest.json`, 'utf8'));
  const course = JSON.parse(await readFile(`${out}/course.json`, 'utf8'));
  const shell = (await readFile(new URL('masterclass-first-days-preview.html', root), 'utf8'))
    .replace(/<script\b[^>]*\bsrc=[^>]*><\/script>/g, '');
  const coursePage = await browser.newPage();
  const errors = [];
  coursePage.on('pageerror', e => errors.push(e.message));
  await coursePage.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.pathname.includes('/api/masterclass/course/manifest')) return route.fulfill({json:manifest});
    if (url.pathname.includes('/api/masterclass/course/days/') || url.pathname === '/api/masterclass/course') return route.fulfill({json:course});
    if (url.pathname.startsWith('/api/')) return route.fulfill({json:{}});
    if (url.pathname.startsWith('/assets/')) {
      try {return route.fulfill({body:await readFile(new URL(url.pathname.slice(8),root)),contentType:url.pathname.endsWith('.css')?'text/css':'application/octet-stream'});} catch {}
    }
    return route.fulfill({body:''});
  });
  for (const day of [4,7]) {
    course.current_day=day; course.days[day-1].opened=true;
    await coursePage.goto(`http://fixture.test/lk?course_day=${day}`);
    await coursePage.setContent(shell.replace('<head>', `<head><script>window.EdabalansIdentity={email:'member@example.test',source:'native'};window.EdabalansAppHost='http://fixture.test';window.EdabalansAppContext={accountUrl:'http://fixture.test/lk'};</script>`));
    await coursePage.locator('#day .topic[disabled] .topic-meta').first().waitFor();
    await coursePage.locator('#close').evaluate(button=>button.click());
    for (const width of [360,430,520,521,768,1440]) {
      await coursePage.setViewportSize({width,height:1000});
      assert(await coursePage.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`course day ${day} overflow at ${width}`);
      await coursePage.screenshot({path:`${out}/course-day-${day}-${width}.png`,fullPage:true,animations:'disabled'});
    }
    const locked=coursePage.locator('#day .topic[disabled]');
    assert(await locked.count()>0);
    assert((await locked.first().innerText()).includes('В обновляемом доступе'));
  }
  assert.deepEqual(errors,[]);
  await coursePage.close();
  const offerPage=await browser.newPage();
  const offerJs=await readFile(new URL('masterclass.js',root),'utf8');
  const offerCss=await readFile(new URL('masterclass.css',root),'utf8');
  await offerPage.setContent(`<meta charset="utf-8"><style>${offerCss}</style><div id="masterclass-offers-app"></div><script>window.EdabalansAppContext={app:'masterclass-offers',accountOffer:true,accountUrl:'https://похудение-это-есть.рф/lk'};window.EdabalansIdentity={email:'member@example.test',source:'native'};window.fetch=()=>Promise.resolve(new Response(JSON.stringify({legacy_upgrade:true}),{status:200}));</script><script>${offerJs}</script>`);
  await offerPage.getByRole('link',{name:'Посмотреть полный пакет и цену в личном кабинете →'}).waitFor();
  for(const width of [360,430,520,521,768,1440]) {
    await offerPage.setViewportSize({width,height:1000});
    assert(await offerPage.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    await offerPage.screenshot({path:`${out}/course-offer-${width}.png`,fullPage:true,animations:'disabled'});
  }
  await offerPage.close();
} finally {await browser.close();}
console.log('legacy-course-offer: prices, consent, checkout, locked course cards and offer link at six widths passed');
