import assert from 'node:assert/strict';
import {readFile,mkdir,writeFile} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
import path from 'node:path';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE_URL || (process.env.CODEX_NODE_MODULES?pathToFileURL(path.join(process.env.CODEX_NODE_MODULES,'playwright/index.mjs')).href:'playwright'));
const base=process.env.QA_BASE_URL || 'http://127.0.0.1:8823';
assert.equal(new URL(base).hostname,'127.0.0.1');
const out=process.env.QA_OUT || process.env.STRENGTH_EVIDENCE_DIR;assert(out,'Set QA_OUT for browser evidence');await mkdir(out,{recursive:true});
const staticRoot=new URL('../../app/static/',import.meta.url),appHtml=await readFile(new URL('apps/strength.html',staticRoot),'utf8');
const guide=JSON.parse(await readFile(new URL('../../app/strength_exercise_guides.json',import.meta.url),'utf8'));
function fixture(manyExercises=false){
 const exercises=guide.slice(0,manyExercises?9:2).map((item,index)=>({exercise_id:item.code,exercise_name:item.name,short_name:item.short_name,full_name:item.full_name,source:'base',active:true,sort_order:index+1,guide:item.guide,media_url:item.media_url}));
 const sessions=[{session_id:'one',workout_type:1,session_number:1,date:'2026-10-01'},{session_id:'two',workout_type:2,session_number:2,date:'2026-10-02'},...Array.from({length:6},(_,i)=>({session_id:'middle-'+i,workout_type:1,session_number:i+3,date:'2026-10-03'})),{session_id:'three',workout_type:1,session_number:9,date:''}];
 const session_exercises=sessions.flatMap(s=>exercises.filter((_,index)=>!(s.session_id==='two'&&index===1)).map(e=>({session_id:s.session_id,exercise_id:e.exercise_id,exercise_name:e.exercise_name,sort_order:e.sort_order,note:''})));
 const sets=sessions.flatMap((s,si)=>exercises.flatMap(e=>Array.from({length:s.session_id==='two'?5:s.session_id==='three'?2:3},(_,i)=>({session_id:s.session_id,exercise_id:e.exercise_id,set_number:i+1,plan_weight:s.session_id==='three'?'':60,plan_reps:s.session_id==='three'?'':8,fact_weight:si===0?60:'',fact_reps:si===0?8:'',rpe:si===0?9:'',completed:si===0}))));
 return {version:1,workout_types:[1,2,3].map(n=>({workout_type:n,title:'Шаблон '+n,active:true,sort_order:n})),exercise_catalog:exercises,sessions,session_exercises,sets};
}
const browser=await chromium.launch();
const errors=[];let rows=[];
async function open(width,managed=false,longNotes=false,manyExercises=false,sameNames=false,shortHistory=false){
 const context=await browser.newContext({viewport:{width,height:900},reducedMotion:'reduce',hasTouch:width<=700});
 const page=await context.newPage(),state=fixture(manyExercises),writes=[],telegramWrites=[];let active=0,overlap=false,failTemplate=false;
 if(sameNames)state.exercise_catalog.forEach(e=>{e.exercise_name=e.short_name='Одинаковое имя <img src=x onerror=alert(1)>';});
 if(longNotes)state.session_exercises[0].note='Примечание с несколькими строками для проверки сохранения позиции при изменении подходов. '.repeat(14);
 if(shortHistory){state.sets=state.sets.filter(set=>set.set_number<=2);state.session_exercises=state.session_exercises.filter(ex=>!(ex.session_id==='one'&&ex.exercise_id===guide[0].code));state.sets=state.sets.filter(set=>!(set.session_id==='one'&&set.exercise_id===guide[0].code));}
 const catalogs=new Map([1,2,3].map(id=>[id,structuredClone(state.exercise_catalog)]));let catalogGate=null;
 page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/*',async route=>{
  const url=new URL(route.request().url());if(url.hostname!=='127.0.0.1')return route.abort();
  if(url.pathname==='/strength-local'||url.pathname==='/strength-admin-local'){
    const managed=url.pathname.includes('admin');
    return route.fulfill({contentType:'text/html',body:'<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{margin:0;background:#f5f5f7}</style><body>'+(managed?'<div class="preview-account">Управляемый аккаунт</div>':'')+'<script>window.EdabalansIdentity={source:"native",email:"example@example.test"};window.EdabalansAppContext='+JSON.stringify(managed?{mode:'admin',targetUserId:'fixture',accountUrl:'/lk'}:{accountUrl:'/lk'})+';</script>'+appHtml+'</body></html>'});
  }
  if(url.pathname==='/admin/api/apps/strength/telegram'){
    telegramWrites.push(JSON.parse(route.request().postData()));
    return route.fulfill({contentType:'application/json',body:JSON.stringify({ok:true})});
  }
  if(url.pathname!=='/api/apps/strength'){
    const asset=new URL(url.pathname.replace(/^\/(assets\/)?/,''),staticRoot);
    if(!asset.href.startsWith(staticRoot.href))return route.abort();
    try{return route.fulfill({contentType:({'.css':'text/css','.js':'text/javascript','.woff2':'font/woff2','.gif':'image/gif','.png':'image/png','.svg':'image/svg+xml'})[path.extname(asset.pathname)] || 'application/octet-stream',body:await readFile(asset)});}catch{return route.abort();}
  }
  const data=route.request().method()==='POST'?JSON.parse(route.request().postData()):Object.fromEntries(url.searchParams);
  let reply={ok:true,user:{user_id:'fixture',email:'example@example.test',display_name:''},version:state.version};
  if(data.action==='getWorkout')reply.workout={...structuredClone(state),exercise_catalog:structuredClone(catalogs.get(Number(data.type)) || state.exercise_catalog.map(e=>({...e,active:false})))};
  if(route.request().method()==='POST'){
   active++;if(active>1)overlap=true;
   writes.push(data);if(data.action==='saveExerciseCatalog'&&catalogGate){const gate=catalogGate;catalogGate=null;await gate;}await new Promise(resolve=>setTimeout(resolve,30));
   if(failTemplate && data.action==='saveWorkoutTypes'){failTemplate=false;reply={ok:false,error:'NETWORK_TEMPORARY'};}
   else if(data.action==='saveExerciseCatalog'&&!state.workout_types.some(t=>Number(t.workout_type)===data.workout_type&&t.active!==false))reply={ok:false,error:'INVALID_WORKOUT_TEMPLATE'};
   else if(data.version!==state.version)reply={ok:false,error:'STRENGTH_STATE_CONFLICT'};
   else{reply.version=++state.version;if(data.action==='saveWorkoutTypes')state.workout_types=data.workout_types;if(data.action==='saveExerciseCatalog')catalogs.set(data.workout_type,data.exercises.map(e=>({...state.exercise_catalog.find(item=>item.exercise_id===e.exercise_id),...e})));if(data.session)reply.session={...data.session,session_number:data.session.session_number || 10};}
   active--;
  }
  await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(reply)});
 });
 await page.goto(base+(managed?'/strength-admin-local':'/strength-local'));
 await page.locator('.st-view-toggle').waitFor();await page.evaluate(()=>document.fonts.ready);
 return {context,page,writes,telegramWrites,getOverlap:()=>overlap,state,holdNextCatalog:()=>{let release;catalogGate=new Promise(resolve=>{release=resolve;});return release;},failNextTemplate:()=>{failTemplate=true;}};
}
async function assertDatesFollowColumns(page){
 await page.waitForFunction(()=>{const dates=document.querySelectorAll('.st-date-cell'),cards=document.querySelector('.st-history-row').querySelectorAll('article');return [...dates].every((e,i)=>Math.abs(e.getBoundingClientRect().left-cards[i].getBoundingClientRect().left)<1);});
}
for(const width of [360,430,700,701,768,1440]){
 const {context,page}=await open(width);
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
 assert.equal(await page.locator('.st-session-sticky .st-view-toggle').count(),1,'view switch belongs to workout toolbar');
 assert.equal(await page.locator('.st-template-composition').count(),0,'composition is inside template management');
 assert.equal(await page.locator('.st-session-toolbar .st-toolbar-delete').count(),0,'delete belongs to each workout date');
 assert.equal(await page.locator('.st-date-cell').last().locator('.st-journal-date-text').getAttribute('placeholder'),'дд.мм.гггг');
 const dateBoxes=await page.locator('.st-date-cell').last().evaluate(e=>{const n=e.querySelector('.st-session-number').getBoundingClientRect(),d=e.querySelector('input').getBoundingClientRect();return {numberRight:n.right,dateLeft:d.left};});
 assert(dateBoxes.numberRight<dateBoxes.dateLeft,'workout number precedes date');
 assert.equal(await page.locator('.st-history-row').first().locator('.st-history-column').count(),8,'all template history is rendered, beyond three records');
 if(width===1440)assert(await page.locator('.st-history-row').first().locator('article').evaluateAll(es=>es.filter(e=>{let r=e.getBoundingClientRect();return r.right>0&&r.left<innerWidth;}).length)>3,'wide display shows more than three history records');
 const columns=await page.locator('.st-history-row').first().locator('.st-modern-editor').evaluateAll(es=>es.map(e=>e.getBoundingClientRect().height));
 assert(Math.abs(columns[0]-columns[1])<1,'same exercise rows retain max-set height');
 const inputs=await page.locator('.st-grid-set').last().locator('input').evaluateAll(es=>es.map(e=>({field:e.dataset.field,w:e.getBoundingClientRect().width,font:getComputedStyle(e).fontSize,placeholder:getComputedStyle(e,'::placeholder').fontSize})));
 assert(inputs[0].w>inputs[1].w);assert.equal(inputs[0].placeholder,inputs[1].placeholder);
 const align=await page.evaluate(()=>{const d=document.querySelectorAll('.st-date-cell'),c=document.querySelector('.st-history-row').querySelectorAll('article');return [...d].map((e,i)=>Math.abs(e.getBoundingClientRect().left-c[i].getBoundingClientRect().left));});
 assert(align.every(x=>x<1),'each sticky date is aligned to its workout column');
 await page.setViewportSize({width,height:400});await page.evaluate(()=>scrollTo(0,200));
 assert(Math.abs((await page.locator('.st-session-sticky').boundingBox()).y)<1,'both toolbar and dates stay pinned');
 await page.evaluate(()=>scrollTo(0,0));await page.setViewportSize({width,height:900});
 await page.screenshot({path:`${out}/training-${width}.png`});
 if(width<=700 && await page.locator('[data-axis=training]').evaluate(e=>e.scrollWidth>e.clientWidth)){
   const touch=await context.newCDPSession(page),axis=page.locator('[data-axis=training]');
   const box=await axis.boundingBox(),start=await axis.evaluate(e=>e.scrollLeft),y=Math.min(box.y+50,800);
   await touch.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x:90,y}]});
   for(const x of [110,140,180,230,280]){await touch.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x,y}]});await page.waitForTimeout(20);}
   await touch.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});await page.waitForTimeout(150);
   assert(await axis.evaluate(e=>e.scrollLeft)<start,'native touch swipe moves the history at '+width);await assertDatesFollowColumns(page);
 }
 if(width>700){const bar=page.locator('.st-history-bottom-bar');assert(await bar.isVisible());await bar.evaluate(e=>{e.scrollLeft=0;});await page.waitForTimeout(50);assert.equal(await page.locator('[data-axis=training]').evaluate(e=>e.scrollLeft),0);await assertDatesFollowColumns(page);}
 const inactiveEye=await page.locator('.st-view-toggle').evaluate(e=>getComputedStyle(e).backgroundColor);
 await page.locator('.st-view-toggle').click();
 assert.equal(await page.locator('.st-view-toggle').getAttribute('aria-pressed'),'true');
 assert.notEqual(await page.locator('.st-view-toggle').evaluate(e=>getComputedStyle(e).backgroundColor),inactiveEye,'eye changes appearance with view');
 assert.equal(await page.locator('.st-date-viewport').count(),0,'exercise view moves dates into individual cards');
 assert.equal(await page.locator('.st-session-toolbar .st-template-row').count(),1,'templates remain in sticky controls in both views');
 assert.equal(await page.locator('[data-axis]').count(),1,'exercise histories have one shared scrolling surface');
 assert.equal(await page.locator('.st-history-row').first().locator('.st-history-column').count(),9,'all exercise history includes other templates beyond three records');
 assert.equal(await page.locator('.st-history-row').nth(1).locator('.st-history-column').count(),8,'skipped exercises leave no gap inside the compact history');
 const before=await page.locator('.st-history-row').nth(1).locator('article').first().evaluate(e=>e.getBoundingClientRect().x);
 const offset=await page.locator('[data-axis]').evaluate(e=>e.scrollLeft);
 await page.locator('[data-axis]').evaluate(e=>e.scrollLeft=0);await page.waitForTimeout(50);
 const after=await page.locator('.st-history-row').nth(1).locator('article').first().evaluate(e=>e.getBoundingClientRect().x);
 assert(Math.abs((after-before)-offset)<1,'all exercise rows move together');
 assert.equal(await page.getByRole('button',{name:'Удалить тренировку',exact:true}).count(),0);
 await page.screenshot({path:`${out}/exercise-${width}.png`});
 await page.getByRole('button',{name:'Статистика',exact:true}).click();
 assert.equal(await page.locator('.st-top,.st-types,.st-session-toolbar').count(),0);
 assert(await page.getByRole('button',{name:'Вернуться к тренировкам'}).isVisible());
 await page.screenshot({path:`${out}/statistics-${width}.png`});
 rows.push({width,columns,inputs});await context.close();
}
const run=await open(1440),p=run.page;
let last=p.locator('.st-history-row').first().locator('.st-history-column').last();
await last.locator('input[data-field=factWeight]').first().click();
assert(await p.locator('.st-modal-bg').isVisible(),'fact without date is blocked');
await p.getByRole('button',{name:'Понятно',exact:true}).click();
const beforeInvalidDate=run.writes.length;
await p.locator('.st-date-cell').last().locator('.st-journal-date-text').fill('31.02.2026');
await p.locator('.st-date-cell').last().locator('.st-journal-date-text').press('Tab');await p.waitForTimeout(100);
assert.equal(run.writes.length,beforeInvalidDate,'impossible date is not saved');
assert.equal(await p.locator('.st-date-cell').last().locator('.st-journal-date-text').evaluate(e=>e.checkValidity()),false);
await p.locator('.st-date-cell').last().locator('.st-journal-date-text').fill('21.10.2026');await p.locator('.st-date-cell').last().locator('.st-journal-date-text').press('Tab');
await p.waitForTimeout(550);
assert.equal(run.writes.filter(w=>w.action==='saveSession').at(-1).session.date,'2026-10-21','Russian date is persisted as ISO');
await p.locator('.st-date-cell').last().locator('.st-date-picker').fill('2026-10-22');await p.waitForTimeout(550);
assert.equal(await p.locator('.st-date-cell').last().locator('.st-journal-date-text').inputValue(),'22.10.2026','native calendar updates Russian display');
assert.equal(run.writes.filter(w=>w.action==='saveSession').at(-1).session.date,'2026-10-22');
const source=p.locator('.st-history-row').first().locator('.st-history-column').first();
const originalWrites=run.writes.length;
await source.getByRole('button',{name:'Скопировать план',exact:true}).click();
assert.equal(run.writes.length,originalWrites,'copy has no persistence side effect');
assert.equal(await p.locator('.st-history-row').first().locator('.st-history-column').count(),8,'copy creates no session');
assert.equal(await p.locator('.st-history-row').nth(1).getByRole('button',{name:'Вставить',exact:true}).count(),0,'clipboard cannot paste to different exercise');
last=p.locator('.st-history-row').first().locator('.st-history-column').last();
await last.getByRole('button',{name:'Вставить',exact:true}).click();
assert.equal(await last.locator('input[data-field=planWeight]').first().inputValue(),'60');
assert.equal(await p.getByRole('button',{name:'Вставить',exact:true}).count(),0,'successful paste consumes the exercise clipboard');
await last.getByRole('button',{name:'Заполнить факт по плану',exact:true}).first().click();
assert.equal(await last.locator('input[data-field=factWeight]').first().inputValue(),'60');
assert(await last.locator('.st-set-done.done').first().isVisible());
assert.equal(await last.locator('.st-set-done.done').first().evaluate(e=>{const r=e.getBoundingClientRect();return r.width===r.height&&getComputedStyle(e).borderRadius==='50%';}),true,'completion control is circular');
await last.getByRole('button',{name:'Выполнено',exact:true}).first().click();
assert.equal(await last.locator('input[data-field=factWeight]').first().inputValue(),'','second click clears copied fact');
assert.equal(await last.locator('input[data-field=factReps]').first().inputValue(),'');
await p.waitForTimeout(550);
const clearedSave=run.writes.filter(w=>w.action==='saveSession').at(-1).session.exercises[0].sets[0];
assert.equal(clearedSave.fact_weight,'','cleared fact weight is persisted');
assert.equal(clearedSave.fact_reps,'','cleared repetitions are persisted');
await last.getByRole('button',{name:'Заполнить факт по плану',exact:true}).first().click();
await p.getByRole('button',{name:'Отменить действие',exact:true}).click();
assert.equal(await last.locator('input[data-field=factWeight]').first().inputValue(),'');
const field=last.locator('input[data-field=planWeight]').first();await field.click();await p.waitForTimeout(20);
assert.equal(await field.evaluate(e=>e.selectionStart),2,'numeric cursor at right edge');
await p.getByRole('button',{name:'Управление шаблонами',exact:true}).click();
await p.getByRole('button',{name:'＋ Шаблон',exact:true}).click();
await p.getByRole('textbox',{name:'Название шаблона 4',exact:true}).fill('Дополнительный');await p.getByRole('textbox',{name:'Название шаблона 4',exact:true}).press('Tab');
await p.getByRole('button',{name:'Готово',exact:true}).click();
await p.waitForTimeout(800);assert(await p.getByRole('button',{name:'Дополнительный',exact:true}).isVisible());
const style=await p.locator('.st-type.active').evaluate(e=>({bg:getComputedStyle(e).backgroundColor,color:getComputedStyle(e).color}));
const inactiveStyle=await p.locator('.st-type:not(.active)').first().evaluate(e=>({bg:getComputedStyle(e).backgroundColor,color:getComputedStyle(e).color}));
assert.notDeepEqual(style,inactiveStyle,'selected template is visually distinct');
await p.getByRole('button',{name:'Шаблон 2',exact:true}).click();
assert.equal(await p.getByRole('button',{name:'Шаблон 2',exact:true}).getAttribute('aria-pressed'),'true');
assert.equal(await p.locator('.st-type[aria-pressed="true"]').count(),1);
await p.getByRole('button',{name:'Шаблон 1',exact:true}).click();
assert.equal(run.getOverlap(),false,'autosave and template writes are serialized');
await p.screenshot({path:`out/templates-complete.png`.replace('out',out)});
await run.context.close();
// A historical exercise from another template retains its original session identity.
const history=await open(430),hp=history.page;
await hp.locator('.st-view-toggle').click();
const beforeTemplate=await hp.locator('.st-type.active').innerText();
await hp.locator('.st-history-row').first().locator('[data-session-index="1"] .st-session-number').click();
assert.equal(await hp.locator('.st-type.active').innerText(),beforeTemplate,'historical record number must not switch current template');
assert.equal(await hp.locator('.st-history-row').count(),2,'current template composition is retained');
let foreign=hp.locator('.st-history-row').first().locator('[data-session-index="1"]');
await foreign.locator('input[data-field=planWeight]').first().click();await hp.waitForTimeout(30);
await foreign.locator('input[data-field=planWeight]').first().fill('75');await foreign.locator('input[data-field=planWeight]').first().press('Tab');
await hp.waitForTimeout(550);
let foreignSave=history.writes.filter(w=>w.action==='saveSession').at(-1);
assert.equal(foreignSave.session.session_id,'two');assert.equal(foreignSave.workout_type,2);assert.equal(foreignSave.session.exercises[0].sets[0].plan_weight,75);
await hp.getByRole('button',{name:'Отменить действие',exact:true}).click();await hp.waitForTimeout(550);
assert.equal(await foreign.locator('input[data-field=planWeight]').first().inputValue(),'60');
await hp.locator('.st-view-toggle').click();await hp.getByRole('button',{name:'Новая тренировка',exact:true}).click();await hp.waitForTimeout(100);
const newest=hp.locator('.st-history-row').first().locator('article').last();
assert.equal(await newest.evaluate(e=>{let r=e.getBoundingClientRect();return r.left>=0&&r.right<=innerWidth;}),true,'created workout is brought into view');
const confirmed=new Promise(resolve=>hp.once('dialog',async d=>{resolve(d.message());await d.dismiss();}));
await hp.getByRole('button',{name:'Удалить тренировку №10',exact:true}).click();assert.match(await confirmed,/№10/,'delete targets newly created workout');
// Delete the explicitly named older column, not the currently selected newest session.
const olderDelete=hp.getByRole('button',{name:'Удалить тренировку №1',exact:true});
const removed=new Promise(resolve=>hp.once('dialog',async d=>{resolve(d.message());await d.accept();}));
await olderDelete.click();assert.match(await removed,/№1 .*01\.10\.2026/);
await hp.waitForTimeout(550);
assert.equal(history.writes.filter(w=>w.action==='saveSession'&&w.session.deleted).at(-1).session.session_id,'one');
assert.equal(await hp.locator('.st-date-cell[data-session-index] .st-toolbar-delete').count(),8,'one button per remaining workout date');
await history.context.close();
// RPE choices start at five and retain a uniform foreground through selection.
const scale=await open(430),sp=scale.page;
await sp.setViewportSize({width:430,height:500});
const rpeSource=sp.locator('.st-history-row').first().locator('article').first().locator('.st-rpe-button').last();
await rpeSource.click();
assert.deepEqual(await sp.locator('.st-rpe-option').allTextContents(),['5','6','7','8','9','×']);
const foregrounds=await sp.locator('.st-rpe-option').evaluateAll(es=>es.map(e=>getComputedStyle(e).color));
assert.equal(new Set(foregrounds).size,1);
const rpeBox=await rpeSource.boundingBox(),pickerBox=await sp.locator('.st-rpe-floating').boundingBox();
assert(pickerBox.y<rpeBox.y&&rpeBox.y-(pickerBox.y+pickerBox.height)<8,'six-choice picker remains next to the source above it');
await sp.getByRole('button',{name:'RPE 5',exact:true}).click();await sp.waitForTimeout(550);
assert.equal(scale.writes.filter(w=>w.action==='saveSession').at(-1).session.exercises[0].sets.at(-1).rpe,5);
await scale.context.close();
// Re-rendering rows with expanded notes must not move the viewport on +/- sets.
const stable=await open(430,false,true),vp=stable.page;await vp.setViewportSize({width:430,height:400});
const target=vp.locator('.st-history-row').nth(1).locator('article').last();
const add=target.getByRole('button',{name:'Добавить подход',exact:true});await add.scrollIntoViewIfNeeded();
const initialSets=await target.locator('.st-grid-set').count();
await vp.evaluate(()=>scrollBy(0,-110));
const y=await vp.evaluate(()=>scrollY),x=await vp.locator('[data-axis]').evaluate(e=>e.scrollLeft),top=(await add.boundingBox()).y;
await add.click();await vp.waitForTimeout(550);
assert.equal(await target.locator('.st-grid-set').count(),initialSets+1,'add creates a visible set');
assert.equal(stable.writes.filter(w=>w.action==='saveSession').at(-1).session.exercises.find(e=>e.exercise_id===guide[1].code).sets.length,initialSets+1,'added set is persisted');
assert(Math.abs(await vp.evaluate(()=>scrollY)-y)<1,'adding set preserves vertical scroll');
assert(Math.abs((await add.boundingBox()).y-top)<1,'adding set preserves heading position: '+top+' -> '+(await add.boundingBox()).y);
assert.equal(await vp.locator('[data-axis]').evaluate(e=>e.scrollLeft),x,'adding set preserves history scroll');
await target.getByRole('button',{name:'Убрать подход',exact:true}).click();await vp.waitForTimeout(550);
assert.equal(await target.locator('.st-grid-set').count(),initialSets,'remove deletes a visible set');
assert.equal(stable.writes.filter(w=>w.action==='saveSession').at(-1).session.exercises.find(e=>e.exercise_id===guide[1].code).sets.length,initialSets,'removed set is persisted');
assert(Math.abs(await vp.evaluate(()=>scrollY)-y)<1,'removing set preserves vertical scroll');
await vp.getByRole('button',{name:'Управление шаблонами',exact:true}).click();
await vp.getByRole('button',{name:'Состав упражнений шаблона 1',exact:true}).click();
assert(await vp.locator('.st-manager-modal').isVisible());
await vp.getByRole('button',{name:'← Назад к шаблонам',exact:true}).click();
assert(await vp.getByRole('dialog',{name:'Шаблоны',exact:true}).isVisible(),'composition returns to template management');
await stable.context.close();
// A new template's composition and order survive reload without rewriting workout history.
const composition=await open(768),cp=composition.page;
const historyBefore=JSON.stringify([composition.state.sessions,composition.state.session_exercises,composition.state.sets]);
await cp.getByRole('button',{name:'Управление шаблонами',exact:true}).click();
await cp.getByRole('button',{name:'＋ Шаблон',exact:true}).click();await cp.waitForTimeout(100);
await cp.getByRole('button',{name:'Состав упражнений шаблона 4',exact:true}).click();
await cp.locator('.st-manager-row').nth(0).getByRole('button',{name:'Добавить',exact:true}).click();
await cp.locator('.st-manager-row').nth(1).getByRole('button',{name:'Добавить',exact:true}).click();
await cp.locator('.st-manager-row').nth(1).getByRole('button',{name:'Выше',exact:true}).click();await cp.waitForTimeout(250);
const catalogSave=composition.writes.filter(w=>w.action==='saveExerciseCatalog').at(-1);
assert.equal(catalogSave.workout_type,4);
assert.deepEqual(catalogSave.exercises.filter(e=>e.active).map(e=>e.exercise_id),[guide[1].code,guide[0].code]);
await cp.reload();await cp.getByRole('button',{name:'Шаблон 4',exact:true}).click();
await cp.getByRole('button',{name:'Управление шаблонами',exact:true}).click();
await cp.getByRole('button',{name:'Состав упражнений шаблона 4',exact:true}).click();
assert.deepEqual(await cp.locator('.st-manager-row.in-template .st-manager-name').allTextContents(),[guide[1].name,guide[0].name]);
assert.equal(composition.writes.some(w=>w.action==='saveSession'),false,'composition edits never rewrite workout history');
assert.equal(JSON.stringify([composition.state.sessions,composition.state.session_exercises,composition.state.sets]),historyBefore);
await composition.context.close();
// Deleting a template discards its pending composition writes after the in-flight save settles.
const deletion=await open(768),dp=deletion.page;dp.on('dialog',d=>d.accept());
await dp.getByRole('button',{name:'Управление шаблонами',exact:true}).click();
await dp.getByRole('button',{name:'Состав упражнений шаблона 1',exact:true}).click();
const releaseCatalog=deletion.holdNextCatalog();
await dp.locator('.st-manager-row').nth(0).getByRole('button',{name:'Убрать',exact:true}).click();
await dp.waitForFunction(()=>document.querySelector('#st-manager-save-state').textContent.includes('Сохраняю'));
await dp.locator('.st-manager-row.in-template').first().getByRole('button',{name:'Убрать',exact:true}).click();
await dp.getByRole('button',{name:'← Назад к шаблонам',exact:true}).click();
await dp.getByRole('button',{name:'Удалить шаблон 1',exact:true}).click();releaseCatalog();await dp.waitForTimeout(1100);
assert.equal(deletion.writes.filter(w=>w.action==='saveExerciseCatalog').length,1,'deleted template has no further queued catalogue writes');
assert.equal(deletion.state.workout_types.find(t=>t.workout_type===1).active,false);
assert.equal(await dp.locator('#st-save-state').innerText(),'Сохранено');assert.equal(deletion.getOverlap(),false);
await deletion.context.close();
// Missing historical cards and stored two-set cards share the same height.
const short=await open(1440,false,false,false,false,true),sh=short.page;
const heights=await sh.locator('.st-history-row').first().locator('article').evaluateAll(es=>es.map(e=>e.getBoundingClientRect().height));
assert(Math.max(...heights)-Math.min(...heights)<1,'synthetic blank exercises participate in maximum-height alignment');
await sh.locator('.st-view-toggle').click();
assert.equal(await sh.locator('.st-history-row').first().locator('.st-history-set-space').evaluateAll(es=>es.every(e=>e.getBoundingClientRect().height===0)),true,'packed history uses actual two-set maximum without missing-card spacers');
await short.context.close();
// Removing all templates preserves the catalogue for a replacement template.
const replacement=await open(430),rp=replacement.page;
rp.on('dialog',d=>d.accept());await rp.getByRole('button',{name:'Управление шаблонами',exact:true}).click();
for(const id of [1,2,3])await rp.getByRole('button',{name:'Удалить шаблон '+id,exact:true}).click();
await rp.getByRole('button',{name:'＋ Шаблон',exact:true}).click();await rp.getByRole('button',{name:'Состав упражнений шаблона 4',exact:true}).click();
assert.equal(await rp.locator('.st-manager-name').count(),2,'replacement can select the account catalogue');await replacement.context.close();
// A successful retry clears the unsaved error indicator.
const retry=await open(430),ep=retry.page;retry.failNextTemplate();
await ep.getByRole('button',{name:'Управление шаблонами',exact:true}).click();
await ep.getByRole('textbox',{name:'Название шаблона 1',exact:true}).fill('Переименован');await ep.getByRole('textbox',{name:'Название шаблона 1',exact:true}).press('Tab');
await ep.waitForTimeout(100);assert.match(await ep.locator('#st-save-state').innerText(),/Ошибка/);
await ep.getByRole('button',{name:'Готово',exact:true}).click();await ep.waitForTimeout(100);
assert.equal(await ep.locator('#st-save-state').innerText(),'Сохранено');await retry.context.close();
// Position colours repeat after seven within a template; different templates use different sets.
const palette=await open(1440,false,false,true),pp=palette.page;
const tones=await pp.locator('.st-history-row').evaluateAll(es=>es.map(e=>getComputedStyle(e.querySelector('.st-modern-head')).backgroundColor));
assert.equal(new Set(tones.slice(0,7)).size,7);assert.equal(tones[7],tones[0]);assert.equal(tones[8],tones[1]);
await pp.getByRole('button',{name:'Шаблон 2',exact:true}).click();
const otherTones=await pp.locator('.st-history-row').evaluateAll(es=>es.map(e=>getComputedStyle(e.querySelector('.st-modern-head')).backgroundColor));
assert.notDeepEqual(otherTones,tones,'same exercise IDs get palette of current template positions');
await pp.screenshot({path:`${out}/palette-template2.png`});await palette.context.close();
// Approved names use the compact label in the journal and full name in information.
const names=await open(430),np=names.page;
const namedRow=np.locator('.st-history-row').nth(1);
assert.equal(await namedRow.locator('.st-modern-title strong').last().innerText(),guide[1].short_name);
await namedRow.locator('.st-exercise-info').last().click();
assert.equal(await np.locator('#st-guide-title').innerText(),guide[1].full_name);
await np.screenshot({path:`${out}/exercise-full-name.png`});
await np.getByRole('button',{name:'Закрыть информацию об упражнении',exact:true}).click();await names.context.close();
// Same labels cannot merge histories or inject markup into exercise cards.
const identities=await open(430,false,false,false,true),ip=identities.page;
assert.equal(await ip.locator('.st-history-row').count(),2);
assert.equal(await ip.locator('.st-modern-title img').count(),0);
const identityTarget=ip.locator('.st-history-row').nth(1).locator('article').last();
await identityTarget.locator('input[data-field=planWeight]').first().fill('42');
await identityTarget.locator('input[data-field=planWeight]').first().press('Tab');await ip.waitForTimeout(550);
const identitySave=identities.writes.filter(w=>w.action==='saveSession').at(-1).session.exercises;
assert.equal(identitySave.find(e=>e.exercise_id===guide[1].code).sets[0].plan_weight,42);
assert.equal(identitySave.find(e=>e.exercise_id===guide[0].code).sets[0].plan_weight,'');
await identities.context.close();
// Same renderer and controls for a managed account; selector is outside the mount.
const plain=await open(768),admin=await open(768,true);
assert.equal(await plain.page.locator('#strength-app').innerHTML(),await admin.page.locator('#strength-app').innerHTML());
assert.equal(await admin.page.locator('#strength-app .preview-account').count(),0);
assert.equal(await admin.page.locator('.preview-account').count(),1);
for(const page of [plain.page,admin.page]){const account=page.getByRole('link',{name:'Личный кабинет',exact:true});assert.equal(await account.getAttribute('href'),'/lk');assert.equal(await account.locator('svg').count(),1,'shared account control uses the standard icon');}
assert.equal(await plain.page.locator('[data-strength-telegram-export]').count(),0);
assert.equal(await admin.page.locator('#strength-app [data-strength-telegram-export]').count(),0,'admin export is outside shared journal');
await admin.page.getByRole('button',{name:'Выбрать тренировку №1',exact:true}).click();
const sentDialog=admin.page.waitForEvent('dialog').then(d=>d.dismiss());
await admin.page.getByRole('button',{name:'Отправить тренировку в Telegram',exact:true}).click();await sentDialog;
assert.equal(admin.telegramWrites.length,1);assert.equal(admin.telegramWrites[0].target_user_id,'fixture');assert.equal(admin.telegramWrites[0].session_id,'one');

await admin.page.screenshot({path:`${out}/managed-768.png`});
await plain.context.close();await admin.context.close();
assert.deepEqual(errors,[]);
await writeFile(`${out}/report.json`,JSON.stringify({rows,status:'pass'},null,2));
await browser.close();console.log('PASS: dual histories, shared scroll, shared admin UI, date gate, copy/paste, completion, undo, cursor and templates');
