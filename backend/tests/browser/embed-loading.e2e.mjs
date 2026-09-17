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
const homepageLoader = await readFile(new URL('../../app/static/homepage.js', import.meta.url), 'utf8')
const intensiveLoader = await readFile(new URL('../../app/static/intensive/tilda-loader.js', import.meta.url), 'utf8')
const dqsHtml = await readFile(new URL('../../app/static/apps/dqs.html', import.meta.url), 'utf8')
const strengthHtml = await readFile(new URL('../../app/static/apps/strength.html', import.meta.url), 'utf8')
const dqsRules = await readFile(new URL('../../app/static/apps/dqs-category-rules.js', import.meta.url), 'utf8')
const accountVisual = await readFile(new URL('../../app/static/account-visual.css', import.meta.url), 'utf8')
const appShellCss = await readFile(new URL('../../app/static/app-shell.css', import.meta.url), 'utf8')
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
async function captureSnapshot(page,name){
  if(!process.env.QA_OUT)return
  const html=await page.evaluate(()=>{
    const copy=document.documentElement.cloneNode(true)
    copy.querySelectorAll('script').forEach(node=>node.remove())
    copy.querySelectorAll('link[href]').forEach(node=>{
      if(node.href.includes('fonts.googleapis.com'))node.remove()
      else node.href=node.href.replace('http://127.0.0.1:18995','http://127.0.0.1:8790')
    })
    return '<!doctype html>'+copy.outerHTML
  })
  await writeFile(process.env.QA_OUT+'/'+name+'.html',html)
}
const origin = 'http://127.0.0.1:18995'
const browser = await chromium.launch({headless: true,args:['--disable-gpu','--in-process-gpu']})
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
  let cssAttempts = 0, cssFailed = true
  await retry.route(origin + '/**', async route => {
    const path = new URL(route.request().url()).pathname
    if (path === '/') return route.fulfill({contentType:'text/html; charset=utf-8',body:'<meta charset="utf-8"><div data-edabalans-app="account"></div><script src="/embed.js"></script>'})
    if (path === '/embed.js') return route.fulfill({contentType:'application/javascript',body:embed})
    if (path === '/api/account-auth/session') return route.fulfill({json:{authenticated:true,email:'reader@example.test'}})
    if (path === '/apps/account.html') return route.fulfill({contentType:'text/html',body:html})
    if (path === '/visual.css') { cssAttempts++; return route.fulfill({status:cssFailed?500:200,contentType:'text/css',body:'#account-app{color:blue}'}) }
    if (path === '/api/test-data') return route.fulfill({json:{ok:true}})
    return route.fulfill({contentType:'application/javascript',body:''})
  })
  await retry.goto(origin, {waitUntil:'domcontentloaded'})
  await retry.locator('.ed-loading-retry').waitFor()
  await capture(retry, 'loader-error')
  assert.equal(await retry.locator('#account-app h1').isVisible(), false)
  assert.equal(await retry.locator('.ed-loading-dots').count(), 0)
  const failedAttempts = cssAttempts
  cssFailed = false
  await retry.locator('.ed-loading-retry').click()
  await retry.waitForFunction(() => !document.querySelector('.ed-loading-screen'))
  assert.equal(cssAttempts, failedAttempts + 1)
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
  const account = {email:'reader@example.test',state:'ready',courses:[{app:'masterclass-course',code:'masterclass',product_code:'masterclass',owned:true,ready:true,title:'Мастер-класс'},{code:'calories',product_code:'calories',owned:false,ready:true,title:'Калорийный курс'}],applications:[]}
  const progress = {current_day:2,server_now:new Date().toISOString(),days:manifest.days.map(d=>({number:d.number,opened:d.number<=5,can_open:d.number<=5,completed:false,completed_steps:d.steps.map((_,i)=>i),checkmarks:{},first_opened_at:new Date().toISOString()}))}
  async function nativePage(query, delays) {
    const native = await browser.newPage({viewport:{width:1440,height:1000}})
    const requests = {account:0,session:0,step:0,corpus:0}
    const faults = []
    await native.addInitScript(()=>{
      window.loaderCounts=[]
      new MutationObserver(()=>loaderCounts.push(document.querySelectorAll('.ed-loading-screen,.ed-loading-inline').length)).observe(document,{childList:true,subtree:true})
    })
    native.on('pageerror',e=>faults.push(String(e)))
    native.on('console',message=>{if(message.type()==='warning')console.error(message.text())})
    await native.route('**/*', async route => {
      const url = new URL(route.request().url()), path = url.pathname
      if(path==='/lk')return route.fulfill({contentType:'text/html; charset=utf-8',body:portalHtml})
      if(path==='/embed.js')return route.fulfill({contentType:'application/javascript; charset=utf-8',body:embed})
      if(path==='/apps/account.html'){if(delays.html)delays.html.release();return route.fulfill({contentType:'text/html; charset=utf-8',body:accountHtml})}
      if(path==='/apps/masterclass-course.html')return route.fulfill({contentType:'text/html; charset=utf-8',body:courseHtml})
      if(path==='/apps/dqs.html')return route.fulfill({contentType:'text/html; charset=utf-8',body:dqsHtml})
      if(path==='/apps/strength.html')return route.fulfill({contentType:'text/html; charset=utf-8',body:strengthHtml})
      if(path==='/apps/dqs-category-rules.js')return route.fulfill({contentType:'application/javascript; charset=utf-8',body:dqsRules})
      if(path==='/apps/masterclass-offers.html'){if(delays.special)await delays.special.promise;return route.fulfill({contentType:'text/html; charset=utf-8',body:'<div id="masterclass-offers-app">Готовые предложения</div>'})}
      if(path==='/assets/course-visual.css')return route.fulfill({contentType:'text/css',body:visualCss})
      if(url.hostname==='fonts.googleapis.com'){if(delays.fontCss)await delays.fontCss.promise;return route.fulfill({contentType:'text/css',body:''})}
      if(path==='/assets/account-visual.css'&&delays.fontFile)return route.fulfill({contentType:'text/css',body:'@font-face{font-family:Manrope;src:url(/slow-font.woff2)} .account-shell{font-family:Manrope,Arial}'})
      if(path==='/assets/account-visual.css')return route.fulfill({contentType:'text/css',body:accountVisual})
      if(path==='/assets/app-shell.css')return route.fulfill({contentType:'text/css',body:appShellCss})
      if(path==='/slow-font.woff2'){await delays.fontFile.promise;return route.abort()}
      if(path==='/assets/content-gallery.js')return route.fulfill({contentType:'application/javascript',body:galleryJs})
      if(path==='/course-assets/masterclass/article-components.js')return route.fulfill({contentType:'application/javascript',body:sliderJs})
      if(path.endsWith('.css'))return route.fulfill({contentType:'text/css',body:''})
      if(path==='/api/account-auth/session'){requests.session++;return route.fulfill({json:{authenticated:true,email:account.email}})}
      if(path==='/api/account-auth/account'){requests.account++;if(delays.auth)await delays.auth.promise;return route.fulfill({json:delays.account||account})}
      if(path==='/api/apps/dqs'){
        const payload={ok:true,email:account.email,startDate:'2026-09-01',needsStartDate:false,days:[]},callback=url.searchParams.get('callback')
        return callback?route.fulfill({contentType:'application/javascript; charset=utf-8',body:callback+'('+JSON.stringify(payload)+')'}):route.fulfill({json:payload})
      }
      if(path==='/api/apps/strength')return route.fulfill({json:{ok:true,user:{user_id:'preview',email:account.email,display_name:'Предпросмотр'},workout:{workout_types:[],exercise_catalog:[],sessions:[],session_exercises:[],sets:[]}}})
      if(path==='/api/masterclass/account-offers'){if(delays.offers)await delays.offers.promise;return route.fulfill({json:{focusable_product_codes:['calories']}})}
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
  const auth=barrier(), offers=barrier(), prefetched=barrier(), fontCss=barrier(), fontFile=barrier()
  const dashboard=await nativePage('',{auth,offers,html:prefetched,fontCss,fontFile})
  await dashboard.native.locator('.ed-loading-screen').waitFor()
  assert.equal(await dashboard.native.locator('.ed-loading-stage').textContent(),'Проверка авторизации')
  await prefetched.promise
  assert.equal(await dashboard.native.locator('#account-app').count(),0,'Prefetch must not execute the app before authorization')
  auth.release()
  await dashboard.native.waitForFunction(()=>!document.querySelector('.ed-loading-screen'))
  assert.equal(await dashboard.native.locator('.account-card').first().isVisible(),true,'Offers and fonts must not delay the first useful screen')
  await dashboard.native.waitForFunction(()=>document.fonts.status==='loading')
  assert.equal(await dashboard.native.locator('[data-offer-product="calories"]').count(),0)
  offers.release()
  await dashboard.native.locator('[data-offer-product="calories"]').waitFor()
  assert.equal(await dashboard.native.locator('[data-offer-product="calories"]').isEnabled(),true,'Background offer must remain purchasable')
  assert.equal(await dashboard.native.evaluate(()=>Math.max(...loaderCounts)),1,'Native portal and app share one loader')
  assert.deepEqual(dashboard.requests,{account:1,session:0,step:0,corpus:0})
  assert.deepEqual(dashboard.faults,[])
  fontCss.release();fontFile.release()
  await dashboard.native.locator('[data-offer-product="calories"]').click()
  await dashboard.native.locator('#masterclass-offers-app').waitFor({state:'visible'})
  assert.equal(await dashboard.native.locator('[data-edabalans-focus-product="calories"]').count(),1,'Background Buy must open the requested product')
  assert.equal(await dashboard.native.locator('[data-edabalans-account-offer="true"]').count(),1,'Background Buy must retain account-offer context')
  assert.deepEqual(dashboard.faults,[])
  await dashboard.native.close()

  const maintenanceAccount={...account,courses:[account.courses[0],
    {code:'calories',product_code:'calories',title:'Калорийный курс',owned:true,ready:false,maintenance:true},
    {code:'recipes',product_code:'recipes',title:'Система рецептов',owned:true,ready:false,maintenance:true},
    {code:'strength',product_code:'training',title:'Курс по тренировкам',owned:false,ready:false}],
    applications:[{code:'recipes',title:'Калькулятор и каталог рецептов',owned:true,ready:false,maintenance:true}]}
  const maintenance=await nativePage('?calories_stage=1',{account:maintenanceAccount})
  await maintenance.native.locator('.account-card').first().waitFor({state:'visible'})
  for(const title of ['Калорийный курс','Система рецептов']){
    const card=maintenance.native.locator('.account-card').filter({has:maintenance.native.getByRole('heading',{name:title,exact:true})})
    assert.equal(await card.getByRole('button',{name:'На ремонте',exact:true}).isDisabled(),true)
    assert.equal(await card.locator('[data-app],[data-offer-product]').count(),0)
  }
  assert.equal(await maintenance.native.getByRole('button',{name:'Скоро',exact:true}).isDisabled(),true)
  assert.equal(await maintenance.native.locator('.application-card').getByRole('button',{name:'На ремонте'}).isDisabled(),true)
  assert.equal(await maintenance.native.locator('[data-app="masterclass-course"]').isEnabled(),true)
  await maintenance.native.waitForFunction(()=>window.__accountOfferContext?.focusable_product_codes)
  assert.equal(await maintenance.native.locator('[data-offer-product="calories"]').count(),0,'Late offers must not enable maintenance purchases')
  await capture(maintenance.native,'account-maintenance')
  await captureSnapshot(maintenance.native,'account-maintenance')
  assert.deepEqual(maintenance.faults,[])
  await maintenance.native.close()

  const navigation=await nativePage('',{account:{...account,applications:[
    {code:'dqs',title:'DQS',owned:true,ready:true,app:'dqs'},
    {code:'strength',title:'Силовые тренировки',owned:true,ready:true,app:'strength'}]}})
  await navigation.native.evaluate(()=>localStorage.setItem('dqs_tutorial_seen_reader@example.test','1'))
  for(const app of ['dqs','strength']){
    await navigation.native.locator('[data-app="'+app+'"]').click()
    const back=navigation.native.getByRole('link',{name:'Личный кабинет',exact:true})
    try{await back.waitFor({state:'visible'})}catch(error){console.error(app,await navigation.native.locator('body').innerText(),navigation.faults);throw error}
    assert.equal(await back.getAttribute('href'),origin+'/lk')
    for(const width of [360,430,768,1440]){
      await navigation.native.setViewportSize({width,height:1000})
      assert.equal(await back.isVisible(),true)
      const box=await back.boundingBox()
      assert(box.x>=0&&box.x+box.width<=width,'Restored account link must fit the app header')
    }
    await capture(navigation.native,'navigation-'+app)
    await captureSnapshot(navigation.native,'navigation-'+app)
    await back.click()
    await navigation.native.locator('.account-card').first().waitFor({state:'visible'})
  }
  assert.deepEqual(navigation.faults,[])
  await navigation.native.close()

  const article=barrier(), corpus=barrier()
  const direct=await nativePage('?course_day=2&course_material=day-02-article-01',{article,corpus})
  await direct.native.waitForFunction(()=>document.querySelector('#article p')?.textContent.includes('Загрузка материала'))
  assert.equal(await direct.native.locator('#masterclass-course-app').isVisible(),false)
  assert.equal(await direct.native.locator('.ed-loading-screen').count(),1,'Portal, account and course must share one loader')
  assert.equal(await direct.native.locator('.ed-loading-screen .ed-loading-stage').count(),1)
  assert.equal(await direct.native.locator('.ed-loading-screen .ed-loading-stage').textContent(),'Загрузка материалов','Nested material loading must replace the completed authorization stage')
  article.release()
  await direct.native.waitForFunction(()=>!document.querySelector('.ed-loading-screen'))
  assert.equal(await direct.native.locator('#article').isVisible(),true)
  assert.match(await direct.native.locator('#article').textContent(),/Готовое содержимое/)
  assert.equal(direct.requests.step,1)
  assert.equal(direct.requests.corpus,0,'Opening one article must not request the whole corpus')
  assert.deepEqual(direct.faults,[])
  assert.equal(await direct.native.evaluate(()=>Math.max(...loaderCounts)),1)
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
  await offer.native.waitForFunction(()=>document.querySelector('#inline-app-frame'))
  assert.equal(await offer.native.locator('.ed-loading-screen').count(),1)
  assert.equal(await offer.native.locator('.ed-loading-inline').count(),0,'Nested inline app reuses the active fullscreen loader')
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

  // Every registered app uses the same loader, including direct standalone entry.
  const appRoots={account:'account-app','masterclass-course':'masterclass-course-app','calories-course':'calories-course-app','masterclass-sales':'masterclass-sales-app',dqs:'dqs-app',strength:'strength-app',metabolism:'metabolism-app','onboarding-questionnaire':'onboarding-questionnaire-app','masterclass-offers':'masterclass-offers-app','recipes-part-1':'recipes-part-1-app','recipes-part-2':'recipes-part-2-app',recipes:'recipes-app','closing-review':'closing-review-app','personal-access':'personal-access-app'}
  for(const [code,id] of Object.entries(appRoots)) {
    console.log('Checking shared loader: '+code)
    const app=await browser.newPage()
    const pending=barrier()
    await app.route(origin+'/**',async route=>{
      const path=new URL(route.request().url()).pathname
      if(path==='/')return route.fulfill({contentType:'text/html; charset=utf-8',body:'<div data-edabalans-app="'+code+'"></div><script src="/embed.js"></script>'})
      if(path==='/embed.js')return route.fulfill({contentType:'application/javascript',body:embed})
      if(path==='/api/account-auth/session')return route.fulfill({json:{authenticated:true,email:account.email}})
      if(path==='/api/apps/dqs/access')return route.fulfill({json:{legal:{required:false}}})
      if(path==='/apps/'+code+'.html')return route.fulfill({contentType:'text/html',body:'<div id="'+id+'">Готово</div><script>EdabalansEmbed.waitUntilReady(document.getElementById("'+id+'"),fetch("/api/first-screen"))</script>'})
      if(path==='/api/first-screen'){await pending.promise;return route.fulfill({json:{ok:true}})}
      return route.fulfill({contentType:'text/css',body:''})
    })
    await app.goto(origin,{waitUntil:'domcontentloaded'})
    await app.waitForFunction(()=>document.querySelector('.ed-loading-stage')?.textContent==='Загрузка материалов').catch(async error=>{
      console.error(code,await app.locator('body').innerHTML())
      throw error
    })
    assert.equal(await app.locator('.ed-loading-screen').count(),1,code)
    assert.equal(await app.locator('#'+id).isVisible(),false,code)
    pending.release()
    await app.waitForFunction(()=>!document.querySelector('.ed-loading-screen'))
    assert.equal(await app.locator('#'+id).isVisible(),true,code)
    await app.close()
  }

  // A nested failure survives its parent finishing; retry reveals the child.
  const nested=await browser.newPage()
  let broken=true
  await nested.route(origin+'/**',async route=>{
    const path=new URL(route.request().url()).pathname
    if(path==='/')return route.fulfill({contentType:'text/html; charset=utf-8',body:'<div data-edabalans-app="account"></div><script src="/embed.js"></script>'})
    if(path==='/embed.js')return route.fulfill({contentType:'application/javascript',body:embed})
    if(path==='/api/account-auth/session')return route.fulfill({json:{authenticated:true,email:account.email}})
    if(path==='/apps/account.html')return route.fulfill({contentType:'text/html',body:'<div id="account-app"><div data-edabalans-app="masterclass-offers"></div></div><script>var parent=document.getElementById("account-app");EdabalansEmbed.waitUntilReady(parent,EdabalansEmbed.load(parent.firstElementChild))</script>'})
    if(path==='/apps/masterclass-offers.html')return route.fulfill({contentType:'text/html',body:'<div id="masterclass-offers-app">Предложения</div><link rel="stylesheet" href="/nested.css">'})
    if(path==='/nested.css')return route.fulfill({status:broken?500:200,contentType:'text/css',body:''})
    return route.fulfill({contentType:'text/css',body:''})
  })
  await nested.goto(origin,{waitUntil:'domcontentloaded'})
  await nested.locator('.ed-loading-retry').waitFor()
  assert.equal(await nested.locator('.ed-loading-screen').count(),1)
  assert.equal(await nested.locator('#masterclass-offers-app').isVisible(),false)
  await capture(nested,'nested-error')
  broken=false
  await nested.locator('.ed-loading-retry').click()
  await nested.waitForFunction(()=>!document.querySelector('.ed-loading-screen'))
  assert.equal(await nested.locator('#masterclass-offers-app').isVisible(),true)
  await nested.close()

  for(const kind of ['homepage','intensive']) {
    const publicPage=await browser.newPage()
    const documentReady=barrier(),analytics=barrier(),pricing=barrier(),pageRequested=barrier()
    const loaderPath=kind==='homepage'?'/homepage.js':'/intensive/tilda-loader.js'
    const sourcePath=kind==='homepage'?'/preview/homepage-release-candidate':'/intensive'
    let authCalls=0
    await publicPage.route('**/*',async route=>{
      const url=new URL(route.request().url()),path=url.pathname
      if(url.origin!==origin)return route.abort()
      if(path==='/')return route.fulfill({contentType:'text/html; charset=utf-8',body:'<div data-edabalans-'+kind+'></div><script src="'+loaderPath+'"></script>'})
      if(path===loaderPath)return route.fulfill({contentType:'application/javascript',body:kind==='homepage'?homepageLoader:intensiveLoader})
      if(path==='/embed.js')return route.fulfill({contentType:'application/javascript',body:embed})
      if(path.startsWith('/api/account-auth/')){authCalls++;return route.fulfill({status:401,json:{}})}
      if(path===sourcePath){pageRequested.release();await documentReady.promise;return route.fulfill({contentType:'text/html',body:kind==='homepage'?'<html><body><h1>Готовая главная</h1><script src="/slow-analytics.js"></script></body></html>':'<html><body><main class="intensive-page"><section data-view="menu"><h1>Готовый интенсив</h1></section></main></body></html>'})}
      if(path==='/api/pricing/site'){await pricing.promise;return route.fulfill({json:{intensive_offer:{expires_at:'2099-01-01T00:00:00Z'}}})}
      if(path==='/slow-analytics.js'||path==='/site-header.js'){await analytics.promise;return route.fulfill({contentType:'application/javascript',body:''})}
      return route.fulfill({contentType:'application/javascript',body:''})
    })
    await publicPage.goto(origin+(kind==='homepage'?'/?source_context=test-source&intensive_offer=test-offer':''),{waitUntil:'domcontentloaded'})
    await publicPage.locator('.ed-loading-screen').waitFor()
    assert.equal(await publicPage.locator('.ed-loading-screen').count(),1)
    assert.equal(await publicPage.locator('.ed-loading-stage').textContent(),'Загрузка страницы')
    await capture(publicPage,'public-'+kind)
    await pageRequested.promise
    if(kind==='homepage') {
      assert.equal(await publicPage.evaluate(()=>window.EdabalansCheckoutSourceContext),'test-source','Shared loading must preserve the accepted commerce source context')
      assert.equal(await publicPage.evaluate(()=>sessionStorage.getItem('edabalans_checkout_source_v1')),'test-source')
    }
    pricing.release()
    documentReady.release()
    await publicPage.waitForFunction(()=>!document.querySelector('.ed-loading-screen')&&document.querySelector('h1'))
    assert.equal(await publicPage.locator('h1').isVisible(),true,'Public content must not wait for analytics/header/footer')
    assert.equal(authCalls,0,'Public loaders must not start authorization')
    analytics.release()
    await publicPage.close()

    // A failed document may arrive before the shared component; no late overlay.
    const late=await browser.newPage(),library=barrier()
    await late.route(origin+'/**',async route=>{
      const path=new URL(route.request().url()).pathname
      if(path==='/')return route.fulfill({contentType:'text/html; charset=utf-8',body:'<div data-edabalans-'+kind+'></div><script src="'+loaderPath+'"></script>'})
      if(path===loaderPath)return route.fulfill({contentType:'application/javascript',body:kind==='homepage'?homepageLoader:intensiveLoader})
      if(path==='/embed.js'){await library.promise;return route.fulfill({contentType:'application/javascript',body:embed})}
      if(path===sourcePath)return route.fulfill({status:503,body:''})
      return route.fulfill({contentType:'application/javascript',body:''})
    })
    await late.goto(origin,{waitUntil:'domcontentloaded'})
    await late.waitForFunction(()=>document.querySelector('[data-edabalans-homepage],[data-edabalans-intensive]')?.textContent.includes('Не удалось'))
    library.release()
    await late.waitForFunction(()=>window.EdabalansEmbed)
    assert.equal(await late.locator('.ed-loading-screen').count(),0,'A late shared script must not cover an already displayed error')
    await late.close()
  }
  console.log('PASS: real portal/course readiness, per-article firstscreen, inline/reduced motion, auth retry, resources and legal gate')
} finally {
  await browser.close()
}
