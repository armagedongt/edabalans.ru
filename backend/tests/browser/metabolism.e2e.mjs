import assert from 'node:assert/strict'
import http from 'node:http'
import { readFile, mkdir } from 'node:fs/promises'

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE_URL || 'playwright')
const html = await readFile(new URL('../../app/static/apps/metabolism.html', import.meta.url), 'utf8')
const oldHtml = await readFile(new URL('../../app/static/apps/metabolism-old.html', import.meta.url), 'utf8')
const personJs = await readFile(new URL('../../app/static/questionnaire-person.js', import.meta.url), 'utf8')
const seed = {gender:'Женщина',age:35,height:170,weight:80,fat_percent:30,protein:100,steps:6000,active_steps_percent:50,train_week:0,deficit:300,time:30}
let state, puts, conflict = false, putDelay = 0
function reset(variants = {'1': {...seed}, '2': {...seed,steps:10000}, '3': {...seed,steps:10000,train_week:1400}}) {
  state = {ok:true,version:1,activeVariant:1,variants,name:'Тестовый аккаунт',email:'client@example.test',personParameters:{gender:'Мужчина',age:40,height:180,weight:90}}
  puts = []; conflict = false; putDelay = 0
}
reset()
const server = http.createServer(async (req,res) => {
  if (req.url === '/api/apps/metabolism') {
    res.setHeader('Content-Type','application/json')
    if(req.method === 'GET') return res.end(JSON.stringify(state))
    let raw = ''; for await (const chunk of req) raw += chunk
    const body = JSON.parse(raw); puts.push(body)
    await new Promise(resolve => setTimeout(resolve, putDelay))
    if(conflict || body.version !== state.version) {res.statusCode=409;return res.end(JSON.stringify({ok:false,error:'Конфликт версий'}))}
    state = {...state,...body,variants:{...state.variants,...body.variants},version:state.version+1}
    return res.end(JSON.stringify(state))
  }
  res.setHeader('Content-Type','text/html; charset=utf-8'); res.end(req.url==='/metabolism-old'?oldHtml:html)
})
await new Promise(resolve => server.listen(0,'127.0.0.1',resolve))
const url = `http://127.0.0.1:${server.address().port}/metabolism`
const browser = await chromium.launch({headless:true})
const page = await browser.newPage({viewport:{width:1920,height:837}})
const errors=[]; page.on('pageerror', error=>errors.push(error.message))
async function load(){await page.goto(url);await page.getByText('Данные загружены',{exact:true}).waitFor()}
async function saved(){await page.getByText('Изменения сохранены',{exact:true}).waitFor()}
async function capture(name){if(process.env.QA_OUT){await mkdir(process.env.QA_OUT,{recursive:true});await page.screenshot({path:`${process.env.QA_OUT}/${name}.png`,fullPage:true})}}
try {
  await load()
  assert.equal(await page.locator('#mw-weight').inputValue(),'80', 'saved variant wins over questionnaire')
  assert.equal(await page.locator('.mw-person').evaluate(node=>node.open),false)
  assert.equal(await page.getByRole('button',{name:/скриншот/i}).count(),0)
  const desktop = await page.locator('[data-section=nutrition]').boundingBox()
  assert.ok(desktop.y+desktop.height <= 837, `primary screen ends at ${desktop.y+desktop.height}`)
  assert.equal(await page.locator('.mw-energy-bar span').count(),4)
  const widths = await page.locator('.mw-energy-bar span').evaluateAll(nodes=>nodes.map(node=>parseFloat(node.style.width)))
  assert.ok(Math.abs(widths.reduce((a,b)=>a+b,0)-100)<0.001)
  assert.match(await page.locator('[data-main-results]').innerText(),/1\s*833/)
  assert.equal(await page.locator('[data-comparison] tr').count(),8)
  assert.equal(await page.locator('[data-comparison] tr').first().locator('td').count(),4)
  await page.locator('[data-unit]').selectOption('percent')
  await page.locator('#mw-deficit').fill('10')
  await page.locator('#mw-protein').fill('')
  await page.setViewportSize({width:1440,height:837})
  assert.equal(await page.locator('#mw-deficit').inputValue(),'10','incomplete calculation still displays the selected percentage')
  await page.locator('#mw-protein').fill('100')
  assert.match(await page.locator('[data-main-results] .mw-line').last().innerText(),/183 ккал · 10,0%/)
  await saved(); await load()
  assert.equal(await page.locator('[data-unit]').inputValue(),'percent')
  assert.equal(await page.locator('#mw-deficit').inputValue(),'10')
  assert.match(await page.locator('[data-hero]').innerText(),/1\s*650/)
  await page.locator('#mw-steps').fill('12000'); await saved()
  assert.ok(Math.abs(state.variants['1'].deficit-207.026805)<0.001,'percentage saves current equivalent kcal after expenditure changes')
  const archived=await browser.newPage()
  await archived.addInitScript(()=>{window.EdabalansIdentity={source:'native',email:'client@example.test'}})
  await archived.route('https://edabalans.ru/api/apps/metabolism',async route=>{
    const response=await route.fetch({url:url.replace('/metabolism','/api/apps/metabolism')})
    await route.fulfill({response})
  })
  await archived.goto(url+'-old')
  await archived.waitForFunction(()=>document.querySelector('#metabolism-old-app input')!==null)
  await archived.evaluate(()=>window.META.setNumber('deficit','500'))
  const deadline=Date.now()+10000
  while(state.variants['1'].deficit!==500){if(Date.now()>deadline)throw Error('Archived save did not arrive');await page.waitForTimeout(30)}
  assert.equal(state.variants['1']._unit,'kcal','actual archived editor resets saved percentage metadata')
  assert.ok(state.variants['3'],'archived save preserves third variant')
  await archived.close();await load()
  assert.equal(await page.locator('[data-unit]').inputValue(),'kcal')
  assert.equal(await page.locator('#mw-deficit').inputValue(),'500')
  await page.locator('.mw-person').evaluate(node=>node.open=true)
  await page.locator('#mw-weight').fill('81');await saved()
  assert.ok(Object.values(state.variants).every(v=>v.weight===81),'personal edit propagates to all three persisted variants')
  await page.locator('.mw-person').evaluate(node=>node.open=false)
  await page.locator('[data-unit]').selectOption('kcal');await saved()

  await page.locator('[data-edit-variant="2"]').click()
  await page.locator('[data-name="2"]').fill('Третий план')
  await page.locator('[data-edit-variant="2"]').click(); await saved()
  await page.locator('[data-variant="2"]').click(); await saved()
  await load()
  assert.equal(state.activeVariant,3)
  assert.equal(await page.locator('[data-variant-name="2"]').innerText(),'Третий план')
  assert.equal(await page.locator('#mw-train_week').inputValue(),'1400')

  putDelay=750
  await page.locator('#mw-steps').fill('11000')
  await page.waitForFunction(()=>document.querySelector('.mw-save-status').textContent.includes('Сохраняю'))
  while(puts.at(-1)?.variants?.['3']?.steps!==11000) await page.waitForTimeout(30)
  await page.locator('#mw-steps').fill('12000'); await saved()
  assert.equal(state.variants['3'].steps,12000,'edit during in-flight save survives')
  assert.equal(puts.at(-1).version,state.version-1)
  putDelay=0; conflict=true
  const prior=state.variants['3'].steps
  await page.locator('#mw-steps').fill('13000')
  await page.getByText(/Данные изменены в другом окне/).waitFor()
  assert.equal(state.variants['3'].steps,prior,'409 never overwrites other window')
  const count=puts.length
  await page.locator('#mw-steps').fill('14000'); await page.waitForTimeout(600)
  assert.equal(puts.length,count,'blocked save does not loop')

  reset({}); await load()
  assert.equal(await page.locator('#mw-weight').inputValue(),'90','own questionnaire prefills empty field')
  assert.equal(await page.locator('#mw-steps').inputValue(),'','no client demo data')
  assert.equal(await page.locator('.mw-energy-bar').count(),0)
  assert.equal(await page.locator('.mw-person').evaluate(node=>node.open),true,'missing fat keeps personal editor open')
  assert.equal(puts.length,0,'loading profile does not silently write variants')
  for(const width of [360,430,720,721,768,999,1000,1440,1920]){await page.setViewportSize({width,height:900});await capture(`missing-person-${width}`)}

  reset(); await load()
  for(const width of [360,430,720,721,768,999,1000,1440,1920]) {
    await page.setViewportSize({width,height:900})
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`overflow at ${width}`)
    await page.locator('[data-help="balance"]').first().click()
    assert.equal(await page.locator('.mw-help-dialog').evaluate(node=>node.open),true)
    await capture(`help-${width}`)
    await page.keyboard.press('Escape')
    if(width<=720) {
      await page.locator('[data-tab=compare]').click()
      assert.ok(await page.locator('[data-section=compare]').isVisible())
      assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`comparison overflow at ${width}`)
      await page.locator('.mw-extra').evaluate(node=>node.open=true)
      await capture(`comparison-technical-${width}`)
      await page.locator('[data-tab=inputs]').click()
    }
    await page.locator('.mw-person').evaluate(node=>node.open=true)
    await page.locator('.mw-food-settings').evaluate(node=>node.open=true)
    await page.locator('.mw-extra').evaluate(node=>node.open=true)
    await capture(`expanded-${width}`)
    await page.locator('.mw-person').evaluate(node=>node.open=false)
    await page.locator('.mw-food-settings').evaluate(node=>node.open=false)
    await page.locator('.mw-extra').evaluate(node=>node.open=false)
    await page.locator('[data-edit-variant="0"]').click()
    await capture(`inline-name-${width}`)
    await page.locator('[data-edit-variant="0"]').click()
  }

  // Shared renderer uses typed controls and stable answer codes, not HTML from answers.
  await page.evaluate(()=>document.body.innerHTML='<div id="fields"></div>')
  await page.addScriptTag({content:personJs})
  await page.evaluate(()=>window.EdabalansQuestionnairePerson.render(document.querySelector('#fields'),{
    personFields:[{key:'gender',code:'person_gender',title:'Пол',options:['Женщина','Мужчина']},{key:'weight',code:'person_weight',title:'Вес',min:10,max:500,step:0.1}],
    personParameters:{gender:'Женщина',weight:80.5}
  }))
  assert.equal(await page.locator('[data-code=person_gender]').inputValue(),'Женщина')
  assert.equal(await page.locator('[data-code=person_weight]').inputValue(),'80.5')
  assert.equal(await page.locator('[data-code=person_weight]').getAttribute('step'),'0.1')
  assert.deepEqual(errors,[])
  console.log('Metabolism browser checks passed: layout, 3 variants, autosave, conflict, prefill, help and typed fields')
} finally {await browser.close();await new Promise(resolve=>server.close(resolve))}
