import assert from 'node:assert/strict';
import {readFile,mkdir,writeFile} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
import path from 'node:path';
const {[process.env.QA_BROWSER || 'chromium']:chromium}=await import(process.env.PLAYWRIGHT_MODULE_URL || (process.env.CODEX_NODE_MODULES?pathToFileURL(path.join(process.env.CODEX_NODE_MODULES,'playwright/index.mjs')).href:'playwright'));
const base=process.env.QA_BASE_URL || 'http://127.0.0.1:8823';
assert.equal(new URL(base).hostname,'127.0.0.1');
const out=process.env.QA_OUT || process.env.STRENGTH_EVIDENCE_DIR;assert(out,'Set QA_OUT for browser evidence');await mkdir(out,{recursive:true});
const staticRoot=new URL('../../app/static/',import.meta.url),appHtml=await readFile(new URL('apps/strength.html',staticRoot),'utf8');
const adminHtml=await readFile(new URL('admin.html',staticRoot),'utf8');
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
async function open(width,managed=false,longNotes=false,manyExercises=false,sameNames=false,shortHistory=false,realAdmin=false,historyGaps=false,holdCatalogueReads=false){
 const context=await browser.newContext({viewport:{width,height:900},reducedMotion:'reduce',hasTouch:width<=700});
 const page=await context.newPage(),state=fixture(manyExercises),writes=[],telegramWrites=[];let active=0,overlap=false,failTemplate=false;let workoutReads=0,deliveryFailure=false,deliveryGate=null,sessionGate=null,failSession=false,transportFailure=false,timeoutSession=false;
 if(sameNames)state.exercise_catalog.forEach(e=>{e.exercise_name=e.short_name='Одинаковое имя <img src=x onerror=alert(1)>';});
 if(longNotes)state.session_exercises[0].note='Примечание с несколькими строками для проверки сохранения позиции при изменении подходов. '.repeat(14);
 if(shortHistory){state.sets=state.sets.filter(set=>set.set_number<=2);state.session_exercises=state.session_exercises.filter(ex=>!(ex.session_id==='one'&&ex.exercise_id===guide[0].code));state.sets=state.sets.filter(set=>!(set.session_id==='one'&&set.exercise_id===guide[0].code));}
 if(historyGaps){
  state.sessions=state.sessions.filter(session=>session.workout_type===1).slice(0,5);
  const ids=new Set(state.sessions.map(session=>session.session_id));
  state.session_exercises=state.session_exercises.filter(ex=>ids.has(ex.session_id)&&ex.session_id!=='middle-0');
  state.sets=state.sets.filter(set=>ids.has(set.session_id)&&set.session_id!=='middle-0');
  state.sets.forEach(set=>{if(set.session_id==='middle-2'||(set.session_id==='middle-1'&&set.exercise_id===guide[0].code)){for(const field of ['plan_weight','plan_reps','fact_weight','fact_reps','rpe'])set[field]='';set.completed=false;}});
 }
 const catalogs=new Map([1,2,3].map(id=>[id,structuredClone(state.exercise_catalog)]));let catalogGate=null,releaseCatalogueReads;const catalogueReadsGate=holdCatalogueReads?new Promise(resolve=>{releaseCatalogueReads=resolve;}):null;const readRequests=[];
 page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/*',async route=>{
  const url=new URL(route.request().url());if(url.hostname!=='127.0.0.1')return route.abort();
  if(url.pathname==='/admin/strength')return route.fulfill({contentType:'text/html',body:adminHtml});
  if(url.pathname==='/admin/api/navigation')return route.fulfill({json:{modules:[{id:'products.strength',admin_catalog:[{category:'applications',order:1,url:'/admin/strength',label:'Силовые',icon:'💪'}]}]}});
  if(url.pathname==='/admin/api/apps/strength/users/fixture')return route.fulfill({json:{user:{id:'fixture',email:'example@example.test',display_name:'Тестовый пользователь'},has_state:true,has_access:true}});
  if(url.pathname==='/admin/api/apps/users')return route.fulfill({json:{users:[{user_id:'fixture',email:'example@example.test',has_state:true,has_access:true,summary:{sessions:9}}]}});
  if(url.pathname==='/api/account-auth/session')return route.fulfill({json:{authenticated:true,email:'example@example.test'}});
  if(url.pathname==='/favicon.png')return route.fulfill({contentType:'image/png',body:await readFile(new URL('brand/favicon.png',staticRoot))});
  if(url.pathname==='/strength-local' ||url.pathname==='/strength-admin-local'){
    const managed=url.pathname.includes('admin');
    return route.fulfill({contentType:'text/html',body:'<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{margin:0;background:#f5f5f7}</style><body>'+(managed?'<div class="preview-account">Управляемый аккаунт</div>':'')+'<script>window.EdabalansIdentity={source:"native",email:"example@example.test"};window.EdabalansAppContext='+JSON.stringify(managed?{mode:'admin',targetUserId:'fixture',accountUrl:'/lk'}:{accountUrl:'/lk'})+';</script>'+appHtml+'</body></html>'});
  }
  if(url.pathname==='/api/apps/strength/send-plan'){
    telegramWrites.push(JSON.parse(route.request().postData()));
    if(deliveryGate){const gate=deliveryGate;deliveryGate=null;await gate;}
    if(deliveryFailure){deliveryFailure=false;return route.fulfill({status:409,json:{detail:'Основной мессенджер не подключён'}});}
    return route.fulfill({contentType:'application/json',body:JSON.stringify({ok:true,platform:managed?'max':'telegram',message_ids:['fixture-delivered']})});
  }
  if(url.pathname!=='/api/apps/strength'){
    const asset=new URL(url.pathname.replace(/^\/(assets\/|admin\/static\/)?/,''),staticRoot);
    if(!asset.href.startsWith(staticRoot.href))return route.abort();
    try{return route.fulfill({contentType:({'.html':'text/html','.css':'text/css','.js':'text/javascript','.mjs':'text/javascript','.woff2':'font/woff2','.gif':'image/gif','.png':'image/png','.svg':'image/svg+xml'})[path.extname(asset.pathname)] || 'application/octet-stream',body:await readFile(asset)});}catch{return route.abort();}
  }
  const data=route.request().method()==='POST'?JSON.parse(route.request().postData()):Object.fromEntries(url.searchParams);
  let reply={ok:true,user:{user_id:'fixture',email:'example@example.test',display_name:'',can_coach:managed,can_calculate_progression:managed},version:state.version};
  if(data.action==='messengerState')return route.fulfill({json:{ok:true,destination:managed?'max':'telegram',linked:{telegram:{linked:!managed},max:{linked:managed}},bot_links:{telegram:'https://t.me/test_bot',max:'https://max.ru/test_bot'}}});
  if(data.action==='getWorkout'){readRequests.push({...data});workoutReads++;const type=data.initial==='1'?1:Number(data.type);reply.workout={...structuredClone(state),selected_type:type,exercise_catalog:structuredClone(catalogs.get(type) || state.exercise_catalog.map(e=>({...e,active:false})))};if(data.catalog_only==='1'){reply.workout.sessions=[];reply.workout.session_exercises=[];reply.workout.sets=[];if(catalogueReadsGate)await catalogueReadsGate;}}
  if(route.request().method()==='POST'){
   if(data.action==='saveSession' && (transportFailure || timeoutSession)){
    writes.push(data);if(transportFailure){transportFailure=false;return route.abort('failed');}
    timeoutSession=false;return;
   }
   active++;if(active>1)overlap=true;
   writes.push(data);if(data.action==='saveExerciseCatalog'&&catalogGate){const gate=catalogGate;catalogGate=null;await gate;}if(data.action==='saveSession'&&sessionGate){const gate=sessionGate;sessionGate=null;await gate;}await new Promise(resolve=>setTimeout(resolve,30));
   if(failSession && data.action==='saveSession'){failSession=false;reply={ok:false,error:'SYNTHETIC_SAVE_ERROR'};}
   else if(failTemplate && data.action==='saveWorkoutTypes'){failTemplate=false;reply={ok:false,error:'NETWORK_TEMPORARY'};}
   else if(data.action==='saveExerciseCatalog'&&!state.workout_types.some(t=>Number(t.workout_type)===data.workout_type&&t.active!==false))reply={ok:false,error:'INVALID_WORKOUT_TEMPLATE'};
   else if(data.version!==state.version)reply={ok:false,error:'STRENGTH_STATE_CONFLICT'};
   else{reply.version=++state.version;if(data.action==='saveWorkoutTypes')state.workout_types=data.workout_types;if(data.action==='saveExerciseCatalog'){
    const incoming=data.exercises.map(e=>({...state.exercise_catalog.find(item=>item.exercise_id===e.exercise_id),...e}));
    catalogs.set(data.workout_type,incoming);
    for(const [type,existing] of catalogs){if(type===data.workout_type)continue;for(const item of incoming){const shared=existing.find(e=>e.exercise_id===item.exercise_id);if(shared){shared.exercise_name=item.exercise_name;shared.short_name=item.short_name||item.exercise_name;}else if(item.source==='custom')existing.push({...item,active:false});}}
    for(const item of incoming){if(!state.exercise_catalog.some(e=>e.exercise_id===item.exercise_id))state.exercise_catalog.push({...item});}
   }if(data.session)reply.session={...data.session,session_number:data.session.session_number || 10};}
   active--;
  }
  await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(reply)});
 });
 await page.goto(base+(realAdmin?'/admin/strength?user=fixture':managed?'/strength-admin-local':'/strength-local'));
 await page.locator('.st-view-toggle').waitFor();await page.evaluate(()=>document.fonts.ready);
 return {context,page,writes,telegramWrites,readRequests,releaseCatalogueReads:()=>releaseCatalogueReads&&releaseCatalogueReads(),getOverlap:()=>overlap,getWorkoutReads:()=>workoutReads,state,holdNextCatalog:()=>{let release;catalogGate=new Promise(resolve=>{release=resolve;});return release;},failNextTemplate:()=>{failTemplate=true;},failNextDelivery:()=>{deliveryFailure=true;},holdNextDelivery:()=>{let release;deliveryGate=new Promise(resolve=>{release=resolve;});return release;},holdNextSessionSave:()=>{let release;sessionGate=new Promise(resolve=>{release=resolve;});return release;},failNextSessionSave:()=>{failSession=true;},failNextTransport:()=>{transportFailure=true;},timeoutNextSave:()=>{timeoutSession=true;}};
}
async function assertDatesFollowColumns(page){
 await page.waitForFunction(()=>{const dates=document.querySelectorAll('.st-date-cell'),cards=document.querySelector('.st-history-row').querySelectorAll('article');return [...dates].every((e,i)=>Math.abs(e.getBoundingClientRect().left-cards[i].getBoundingClientRect().left)<1);});
}
async function entryGeometry(page){
 return page.locator('.st-history-row').first().locator('article').last().locator('.st-grid-set').first().evaluate(row=>{
  const fields=[...row.querySelectorAll('input')].map(field=>({width:field.getBoundingClientRect().width,font:parseFloat(getComputedStyle(field).fontSize),readonly:field.readOnly}));
  const done=row.querySelector('.st-set-done').getBoundingClientRect(),rpe=row.querySelector('.st-rpe-button');
  return {fields,doneWidth:done.width,leftGap:done.left-row.querySelector('[data-field=planReps]').getBoundingClientRect().right,rightGap:row.querySelector('[data-field=factWeight]').getBoundingClientRect().left-done.right,rpeWidth:rpe.getBoundingClientRect().width,rpeFont:parseFloat(getComputedStyle(rpe).fontSize)};
 });
}
if(process.env.QA_FOCUS==='date'){
 for(const width of [360,430,700,701,768,1440])for(const view of ['training','exercise']){
  const trial=await open(width),page=trial.page;
  if(view==='exercise')await page.locator('.st-view-toggle').click();
  await page.evaluate(()=>{HTMLInputElement.prototype.showPicker=function(){throw new Error('Calendar unavailable');};});
  const field=page.locator(view==='training'?'.st-date-cell':'.st-history-date').last(),dialog=page.getByRole('dialog',{name:'Дата тренировки',exact:true});
  const activate=async locator=>width<=700?locator.tap():locator.click();
  await activate(field.locator('.st-journal-date-text'));await dialog.waitFor();
  await page.locator('#st-session-date-text').fill('31.02.2026');await dialog.getByRole('button',{name:'Сохранить',exact:true}).click();
  assert(await page.locator('#st-session-date-error').innerText());assert.equal(trial.writes.length,0,'invalid date is not saved');
  await page.locator('.st-session-date-calendar').evaluate(el=>el.setCustomValidity('Incomplete optional calendar'));
  await page.locator('#st-session-date-text').fill('28.02.2026');await dialog.getByRole('button',{name:'Сохранить',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('.st-saving')?.textContent.includes('Сохранено'));
  const saved=trial.writes.filter(w=>w.action==='saveSession').at(-1).session;assert.equal(saved.date,'2026-02-28');assert.equal(await field.locator('.st-journal-date-text').inputValue(),'28.02.2026');
  const dateIndex=await field.getAttribute('data-session-index'),card=page.locator('article[data-session-index="'+dateIndex+'"]').last(),fact=card.locator('[data-field="factWeight"]').first();
  await fact.fill('42');await fact.press('Tab');await page.waitForTimeout(550);
  assert.equal(await page.locator('.st-modal-bg').count(),0,'date unlocks fact entry');assert.equal(trial.writes.filter(w=>w.action==='saveSession').at(-1).session.session_id,saved.session_id,'fact belongs to the newly dated session');assert(trial.writes.filter(w=>w.action==='saveSession').at(-1).session.exercises.some(e=>e.sets.some(s=>s.fact_weight===42)));
  await activate(field.locator('.st-date-picker'));await dialog.waitFor();
  await page.locator('.st-session-date-calendar').fill('2026-03-01');assert.equal(await page.locator('#st-session-date-text').inputValue(),'01.03.2026');
  await page.screenshot({path:`${out}/date-${process.env.QA_BROWSER || 'chromium'}-${view}-${width}.png`});
  const writes=trial.writes.length;await dialog.getByRole('button',{name:'Отменить',exact:true}).click();assert.equal(trial.writes.length,writes);assert.equal(await field.locator('.st-journal-date-text').inputValue(),'28.02.2026');
  trial.state.sessions.find(s=>s.session_id===saved.session_id).date=saved.date;
  await page.reload();await page.locator('.st-view-toggle').waitFor();assert.equal(await page.locator('.st-date-cell').last().locator('.st-journal-date-text').inputValue(),'28.02.2026','saved date survives reload');
  if(view==='exercise')await page.locator('.st-view-toggle').click();
  const releaseCreation=trial.holdNextSessionSave(),creationRequest=page.waitForRequest(request=>request.method()==='POST'&&request.postDataJSON()?.action==='saveSession');
  await page.getByRole('button',{name:'Новая тренировка',exact:true}).click();await creationRequest;
  await activate(field.locator('.st-journal-date-text'));await page.locator('#st-session-date-text').fill('01.04.2026');
  releaseCreation();await page.waitForFunction(()=>document.querySelector('.st-saving')?.textContent.includes('Сохранено'));
  assert.equal(await page.locator('#st-session-date-text').inputValue(),'01.04.2026','server response cannot erase an in-progress date');
  await page.goBack();await dialog.waitFor({state:'detached'});
  await page.goForward();await dialog.waitFor();assert.equal(await page.locator('#st-session-date-text').inputValue(),'01.04.2026','date edits are one screen and retain the draft');
  await dialog.getByRole('button',{name:'Сохранить',exact:true}).click();await page.waitForTimeout(550);
  assert.equal(trial.writes.filter(w=>w.action==='saveSession').at(-1).session.date,'2026-04-01');
  await trial.context.close();
 }
 assert.deepEqual(errors,[]);await browser.close();console.log('PASS: date entry with unavailable native picker, invalid date, save, fact entry, cancel and reload on mobile/desktop');process.exit(0);
}
for(const width of [360,430,700,701,768,1440]){
 const {context,page}=await open(width);
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
 assert.equal(await page.locator('.st-session-sticky .st-view-toggle').count(),1,'view switch belongs to workout toolbar');
 assert.equal(await page.locator('.st-view-toggle').getAttribute('aria-pressed'),'false','unpressed eye is whole workouts');
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
 const filling=await entryGeometry(page);
 if(width<=700){
  const geometry=await page.locator('[data-axis=training]').evaluate(axis=>{const card=axis.querySelector('.st-history-row article:last-child').getBoundingClientRect(),box=axis.getBoundingClientRect();return {cardWidth:card.width,axisWidth:box.width,left:card.left-box.left,right:card.right-box.right};});
  assert(Math.abs(geometry.cardWidth-geometry.axisWidth)<1&&Math.abs(geometry.left)<1&&Math.abs(geometry.right)<1,'phone whole workout occupies the entire workspace');
  assert(filling.fields[2].width>filling.fields[0].width*1.3&&filling.fields[3].width>filling.fields[1].width*1.3,'phone fact fields receive more width than plan');
  assert(filling.fields[2].font>filling.fields[0].font&&filling.fields.every(field=>!field.readonly),'plan remains editable with smaller type than fact');
 }else{
  assert(Math.abs(inputs[2].w/inputs[0].w-1.1)<.015,'desktop keeps compact fact width');assert(Math.abs(inputs[3].w/inputs[1].w-1.1)<.015);
 }
 assert(inputs[0].w>inputs[1].w);
 const align=await page.evaluate(()=>{const d=document.querySelectorAll('.st-date-cell'),c=document.querySelector('.st-history-row').querySelectorAll('article');return [...d].map((e,i)=>Math.abs(e.getBoundingClientRect().left-c[i].getBoundingClientRect().left));});
 assert(align.every(x=>x<1),'each sticky date is aligned to its workout column');
 await page.setViewportSize({width,height:400});await page.evaluate(()=>scrollTo(0,200));
 assert(Math.abs((await page.locator('.st-session-sticky').boundingBox()).y)<1,'both toolbar and dates stay pinned');
 await page.evaluate(()=>scrollTo(0,0));await page.setViewportSize({width,height:900});
 const noteBounds=await page.locator('.st-modern-comment').first().evaluate(e=>{const box=e.getBoundingClientRect(),text=e.querySelector('span').getBoundingClientRect();return text.top>=box.top&&text.bottom<=box.bottom;});
 assert(noteBounds,'one-line note text fits vertically at '+width);
 await page.screenshot({path:`${out}/training-${width}.png`});
 if(width<=700 && await page.locator('[data-axis=training]').evaluate(e=>e.scrollWidth>e.clientWidth)){
   const touch=await context.newCDPSession(page),axis=page.locator('[data-axis=training]');
   const box=await axis.boundingBox(),start=await axis.evaluate(e=>e.scrollLeft),y=Math.min(box.y+50,800);
   await touch.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x:35,y}]});
   for(const x of [.2,.4,.6,.8,1].map(fraction=>35+fraction*(width-70))){await touch.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x,y}]});await page.waitForTimeout(20);}
   await touch.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});await page.waitForTimeout(150);
   assert(await axis.evaluate(e=>e.scrollLeft)<start,'native touch swipe moves the history at '+width);await assertDatesFollowColumns(page);
 }
 if(width>700){const bar=page.locator('.st-history-bottom-bar');assert(await bar.isVisible());await bar.evaluate(e=>{e.scrollLeft=0;});await page.waitForTimeout(50);assert.equal(await page.locator('[data-axis=training]').evaluate(e=>e.scrollLeft),0);await assertDatesFollowColumns(page);}
 const plusTraining=await page.locator('.st-toolbar-add').boundingBox();
 const inactiveEye=await page.locator('.st-view-toggle').evaluate(e=>getComputedStyle(e).backgroundColor);
 await page.locator('.st-view-toggle').click();
 assert.equal(await page.locator('.st-view-toggle').getAttribute('aria-pressed'),'true','pressed eye is packed exercise history');
 assert.notEqual(await page.locator('.st-view-toggle').evaluate(e=>getComputedStyle(e).backgroundColor),inactiveEye,'eye changes appearance with view');
 assert.equal(await page.locator('.st-date-viewport').count(),0,'packed mode puts dates over each exercise instead of the sticky row');
 assert.equal(await page.locator('.st-view-toggle').count(),1);
 assert.equal(await page.locator('[data-axis=exercise-history]').count(),1,'packed rows share one horizontal axis');
 const packed=await entryGeometry(page);
 assert(Math.abs(packed.fields[2].width/packed.fields[0].width-1.1)<.015,'packed fields remain compact on every device');
 if(width<=700){
  assert(filling.fields[2].width>packed.fields[2].width*1.3&&filling.rpeWidth>packed.rpeWidth*1.3,'phone fill mode enlarges fact and RPE over packed mode');
  assert(filling.rpeFont>packed.rpeFont&&filling.leftGap>packed.leftGap&&filling.rightGap>packed.rightGap,'phone fill mode increases RPE and space around the circle');
 }else assert.deepEqual(filling,packed,'desktop input geometry stays compact in both views');

 assert(await page.locator('.st-history-row').first().locator('article[data-session-index="1"]').count(),'filled exercise from another template is included');
 assert.equal(await page.locator('.st-history-row article[data-session-index="8"]').count(),2,'latest workout remains available for every exercise, even while blank');
 assert.equal(await page.locator('.st-history-row article').count(),await page.locator('.st-history-date').count(),'every record has its own number/date');
 assert.equal(await page.locator('.st-toolbar-add').count(),1,'plus remains in both modes');
 const plusPacked=await page.locator('.st-toolbar-add').boundingBox();
 assert(Math.abs(plusPacked.x-plusTraining.x)<1&&Math.abs(plusPacked.y-plusTraining.y)<1,'plus keeps its toolbar position');
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
 if(width<=700){
  const axis=page.locator('[data-axis=exercise-history]'),before=await axis.evaluate(e=>e.scrollLeft),box=await axis.boundingBox(),touch=await context.newCDPSession(page),y=Math.min(box.y+65,800);
  await touch.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x:80,y}]});
  for(const x of [110,150,210,280]){await touch.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x,y}]});await page.waitForTimeout(20);}
  await touch.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});await page.waitForTimeout(150);
  assert(await axis.evaluate(e=>e.scrollLeft)<before,'packed history supports native touch swipe at '+width);
 }
 if(width>700){await page.locator('.st-history-bottom-bar').evaluate(e=>e.scrollLeft=0);await page.waitForTimeout(50);assert.equal(await page.locator('[data-axis=exercise-history]').evaluate(e=>e.scrollLeft),0);}
 await page.screenshot({path:`${out}/packed-${width}.png`});
 await page.locator('.st-view-toggle').click();
 assert.equal(await page.locator('.st-view-toggle').getAttribute('aria-pressed'),'false');
 await assertDatesFollowColumns(page);
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
assert.equal(await p.locator('.st-date-cell').last().locator('.st-journal-date-text').getAttribute('readonly'),'');
await p.locator('.st-date-cell').last().locator('.st-journal-date-text').click();
await p.getByRole('dialog',{name:'Дата тренировки',exact:true}).waitFor();await p.getByRole('button',{name:'Отменить',exact:true}).click();
await p.locator('.st-date-cell').last().locator('.st-date-picker').click();
await p.locator('.st-session-date-calendar').fill('2026-10-21');await p.getByRole('button',{name:'Сохранить',exact:true}).click();await p.waitForTimeout(550);
assert.equal(run.writes.filter(w=>w.action==='saveSession').at(-1).session.date,'2026-10-21','calendar date is persisted as ISO');
await p.locator('.st-date-cell').last().locator('.st-date-picker').click();await p.locator('#st-session-date-text').fill('22.10.2026');await p.getByRole('button',{name:'Сохранить',exact:true}).click();await p.waitForTimeout(550);
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
assert.deepEqual(await field.evaluate(e=>[e.selectionStart,e.selectionEnd]),[0,2],'desktop selects the existing number');
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
// Workout creation and per-date deletion still address the same selected template.
const history=await open(430),hp=history.page;
await hp.getByRole('button',{name:'Новая тренировка',exact:true}).click();await hp.waitForTimeout(100);
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
// RPE can be cleared without assigning zero, followed by ratings five to ten.
const scale=await open(430),sp=scale.page;
await sp.setViewportSize({width:430,height:500});
const rpeSource=sp.locator('.st-history-row').first().locator('article').first().locator('.st-rpe-button').last();
await rpeSource.click();
assert.deepEqual(await sp.locator('.st-rpe-option').allTextContents(),['—','5','6','7','8','9','10']);
const foregrounds=await sp.locator('.st-rpe-option').evaluateAll(es=>es.map(e=>getComputedStyle(e).color));
assert.equal(new Set(foregrounds).size,1);
const rpeBox=await rpeSource.boundingBox(),pickerBox=await sp.locator('.st-rpe-floating').boundingBox();
assert(pickerBox.y<rpeBox.y&&rpeBox.y-(pickerBox.y+pickerBox.height)<8,'seven-choice picker remains next to the source above it');
await sp.getByRole('button',{name:'RPE 5',exact:true}).click();await sp.waitForTimeout(550);
assert.equal(scale.writes.filter(w=>w.action==='saveSession').at(-1).session.exercises[0].sets.at(-1).rpe,5);
await rpeSource.click();
await sp.getByRole('button',{name:'RPE 10',exact:true}).click();await sp.waitForTimeout(550);
assert.equal(await rpeSource.textContent(),'10','RPE ten is a number in the filled cell too');
assert.equal(scale.writes.filter(w=>w.action==='saveSession').at(-1).session.exercises[0].sets.at(-1).rpe,10);
await rpeSource.click();await sp.getByRole('button',{name:'RPE — без оценки',exact:true}).click();await sp.waitForTimeout(550);
assert.equal(await rpeSource.textContent(),'—');
assert.equal(scale.writes.filter(w=>w.action==='saveSession').at(-1).session.exercises[0].sets.at(-1).rpe,'','dash saves an absent rating, not zero');
const savedRpeSession=scale.writes.filter(w=>w.action==='saveSession').at(-1).session;
for(const exercise of savedRpeSession.exercises)for(const set of exercise.sets){const stored=scale.state.sets.find(row=>row.session_id===savedRpeSession.session_id&&row.exercise_id===exercise.exercise_id&&row.set_number===set.set_number);if(stored)stored.rpe=set.rpe;}
await sp.reload();await rpeSource.waitFor();assert.equal(await rpeSource.textContent(),'—','cleared rating survives reloading');
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
// Browser Back/Forward follows nested screens rather than leaving the app.
const navigation=await open(430,false,true),bp=navigation.page;
await bp.locator('[data-axis]').evaluate(e=>e.scrollLeft=221);await bp.waitForTimeout(60);
const navigationInfo=bp.locator('.st-history-row').first().locator('.st-exercise-info').nth(1);
await navigationInfo.scrollIntoViewIfNeeded();
const originalAxis=await bp.locator('[data-axis]').evaluate(e=>e.scrollLeft);
await navigationInfo.click();await bp.goBack();
await bp.locator('.st-guide-header').waitFor({state:'detached'});
assert(await bp.locator('[data-axis]').evaluate(e=>Math.abs(e.scrollWidth-e.clientWidth-e.scrollLeft)<2));
await bp.screenshot({path:`${out}/back-restored.png`});
await bp.goForward();await bp.locator('.st-guide-header').waitFor();
await bp.getByRole('button',{name:'Закрыть информацию об упражнении'}).click();
await bp.getByRole('button',{name:'Управление шаблонами',exact:true}).click();
await bp.getByRole('button',{name:'Состав упражнений шаблона 1',exact:true}).click();
await bp.goBack();await bp.getByRole('dialog',{name:'Шаблоны',exact:true}).waitFor();
await bp.goBack();await bp.locator('.st-modal-bg').waitFor({state:'detached'});
const note=bp.locator('.st-history-row').first().locator('article').first().getByRole('button',{name:'Примечание к упражнению'});
assert.equal(await note.evaluate(e=>getComputedStyle(e.querySelector('span')).textOverflow),'ellipsis');
assert(await note.evaluate(e=>e.classList.contains('has-note')));
await note.click();assert((await bp.getByRole('textbox',{name:'Ваш комментарий'}).inputValue()).length>300);
await bp.screenshot({path:`${out}/note-full.png`});
await bp.getByRole('textbox',{name:'Ваш комментарий'}).fill('Изменённое полное примечание');
await bp.getByRole('button',{name:'Сохранить',exact:true}).click();await bp.waitForTimeout(550);
assert.equal(navigation.writes.filter(w=>w.action==='saveSession').at(-1).session.exercises[0].note,'Изменённое полное примечание');
await bp.getByRole('button',{name:'Статистика',exact:true}).click();await bp.goBack();
await bp.locator('.st-view-toggle').waitFor();assert(!new URL(bp.url()).searchParams.has('view'));
await bp.goBack();assert(!bp.url().includes('/strength-local'),'Back from the root is not trapped');
await navigation.context.close();
const reloaded=await open(430),reloadPage=reloaded.page;
await reloadPage.getByRole('button',{name:'Статистика',exact:true}).click();await reloadPage.reload();
await reloadPage.getByRole('button',{name:'Вернуться к тренировкам'}).waitFor();
await reloadPage.goBack();await reloadPage.locator('.st-view-toggle').waitFor();assert(!new URL(reloadPage.url()).searchParams.has('view'));
await reloadPage.goForward();await reloadPage.getByRole('button',{name:'Вернуться к тренировкам'}).waitFor();
await reloadPage.getByRole('button',{name:'Вернуться к тренировкам'}).click();await reloadPage.locator('.st-view-toggle').waitFor();
await reloaded.context.close();
// Switching views always anchors the latest record at the right edge, without writes.
{
const viewing=await open(430),vp=viewing.page;
await vp.locator('[data-axis]').evaluate(e=>e.scrollLeft=221);await vp.waitForTimeout(60);
const trainingScroll=await vp.locator('[data-axis]').evaluate(e=>e.scrollLeft);
await vp.locator('.st-view-toggle').click();await vp.locator('[data-axis]').evaluate(e=>e.scrollLeft=442);await vp.waitForTimeout(60);
const packedScroll=await vp.locator('[data-axis]').evaluate(e=>e.scrollLeft);
await vp.locator('.st-view-toggle').click();assert(await vp.locator('[data-axis]').evaluate(e=>Math.abs(e.scrollLeft-e.scrollWidth+e.clientWidth)<1));
await vp.locator('.st-view-toggle').click();assert(await vp.locator('[data-axis]').evaluate(e=>Math.abs(e.scrollLeft-e.scrollWidth+e.clientWidth)<1));
assert.equal(viewing.writes.length,0,'view changes never create or rewrite records');
const foreign=vp.locator('.st-history-row').first().locator('article[data-session-index="1"]');
const foreignWeight=foreign.locator('input[data-field=planWeight]').first();
await foreignWeight.focus();await foreignWeight.evaluate(()=>new Promise(resolve=>setTimeout(resolve,0)));
await foreignWeight.fill('72');await foreignWeight.press('Tab');await vp.waitForTimeout(550);
const foreignSave=viewing.writes.filter(w=>w.action==='saveSession').at(-1);
assert.equal(foreignSave.workout_type,2);assert.equal(foreignSave.session.session_id,'two');assert.equal(foreignSave.session.exercises[0].sets[0].plan_weight,72);
assert.equal(await vp.getByRole('button',{name:'Шаблон 1',exact:true}).getAttribute('aria-pressed'),'true','editing another-template history does not switch the active template');
await viewing.context.close();
// Five workouts with missing and explicitly blank exercises pack independently to the right.
for(const width of [360,430,700,701,768,1440]){
 const gaps=await open(width,false,false,false,false,false,false,true),gp=gaps.page;
 assert.deepEqual(await gp.locator('.st-history-row').evaluateAll(rows=>rows.map(row=>row.querySelectorAll('article').length)),[5,5]);
 const blank=gp.locator('.st-history-row').first().locator('article').nth(1);
 assert(await blank.locator('input').evaluateAll(fields=>fields.every(field=>field.value==='')),'whole view preserves the missing workout position');
 await gp.screenshot({path:`${out}/five-workouts-${width}.png`});
 await gp.locator('.st-view-toggle').click();
 assert.deepEqual(await gp.locator('.st-history-row').evaluateAll(rows=>rows.map(row=>row.querySelectorAll('article').length)),[4,5]);
 const ends=await gp.locator('.st-history-row').evaluateAll(rows=>rows.map(row=>row.querySelector('article:last-child').getBoundingClientRect().right));
 assert(Math.max(...ends)-Math.min(...ends)<1,'packed rows are aligned at their newest record on the right');
 assert.equal(await gp.locator('.st-history-date').count(),9);
 assert.equal(gaps.writes.length,0);
 await gp.screenshot({path:`${out}/five-packed-${width}.png`});
 if(width===430){
  const second=gp.locator('.st-history-row').nth(1).locator('article').last(),date=second.locator('.st-history-date');
  await date.locator('.st-journal-date-text').click();await gp.getByRole('dialog',{name:'Дата тренировки',exact:true}).waitFor();
  await gp.locator('#st-session-date-text').fill('20.10.2026');await gp.getByRole('button',{name:'Сохранить',exact:true}).click();await gp.waitForTimeout(550);
  assert.equal(gaps.writes.filter(w=>w.action==='saveSession').at(-1).session.session_id,'middle-3');
  assert.equal(gaps.writes.filter(w=>w.action==='saveSession').at(-1).session.date,'2026-10-20');
  await second.locator('input[data-field=planWeight]').first().fill('77');await second.locator('input[data-field=planWeight]').first().press('Tab');await gp.waitForTimeout(550);
  const saved=gaps.writes.filter(w=>w.action==='saveSession').at(-1).session;
  assert.equal(saved.session_id,'middle-3');assert.equal(saved.exercises.find(e=>e.exercise_id===guide[1].code).sets[0].plan_weight,77);
  await gp.getByRole('button',{name:'Новая тренировка',exact:true}).click();await gp.waitForTimeout(200);
  assert.equal(await gp.locator('.st-view-toggle').getAttribute('aria-pressed'),'true','plus preserves the current packed view');
  assert.equal(await gp.locator('.st-history-row').first().locator('article').last().locator('.st-journal-date-text').inputValue(),'');
 }
 await gaps.context.close();
}
}
// Desktop clicks select the whole number so typing replaces it; touch keeps its cursor behaviour.
{
 const desktop=await open(1440),page=desktop.page;
 const card=page.locator('.st-history-row').first().locator('article[data-session-index="0"]');
 for(const fieldName of ['planWeight','planReps','factWeight','factReps']){
  const field=card.locator('input[data-field="'+fieldName+'"]').first();
  await field.click();
  await page.waitForFunction(name=>{const input=document.activeElement;return input.dataset.field===name&&input.selectionStart===0&&input.selectionEnd===input.value.length;},fieldName);
  await page.keyboard.type('7');assert.equal(await field.inputValue(),'7','typing replaces the selected '+fieldName);
  await field.press('Tab');await page.waitForTimeout(550);
  const saved=desktop.writes.filter(write=>write.action==='saveSession').at(-1).session;
  const key={planWeight:'plan_weight',planReps:'plan_reps',factWeight:'fact_weight',factReps:'fact_reps'}[fieldName];
  assert.equal(saved.session_id,'one');assert.equal(saved.exercises[0].sets[0][key],7);
 }
 await desktop.context.close();
 const touch=await open(430),touchField=touch.page.locator('.st-history-row').first().locator('article').last().locator('input[data-field=planWeight]').first();
 await touchField.fill('60');await touchField.tap();await touch.page.waitForFunction(()=>document.activeElement.selectionStart===2&&document.activeElement.selectionEnd===2);
 assert.deepEqual(await touchField.evaluate(input=>[input.selectionStart,input.selectionEnd]),[2,2],'touch keeps the numeric cursor at the right edge');
 await touch.context.close();
}
// A new workout stays editable in both views, including its still-empty exercises.
for(const width of [430,1440]){
 const draft=await open(width),page=draft.page;
 await page.locator('.st-view-toggle').click();
 await page.locator('[data-axis]').evaluate(axis=>axis.scrollLeft=0);
 await page.getByRole('button',{name:'Новая тренировка',exact:true}).click();await page.waitForTimeout(150);
 assert.equal(await page.locator('.st-view-toggle').getAttribute('aria-pressed'),'true');
 let cards=page.locator('.st-history-row article[data-session-index="9"]');
 const createdId=draft.writes.find(write=>write.action==='saveSession').session.session_id;
 assert.equal(await cards.count(),2,'blank exercises of the new workout are present in packed mode');
 assert(await cards.first().evaluate(card=>{const box=card.getBoundingClientRect(),axis=card.closest('[data-axis]').getBoundingClientRect();return box.right<=axis.right+1&&box.left>=axis.left-1;}),'new packed column is scrolled into view');
 const weight=cards.first().locator('input[data-field=planWeight]').first();await weight.fill('45');await weight.press('Tab');await page.waitForTimeout(550);
 await page.locator('.st-view-toggle').click();assert.equal(await page.locator('.st-history-row article[data-session-index="9"]').count(),2);
 await page.locator('.st-view-toggle').click();cards=page.locator('.st-history-row article[data-session-index="9"]');
 assert.equal(await cards.count(),2);assert.equal(await cards.first().locator('input[data-field=planWeight]').first().inputValue(),'45');
 assert.equal(await cards.last().locator('input[data-field=planWeight]').first().inputValue(),'','unfilled exercise stays available beside the filled one');
 const bounds=await page.locator('.st-history-row').evaluateAll(rows=>rows.map(row=>row.querySelector('article:last-child').getBoundingClientRect().right));
 assert(Math.max(...bounds)-Math.min(...bounds)<1,'each exercise history ends at the same right edge');
 await page.screenshot({path:`${out}/new-packed-${width}.png`});
 let prompt='';page.once('dialog',async dialog=>{prompt=dialog.message();await dialog.dismiss();});
 await cards.last().getByRole('button',{name:'Удалить тренировку №10',exact:true}).click();
 assert.match(prompt,/№10 .*без даты/);assert.equal(await cards.count(),2,'cancel leaves the entire workout intact');
 page.once('dialog',dialog=>dialog.accept());
 await cards.last().getByRole('button',{name:'Удалить тренировку №10',exact:true}).click();await page.waitForTimeout(550);
 assert.equal(await page.locator('.st-history-row article[data-session-index="9"]').count(),0,'delete from any exercise removes the complete workout');
 const deleted=draft.writes.filter(write=>write.action==='saveSession'&&write.session.deleted).at(-1);
 assert(deleted);assert.equal(deleted.session.session_id,createdId);
 assert.equal(await page.locator('.st-history-row article[data-session-index="8"]').count(),2,'the previous latest workout becomes available again');
 await page.getByRole('button',{name:'Отменить действие',exact:true}).click();await page.waitForTimeout(550);
 assert.equal(await page.locator('.st-history-row article[data-session-index="9"]').count(),2,'undo restores the deleted workout with both exercises');
 assert.equal(await page.locator('.st-history-row article[data-session-index="9"]').first().locator('input[data-field=planWeight]').first().inputValue(),'45');
 await draft.context.close();
}
// Any meaningful recorded value survives packing, even without a plan.
{
 const templates=await open(768),page=templates.page;
 templates.state.sets.filter(set=>set.session_id==='two').forEach(set=>{for(const key of ['plan_weight','plan_reps','fact_weight','fact_reps','rpe'])set[key]='';set.completed=false;});
 await page.reload();await page.locator('.st-view-toggle').waitFor();
 await page.getByRole('button',{name:'Шаблон 2',exact:true}).click();await page.locator('.st-view-toggle').click();
 assert.equal(await page.locator('.st-history-row article[data-session-index="1"]').count(),2,'latest of the active template remains visible even when a different template has newer workouts');
 assert.equal(await page.locator('.st-history-row article[data-session-index="8"]').count(),0,'blank latest of a different template is not pinned');
 await page.getByRole('button',{name:'Шаблон 1',exact:true}).click();
 assert.equal(await page.locator('.st-history-row article[data-session-index="8"]').count(),2);
 assert.equal(await page.locator('.st-history-row article[data-session-index="1"]').count(),0,'old blank workout stops being pinned outside its template');
 await page.getByRole('button',{name:'Шаблон 2',exact:true}).click();
 assert.equal(await page.locator('.st-history-row article[data-session-index="1"]').count(),2);
 assert.equal(templates.writes.length,0,'showing the latest blank workout never materializes records');
 await templates.context.close();
}
{
 const visibility=await open(768),page=visibility.page,id=guide[0].code,state=visibility.state;
 state.sets.filter(set=>set.exercise_id===id).forEach(set=>{for(const field of ['plan_weight','plan_reps','fact_weight','fact_reps','rpe'])set[field]='';set.completed=false;});
 state.session_exercises.filter(ex=>ex.exercise_id===id).forEach(ex=>ex.note='');
 function firstSet(index){return state.sets.find(set=>set.session_id===state.sessions[index].session_id&&set.exercise_id===id);}
 firstSet(0).plan_weight=0;
 firstSet(1).fact_weight=40;
 firstSet(2).rpe=7;
 firstSet(3).completed=true;
 state.session_exercises.find(ex=>ex.session_id===state.sessions[4].session_id&&ex.exercise_id===id).note='Только примечание';
 state.session_exercises.find(ex=>ex.session_id===state.sessions[6].session_id&&ex.exercise_id===id).note='   ';
 firstSet(7).plan_reps=10;
 firstSet(8).fact_reps=12;
 await page.reload();await page.locator('.st-view-toggle').waitFor();await page.locator('.st-view-toggle').click();
 assert.deepEqual(await page.locator('.st-history-row').first().locator('article').evaluateAll(cards=>cards.map(card=>Number(card.dataset.sessionIndex))),[0,1,2,3,4,7,8],'zero weight, fact-only, RPE-only, completed-only, note-only and repetition-only records survive; blanks and whitespace do not');
 assert.equal(visibility.writes.length,0);await visibility.context.close();
}
// Rotation returns to the latest workout while preserving drafts in older records.
{
 const responsive=await open(430),page=responsive.page;
 await page.getByRole('button',{name:'Выбрать тренировку №4',exact:true}).click();
 const record=page.locator('.st-history-row').first().locator('article[data-session-index="3"]');
 const draft=record.locator('input[data-field=planWeight]').first();
 await draft.focus();await draft.evaluate(()=>new Promise(resolve=>setTimeout(resolve,0)));await draft.fill('92');
 for(const width of [360,700,701,430]){
  await page.setViewportSize({width,height:900});
  await page.waitForFunction(({width})=>{const axis=document.querySelector('[data-axis=training]'),card=axis.querySelector('.st-history-row article:last-child').getBoundingClientRect(),box=axis.getBoundingClientRect();return width<=700?Math.abs(card.width-box.width)<1&&Math.abs(card.left-box.left)<1:card.left>=box.left-1&&card.right<=box.right+1;},{width});
  assert.equal(await draft.inputValue(),'92','rotation preserves the in-progress value at '+width);
  await assertDatesFollowColumns(page);
 }
 await draft.press('Tab');await page.waitForTimeout(550);
 const saved=responsive.writes.filter(write=>write.action==='saveSession').at(-1).session;
 assert.equal(saved.session_id,'middle-1');assert.equal(saved.exercises[0].sets[0].plan_weight,92);
 await page.locator('.st-view-toggle').click();const compact=await entryGeometry(page);
 await page.setViewportSize({width:1440,height:900});await page.waitForTimeout(80);
 assert.deepEqual(await entryGeometry(page),compact,'packed fields stay compact when the viewport grows');
 await responsive.context.close();
}
// Test actual administrative shell geometry and Back integration, not a fake wrapper.
for(const width of [360,430,700,701,760,761,768,1440]){
 const managed=await open(width,true,false,false,false,false,true),mp=managed.page;
 await mp.locator('.admin-strength-toolbar').waitFor();
 assert.equal(await mp.locator('.admin-managed-app-select').count(),0);
 assert.equal(await mp.locator('.admin-managed-back').getAttribute('href'),'/admin/strength');
 assert.equal(await mp.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
 const available=await mp.locator('#admin-content').evaluate(e=>e.clientWidth),appWidth=await mp.locator('#strength-app').evaluate(e=>e.clientWidth);
 assert(Math.abs(available-appWidth)<2,'managed journal fills admin workspace at '+width);
 if(width<=700){
  const full=await mp.locator('[data-axis=training]').evaluate(axis=>Math.abs(axis.clientWidth-axis.querySelector('article').getBoundingClientRect().width)<1);
  assert(full,'managed phone uses the same full-width filling layout');
 }
 const historyReads=()=>managed.readRequests.filter(r=>r.catalog_only!=='1').length;
 const reads=historyReads();
 await mp.locator('.st-exercise-info').last().click();await mp.goBack();await mp.locator('.st-guide-header').waitFor({state:'detached'});
 assert.equal(historyReads(),reads,'internal Back never reloads the managed profile');
 if(width===430){
  await mp.getByRole('button',{name:'Статистика',exact:true}).click();await mp.reload();
  await mp.getByRole('button',{name:'Вернуться к тренировкам'}).waitFor();
  const afterReload=historyReads();
  await mp.goBack();await mp.locator('.st-view-toggle').waitFor();assert(!new URL(mp.url()).searchParams.has('view'));
  assert.equal(historyReads(),afterReload,'Back after statistics reload restores the journal internally');
  await mp.goForward();await mp.getByRole('button',{name:'Вернуться к тренировкам'}).waitFor();
  await mp.getByRole('button',{name:'Вернуться к тренировкам'}).click();await mp.locator('.st-view-toggle').waitFor();
 }
 await mp.setViewportSize({width,height:400});await mp.evaluate(()=>scrollTo(0,220));
 const toolbar=await mp.locator('.admin-strength-toolbar').boundingBox(),journal=await mp.locator('.st-session-sticky').boundingBox();
 assert(Math.abs(toolbar.y)<1,'admin context remains at the top');assert(Math.abs(journal.y-toolbar.height)<2,'journal is pinned immediately below admin context');
 await mp.screenshot({path:`${out}/real-admin-${width}.png`});await managed.context.close();
}
// Both comment categories use one shared pop-up and independent persisted fields.
for(const width of [360,430,768,1440]){
 const comments=await open(width,true),page=comments.page;
 const card=page.locator('.st-history-row').first().locator('article').last();
 const note=card.getByRole('button',{name:'Примечание к упражнению'});
 assert.equal((await note.innerText()).trim(),'Добавить примечание');
 await note.click();
 assert.equal(await page.getByRole('textbox',{name:'Ваш комментарий',exact:true}).inputValue(),'');
 assert.equal(await page.getByRole('textbox',{name:'Комментарий тренера',exact:true}).inputValue(),'');
 assert.equal(await page.locator('.st-modal-sub').count(),0,'no redundant note subtitle');
 const userText='Самочувствие <img src=x onerror=alert(1)>\nВторая строка';
 const coachText='Рекомендация тренера\n'+ 'Полный текст сохраняется. '.repeat(12);
 await page.getByRole('textbox',{name:'Ваш комментарий',exact:true}).fill(userText);
 await page.getByRole('button',{name:'Сохранить',exact:true}).click();await page.waitForTimeout(550);
 assert(await note.evaluate(e=>e.classList.contains('has-note')));
 await note.click();
 await page.getByRole('textbox',{name:'Комментарий тренера',exact:true}).fill(coachText);
 await page.screenshot({path:`${out}/comments-dialog-${width}.png`});
 await page.getByRole('button',{name:'Сохранить',exact:true}).click();await page.waitForTimeout(550);
 assert.equal(await note.locator('span').count(),2);
 assert.equal(await note.locator('img').count(),0,'comment text is escaped');
 assert.equal(await note.locator('.st-user-note').textContent(),userText);
 const latest=comments.writes.filter(w=>w.action==='saveSession').at(-1).session;
 assert.equal(latest.exercises[0].note,userText);assert.equal(latest.exercises[0].coach_note,coachText);
 assert.equal(latest.session_id,'three','comments save into their own workout');
 const stored=comments.state.session_exercises.find(ex=>ex.session_id===latest.session_id&&ex.exercise_id===latest.exercises[0].exercise_id);
 stored.note=latest.exercises[0].note;stored.coach_note=latest.exercises[0].coach_note;
 await page.reload();await page.locator('.st-view-toggle').waitFor();
 assert(await note.evaluate(e=>e.classList.contains('both-notes')),'both persisted categories are restored from getWorkout');
 assert(await note.evaluate(e=>{const spans=[...e.querySelectorAll('span')],r=e.getBoundingClientRect();return spans.every(s=>{const b=s.getBoundingClientRect();return b.left>=r.left&&b.right<=r.right&&getComputedStyle(s).textOverflow==='ellipsis';})}));
 await page.screenshot({path:`${out}/comments-both-${width}.png`});
 await note.click();
 assert.equal(await page.getByRole('textbox',{name:'Ваш комментарий',exact:true}).inputValue(),userText);
 assert.equal(await page.getByRole('textbox',{name:'Комментарий тренера',exact:true}).inputValue(),coachText);
 await page.getByRole('textbox',{name:'Ваш комментарий',exact:true}).fill('');
 await page.getByRole('button',{name:'Сохранить',exact:true}).click();await page.waitForTimeout(550);
 assert(await note.evaluate(e=>e.classList.contains('coach-note')));
 await page.getByRole('button',{name:'Отменить действие',exact:true}).click();await page.waitForTimeout(550);
 assert(await note.evaluate(e=>e.classList.contains('both-notes')),'undo restores both categories');
 await page.getByRole('button',{name:'Повторить действие',exact:true}).click();await page.waitForTimeout(550);
 assert(await note.evaluate(e=>e.classList.contains('coach-note')));
 assert.equal(await card.getByRole('button',{name:'Добавить подход',exact:true}).getAttribute('title'),'Добавить подход');
 await page.locator('.st-view-toggle').click();
 const coachOnly=page.locator('.st-history-row').first().locator('article[data-session-index="8"]');
 assert.equal(await coachOnly.count(),1,'a coach-only record remains in packed history');
 assert.equal(await coachOnly.locator('.st-coach-note').textContent(),coachText.trim());
 await coachOnly.getByRole('button',{name:'Примечание к упражнению'}).click();
 assert.equal(await page.getByRole('textbox',{name:'Комментарий тренера',exact:true}).inputValue(),coachText);
 assert.equal(await page.getByRole('textbox',{name:'Ваш комментарий',exact:true}).inputValue(),'');
 await comments.context.close();
}
// Unsaved or failed changes must never send the older stored plan.
{
 const unsaved=await open(430),page=unsaved.page,releaseSave=unsaved.holdNextSessionSave();unsaved.failNextSessionSave();
 const savedRequest=page.waitForRequest(request=>request.url().endsWith('/api/apps/strength')&&request.method()==='POST'&&request.postDataJSON().action==='saveSession');
 const field=page.locator('.st-history-row').first().locator('article').last().locator('[data-field=planWeight]').first();
 await field.focus();await field.evaluate(()=>new Promise(resolve=>setTimeout(resolve,0)));await field.fill('71');await field.press('Tab');
 const send=page.getByRole('button',{name:'Отправить план тренировки №9',exact:true});
 assert(await send.isDisabled(),'pending autosave blocks delivery');
 await savedRequest;assert(await send.isDisabled(),'in-flight save blocks delivery');assert.equal(unsaved.telegramWrites.length,0);
 releaseSave();await page.waitForFunction(()=>document.querySelector('#st-save-state').classList.contains('error'));
 assert(await send.isDisabled(),'save error blocks delivery');
 await page.evaluate(()=>ST.sendTelegram(8));assert.equal(unsaved.telegramWrites.length,0,'handler cannot send stale stored data after save failure');
 await unsaved.context.close();
}
// Scaling preserves whole-workout column width, but scales every compact-column proportion.
for(const width of [360,430,701,768,1440]){
 const scaled=await open(width),page=scaled.page;
 const column=page.locator('.st-history-row article').last();
 const before=await column.boundingBox();const rowBefore=await column.locator('.st-grid-set').first().boundingBox();
 await page.locator('.st-scale-button').selectOption('105');
 const after=await column.boundingBox();const rowAfter=await column.locator('.st-grid-set').first().boundingBox();
 assert(Math.abs(before.width-after.width)<1,'whole view keeps physical column width at '+width);
 assert(rowAfter.height>rowBefore.height,'whole view gains vertical size');
 await page.screenshot({path:`${out}/scale-training-105-${width}.png`});
 await page.locator('.st-view-toggle').click();const compactBefore=await column.boundingBox();
 await page.locator('.st-scale-button').selectOption('110');const compactAfter=await column.boundingBox();
 assert(Math.abs(compactAfter.width/compactBefore.width-110/105)<.01,'compact columns scale proportionally');
 assert.equal(await page.locator('.st-scale-button').inputValue(),'110');
 await page.screenshot({path:`${out}/scale-packed-110-${width}.png`});
 await page.reload();assert.equal(await page.locator('.st-scale-button').inputValue(),'110','scale preference survives reload');
 assert.equal(await page.locator('.st-scale-button option').count(),21);
 await page.locator('.st-view-toggle').click();
 const compactAt110=await column.boundingBox();
 await page.locator('.st-scale-button').selectOption('50');
 const compactAt50=await column.boundingBox();
 assert(Math.abs(compactAt50.width/compactAt110.width-50/110)<.01,'compact view really shrinks below100%');
 await page.screenshot({path:`${out}/scale-packed-before-reload-50-${width}.png`});
 assert.equal(await page.locator('.st-scale-button').inputValue(),'50');
 await page.reload();assert.equal(await page.locator('.st-scale-button').inputValue(),'50');
 const wholeAt50=await column.boundingBox(),rowAt50=await column.locator('.st-grid-set').first().boundingBox();
 assert(Math.abs(wholeAt50.width-before.width)<1,'shrinking whole view preserves column width');
 assert(rowAt50.height<rowBefore.height,'whole view really shrinks vertically below100%');
 await page.screenshot({path:`${out}/scale-packed-50-${width}.png`});
 await page.locator('.st-scale-button').selectOption('150');
 assert.equal(await page.locator('.st-scale-button').inputValue(),'150');
 await page.evaluate(()=>{localStorage.setItem('edabalans-strength-scale','200');});
 await page.reload();assert.equal(await page.locator('.st-scale-button').inputValue(),'150','old larger scale clamps to supported maximum');
 await page.evaluate(()=>ST.resetScale());
 for(let i=0;i<3;i++){await page.getByRole('button',{name:'Новая тренировка',exact:true}).click();await page.waitForTimeout(150);}
 await page.locator('.st-view-toggle').click();
 for(const index of [9,10,11])assert.equal(await page.locator('.st-history-row article[data-session-index="'+index+'"]').count(),2,'every newly created empty workout stays available');
 assert.equal(scaled.writes.filter(w=>w.action==='saveSession').length,3);
 await page.screenshot({path:`${out}/scale-and-blank-${width}.png`});
 await scaled.context.close();
}

// A rejected fetch and an unanswered request retain edits and recover via the visible retry action.
for(const failure of ['network','timeout']){
 const retry=await open(430),page=retry.page;await page.clock.install();
 if(failure==='network')retry.failNextTransport();else retry.timeoutNextSave();
 const input=page.locator('.st-history-row article').last().locator('input[data-field=planWeight]').first();
 await input.fill('95');await input.press('Tab');await page.clock.runFor(460);
 if(failure==='timeout')await page.clock.fastForward(20001);
 await page.locator('#st-save-state.error').waitFor();assert.equal(await input.inputValue(),'95');
 assert.match(await page.locator('#st-save-state').textContent(),failure==='network'?/Нет связи/:/не ответил вовремя/);
 await page.getByRole('button',{name:'Повторить',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('#st-save-state').textContent==='Сохранено');
 const saved=retry.writes.filter(w=>w.action==='saveSession').at(-1);
 assert.equal(saved.session.exercises[1].sets[0].plan_weight,95);assert.equal(saved.session.session_id,'three');
 assert.equal(retry.telegramWrites.length,0);await retry.context.close();
}
// At the largest supported scale normal three-digit weights stay readable in the fixed-width view.
for(const width of [360,430,701,768,1440]){
 const large=await open(width),page=large.page;
 await page.locator('.st-scale-button').selectOption('150');
 assert.equal(await page.locator('.st-scale-button').inputValue(),'150');
 const input=page.locator('.st-history-row article').last().locator('input[data-field=planWeight]').first();await input.fill('100');
 const fit=await input.evaluate(input=>{const style=getComputedStyle(input),ctx=document.createElement('canvas').getContext('2d');ctx.font=style.font;return input.clientWidth-parseFloat(style.paddingLeft)-parseFloat(style.paddingRight)>=ctx.measureText(input.value).width;});
 assert(fit,'three-digit weight fits at150% '+width);assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
 await page.screenshot({path:`${out}/scale-training-150-${width}.png`});
 await page.locator('.st-view-toggle').click();assert.equal(await page.locator('.st-view-toggle').getAttribute('aria-pressed'),'true','first click after numeric edit must switch view');
 await page.screenshot({path:`${out}/scale-packed-150-${width}.png`});
 const rpe=page.locator('article[data-session-index="0"]').first().locator('.st-rpe-button').first();await rpe.click();
 const popup=await page.locator('.st-rpe-floating').boundingBox();assert(popup.x>=0 && popup.y>=0 && popup.x+popup.width<=width && popup.y+popup.height<=900,'scaled RPE menu stays in viewport');
 await page.screenshot({path:`${out}/scale-rpe-150-${width}.png`});await page.locator('.st-rpe-option').first().click();
 await large.context.close();
}

// Mobile feedback: secondary screens fill the viewport at every journal scale.
for(const width of [360,430,700,701,768,1440]){
 const trial=await open(width),page=trial.page;
 assert.equal(await page.getByRole('button',{name:'Как пользоваться',exact:true}).textContent(),'?');
 const emailAt100=await page.locator('.st-top-email').evaluate(el=>parseFloat(getComputedStyle(el).fontSize));
 for(const scale of [50,80,150]){
  if(await page.locator('.st-view-toggle').getAttribute('aria-pressed')==='false')await page.locator('.st-view-toggle').click();
  await page.locator('.st-scale-button').selectOption(String(scale));
  const effectiveEmail=await page.locator('.st-top-email').evaluate(el=>parseFloat(getComputedStyle(el).fontSize)*Number(el.closest('#strength-app').style.zoom));
  assert(Math.abs(effectiveEmail-emailAt100)<.1,'email font stays fixed');
  await page.locator('.st-exercise-info').last().click();
  const full=await page.locator('.st-exercise-guide').boundingBox();
  const layoutWidth=await page.evaluate(()=>document.body.clientWidth);
  assert(Math.abs(full.x)<1&&Math.abs(full.y)<1&&Math.abs(full.width-layoutWidth)<1&&Math.abs(full.height-900)<1,'exercise details fill the layout viewport, excluding a reserved scrollbar, at '+scale+'% '+width);
  if(width===430&&scale===80)await page.screenshot({path:`${out}/guide-fullscreen-80-430.png`});
  await page.getByRole('button',{name:'Закрыть информацию об упражнении'}).click();
  await page.getByRole('button',{name:'Статистика',exact:true}).click();
  assert.equal(await page.locator('#strength-app').evaluate(el=>Number(el.style.zoom)),1);
  await page.getByRole('button',{name:'Вернуться к тренировкам'}).click();
 }
 await page.locator('.st-scale-button').selectOption('100');
 await page.screenshot({path:`${out}/header-mobile-${width}.png`});await trial.context.close();
}
// A background catalogue cannot delay or overwrite the usable first template.
{
 const trial=await open(430,false,false,false,false,false,false,false,true),page=trial.page;
 assert(await page.locator('.st-history-row').first().isVisible());
 assert.equal(trial.readRequests.filter(r=>r.initial==='1').length,1);
 assert.equal(trial.readRequests.filter(r=>r.type==='1'&&!r.initial).length,0,'no repeated first-template request');
 await page.getByRole('button',{name:'Шаблон 2',exact:true}).click();await page.locator('.st-template-loading').waitFor();
 trial.releaseCatalogueReads();await page.locator('.st-history-row').first().waitFor();
 assert(trial.readRequests.filter(r=>r.catalog_only==='1').length>=1);
 assert.equal(trial.writes.length,0);await trial.context.close();
}
// A stale catalogue read is retried after editing the account catalogue in the first template.
{
 const trial=await open(430,false,false,false,false,false,false,false,true),page=trial.page;
 await page.waitForFunction(()=>document.querySelector('.st-history-row'));
 await page.waitForTimeout(60);
 await page.getByRole('button',{name:'Управление шаблонами',exact:true}).click();
 await page.getByRole('button',{name:'Состав упражнений шаблона 1',exact:true}).click();
 await page.getByPlaceholder('Название своего упражнения').fill('Своё упражнение после старого чтения');
 await page.getByRole('button',{name:'Добавить своё',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('#st-manager-save-state')?.textContent==='Сохранено');
 assert(trial.writes.some(w=>w.action==='saveExerciseCatalog'));
 await page.getByRole('button',{name:'Закрыть',exact:true}).click();
 await page.getByRole('button',{name:'Готово',exact:true}).click();
 trial.releaseCatalogueReads();
 await page.getByRole('button',{name:'Шаблон 2',exact:true}).click();
 await page.locator('.st-template-loading').waitFor({state:'detached'});
 await page.getByRole('button',{name:'Управление шаблонами',exact:true}).click();
 await page.getByRole('button',{name:'Состав упражнений шаблона 2',exact:true}).click();
 assert(await page.locator('.st-manager-row').filter({hasText:'Своё упражнение после старого чтения'}).isVisible());
 assert(trial.readRequests.filter(r=>r.catalog_only==='1'&&r.type==='2').length>=2,'old snapshot is discarded and re-read');
 await trial.context.close();
}
// Plan field tint compares with the last actual execution across templates, not the old plan.
{
 const trial=await open(430),page=trial.page;
 const previous=trial.state.sets.filter(s=>s.session_id==='two');previous.forEach(s=>{s.fact_weight=70;s.fact_reps=9;});
 await page.reload();await page.locator('.st-view-toggle').waitFor();
 const card=page.locator('.st-history-row').first().locator('article').last();
 const weight=card.locator('[data-field=planWeight]').first(),reps=card.locator('[data-field=planReps]').first();
 await weight.fill('72');await weight.press('Tab');await page.waitForTimeout(550);
 await reps.fill('8');await reps.press('Tab');await page.waitForTimeout(550);
 assert(await weight.evaluate(el=>el.classList.contains('plan-up')));assert(await reps.evaluate(el=>el.classList.contains('plan-down')));
 assert.equal(await weight.evaluate(el=>getComputedStyle(el).backgroundColor),'rgb(233, 243, 255)');assert.equal(await reps.evaluate(el=>getComputedStyle(el).backgroundColor),'rgb(238, 240, 243)');
 await page.locator('.st-app-icon').click();
 await page.screenshot({path:`${out}/plan-comparison-430.png`});
 await weight.fill('70');await weight.press('Tab');await page.waitForTimeout(550);assert.equal(await weight.getAttribute('class'),'');
 await page.evaluate(()=>ST.renameTemplate(1,'Верх'));await page.waitForTimeout(100);await page.evaluate(()=>ST.renameTemplate(2,'Низ'));await page.waitForTimeout(100);
 await page.getByRole('button',{name:'Статистика',exact:true}).click();
 const legend=await page.locator('.st-calendar-legend').textContent();assert(legend.includes('Верх')&&legend.includes('Низ'));
 assert(!/Т[123] №/.test(await page.locator('.st-cal-workout').first().textContent()));
 await page.screenshot({path:`${out}/calendar-template-names-430.png`});await trial.context.close();
}
// Delivery has an explicit cancellable dialog and respects the selected view's scope.
{
 const trial=await open(430),page=trial.page;
 await page.getByRole('button',{name:'Отправить план тренировки №1',exact:true}).click();
 await page.getByRole('dialog',{name:'Отправка плана'}).waitFor();assert.equal(trial.telegramWrites.length,0);
 await page.getByRole('button',{name:'Отменить',exact:true}).click();assert.equal(trial.telegramWrites.length,0);
 await page.locator('.st-view-toggle').click();
 const card=page.locator('.st-history-row').first().locator('article[data-session-index="0"]');
 await card.getByRole('button',{name:'Отправить план упражнения',exact:true}).click();
 await page.screenshot({path:`${out}/confirm-exercise-delivery-430.png`});
 assert((await page.locator('.st-modal-sub').textContent()).includes(trial.state.exercise_catalog[0].exercise_name));
 await page.getByRole('button',{name:'Отправить',exact:true}).click();await page.locator('.st-delivery-notice').waitFor();
 assert.equal(trial.telegramWrites.length,1);assert.equal(trial.telegramWrites[0].exercise_id,trial.state.exercise_catalog[0].exercise_id);
 assert((await page.locator('.st-delivery-notice').textContent()).includes('План упражнения'));
 await trial.context.close();
}
// End mobile feedback.

// Shared journal, with coach controls only for the managed account; selector stays outside.
const plain=await open(768),admin=await open(768,true);
assert.equal(await plain.page.locator('.st-history-row article').count(),await admin.page.locator('.st-history-row article').count());
assert.equal(await plain.page.locator('.st-progression-trigger').count(),0);
assert((await admin.page.locator('.st-progression-trigger').count())>0);
assert.equal(await admin.page.locator('#strength-app .preview-account').count(),0);
assert.equal(await admin.page.locator('.preview-account').count(),1);
for(const page of [plain.page,admin.page]){const account=page.getByRole('link',{name:'Личный кабинет',exact:true});assert.equal(await account.getAttribute('href'),'/lk');assert.equal(await account.locator('svg').count(),1,'shared account control uses the standard icon');}
assert.equal(await plain.page.locator('[data-strength-telegram-export]').count(),0);
assert.equal(await admin.page.locator('[data-strength-telegram-export]').count(),0,'old external export control is replaced');

await admin.page.getByRole('button',{name:'Отправить план тренировки №1',exact:true}).click();await admin.page.getByRole('button',{name:'Отправить',exact:true}).click();await admin.page.locator('.st-delivery-notice').waitFor();
assert.equal(admin.telegramWrites.length,1);assert.equal(admin.telegramWrites[0].target_user_id,'fixture');assert.equal(admin.telegramWrites[0].session_id,'one');
assert.equal(await admin.page.locator('.st-session-number[aria-pressed=true]').textContent(),'№9','sending another column does not select or send the last workout');

await plain.page.getByRole('button',{name:'Отправить план тренировки №1',exact:true}).click();await plain.page.getByRole('button',{name:'Отправить',exact:true}).click();await plain.page.locator('.st-delivery-notice').waitFor();
assert.equal(plain.telegramWrites.length,1);assert.equal(plain.telegramWrites[0].session_id,'one');assert(!('target_user_id' in plain.telegramWrites[0]));
for(const body of [plain.telegramWrites[0],admin.telegramWrites[0]])assert.match(body.request_id,/^[0-9a-f-]{36}$/);
const releaseDelivery=plain.holdNextDelivery();plain.failNextDelivery();

await plain.page.getByRole('button',{name:'Отправить план тренировки №1',exact:true}).click();
await plain.page.getByRole('button',{name:'Отправить',exact:true}).click();
await plain.page.waitForFunction(()=>[...document.querySelectorAll('[data-strength-send-plan]')].every(button=>button.disabled));
assert.equal(plain.telegramWrites.length,2);releaseDelivery();
await plain.page.locator('.st-delivery-notice.error').waitFor();assert.match(await plain.page.locator('.st-delivery-notice.error').textContent(),/Основной мессенджер не подключён/);
await plain.page.waitForFunction(()=>!document.querySelector('[data-strength-send-plan]').disabled);
assert.equal(plain.telegramWrites.length,2,'delivery errors are never retried automatically');

await admin.page.screenshot({path:`${out}/managed-768.png`});
await plain.context.close();await admin.context.close();
assert.deepEqual(errors,[]);
await writeFile(`${out}/report.json`,JSON.stringify({rows,status:'pass'},null,2));
await browser.close();console.log('PASS: whole/packed history, shared scroll, shared admin UI, date gate, copy/paste, completion, undo, cursor and templates');
