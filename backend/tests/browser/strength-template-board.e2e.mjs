import assert from 'node:assert/strict';
import {readFile,mkdir,writeFile} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
import path from 'node:path';
const engine=process.env.QA_BROWSER||'chromium';
const {[engine]:browserType}=await import(pathToFileURL(path.join(process.env.CODEX_NODE_MODULES,'playwright/index.mjs')).href);
const root=new URL('../../app/static/',import.meta.url),html=await readFile(new URL('apps/strength.html',root),'utf8');
const guides=JSON.parse(await readFile(new URL('../../app/strength_exercise_guides.json',import.meta.url),'utf8')).slice(0,16);
const ids=guides.map(g=>g.code),out=process.env.QA_OUT;assert(out);await mkdir(out,{recursive:true});
const browser=await browserType.launch(),results=[];
async function open(width,managed=false,options={}){
 const context=await browser.newContext({viewport:{width,height:1000},hasTouch:width<=700}),page=await context.newPage();page.setDefaultTimeout(15000);
 const errors=[],writes=[],history=[{session_id:'old',session_number:1,workout_type:1,date:'2026-11-20'},
  {session_id:'archived',session_number:2,workout_type:4,date:'2026-11-19'}];
 const types=[{workout_type:1,title:'Верх',active:true,sort_order:1},{workout_type:2,title:'Низ',active:true,sort_order:2},{workout_type:3,title:'Пустой',active:true,sort_order:3},{workout_type:4,title:'Архив',active:false,sort_order:4}];
 let lists={1:ids.slice(0,options.longList?14:6),2:ids.slice(5,9),3:[]},version=1,failRead=!!options.failRead,failSave=false,conflict=false,hold=null,release,concurrent=0;
 const sourceHistory=JSON.stringify(history);
 page.on('pageerror',error=>errors.push(error.message));
 await page.route('**/*',async route=>{
  const url=new URL(route.request().url());if(url.hostname!=='127.0.0.1')return route.abort();
  if(options.moduleFail&&url.pathname==='/assets/strength-template-board.js')return route.abort();
  if(url.pathname==='/template-board-fixture')return route.fulfill({contentType:'text/html',body:'<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{margin:0;background:#f5f5f7}main{max-width:1420px;margin:auto}</style><main><script>window.EdabalansIdentity={source:"native",email:"board@example.test"};window.EdabalansAppContext='+JSON.stringify(managed?{mode:'admin',targetUserId:'fixture',accountUrl:'/lk'}:{accountUrl:'/lk'})+';</script>'+html+'</main>'});
  if(url.pathname==='/api/apps/strength'){
   const request=route.request(),data=request.method()==='POST'?JSON.parse(request.postData()):Object.fromEntries(url.searchParams);
   const response={ok:true,version,user:{user_id:'fixture',email:'board@example.test',can_coach:managed,can_calculate_progression:managed}};
   if(data.action==='getWorkout'){
    if(failRead&&Number(data.type)===2)return route.fulfill({json:{ok:false,error:'SYNTHETIC_CATALOG_ERROR'}});
    const type=Number(data.type)||1,selected=lists[type]||[];
    response.workout={selected_type:type,version,workout_types:structuredClone(types),sessions:structuredClone(history),
     exercise_catalog:guides.map((g,i)=>({exercise_id:g.code,exercise_name:g.name,full_name:g.full_name,short_name:g.short_name,source:'base',catalog_active:true,active:selected.includes(g.code),sort_order:selected.includes(g.code)?selected.indexOf(g.code)+1:100+i,guide:g.guide})),
     session_exercises:[{session_id:'old',exercise_id:ids[0],exercise_name:guides[0].name,sort_order:1}],
     sets:[{session_id:'old',exercise_id:ids[0],set_number:1,plan_weight:35,plan_reps:12,fact_weight:35,fact_reps:13,rpe:8}]};
   }
   if(request.method()==='POST'){
    writes.push(structuredClone(data));assert.equal(data.action,'saveWorkoutTypes','board edits never rewrite workout snapshots');
    assert.equal(++concurrent,1,'versioned writes are serialized');if(hold)await hold;
    if(failSave){failSave=false;concurrent--;return route.fulfill({json:{ok:false,error:'SYNTHETIC_SAVE_ERROR'}});}
    if(conflict||data.version!==version){conflict=false;concurrent--;return route.fulfill({json:{ok:false,error:'STRENGTH_STATE_CONFLICT'}});}
    assert.deepEqual(data.template_exercises.map(t=>t.workout_type).sort(),data.workout_types.filter(t=>t.active!==false).map(t=>t.workout_type).sort());
    for(const t of data.template_exercises){assert.equal(new Set(t.exercise_ids).size,t.exercise_ids.length);lists[t.workout_type]=t.exercise_ids.slice();}
    types.splice(0,types.length,...structuredClone(data.workout_types));version++;response.version=version;response.workout_types=types;concurrent--;
   }
   assert.equal(JSON.stringify(history),sourceHistory);
   return route.fulfill({json:response});
  }
  const asset=new URL(url.pathname.replace(/^\/assets\//,''),root);
  if(!asset.href.startsWith(root.href))return route.abort();
  try{return route.fulfill({contentType:({'.html':'text/html','.css':'text/css','.js':'text/javascript','.mjs':'text/javascript','.woff2':'font/woff2','.svg':'image/svg+xml','.png':'image/png','.webp':'image/webp'})[path.extname(asset.pathname)]||'application/octet-stream',body:await readFile(asset)});}catch{return route.abort();}
 });
 await page.goto('http://127.0.0.1:8823/template-board-fixture');await page.locator('.st-view-toggle').waitFor();await page.evaluate(()=>document.fonts.ready);
 await page.getByRole('button',{name:'Управление шаблонами',exact:true}).click();
 if(options.moduleFail)await page.getByRole('button',{name:'Обновить страницу',exact:true}).waitFor();
 else if(options.failRead)await page.getByText('SYNTHETIC_CATALOG_ERROR').waitFor();else await page.locator('[data-board-list="3"]').waitFor();
 return {page,context,writes,errors,get lists(){return structuredClone(lists);},get version(){return version;},
  failNext:()=>{failSave=true;},externalEdit:()=>{version++;conflict=true;},
  holdNext:()=>{hold=new Promise(resolve=>{release=()=>{hold=null;resolve();};});return ()=>release();},
  failCatalog:()=>{failRead=true;},allowCatalog:()=>{failRead=false;}};
}
function list(page,type){return page.locator('[data-board-list="'+type+'"]');}
async function entries(page,type){return list(page,type).locator('[data-board-exercise]').evaluateAll(rows=>rows.map(row=>row.dataset.boardExercise));}
async function exerciseRow(page,type,id){return list(page,type).locator('[data-board-exercise]').evaluateAll((rows,id)=>rows.findIndex(r=>r.dataset.boardExercise===id),id).then(index=>{assert(index>=0);return list(page,type).locator('[data-board-exercise]').nth(index);});}
async function saved(page){await page.waitForFunction(()=>document.querySelector('#st-template-board-status')?.textContent==='Сохранено');}
async function drag(page,from,id,to,before,touch=false,cancel=false,capture=null){
 const source=await exerciseRow(page,from,id);await source.locator('[data-board-handle]').scrollIntoViewIfNeeded();
 const start=await source.locator('[data-board-handle]').boundingBox(),board=page.locator('.st-template-board');
 const cdp=touch?await page.context().newCDPSession(page):null;
 const move=async(x,y)=>{if(cdp)await cdp.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x,y,id:1}]});else await page.mouse.move(x,y);};
 if(cdp)await cdp.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x:start.x+start.width/2,y:start.y+start.height/2,id:1}]});else {await page.mouse.move(start.x+start.width/2,start.y+start.height/2);await page.mouse.down();}
 await move(start.x+start.width/2+8,start.y+start.height/2+8);await page.locator('.st-board-ghost').waitFor();
 const frame=await board.boundingBox(),target=list(page,to),targetBox=await target.boundingBox();
 if(targetBox.x>=frame.x+frame.width-25){
  await move(frame.x+frame.width-5,Math.min(frame.y+200,frame.y+frame.height-45));
  await page.waitForFunction(type=>{const b=document.querySelector('.st-template-board').getBoundingClientRect(),t=document.querySelector('[data-board-list="'+type+'"]').getBoundingClientRect();return t.left<b.left+45;},to);
 }
 const destination=before?await (await exerciseRow(page,to,before)).boundingBox():await target.boundingBox();
 if(destination.y+destination.height>frame.y+frame.height-30){
  await move(Math.min(frame.x+frame.width-40,Math.max(frame.x+40,destination.x+destination.width/2)),frame.y+frame.height-5);
  await page.waitForFunction(({type,id})=>{const board=document.querySelector('.st-template-board'),b=board.getBoundingClientRect(),list=document.querySelector('[data-board-list="'+type+'"]');const row=id?[...list.querySelectorAll('[data-board-exercise]')].find(e=>e.dataset.boardExercise===id):list;return row.getBoundingClientRect().bottom<b.bottom-70||board.scrollTop>=board.scrollHeight-board.clientHeight-1;},{type:to,id:before});
 }
 for(let i=0;i<3;i++){
  const box=before?await (await exerciseRow(page,to,before)).boundingBox():await target.boundingBox();
  await move(Math.max(frame.x+20,Math.min(box.x+box.width/2,frame.x+frame.width-20)),before?box.y+6:Math.max(frame.y+150,Math.min(box.y+box.height-18,frame.y+frame.height-50)));
  await page.waitForTimeout(45);
 }
 assert.equal(await page.locator('.st-template-drop-slot').count(),1,'insertion slot is visible before dropping');
 if(capture)await page.screenshot({path:path.join(out,capture)});
 if(cancel){if(cdp)await cdp.send('Input.dispatchTouchEvent',{type:'touchCancel',touchPoints:[]});else await page.keyboard.press('Escape');}
 if(cdp){if(!cancel)await cdp.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});await cdp.detach();}else await page.mouse.up();
 await page.locator('.st-board-ghost').waitFor({state:'detached'});
}
try{
 const widths=process.env.QA_WIDTHS?process.env.QA_WIDTHS.split(',').map(Number):[360,430,700,701,768,1440,1919];
 for(const width of widths)for(const managed of (width===430||width===1440?[false,true]:[false])){
  const test=await open(width,managed),{page}=test,touch=engine==='chromium'&&width<=700;
  await page.screenshot({path:path.join(out,`${engine}-${width}-${managed?'managed':'self'}-board.png`)});
  assert.equal(await page.locator('[data-board-column]').count(),3);
  const before=test.writes.length;
  await drag(page,1,ids[0],1,ids[3],touch,false,`${engine}-${width}-${managed?'managed':'self'}-within-drag.png`);await saved(page);
  assert.deepEqual(await entries(page,1),[ids[1],ids[2],ids[0],ids[3],ids[4],ids[5]]);
  await drag(page,1,ids[0],2,ids[7],touch,false,`${engine}-${width}-${managed?'managed':'self'}-cross-drag.png`);await saved(page);
  assert.deepEqual(await entries(page,2),[ids[5],ids[6],ids[0],ids[7],ids[8]]);
  await drag(page,1,ids[5],2,ids[7],touch);await saved(page);
  assert.deepEqual(await entries(page,2),[ids[6],ids[0],ids[5],ids[7],ids[8]],'existing destination exercise is repositioned, not duplicated');
  await drag(page,2,ids[0],3,null,touch);await saved(page);assert.deepEqual(await entries(page,3),[ids[0]]);
  const cancelled=test.writes.length;await drag(page,3,ids[0],3,null,touch,true);assert.equal(test.writes.length,cancelled);assert.equal(await page.getByRole('dialog',{name:'Шаблоны',exact:true}).count(),1);
  const column=page.locator('[data-board-column="3"]');await column.getByRole('button',{name:'Добавить упражнение',exact:false}).click();
  if(width===430&&!managed){
   await page.setViewportSize({width,height:500});await page.waitForTimeout(100);
   const dropdown=await column.locator('[data-board-results]').boundingBox(),viewport=await page.locator('.st-template-board').boundingBox();
   await page.screenshot({path:path.join(out,engine+'-search-short-viewport.png')});
   assert(dropdown.y>=viewport.y&&dropdown.y+dropdown.height<=viewport.y+viewport.height,'dropdown remains usable when the keyboard reduces available height: '+JSON.stringify({dropdown,viewport}));
   await page.setViewportSize({width,height:1000});
  }
  const search=column.locator('[data-board-search]');await search.fill(guides[10].name);
  assert(await column.locator('[data-board-results] button').count()>0);await page.screenshot({path:path.join(out,`${engine}-${width}-${managed?'managed':'self'}-search.png`)});
  await column.locator('[data-board-add-id="'+ids[10]+'"]').click();await saved(page);
  assert((await entries(page,3)).includes(ids[10]));
  const escape=column.locator('[data-board-search]');await escape.press('Escape');assert.equal(await page.getByRole('dialog',{name:'Шаблоны',exact:true}).count(),1);
  const order=await entries(page,3),last=await exerciseRow(page,3,order.at(-1));await last.locator('[data-board-handle]').focus();await page.keyboard.press('ArrowUp');await saved(page);
  assert.deepEqual(await entries(page,3),order.slice().reverse());
  const keyboard=order.at(-1);await (await exerciseRow(page,3,keyboard)).locator('[data-board-handle]').focus();await page.keyboard.press('ArrowLeft');await saved(page);
  assert(!(await entries(page,3)).includes(keyboard));assert((await entries(page,2)).includes(keyboard));
  await page.keyboard.press('ArrowRight');await saved(page);assert.deepEqual(await entries(page,3),order.slice().reverse());
  if(width===1440&&managed){
   const queueStart=test.writes.length,release=test.holdNext(),moving=(await entries(page,3))[0];
   await (await exerciseRow(page,3,moving)).locator('[data-board-handle]').focus();await page.keyboard.press('ArrowDown');
   await (await exerciseRow(page,3,moving)).locator('[data-board-handle]').focus();await page.keyboard.press('ArrowUp');
   assert.equal(test.writes.length,queueStart+1,'a second edit waits behind in-flight save');release();await saved(page);
   assert.equal(test.writes.length,queueStart+2);assert.equal(test.writes.at(-1).version,test.writes.at(-2).version+1);
   test.failNext();await (await exerciseRow(page,3,moving)).locator('[data-board-handle]').focus();await page.keyboard.press('ArrowDown');
   await page.locator('#st-template-board-status.error').waitFor();const draft=await entries(page,3);
   await page.screenshot({path:path.join(out,engine+'-save-error.png')});
   await page.locator('#st-template-board-status').getByRole('button',{name:'Повторить',exact:true}).click();await saved(page);assert.deepEqual(test.lists[3],draft);
   test.externalEdit();await (await exerciseRow(page,3,(await entries(page,3))[0])).locator('[data-board-handle]').focus();await page.keyboard.press('ArrowDown');
   await page.locator('#st-template-board-status.error').waitFor();const count=test.writes.length,actual=test.lists[3];
   await page.locator('#st-template-board-status').getByRole('button',{name:'Загрузить актуальное',exact:true}).click();await page.locator('.st-view-toggle').waitFor();
   await page.getByRole('button',{name:'Управление шаблонами',exact:true}).click();await list(page,3).waitFor();
   assert.equal(test.writes.length,count,'loading actual state does not replay a stale template board');assert.deepEqual(await entries(page,3),actual);
   page.once('dialog',dialog=>dialog.accept());await page.getByRole('button',{name:'Удалить шаблон 3',exact:true}).click();await page.locator('[data-board-column="3"]').waitFor({state:'detached'});await saved(page);
   await page.getByRole('button',{name:'＋ Шаблон',exact:true}).click();await list(page,5).waitFor();await saved(page);assert.deepEqual(await entries(page,5),[]);
  }
  if(width===430&&!managed){
   const before=await page.locator('.st-template-board-modal').boundingBox();
   for(const scale of [60,150]){await page.evaluate(scale=>ST.setScale(scale),scale);const box=await page.locator('.st-template-board-modal').boundingBox();assert(Math.abs(box.width-before.width)<2&&Math.abs(box.height-before.height)<2,'template editor has its own unscaled profile');await page.screenshot({path:path.join(out,engine+'-board-scale-'+scale+'.png')});}
   await page.evaluate(()=>ST.setScale(100));
   await page.getByRole('button',{name:'Состав упражнений шаблона 3',exact:true}).click();await page.locator('.st-manager-modal').waitFor();
   await page.getByRole('button',{name:'Назад к шаблонам',exact:false}).click();await list(page,3).waitFor();
  }
  assert(test.writes.length>before);assert.deepEqual(test.errors,[]);
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  const snapshot=test.lists,active=await page.locator('[data-board-list]').evaluateAll(lists=>lists.map(list=>Number(list.dataset.boardList)));
  await page.reload();await page.locator('.st-view-toggle').waitFor();await page.getByRole('button',{name:'Управление шаблонами',exact:true}).click();await list(page,active.at(-1)).waitFor();
  for(const type of active)assert.deepEqual(await entries(page,type),snapshot[type]);
  results.push({width,managed,touch,version:test.version});await test.context.close();
 }
 if(widths.includes(430)){
  const failing=await open(430,false,{failRead:true});assert.equal(failing.writes.length,0,'incomplete catalogues cannot be saved as empty columns');
  failing.allowCatalog();await failing.page.getByRole('button',{name:'Повторить',exact:true}).click();await list(failing.page,3).waitFor();assert.deepEqual(await entries(failing.page,1),ids.slice(0,6));
  if(engine==='chromium'){
   const page=failing.page,span=await list(page,1).locator('.st-template-exercise>span').first().boundingBox(),cdp=await page.context().newCDPSession(page);
   const y=span.y+span.height/2,x=span.x+span.width-15;
   await cdp.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x,y,id:1}]});
   for(let step=1;step<=6;step++){await cdp.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x:x-step*25,y,id:1}]});await page.waitForTimeout(20);}
   await cdp.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});await cdp.detach();
   await page.waitForFunction(()=>document.querySelector('.st-template-board').scrollLeft>20);assert.equal(failing.writes.length,0,'swiping exercise text scrolls columns without moving exercises');
  }
  await failing.context.close();
  const long=await open(430,false,{longList:true});await drag(long.page,1,ids[0],1,ids[13],engine==='chromium',false,engine+'-vertical-drag.png');await saved(long.page);
  assert.deepEqual(await entries(long.page,1),[...ids.slice(1,13),ids[0],ids[13]]);await long.context.close();
  const options={moduleFail:true},missing=await open(430,false,options);assert.deepEqual(missing.errors,[]);assert.equal(missing.writes.length,0);
  options.moduleFail=false;await missing.page.getByRole('button',{name:'Обновить страницу',exact:true}).click();await missing.page.locator('.st-view-toggle').waitFor();
  await missing.page.getByRole('button',{name:'Управление шаблонами',exact:true}).click();await list(missing.page,3).waitFor();await missing.context.close();
 }
 await writeFile(path.join(out,'results.json'),JSON.stringify(results,null,2));
}catch(error){console.error(error);throw error;}finally{await browser.close();}
console.log('Template board PASS '+engine+' '+results.length+' viewport/role cases');
