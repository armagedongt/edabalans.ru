import assert from 'node:assert/strict'
import { readFile, mkdir, writeFile } from 'node:fs/promises'

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE_URL || 'playwright')
const embed = await readFile(new URL('../../app/static/embed.js', import.meta.url), 'utf8')
const portalHtml = await readFile(new URL('../../app/static/account-portal.html', import.meta.url), 'utf8')
const accountHtml = await readFile(new URL('../../app/static/apps/account.html', import.meta.url), 'utf8')
const courseHtml = await readFile(new URL('../../app/static/masterclass-first-days-preview.html', import.meta.url), 'utf8')
const manifest = JSON.parse(await readFile(new URL('../../../content/masterclass/course/course.json', import.meta.url), 'utf8'))
const visualCss = await readFile(new URL('../../app/static/course-visual.css', import.meta.url), 'utf8')
const galleryJs = await readFile(new URL('../../app/static/content-gallery.js', import.meta.url), 'utf8')
const sliderJs = await readFile(new URL('../../../content/masterclass/components/dqs-image-slider/slider.js', import.meta.url), 'utf8')
async function capture(page, name) {
  if (!process.env.QA_OUT) return
  await mkdir(process.env.QA_OUT, {recursive:true})
  const previous=page.viewportSize()
  for(const width of [360,430,768,1440]) {
    await page.setViewportSize({width,height:1000})
    await page.screenshot({path:process.env.QA_OUT+'/'+name+'-'+width+'.png'})
  }
  await page.setViewportSize(previous)
}
const origin = 'http://127.0.0.1:18995'
const browser = await chromium.launch({headless: true})
const html = '<div id="account-app"><h1>Готовый кабинет</h1><iframe src="/slow-video"></iframe></div><link rel="stylesheet" href="/visual.css"><script>EdabalansEmbed.waitUntilReady(document.getElementById("account-app"),fetch("/api/test-data").then(r=>{if(!r.ok)throw Error("Ошибка данных");return r.json()}))</script>'

function barrier() {
  let release
  const promise = new Promise(resolve => { release = resolve })
  return {promise, release}
}

try {
  // The boundary is the real embed + browser DOM/CSS lifecycle, not a mocked loader.
  const page = await browser.newPage()
  const css = barrier(), data = barrier()
  const counts = {session: 0, html: 0, css: 0}
  const errors = []
  page.on('pageerror', error => errors.push(String(error)))
  await page.route(origin + '/**', async route => {
    const path = new URL(route.request().url()).pathname
    if (path === '/') return route.fulfill({contentType:'text/html; charset=utf-8',body:'<meta charset="utf-8"><div data-edabalans-app="account"></div><script src="/embed.js"></script>'})
    if (path === '/embed.js') return route.fulfill({contentType:'application/javascript',body:embed})
    if (path === '/api/account-auth/session') { counts.session++; return route.fulfill({json:{authenticated:true,email:'reader@example.test'}}) }
    if (path === '/apps/account.html') { counts.html++; return route.fulfill({contentType:'text/html',body:html}) }
    if (path === '/visual.css') { counts.css++; await css.promise; return route.fulfill({contentType:'text/css',body:'#account-app h1{color:rgb(17,142,216)}'}) }
    if (path === '/api/test-data') { await data.promise; return route.fulfill({json:{ok:true}}) }
    if (path === '/slow-video') return route.abort()
    return route.fulfill({contentType:'application/javascript',body:''})
  })
  await page.goto(origin, {waitUntil:'domcontentloaded'})
  await page.waitForFunction(() => document.querySelector('.ed-loading-stage')?.textContent === 'Загрузка оформления')
  assert.equal(await page.locator('#account-app h1').isVisible(), false)
  const before = await page.locator('.ed-loading-stage').boundingBox()
  await capture(page, 'loader-styles')
  css.release()
  await page.waitForFunction(() => document.querySelector('.ed-loading-stage')?.textContent === 'Загрузка материалов')
  assert.equal(await page.locator('#account-app h1').isVisible(), false)
  const after = await page.locator('.ed-loading-stage').boundingBox()
  assert.equal(before.y, after.y, 'Changing the stage must not move the loader')
  data.release()
  await page.waitForFunction(() => !document.querySelector('.ed-loading-screen'))
  assert.equal(await page.locator('#account-app h1').isVisible(), true)
  assert.equal(await page.locator('#account-app h1').evaluate(el=>getComputedStyle(el).color), 'rgb(17, 142, 216)')
  assert.deepEqual(counts, {session:1,html:1,css:1}, 'Prefetch and load share one request')
  await page.evaluate(() => EdabalansEmbed.load(document.getElementById('account-app')))
  assert.deepEqual(counts, {session:1,html:1,css:1}, 'Internal reload reuses HTML/CSS without another frontend login')
  assert.equal(await page.locator('#account-app h1').isVisible(), true)
  assert.deepEqual(errors, [])
  await page.close()

  // A failed stylesheet must not reveal unstyled content or poison the retry cache.
  const retry = await browser.newPage()
  let cssAttempts = 0
  await retry.route(origin + '/**', async route => {
    const path = new URL(route.request().url()).pathname
    if (path === '/') return route.fulfill({contentType:'text/html; charset=utf-8',body:'<meta charset="utf-8"><div data-edabalans-app="account"></div><script src="/embed.js"></script>'})
    if (path === '/embed.js') return route.fulfill({contentType:'application/javascript',body:embed})
    if (path === '/api/account-auth/session') return route.fulfill({json:{authenticated:true,email:'reader@example.test'}})
    if (path === '/apps/account.html') return route.fulfill({contentType:'text/html',body:html})
    if (path === '/visual.css') { cssAttempts++; return route.fulfill({status:cssAttempts===1?500:200,contentType:'text/css',body:'#account-app{color:blue}'}) }
    if (path === '/api/test-data') return route.fulfill({json:{ok:true}})
    return route.fulfill({contentType:'application/javascript',body:''})
  })
  await retry.goto(origin, {waitUntil:'domcontentloaded'})
  await retry.locator('.ed-loading-retry').waitFor()
  await capture(retry, 'loader-error')
  assert.equal(await retry.locator('#account-app h1').isVisible(), false)
  assert.equal(await retry.locator('.ed-loading-dots').count(), 0)
  await retry.locator('.ed-loading-retry').click()
  await retry.waitForFunction(() => !document.querySelector('.ed-loading-screen'))
  assert.equal(cssAttempts, 2)
  assert.equal(await retry.locator('#account-app h1').isVisible(), true)
  await retry.close()

  // DQS legal acceptance remains actionable while its preflight is pending.
  const legal = await browser.newPage()
  await legal.route(origin + '/**', async route => {
    const path = new URL(route.request().url()).pathname
    if (path === '/') return route.fulfill({contentType:'text/html; charset=utf-8',body:'<meta charset="utf-8"><div data-edabalans-app="dqs"></div><script src="/embed.js"></script>'})
    if (path === '/embed.js') return route.fulfill({contentType:'application/javascript',body:embed})
    if (path === '/api/account-auth/session') return route.fulfill({json:{authenticated:true,email:'reader@example.test'}})
    if (path === '/api/apps/dqs/access') return route.fulfill({json:{legal:{required:true,documents:[{code:'disclaimer',title:'Документ',summary:'Подтверждение',url:'/legal/disclaimer.html'}]}}})
    if (path === '/api/account/legal-acceptances') return route.fulfill({json:{legal:{required:false}}})
    if (path === '/apps/dqs.html') return route.fulfill({contentType:'text/html',body:'<div id="dqs-app"><h1>Приложение DQS</h1></div>'})
    return route.fulfill({contentType:'application/javascript',body:''})
  })
  await legal.goto(origin, {waitUntil:'domcontentloaded'})
  await legal.locator('[data-edabalans-dqs-legal]').check()
  await legal.locator('.edabalans-dqs-legal-action').click()
  await legal.waitForFunction(() => !document.querySelector('.ed-loading-screen'))
  assert.equal(await legal.locator('#dqs-app h1').isVisible(), true)
  await legal.close()

  // The real native portal and account app must propagate readiness, not just our fixture.
  const account = {email:'reader@example.test',state:'ready',courses:[{app:'masterclass-course',code:'masterclass',product_code:'masterclass',owned:true,ready:true,title:'Мастер-класс'}],applications:[]}
  const progress = {current_day:2,server_now:new Date().toISOString(),days:manifest.days.map(d=>({number:d.number,opened:d.number<=5,can_open:d.number<=5,completed:false,completed_steps:d.steps.map((_,i)=>i),checkmarks:{},first_opened_at:new Date().toISOString()}))}
  async function nativePage(query, delays) {
    const native = await browser.newPage({viewport:{width:1440,height:1000}})
    const requests = {account:0,session:0,step:0,corpus:0}
    const faults = []
    native.on('pageerror',e=>faults.push(String(e)))
    native.on('console',message=>{if(message.type()==='warning')console.error(message.text())})
    await native.route('**/*', async route => {
      const url = new URL(route.request().url()), path = url.pathname
      if(path==='/lk')return route.fulfill({contentType:'text/html; charset=utf-8',body:portalHtml})
      if(path==='/embed.js')return route.fulfill({contentType:'application/javascript; charset=utf-8',body:embed})
      if(path==='/apps/account.html')return route.fulfill({contentType:'text/html; charset=utf-8',body:accountHtml})
      if(path==='/apps/masterclass-course.html')return route.fulfill({contentType:'text/html; charset=utf-8',body:courseHtml})
      if(path==='/apps/masterclass-offers.html'){if(delays.special)await delays.special.promise;return route.fulfill({contentType:'text/html; charset=utf-8',body:'<div id="masterclass-offers-app">Готовые предложения</div>'})}
      if(path==='/assets/course-visual.css')return route.fulfill({contentType:'text/css',body:visualCss})
      if(path==='/assets/content-gallery.js')return route.fulfill({contentType:'application/javascript',body:galleryJs})
      if(path==='/course-assets/masterclass/article-components.js')return route.fulfill({contentType:'application/javascript',body:sliderJs})
      if(path.endsWith('.css'))return route.fulfill({contentType:'text/css',body:''})
      if(path==='/api/account-auth/session'){requests.session++;return route.fulfill({json:{authenticated:true,email:account.email}})}
      if(path==='/api/account-auth/account'){requests.account++;if(delays.auth)await delays.auth.promise;return route.fulfill({json:account})}
      if(path==='/api/masterclass/account-offers'){if(delays.offers)await delays.offers.promise;return route.fulfill({json:{focusable_product_codes:[]}})}
      if(path==='/api/masterclass/course/manifest')return route.fulfill({json:manifest})
      if(path==='/api/masterclass/course')return route.fulfill({json:progress})
      if(/\/steps\/\d+\/complete$/.test(path))return route.fulfill({json:progress})
      if(path==='/api/masterclass/course/materials'){
        const id=url.searchParams.get('step_id')
        if(id){requests.step++;if(delays.article)await delays.article.promise;return route.fulfill({json:{materials:id==='day-04-dqs'?{}:{[id]:{html:'<p>Готовое содержимое выбранной статьи.</p><img class="article-inline-image" src="https://cdn.example.test/diagram.svg" alt="Проверка обычного изображения">',word_count:5,version:1}}}})}
        requests.corpus++;if(delays.corpus)await delays.corpus.promise;return route.fulfill({json:{materials:{}}})
      }
      if(path.includes('/questionnaires/')){if(delays.questionnaire)await delays.questionnaire.promise;return route.fulfill({json:{questions:[],answers:[]}})}
      if(path.includes('/course/content/')){if(delays.asset)await delays.asset.promise;return route.fulfill({contentType:'text/plain; charset=utf-8',body:'## Инструкция DQS\n\nГотовое описание приложения.'})}
      if(path==='/diagram.svg')return route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="600"><rect width="1200" height="600" fill="#eaf8ff"/><rect x="50" y="50" width="1100" height="500" fill="#27aff5"/></svg>'})
      if(path.startsWith('/api/'))return route.fulfill({json:{ok:true}})
      return route.fulfill({contentType:'application/javascript',body:''})
    })
    await native.goto(origin+'/lk'+query,{waitUntil:'domcontentloaded'})
    return {native,requests,faults}
  }
  const auth=barrier(), offers=barrier()
  const dashboard=await nativePage('',{auth,offers})
  await dashboard.native.locator('.ed-loading-screen').waitFor()
  assert.equal(await dashboard.native.locator('.ed-loading-stage').textContent(),'Проверка авторизации')
  auth.release()
  await dashboard.native.waitForFunction(()=>document.getElementById('account-app'))
  assert.equal(await dashboard.native.locator('#account-app').isVisible(),false)
  offers.release()
  await dashboard.native.waitForFunction(()=>!document.querySelector('.ed-loading-screen'))
  assert.equal(await dashboard.native.locator('.account-card').isVisible(),true)
  assert.deepEqual(dashboard.requests,{account:1,session:0,step:0,corpus:0})
  assert.deepEqual(dashboard.faults,[])
  await dashboard.native.close()

  const article=barrier(), corpus=barrier()
  const direct=await nativePage('?course_day=2&course_material=day-02-article-01',{article,corpus})
  await direct.native.waitForFunction(()=>document.querySelector('#article p')?.textContent.includes('Загрузка материала'))
  assert.equal(await direct.native.locator('#masterclass-course-app').isVisible(),false)
  article.release()
  await direct.native.waitForFunction(()=>!document.querySelector('.ed-loading-screen'))
  assert.equal(await direct.native.locator('#article').isVisible(),true)
  assert.match(await direct.native.locator('#article').textContent(),/Готовое содержимое/)
  assert.equal(direct.requests.step,1)
  assert.equal(direct.requests.corpus,0,'Opening one article must not request the whole corpus')
  assert.deepEqual(direct.faults,[])
  await capture(direct.native,'native-material')
  if(process.env.QA_OUT) {
    const snapshot=await direct.native.evaluate(()=>{const copy=document.documentElement.cloneNode(true);copy.querySelectorAll('script').forEach(e=>e.remove());copy.querySelectorAll('link[href]').forEach(e=>{e.href=e.href.replace('http://127.0.0.1:18995','http://127.0.0.1:8796')});copy.querySelector('.article-inline-image').src='data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="1200" height="600"%3E%3Crect width="1200" height="600" fill="%2327aff5"/%3E%3C/svg%3E';const base=document.createElement('base');base.href='http://127.0.0.1:8796/';copy.querySelector('head').prepend(base);return '<!doctype html>'+copy.outerHTML})
    await writeFile(process.env.QA_OUT+'/ready-material.html',snapshot)
  }
  for(const width of [360,430]) {
    await direct.native.setViewportSize({width,height:1000})
    const box=await direct.native.locator('.article-inline-image').boundingBox()
    assert(box.x>=-1&&box.x+box.width<=width+1,'Ordinary image preserves mobile edge-to-edge bounds')
  }
  corpus.release()
  await direct.native.close()

  const questionnaire=barrier()
  const form=await nativePage('?course_day=1&course_material=day-01-questionnaire',{questionnaire})
  await form.native.waitForFunction(()=>document.querySelector('#q-fields')?.textContent.includes('Загружаю вопросы'))
  assert.equal(await form.native.locator('#masterclass-course-app').isVisible(),false)
  questionnaire.release()
  await form.native.waitForFunction(()=>!document.querySelector('.ed-loading-screen'))
  assert.equal(await form.native.locator('#questionnaire').isVisible(),true)
  assert.doesNotMatch(await form.native.locator('#q-fields').textContent(),/Загружаю вопросы/)
  assert.deepEqual(form.faults,[])
  await form.native.close()

  const firstArticle=barrier()
  const tutorial=await nativePage('?course_day=1&course_material=day-01-article-tutorial',{article:firstArticle})
  await tutorial.native.waitForFunction(()=>document.querySelector('#article p')?.textContent.includes('Загрузка материала'))
  assert.equal(await tutorial.native.locator('#masterclass-course-app').isVisible(),false)
  firstArticle.release()
  await tutorial.native.waitForFunction(()=>!document.querySelector('.ed-loading-screen'))
  assert.match(await tutorial.native.locator('#article').textContent(),/Готовое содержимое/)
  assert.equal(tutorial.requests.step,1,'Published text without contentAsset must still load')
  assert.equal(tutorial.requests.corpus,0)
  assert.deepEqual(tutorial.faults,[])
  await tutorial.native.close()

  const asset=barrier()
  const dqs=await nativePage('?course_day=4&course_material=day-04-dqs',{asset})
  await dqs.native.waitForFunction(()=>document.querySelector('#masterclass-course-app'))
  assert.equal(await dqs.native.locator('#masterclass-course-app').isVisible(),false)
  asset.release()
  await dqs.native.waitForFunction(()=>!document.querySelector('.ed-loading-screen'))
  assert.match(await dqs.native.locator('#article').textContent(),/Готовое описание приложения/)
  assert.deepEqual(dqs.faults,[])
  await dqs.native.close()

  const special=barrier()
  const offer=await nativePage('?course_day=1&course_material=day-01-offer',{special})
  await offer.native.waitForFunction(()=>document.querySelector('#inline-app-frame .ed-loading-inline'))
  assert.equal(await offer.native.locator('#masterclass-course-app').isVisible(),false)
  special.release()
  await offer.native.waitForFunction(()=>!document.querySelector('.ed-loading-screen'))
  assert.equal(await offer.native.locator('#masterclass-offers-app').isVisible(),true)
  assert.deepEqual(offer.faults,[])
  await offer.native.close()

  // An inline loader stays inside its frame and restores positioning and visibility.
  const inline=await browser.newPage({reducedMotion:'reduce'})
  await inline.route(origin+'/**',async route=>{
    const path=new URL(route.request().url()).pathname
    return route.fulfill({contentType:path.endsWith('.js')?'application/javascript; charset=utf-8':'text/html; charset=utf-8',body:path==='/embed.js'?embed:'<meta charset="utf-8"><nav>Оглавление</nav><div id="inline-app-frame" style="height:400px"><div id="inline-root">Приложение</div></div><script src="/embed.js"></script>'})
  })
  await inline.goto(origin,{waitUntil:'domcontentloaded'})
  await inline.evaluate(()=>EdabalansEmbed.beginLoading(document.getElementById('inline-root'),'Загрузка материалов'))
  assert.equal(await inline.locator('.ed-loading-screen').count(),0)
  assert.equal(await inline.locator('.ed-loading-inline').count(),1)
  assert.equal(await inline.locator('nav').isVisible(),true)
  assert.equal(await inline.locator('.ed-loading-dots i').first().evaluate(e=>getComputedStyle(e).animationName),'none')
  await capture(inline,'loader-inline')
  await inline.evaluate(()=>EdabalansEmbed.finishLoading(document.getElementById('inline-root')))
  assert.equal(await inline.locator('#inline-root').isVisible(),true)
  assert.equal(await inline.locator('#inline-app-frame').evaluate(e=>e.style.position),'')
  await inline.close()

  // A transient session failure must remain a retryable error, not silently redirect to login.
  const sessionRetry=await browser.newPage()
  let attempts=0
  await sessionRetry.route(origin+'/**',async route=>{
    const path=new URL(route.request().url()).pathname
    if(path==='/')return route.fulfill({contentType:'text/html; charset=utf-8',body:'<meta charset="utf-8"><div data-edabalans-app="account"></div><script src="/embed.js"></script>'})
    if(path==='/embed.js')return route.fulfill({contentType:'application/javascript; charset=utf-8',body:embed})
    if(path==='/api/account-auth/session'){attempts++;return route.fulfill({status:attempts===1?503:200,json:{authenticated:true,email:account.email}})}
    if(path==='/apps/account.html')return route.fulfill({contentType:'text/html',body:'<div id="account-app">Готово</div>'})
    return route.fulfill({contentType:'application/javascript',body:''})
  })
  await sessionRetry.goto(origin,{waitUntil:'domcontentloaded'})
  await sessionRetry.locator('.ed-loading-retry').waitFor()
  assert.equal(sessionRetry.url(),origin+'/')
  assert.equal(await sessionRetry.locator('.ed-loading-dots').count(),0)
  await sessionRetry.locator('.ed-loading-retry').click()
  await sessionRetry.waitForFunction(()=>!document.querySelector('.ed-loading-screen'))
  assert.equal(attempts,2)
  assert.equal(await sessionRetry.locator('#account-app').isVisible(),true)
  await sessionRetry.close()
  console.log('PASS: real portal/course readiness, per-article firstscreen, inline/reduced motion, auth retry, resources and legal gate')
} finally {
  await browser.close()
}
