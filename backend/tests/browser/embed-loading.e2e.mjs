import assert from 'node:assert/strict'
import { readFile, mkdir, writeFile } from 'node:fs/promises'

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE_URL || 'playwright')
const embed = await readFile(new URL('../../app/static/embed.js', import.meta.url), 'utf8')
const portalHtml = await readFile(new URL('../../app/static/account-portal.html', import.meta.url), 'utf8')
const accountHtml = await readFile(new URL('../../app/static/apps/account.html', import.meta.url), 'utf8')
const courseHtml = await readFile(new URL('../../app/static/masterclass-first-days-preview.html', import.meta.url), 'utf8')
const questionnaireJs = await readFile(new URL('../../app/static/masterclass.js', import.meta.url), 'utf8')
const personJs = await readFile(new URL('../../app/static/questionnaire-person.js', import.meta.url), 'utf8')
const personCss = await readFile(new URL('../../app/static/questionnaire-person.css', import.meta.url), 'utf8')
const standaloneCss = await readFile(new URL('../../app/static/masterclass.css', import.meta.url), 'utf8')
const personFields=[{key:'gender',code:'person_gender',title:'Пол',options:['Женщина','Мужчина']},{key:'age',code:'person_age',title:'Возраст, лет',min:1,max:120,step:1},{key:'height',code:'person_height',title:'Рост, см',min:50,max:250,step:0.1},{key:'weight',code:'person_weight',title:'Вес, кг',min:10,max:500,step:0.1}]
const personParameters={gender:'Женщина',age:35,height:170,weight:80}
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
const accountTheme = await readFile(new URL('../../app/static/account-theme.css', import.meta.url), 'utf8')
const accountThemeJs = await readFile(new URL('../../app/static/account-theme.js', import.meta.url), 'utf8')
const articleTypography = await readFile(new URL('../../../content/article-components/typography.css', import.meta.url), 'utf8')
const articleNote = await readFile(new URL('../../../content/article-components/note.css', import.meta.url), 'utf8')
const appShellCss = await readFile(new URL('../../app/static/app-shell.css', import.meta.url), 'utf8')
async function waitUntil(predicate){const deadline=Date.now()+15000;while(!predicate()){if(Date.now()>deadline)throw Error('Timed out waiting for background request');await new Promise(resolve=>setTimeout(resolve,20))}}
async function capture(page, name, currentViewportOnly=false) {
  if (!process.env.QA_OUT) return
  await mkdir(process.env.QA_OUT, {recursive:true})
  const previous=page.viewportSize()
  for(const width of currentViewportOnly?[previous.width]:[360,430,768,1440]) {
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
async function waitForReveal(page){
  await page.waitForFunction(()=>!document.querySelector('.ed-loading-screen'))
  // Visibility inherited by nested mounts is asserted after Chromium has painted it.
  await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))))
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
  const css = barrier(), data = barrier(), dataStarted = barrier()
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
    if (path === '/api/test-data') { dataStarted.release(); await data.promise; return route.fulfill({json:{ok:true}}) }
    if (path === '/slow-video') return route.abort()
    return route.fulfill({contentType:'application/javascript',body:''})
  })
  await page.goto(origin, {waitUntil:'domcontentloaded'})
  await page.locator('#account-app h1').waitFor({state:'attached'})
  assert.equal(await page.locator('.ed-loading-stage').textContent(), 'Загрузка страницы')
  assert.equal(await page.locator('#account-app h1').isVisible(), false)
  const before = await page.locator('.ed-loading-stage').boundingBox()
  await capture(page, 'loader-styles')
  css.release()
  await dataStarted.promise
  assert.equal(await page.locator('.ed-loading-stage').textContent(), 'Загрузка страницы', 'Cosmetic sub-stages must not cycle through extra captions')
  assert.equal(await page.locator('#account-app h1').isVisible(), false)
  const after = await page.locator('.ed-loading-stage').boundingBox()
  assert.equal(before.y, after.y, 'Changing the stage must not move the loader')
  data.release()
  await waitForReveal(page)
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
  await waitForReveal(retry)
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
  await legal.locator('#dqs-app h1').waitFor({state:'visible'})
  await waitForReveal(legal)
  assert.equal(await legal.locator('#dqs-app h1').isVisible(), true)
  await legal.close()

  // Shared fragments retain their maintenance layout after root.innerHTML mounting.
  for(const app of ['calories-course','recipes','recipes-part-1','recipes-part-2']){
    const fragment=process.env.MAINTENANCE_ORIGIN
      ? await fetch(process.env.MAINTENANCE_ORIGIN+'/apps/'+app+'.html').then(response=>{assert.equal(response.status,200);return response.text()})
      : '<link rel="stylesheet" href="/assets/app-shell.css"><section id="'+app+'-app"><div class="ed-app-maintenance"><h1>На ремонте</h1><a class="ed-app-account-link ed-app-maintenance-account" href="/lk">Личный кабинет</a></div></section>'
    const paused=await browser.newPage({viewport:{width:360,height:1000}})
    await paused.route(origin+'/**',async route=>{
      const path=new URL(route.request().url()).pathname
      if(path==='/')return route.fulfill({contentType:'text/html; charset=utf-8',body:'<meta charset="utf-8"><div data-edabalans-app="'+app+'"></div><script src="/embed.js"></script>'})
      if(path==='/embed.js')return route.fulfill({contentType:'application/javascript',body:embed})
      if(path==='/api/account-auth/session')return route.fulfill({json:{authenticated:true,email:'reader@example.test'}})
      if(path==='/apps/'+app+'.html')return route.fulfill({contentType:'text/html; charset=utf-8',body:fragment})
      if(path==='/assets/app-shell.css')return route.fulfill({contentType:'text/css',body:appShellCss})
      return route.fulfill({contentType:'application/javascript',body:''})
    })
    await paused.goto(origin,{waitUntil:'domcontentloaded'})
    await paused.waitForFunction(()=>!document.querySelector('.ed-loading-screen')&&document.querySelector('.ed-app-maintenance'))
    assert.equal(await paused.locator('.ed-app-maintenance').evaluate(el=>getComputedStyle(el).display),'grid')
    assert.equal(await paused.getByRole('heading',{name:'На ремонте'}).evaluate(el=>getComputedStyle(el).fontSize),'28px')
    assert.equal(await paused.getByRole('link',{name:'Личный кабинет'}).isVisible(),true)
    if(app==='calories-course')await capture(paused,'maintenance-mounted')
    await paused.close()
  }

  // The real native portal and account app must propagate readiness, not just our fixture.
  const account = {email:'reader@example.test',state:'ready',courses:[{app:'masterclass-course',code:'masterclass',product_code:'masterclass',owned:true,ready:true,title:'Мастер-класс'},{code:'calories',product_code:'calories',owned:false,ready:true,title:'Калорийный курс'}],applications:[]}
  const progress = {current_day:2,server_now:new Date().toISOString(),days:manifest.days.map(d=>({number:d.number,opened:d.number<=5,can_open:d.number<=5,completed:false,completed_steps:d.steps.map((_,i)=>i),checkmarks:{},first_opened_at:new Date().toISOString()}))}
  async function nativePage(query, delays) {
    const native = await browser.newPage({viewport:{width:delays.width||1440,height:1000},reducedMotion:'reduce'})
    const requests = {account:0,session:0,step:0,corpus:0,answers:[],submitted:0,completed:0}
    const completedSteps=new Set((delays.progress||progress).days[0].completed_steps)
    const questionnaireStepIndex=(delays.manifest||manifest).days[0].steps.findIndex(step=>step.kind==='questionnaire')
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
      if(path==='/assets/account-theme.css')return route.fulfill({contentType:'text/css',body:accountTheme})
      if(path==='/assets/account-theme.js')return route.fulfill({contentType:'application/javascript',body:accountThemeJs})
      if(path==='/assets/article-typography.css')return route.fulfill({contentType:'text/css',body:articleTypography})
      if(path==='/assets/article-note.css')return route.fulfill({contentType:'text/css',body:articleNote})
      if(url.hostname==='fonts.googleapis.com'){if(delays.fontCss)await delays.fontCss.promise;return route.fulfill({contentType:'text/css',body:''})}
      if(path==='/assets/account-visual.css'&&delays.fontFile)return route.fulfill({contentType:'text/css',body:'@font-face{font-family:Manrope;src:url(/slow-font.woff2)} .account-shell{font-family:Manrope,Arial}'})
      if(path==='/assets/account-visual.css')return route.fulfill({contentType:'text/css',body:accountVisual})
      if(path==='/assets/app-shell.css')return route.fulfill({contentType:'text/css',body:appShellCss})
      if(path==='/slow-font.woff2'){await delays.fontFile.promise;return route.abort()}
      if(path==='/assets/content-gallery.js')return route.fulfill({contentType:'application/javascript',body:galleryJs})
      if(path==='/assets/questionnaire-person.js')return route.fulfill({contentType:'application/javascript',body:personJs})
      if(path==='/assets/questionnaire-person.css')return route.fulfill({contentType:'text/css',body:personCss})
      if(path==='/course-assets/masterclass/article-components.js')return route.fulfill({contentType:'application/javascript',body:sliderJs})
      if(path.endsWith('.css'))return route.fulfill({contentType:'text/css',body:''})
      if(path==='/api/account-auth/session'){requests.session++;return route.fulfill({json:{authenticated:true,email:account.email}})}
      if(path==='/api/account-auth/account'){
        requests.account++
        if(delays.auth)await delays.auth.promise
        if(delays.loginRequired&&requests.account===1)return route.fulfill({status:401,json:{detail:'Требуется вход'}})
        return route.fulfill({json:delays.account||account})
      }
      if(path==='/api/account-auth/login')return route.fulfill({json:{ok:true,email:account.email,expires_at:'2026-10-19T00:00:00Z'}})
      if(path==='/api/apps/dqs'){
        const payload={ok:true,email:account.email,startDate:'2026-09-01',needsStartDate:false,days:[]},callback=url.searchParams.get('callback')
        return callback?route.fulfill({contentType:'application/javascript; charset=utf-8',body:callback+'('+JSON.stringify(payload)+')'}):route.fulfill({json:payload})
      }
      if(path==='/api/apps/strength')return route.fulfill({json:{ok:true,user:{user_id:'preview',email:account.email,display_name:'Предпросмотр'},workout:{workout_types:[],exercise_catalog:[],sessions:[],session_exercises:[],sets:[]}}})
      if(path==='/api/masterclass/account-offers'){if(delays.offers)await delays.offers.promise;return route.fulfill({json:{focusable_product_codes:['calories']}})}
      if(path==='/api/masterclass/course/manifest')return route.fulfill({json:delays.manifest||manifest})
      if(path==='/api/masterclass/course')return route.fulfill({json:delays.progress||progress})
      if(/\/steps\/\d+\/complete$/.test(path)){
        const index=Number(path.match(/\/steps\/(\d+)\/complete$/)[1])
        if(path.includes('/days/1/')&&index>questionnaireStepIndex&&!completedSteps.has(questionnaireStepIndex))return route.fulfill({status:409,json:{detail:{reason:'previous_step_not_completed'}}})
        completedSteps.add(index);requests.completed++;
        const updated=structuredClone(delays.progress||progress)
        updated.days[0].completed_steps=[...completedSteps]
        return route.fulfill({json:updated})
      }
      if(path.endsWith('/task/open')){
        requests.taskOpened=(requests.taskOpened||0)+1
        if(!completedSteps.has(questionnaireStepIndex))return route.fulfill({status:409,json:{detail:{reason:'materials_not_completed'}}})
        const updated=structuredClone(delays.progress||progress)
        updated.days[0].completed_steps=[...completedSteps]
        updated.days[0].task_opened=true
        return route.fulfill({json:updated})
      }
      if(path==='/api/masterclass/course/materials'){
        const id=url.searchParams.get('step_id')
        if(id){requests.step++;if(delays.article)await delays.article.promise;return route.fulfill({json:{materials:id==='day-04-dqs'?{}:{[id]:{html:'<p>Готовое содержимое выбранной статьи.</p><img class="article-inline-image" src="https://cdn.example.test/diagram.svg" alt="Проверка обычного изображения">',word_count:5,version:1}}}})}
        requests.corpus++;if(delays.corpus)await delays.corpus.promise;return route.fulfill({json:{materials:{}}})
      }
      if(path.includes('/questionnaires/')){
        if(path.endsWith('/answer')){
          requests.answers.push(route.request().postDataJSON())
          if(delays.answerSave&&requests.answers.length===1)await delays.answerSave.promise
          return route.fulfill({status:delays.failAnswer?500:200,json:delays.failAnswer?{detail:'Save failed'}:{ok:true}})
        }
        if(path.endsWith('/submit')){
          requests.submitted++
          if(delays.questionnaireSubmit)await delays.questionnaireSubmit.promise
          const courseStepCompleted=delays.questionnaireCourseStepCompleted!==false
          if(courseStepCompleted)completedSteps.add(questionnaireStepIndex)
          return route.fulfill({json:{ok:true,messenger_link_status:'queued',course_step_completed:courseStepCompleted}})
        }
        if(delays.questionnaire)await delays.questionnaire.promise
        return route.fulfill({json:{questions:delays.questions||[],answers:[],copy:delays.questionnaireCopy,personFields:delays.personFields||[],personParameters:delays.personParameters||{}}})
      }
      if(path.includes('/course/content/')){if(delays.asset)await delays.asset.promise;return route.fulfill({contentType:'text/plain; charset=utf-8',body:'## Инструкция DQS\n\nГотовое описание приложения.'})}
      if(path==='/diagram.svg')return route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="600"><rect width="1200" height="600" fill="#eaf8ff"/><rect x="50" y="50" width="1100" height="500" fill="#27aff5"/></svg>'})
      if(path.startsWith('/api/'))return route.fulfill({json:{ok:true}})
      return route.fulfill({contentType:'application/javascript',body:''})
    })
    await native.goto(origin+'/lk'+query,{waitUntil:'domcontentloaded'})
    return {native,requests,faults}
  }
  const loginFlow=await nativePage('',{loginRequired:true})
  await loginFlow.native.locator('#login-form').waitFor({state:'visible'})
  await loginFlow.native.locator('[name="email"]').fill(account.email)
  await loginFlow.native.locator('[name="password"]').fill('correct-horse-battery-staple')
  await loginFlow.native.getByRole('button',{name:'Войти'}).click()
  await loginFlow.native.locator('.account-card').first().waitFor({state:'visible'})
  assert.equal(loginFlow.requests.account,2,'Login must reload the complete account payload before rendering the dashboard')
  assert.equal(await loginFlow.native.getByRole('heading',{name:'Мастер-класс',exact:true}).isVisible(),true)
  assert.deepEqual(loginFlow.faults,[])
  await loginFlow.native.close()

  const auth=barrier(), offers=barrier(), prefetched=barrier(), fontCss=barrier(), fontFile=barrier()
  const dashboard=await nativePage('',{auth,offers,html:prefetched,fontCss,fontFile})
  await dashboard.native.locator('.ed-loading-screen').waitFor()
  assert.equal(await dashboard.native.locator('.ed-loading-stage').textContent(),'Проверка авторизации')
  await prefetched.promise
  assert.equal(await dashboard.native.locator('#account-app').count(),0,'Prefetch must not execute the app before authorization')
  auth.release()
  await waitForReveal(dashboard.native)
  assert.equal(await dashboard.native.locator('.account-card').first().isVisible(),true,'Offers and fonts must not delay the first useful screen')
  await dashboard.native.waitForFunction(()=>document.fonts.status==='loading')
  assert.equal(await dashboard.native.locator('[data-offer-product="calories"]').count(),0)
  offers.release()
  await dashboard.native.locator('[data-offer-product="calories"]').waitFor()
  assert.equal(await dashboard.native.locator('[data-offer-product="calories"]').isEnabled(),true,'Background offer must remain purchasable')
  assert.equal(await dashboard.native.evaluate(()=>Math.max(...loaderCounts)),1,'Native portal and app share one loader')
  assert.deepEqual(dashboard.requests,{account:1,session:0,step:0,corpus:0,answers:[],submitted:0,completed:0})
  assert.deepEqual(dashboard.faults,[])
  fontCss.release();fontFile.release()
  await dashboard.native.locator('[data-offer-product="calories"]').click()
  await dashboard.native.locator('#masterclass-offers-app').waitFor({state:'visible'})
  assert.equal(await dashboard.native.locator('[data-edabalans-focus-product="calories"]').count(),1,'Background Buy must open the requested product')
  assert.equal(await dashboard.native.locator('[data-edabalans-account-offer="true"]').count(),1,'Background Buy must retain account-offer context')
  assert.deepEqual(dashboard.faults,[])
  await dashboard.native.close()

  const maintenanceAccount={...account,courses:[account.courses[0],
    {code:'calories',product_code:'calories',title:'Калорийный курс',owned:false,ready:false,maintenance:true},
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

  // Selection and completion are independent: revisiting a completed day keeps
  // the active card, gold number and completion checkmark at the same time.
  const completedSelectedProgress=structuredClone(progress)
  completedSelectedProgress.current_day=2
  completedSelectedProgress.days[0].completed=true
  completedSelectedProgress.days[0].completed_at=new Date().toISOString()
  const completedSelected=await nativePage('?course_day=2&theme=light',{progress:completedSelectedProgress})
  await completedSelected.native.waitForFunction(()=>!document.querySelector('.ed-loading-screen')&&document.querySelector('#days .day-button[data-day="2"]')?.classList.contains('active'))
  await waitForReveal(completedSelected.native)
  const completedSelectedDay=completedSelected.native.locator('#days .day-button[data-day="1"]')
  assert.equal(await completedSelectedDay.evaluate(element=>element.classList.contains('done')),true,'The earlier day is already completed before revisiting it')
  assert.equal(await completedSelectedDay.evaluate(element=>element.classList.contains('active')),false,'A completed day is not active before the user selects it')
  assert.equal(await completedSelected.native.locator('#days .day-button.active').count(),1,'Only the currently selected day is active before revisiting')
  const activeUnfinishedDay=completedSelected.native.locator('#days .day-button[data-day="2"]')
  assert.equal(await activeUnfinishedDay.evaluate(element=>element.classList.contains('done')),false,'The current ordinary day starts unfinished')
  assert.doesNotMatch(await activeUnfinishedDay.evaluate(element=>getComputedStyle(element).boxShadow),/rgb\(255, 194, 90\)/,'An active unfinished ordinary day does not acquire the recipe marker')
  await completedSelectedDay.click()
  await completedSelected.native.mouse.move(1200,500)
  for(const width of [360,430,768,1440]){
    await completedSelected.native.setViewportSize({width,height:1000})
    if(width<=900&&!await completedSelected.native.locator('#sidebar').evaluate(element=>element.classList.contains('open')))await completedSelected.native.locator('#menu').click()
    assert.equal(await completedSelected.native.locator('#days .day-button.active').count(),1,'Exactly one day remains active at '+width+'px')
    assert.equal(await completedSelectedDay.evaluate(element=>element.classList.contains('active')),true,'A revisited completed day remains selected at '+width+'px')
    assert.equal(await completedSelectedDay.evaluate(element=>element.classList.contains('done')),true,'The selected day retains its completed state at '+width+'px')
    assert.match(await completedSelectedDay.evaluate(element=>getComputedStyle(element).backgroundColor),/^rgba\(17, 142, 216, 0\.(27|32)\)$/,'The selected completed day keeps the active or active-hover card background at '+width+'px')
    const selectedNumberBackground=await completedSelectedDay.locator('.day-number').evaluate(element=>getComputedStyle(element).backgroundImage)
    assert.match(selectedNumberBackground,/linear-gradient\(/,'The selected completed day keeps a gradient number at '+width+'px')
    assert.match(selectedNumberBackground,/rgb\(255, 194, 90\)/,'The selected completed day keeps the agreed gold start color at '+width+'px')
    assert.match(selectedNumberBackground,/rgb\(243, 154, 47\)/,'The selected completed day keeps the agreed gold end color at '+width+'px')
    assert.doesNotMatch(await completedSelectedDay.evaluate(element=>getComputedStyle(element).boxShadow),/rgb\(255, 194, 90\)/,'A selected ordinary day does not acquire the recipe marker at '+width+'px')
    const recipeDay=completedSelected.native.locator('#days .day-button.recipe').first()
    assert.equal(await recipeDay.count()>0,true,'The course exposes a recipe day at '+width+'px')
    assert.equal(await recipeDay.evaluate(element=>element.classList.contains('active')),false,'The recipe day starts non-selected at '+width+'px')
    await completedSelected.native.waitForFunction(()=>{
      const recipe=document.querySelector('#days .day-button.recipe:not(.active)')
      return recipe?.isConnected&&getComputedStyle(recipe).boxShadow.includes('rgb(255, 194, 90)')
    })
    assert.match(await recipeDay.evaluate(element=>getComputedStyle(element).boxShadow),/rgb\(255, 194, 90\)/,'A recipe day keeps its permanent gold marker at '+width+'px')
    assert.equal(await completedSelectedDay.locator('.day-state').evaluate(element=>getComputedStyle(element,'::after').content),'"✓"','The selected completed day keeps its checkmark at '+width+'px')
    if(process.env.QA_OUT){
      await mkdir(process.env.QA_OUT,{recursive:true})
      await completedSelected.native.screenshot({path:process.env.QA_OUT+'/course-completed-selected-day-'+width+'.png'})
    }
  }
  await completedSelected.native.setViewportSize({width:1440,height:1000})
  await completedSelected.native.locator('#days .day-button[data-day="1"]').hover()
  assert.doesNotMatch(await completedSelected.native.locator('#days .day-button[data-day="1"]').evaluate(element=>getComputedStyle(element).boxShadow),/rgb\(255, 194, 90\)/,'Hover does not add the recipe marker to an ordinary selected day')
  await completedSelected.native.locator('#days .day-button.recipe').first().hover()
  await completedSelected.native.waitForFunction(()=>{
    const recipe=document.querySelector('#days .day-button.recipe:hover')
    return recipe?.isConnected&&getComputedStyle(recipe).boxShadow.includes('rgb(255, 194, 90)')
  })
  assert.deepEqual(completedSelected.faults,[])
  await completedSelected.native.close()

  const ordinaryMaterial=await nativePage('?course_day=1&course_material=day-01-article-02&theme=light',{progress})
  await ordinaryMaterial.native.waitForFunction(()=>!document.querySelector('.ed-loading-screen')&&document.querySelector('#days .day-button[data-day="1"]')?.classList.contains('current-material'))
  const ordinaryMaterialDay=ordinaryMaterial.native.locator('#days .day-button[data-day="1"]')
  assert.equal(await ordinaryMaterialDay.evaluate(element=>element.classList.contains('recipe')),false,'The open ordinary material remains non-recipe')
  assert.doesNotMatch(await ordinaryMaterialDay.evaluate(element=>getComputedStyle(element).boxShadow),/rgb\(255, 194, 90\)/,'An open material does not add the recipe marker to an ordinary day')
  assert.deepEqual(ordinaryMaterial.faults,[])
  await ordinaryMaterial.native.close()

  const recipeIncompleteProgress=structuredClone(progress)
  Object.assign(recipeIncompleteProgress.days[5],{opened:true,can_open:true,completed:false,completed_at:null})
  const recipeIncomplete=await nativePage('?course_day=6&theme=light',{progress:recipeIncompleteProgress})
  await recipeIncomplete.native.waitForFunction(()=>!document.querySelector('.ed-loading-screen')&&document.querySelector('#days .day-button[data-day="6"]')?.classList.contains('active'))
  await waitForReveal(recipeIncomplete.native)
  const activeRecipeDay=recipeIncomplete.native.locator('#days .day-button[data-day="6"]')
  assert.equal(await activeRecipeDay.evaluate(element=>element.classList.contains('recipe')),true,'The selected recipe day retains its type')
  assert.equal(await activeRecipeDay.evaluate(element=>element.classList.contains('done')),false,'The selected recipe day can be unfinished')
  assert.equal(await activeRecipeDay.evaluate(element=>element.classList.contains('locked')),false,'The selected recipe day is genuinely available')
  assert.match(await activeRecipeDay.evaluate(element=>getComputedStyle(element).boxShadow),/rgb\(255, 194, 90\)/,'An active unfinished recipe day keeps its marker')
  await recipeIncomplete.native.locator('#day .topic-list [data-step="0"]').click()
  await recipeIncomplete.native.waitForFunction(()=>document.querySelector('#days .day-button[data-day="6"]')?.classList.contains('current-material'))
  assert.match(await activeRecipeDay.evaluate(element=>getComputedStyle(element).boxShadow),/rgb\(255, 194, 90\)/,'A recipe day keeps its marker while a material is open')
  assert.deepEqual(recipeIncomplete.faults,[])
  await recipeIncomplete.native.close()

  const recipeCompletedProgress=structuredClone(recipeIncompleteProgress)
  Object.assign(recipeCompletedProgress.days[5],{completed:true,completed_at:new Date().toISOString()})
  const recipeCompleted=await nativePage('?course_day=6&theme=light',{progress:recipeCompletedProgress})
  await recipeCompleted.native.waitForFunction(()=>!document.querySelector('.ed-loading-screen')&&document.querySelector('#days .day-button[data-day="6"]')?.classList.contains('active'))
  await waitForReveal(recipeCompleted.native)
  const completedRecipeDay=recipeCompleted.native.locator('#days .day-button[data-day="6"]')
  assert.equal(await completedRecipeDay.evaluate(element=>element.classList.contains('done')),true,'The selected recipe day is genuinely completed')
  assert.match(await completedRecipeDay.evaluate(element=>getComputedStyle(element).boxShadow),/rgb\(255, 194, 90\)/,'A selected completed recipe day keeps its marker')
  await recipeCompleted.native.locator('#days .day-button[data-day="5"]').click()
  await recipeCompleted.native.waitForFunction(()=>document.querySelector('#days .day-button[data-day="5"]')?.classList.contains('active'))
  await recipeCompleted.native.waitForFunction(()=>{
    const recipe=document.querySelector('#days .day-button[data-day="6"]')
    return recipe?.isConnected&&recipe.classList.contains('recipe')&&getComputedStyle(recipe).boxShadow.includes('rgb(255, 194, 90)')
  })
  assert.equal(await completedRecipeDay.evaluate(element=>element.classList.contains('active')),false,'The completed recipe day becomes non-selected after navigation')
  assert.match(await completedRecipeDay.evaluate(element=>getComputedStyle(element).boxShadow),/rgb\(255, 194, 90\)/,'A non-selected completed recipe day keeps its marker')
  assert.deepEqual(await recipeCompleted.native.locator('#days .day-button.recipe').evaluateAll(elements=>elements.map(element=>Number(element.dataset.day))),[6,7,8,15],'Only the four canonical days retain the recipe marker')
  assert.deepEqual(recipeCompleted.faults,[])
  await recipeCompleted.native.close()

  // Day totals count article reading time and a real displayed video only.
  // Intro copy and zero-minute service steps stay outside the estimate.
  for(const [dayNumber,expectedMinutes] of [[1,28],[2,23],[3,64],[4,64]]){
    const durationPage=await nativePage('?course_day='+dayNumber,{progress:{...progress,current_day:dayNumber}})
    await durationPage.native.waitForFunction(()=>!document.querySelector('.ed-loading-screen')&&document.querySelector('#day .hero h1'))
    await waitForReveal(durationPage.native)
    assert.match(
      await durationPage.native.locator('#day .eyebrow-time').textContent(),
      new RegExp('≈ '+expectedMinutes+' минут'),
      'Day '+dayNumber+' must show its article and displayed-video total',
    )
    const sourceDay=manifest.days[dayNumber-1]
    for(const step of sourceDay.steps.filter(item=>!item.hidden&&item.durationMinutes===0)){
      const index=sourceDay.steps.findIndex(item=>item.id===step.id)
      assert.equal(
        await durationPage.native.locator('#day [data-step="'+index+'"] .topic-meta').count(),
        0,
        step.id+' must not show a zero-minute label',
      )
    }
    assert.deepEqual(durationPage.faults,[])
    await durationPage.native.close()
  }

  const oneMinuteManifest=structuredClone(manifest)
  oneMinuteManifest.days[1].steps[0].durationMinutes=1
  const oneMinutePage=await nativePage('?course_day=2',{manifest:oneMinuteManifest,progress:{...progress,current_day:2}})
  await oneMinutePage.native.waitForFunction(()=>!document.querySelector('.ed-loading-screen')&&document.querySelector('#day .hero h1'))
  await waitForReveal(oneMinutePage.native)
  assert.equal(await oneMinutePage.native.locator('#day [data-step="0"] .topic-meta').textContent(),'≈ 1 минута')
  assert.deepEqual(oneMinutePage.faults,[])
  await oneMinutePage.native.close()

  const displayedVideoManifest=structuredClone(manifest)
  displayedVideoManifest.days[0].media='none'
  displayedVideoManifest.days[0].videoId='https://cdn.example.test/day-one.mp4'
  displayedVideoManifest.days[0].video=7
  const displayedVideoPage=await nativePage('?course_day=1',{manifest:displayedVideoManifest,progress:{...progress,current_day:1}})
  await displayedVideoPage.native.waitForFunction(()=>!document.querySelector('.ed-loading-screen')&&document.querySelector('#day .media.video'))
  await waitForReveal(displayedVideoPage.native)
  assert.match(await displayedVideoPage.native.locator('#day .eyebrow-time').textContent(),/≈ 35 минут/)
  assert.deepEqual(displayedVideoPage.faults,[])
  await displayedVideoPage.native.close()

  // A deep link prefetches the course before mounting it; dashboard entry mounts it
  // before the first course fetch. Both must expose exactly the same visual system.
  const courseSkin = native => native.evaluate(() => {
    const selectors=['.sidebar','.sidebar-account','.course-name','.content','.hero h1','.hero .day-label',
      '.day-button[data-day="2"] .day-number','.day-button[data-day="3"] .day-number',
      '.topic','.topic-index','.assignment','.next-day'];
    const properties=['backgroundColor','backgroundImage','color','fontFamily','fontSize','fontWeight',
      'borderColor','borderRadius','padding','width','maxWidth'];
    return Object.fromEntries(selectors.map(selector=>{
      const element=document.querySelector(selector);
      if(!element) return [selector,null];
      const css=getComputedStyle(element);
      return [selector,Object.fromEntries(properties.map(property=>[property,css[property]]))];
    }));
  });
  for(const theme of ['light','dark'])for(const width of [360,430,619,620,621,768,900,901,1440,1920]){
    const entry={width,progress:{...progress,current_day:3}};
    const deep=await nativePage('?course_day=3&theme='+theme,entry);
    await deep.native.waitForFunction(()=>!document.querySelector('.ed-loading-screen')&&document.querySelector('#day .hero h1'));
    await waitForReveal(deep.native);
    const expected=await courseSkin(deep.native);
    assert(expected['.sidebar']&&expected['.hero h1']&&expected['.topic'],'Compare rendered course blocks, not missing nodes');
    assert.equal(expected['.content'].fontWeight,'400','Course body text must not inherit dashboard font weight');
    assert(expected['.hero .day-label'],'The day designation must be rendered');
    assert.match(expected['.hero .day-label'].backgroundImage,/linear-gradient\(/,'Transparent day text must retain its visible gold gradient');
    assert.match(expected['.hero .day-label'].backgroundImage,/rgb\(255, 194, 90\)/,'Preserve the agreed gold start color');
    assert.match(expected['.hero .day-label'].backgroundImage,/rgb\(243, 154, 47\)/,'Preserve the agreed gold end color');
    const fromDashboard=await nativePage('?theme='+theme,entry);
    await fromDashboard.native.locator('[data-app="masterclass-course"]').waitFor({state:'visible'});
    await fromDashboard.native.locator('[data-app="masterclass-course"]').click();
    await fromDashboard.native.waitForFunction(()=>!document.querySelector('.ed-loading-screen')&&document.querySelector('#day .hero h1'));
    await fromDashboard.native.waitForFunction(()=>document.querySelector('#days .day-button[data-day="3"]')?.classList.contains('active'));
    await waitForReveal(fromDashboard.native);
    assert.deepEqual(await courseSkin(fromDashboard.native),expected,'Direct and dashboard course skin must match at '+theme+' '+width);
    assert.equal(await deep.native.locator('link[href*="/assets/course-visual.css"]').count(),1,'Course has one canonical stylesheet');
    assert.deepEqual(deep.faults,[]);assert.deepEqual(fromDashboard.faults,[]);
    if(process.env.QA_OUT&&[360,430,768,901,1440,1920].includes(width)){
      await deep.native.screenshot({path:process.env.QA_OUT+'/parity-direct-'+theme+'-'+width+'.png'});
      await fromDashboard.native.screenshot({path:process.env.QA_OUT+'/parity-dashboard-'+theme+'-'+width+'.png'});
    }
    await deep.native.close();await fromDashboard.native.close();
  }

  const article=barrier(), corpus=barrier()
  const direct=await nativePage('?course_day=2&course_material=day-02-article-01',{article,corpus})
  await direct.native.waitForFunction(()=>document.querySelector('#article p')?.textContent.includes('Загрузка материала'))
  assert.equal(await direct.native.locator('#masterclass-course-app').isVisible(),false)
  assert.equal(await direct.native.locator('.ed-loading-screen').count(),1,'Portal, account and course must share one loader')
  assert.equal(await direct.native.locator('.ed-loading-screen .ed-loading-stage').count(),1)
  assert.equal(await direct.native.locator('.ed-loading-screen .ed-loading-stage').textContent(),'Загрузка страницы','Nested loading must replace authorization without cycling cosmetic captions')
  article.release()
  await waitForReveal(direct.native)
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
    await direct.native.waitForFunction(expectedWidth=>innerWidth===expectedWidth&&matchMedia('(max-width:620px)').matches,width)
    await direct.native.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))))
    const box=await direct.native.locator('.article-inline-image').boundingBox()
    assert(box.x>=-1&&box.x+box.width<=width+1,'Ordinary image preserves mobile edge-to-edge bounds: '+JSON.stringify({width,box}))
  }
  corpus.release()
  await direct.native.close()

  const mdCopy={title:'Название из программы',leadHtml:'<p>Подводка из MD</p>',button:'Кнопка из MD',noteHtml:'<p>После формы из MD</p>',questions:[{code:'parameters',promptHtml:'<p><strong>Подсказка из MD</strong></p>'}]}
  const mdManifest=structuredClone(manifest)
  const mdStep=mdManifest.days[0].steps.find(step=>step.id==='day-01-questionnaire')
  mdStep.title=mdCopy.title;mdStep.label=mdCopy.title;mdStep.editorialHtml=mdCopy.leadHtml
  const mdQuestions=[{code:'parameters',title:'Вопрос из MD',prompt:'Подсказка из MD',answer:'Прежний ответ'}]
  const mdForm=await nativePage('?course_day=1&course_material=day-01-questionnaire',{manifest:mdManifest,questions:mdQuestions,questionnaireCopy:mdCopy,personFields,personParameters})
  await mdForm.native.locator('#q-fields textarea').waitFor()
  assert.equal(await mdForm.native.locator('#questionnaire-title').textContent(),mdCopy.title)
  assert.equal(await mdForm.native.locator('#q-submit').textContent(),mdCopy.button)
  assert.equal(await mdForm.native.locator('#q-fields strong').textContent(),'Подсказка из MD')
  assert.equal(await mdForm.native.locator('#q-fields textarea').inputValue(),'Прежний ответ')
  assert.equal(await mdForm.native.locator('#q-note').textContent(),'После формы из MD')
  for(const width of [360,430,720,721,768,999,1000,1440,1920]){await mdForm.native.setViewportSize({width,height:900});await capture(mdForm.native,'questionnaire-person-course-'+width,true)}
  await mdForm.native.close()
  mdStep.editorialHtml=''
  const emptyMdForm=await nativePage('?course_day=1&course_material=day-01-questionnaire',{manifest:mdManifest,questions:mdQuestions,questionnaireCopy:{...mdCopy,leadHtml:''}})
  await emptyMdForm.native.locator('#q-fields textarea').waitFor()
  assert.equal(await emptyMdForm.native.locator('#questionnaire-lead').isVisible(),false,'Deleting MD prelude must not resurrect legacy prose')
  await emptyMdForm.native.close()
  const standalone=await browser.newPage()
  let standaloneCopy=mdCopy
  await standalone.route(origin+'/**',route=>{
    const path=new URL(route.request().url()).pathname
    if(path==='/')return route.fulfill({contentType:'text/html; charset=utf-8',body:'<link rel="stylesheet" href="/masterclass.css"><link rel="stylesheet" href="/person.css"><div id="onboarding-questionnaire-app"></div><script>window.EdabalansAppContext={app:"onboarding-questionnaire"};window.EdabalansIdentity={email:"reader@example.test"}</script><script src="/person.js"></script><script src="/questionnaire.js"></script>'})
    if(path==='/person.js')return route.fulfill({contentType:'application/javascript',body:personJs})
    if(path==='/person.css')return route.fulfill({contentType:'text/css',body:personCss})
    if(path==='/masterclass.css')return route.fulfill({contentType:'text/css',body:standaloneCss})
    if(path==='/questionnaire.js')return route.fulfill({contentType:'application/javascript',body:questionnaireJs})
    if(path==='/api/masterclass/questionnaires/onboarding')return route.fulfill({json:{questions:mdQuestions,copy:standaloneCopy,personFields,personParameters}})
    return route.fulfill({contentType:'text/css',body:''})
  })
  await standalone.goto(origin,{waitUntil:'domcontentloaded'})
  await standalone.locator('#mc-submit').waitFor()
  assert.equal(await standalone.locator('h1').textContent(),mdCopy.title)
  assert.equal(await standalone.locator('#mc-submit').textContent(),mdCopy.button)
  assert.equal(await standalone.locator('.mc-question strong').textContent(),'Подсказка из MD')
  assert.equal(await standalone.locator('textarea').inputValue(),'Прежний ответ')
  for(const width of [360,430,720,721,768,999,1000,1440,1920]){await standalone.setViewportSize({width,height:900});await capture(standalone,'questionnaire-person-standalone-'+width,true)}
  standaloneCopy={...mdCopy,leadHtml:''}
  await standalone.reload({waitUntil:'domcontentloaded'})
  await standalone.locator('#mc-submit').waitFor()
  assert.equal(await standalone.locator('.lead').isVisible(),false)
  await standalone.close()
  const questionnaire=barrier()
  const form=await nativePage('?course_day=1&course_material=day-01-questionnaire',{questionnaire})
  await form.native.waitForFunction(()=>document.querySelector('#q-fields')?.textContent.includes('Загружаю вопросы'))
  assert.equal(await form.native.locator('#masterclass-course-app').isVisible(),false)
  questionnaire.release()
  await waitForReveal(form.native)
  assert.equal(await form.native.locator('#questionnaire').isVisible(),true)
  assert.doesNotMatch(await form.native.locator('#q-fields').textContent(),/Загружаю вопросы/)
  assert.deepEqual(form.faults,[])
  await form.native.close()

  // The explicit continuation waits for the atomic questionnaire transaction; final answers win over old autosaves.
  const answerSave=barrier()
  const unanswered=structuredClone(progress)
  const questionnaireIndex=manifest.days[0].steps.findIndex(step=>step.kind==='questionnaire')
  unanswered.days[0].completed_steps=Array.from({length:questionnaireIndex},(_,index)=>index)
  const fastForm=await nativePage('?course_day=1&course_material=day-01-questionnaire',{
    answerSave,progress:unanswered,questions:[{code:'main_request',title:'Главный запрос',prompt:'',answer:''}],
    personFields:[{key:'weight',code:'person_weight',title:'Вес, кг',min:10,max:500,step:0.1}],personParameters:{weight:80},
  })
  await waitForReveal(fastForm.native)
  assert.equal(await fastForm.native.locator('#q-submit').evaluate(el=>getComputedStyle(el).cursor),'pointer')
  await fastForm.native.locator('#q-submit').hover()
  assert.notEqual(await fastForm.native.locator('#q-submit').evaluate(el=>getComputedStyle(el).filter),'none')
  await capture(fastForm.native,'questionnaire-submit-hover')
  await fastForm.native.locator('textarea').fill('Старый ответ')
  await waitUntil(()=>fastForm.requests.answers.length===1)
  await fastForm.native.locator('textarea').evaluate(el=>{window.firstAutosave=el.saveRequest})
  await fastForm.native.locator('textarea').fill('Промежуточный ответ')
  await fastForm.native.waitForFunction(()=>document.querySelector('textarea').saveRequest!==window.firstAutosave)
  await fastForm.native.locator('textarea').fill('Последний ответ')
  assert.equal(await fastForm.native.locator('[data-person-field=weight]').inputValue(),'80')
  await fastForm.native.locator('[data-person-field=weight]').fill('81.5')
  await fastForm.native.locator('#q-submit').click()
  assert.equal(await fastForm.native.locator('#questionnaire').isVisible(),true)
  assert.equal(await fastForm.native.locator('#questionnaire-continue').isDisabled(),true)
  assert.equal(fastForm.requests.submitted,0)
  assert.equal(fastForm.requests.completed,0)
  assert.equal(fastForm.requests.taskOpened||0,0,'Checklist opening must wait for the questionnaire transaction')
  assert.equal(fastForm.requests.answers.filter(item=>item.question_code==='main_request').length,1,'Final snapshot of each field waits until its own old autosave completes')
  answerSave.release()
  await waitUntil(()=>fastForm.requests.submitted===1)
  await fastForm.native.waitForFunction(()=>!document.querySelector('#questionnaire-continue').disabled)
  assert.match(await fastForm.native.locator('#q-status').textContent(),/Можно продолжить/)
  await fastForm.native.locator('#questionnaire-continue').click()
  await fastForm.native.waitForURL('**/*course_material=day-01-offer')
  assert.equal(await fastForm.native.locator('#questionnaire').isVisible(),false)
  assert.equal(await fastForm.native.locator('#inline-app-view').isVisible(),true)
  await fastForm.native.locator('#inline-app-next').click()
  await waitUntil(()=>(fastForm.requests.taskOpened||0)===1)
  await fastForm.native.waitForFunction(()=>!document.querySelector('[data-check]').disabled)
  assert.equal(await fastForm.native.locator('[data-check]').first().isEnabled(),true)
  assert.equal(fastForm.requests.completed,1,'Atomic questionnaire submit must not send a second step-completion request')
  assert.deepEqual(fastForm.requests.answers.filter(item=>item.question_code==='main_request').map(item=>item.answer_text),['Старый ответ','Промежуточный ответ','Последний ответ'])
  assert.equal(fastForm.requests.answers.filter(item=>item.question_code==='person_weight').at(-1).answer_text,'81.5','Submit flushes the latest structured field even with an old answer save in flight')
  assert.equal(fastForm.requests.submitted,1)
  assert.deepEqual(fastForm.faults,[])
  await fastForm.native.close()

  const conflictDialogs=[]
  const conflictForm=await nativePage('?course_day=1&course_material=day-01-questionnaire',{
    progress:unanswered,questionnaireCourseStepCompleted:false,
    questions:[{code:'main_request',title:'Главный запрос',prompt:'',answer:'Ответ'}],
  })
  conflictForm.native.on('dialog',async dialog=>{conflictDialogs.push(dialog.message());await dialog.dismiss()})
  await waitForReveal(conflictForm.native)
  await conflictForm.native.locator('#q-submit').click()
  await conflictForm.native.locator('#day').waitFor({state:'visible'})
  await conflictForm.native.waitForFunction(()=>!location.search.includes('course_material='))
  assert.equal(conflictForm.requests.submitted,1)
  assert.equal(conflictForm.requests.completed,0,'A rejected questionnaire step must cancel optimistic completion of following materials')
  assert.equal(conflictForm.requests.taskOpened||0,0)
  assert.deepEqual(conflictDialogs,[],'Progress conflicts must not expose internal reason codes')
  assert.deepEqual(conflictForm.faults,[])
  await conflictForm.native.close()

  const failedSave=barrier(),saveErrors=[]
  const failedForm=await nativePage('?course_day=1&course_material=day-01-questionnaire',{
    answerSave:failedSave,failAnswer:true,progress:unanswered,questions:[{code:'main_request',title:'Главный запрос',prompt:'',answer:'Ответ'}],
  })
  failedForm.native.on('dialog',async dialog=>{saveErrors.push(dialog.message());await dialog.dismiss()})
  await waitForReveal(failedForm.native)
  await failedForm.native.locator('#q-submit').click()
  assert.equal(await failedForm.native.locator('#questionnaire').isVisible(),true)
  assert.equal(await failedForm.native.locator('#questionnaire-continue').isDisabled(),true)
  failedSave.release()
  await waitUntil(()=>saveErrors.length===1)
  assert.match(saveErrors[0],/Save failed/)
  assert.equal(failedForm.requests.submitted,0)
  assert.equal(failedForm.requests.completed,0)
  await failedForm.native.close()

  const firstArticle=barrier()
  const tutorial=await nativePage('?course_day=1&course_material=day-01-article-tutorial',{article:firstArticle})
  await tutorial.native.waitForFunction(()=>document.querySelector('#article p')?.textContent.includes('Загрузка материала'))
  assert.equal(await tutorial.native.locator('#masterclass-course-app').isVisible(),false)
  firstArticle.release()
  await waitForReveal(tutorial.native)
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
  await waitForReveal(dqs.native)
  assert.match(await dqs.native.locator('#article').textContent(),/Готовое описание приложения/)
  assert.equal(await dqs.native.locator('#count .material-meta-time').count(),0,'A zero-minute application must not show time in the open material header')
  assert.deepEqual(dqs.faults,[])
  await dqs.native.close()

  const special=barrier()
  const offer=await nativePage('?course_day=1&course_material=day-01-offer',{special})
  await offer.native.waitForFunction(()=>document.querySelector('#inline-app-frame'))
  assert.equal(await offer.native.locator('.ed-loading-screen').count(),1)
  assert.equal(await offer.native.locator('.ed-loading-inline').count(),0,'Nested inline app reuses the active fullscreen loader')
  assert.equal(await offer.native.locator('#masterclass-course-app').isVisible(),false)
  special.release()
  await waitForReveal(offer.native)
  // Route restoration resolves before the nested offer mount has painted on
  // some Chromium runs. Wait for the user-visible app, not only its parent
  // loader, before checking the final state.
  await offer.native.locator('#masterclass-offers-app').waitFor({state:'visible'})
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
  await waitForReveal(sessionRetry)
  assert.equal(attempts,2)
  assert.equal(await sessionRetry.locator('#account-app').isVisible(),true)
  await sessionRetry.close()

  // Every registered app uses the same loader, including direct standalone entry.
  const appRoots={account:'account-app','masterclass-course':'masterclass-course-app','calories-course':'calories-course-app','recipes-course':'recipes-course-app','masterclass-sales':'masterclass-sales-app',dqs:'dqs-app',strength:'strength-app',metabolism:'metabolism-app','onboarding-questionnaire':'onboarding-questionnaire-app','masterclass-offers':'masterclass-offers-app','recipes-part-1':'recipes-part-1-app','recipes-part-2':'recipes-part-2-app',recipes:'recipes-app','closing-review':'closing-review-app','personal-access':'personal-access-app'}
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
    await app.waitForFunction(()=>document.querySelector('.ed-loading-stage')?.textContent==='Загрузка страницы').catch(async error=>{
      console.error(code,await app.locator('body').innerHTML())
      throw error
    })
    assert.equal(await app.locator('.ed-loading-screen').count(),1,code)
    assert.equal(await app.locator('#'+id).isVisible(),false,code)
    pending.release()
    await waitForReveal(app)
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
  await waitForReveal(nested)
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
    await waitForReveal(publicPage)
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
