import assert from 'node:assert/strict';
import {readFile,mkdir,writeFile} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
import path from 'node:path';
const engine=process.env.QA_BROWSER||'chromium';
const {[engine]:browserType}=await import(pathToFileURL(path.join(process.env.CODEX_NODE_MODULES,'playwright/index.mjs')).href);
const staticRoot=new URL('../../app/static/',import.meta.url);
const html=await readFile(new URL('apps/strength.html',staticRoot),'utf8');
const guides=JSON.parse(await readFile(new URL('../../app/strength_exercise_guides.json',import.meta.url),'utf8')).slice(0,8);
const out=process.env.QA_OUT;assert(out);await mkdir(out,{recursive:true});
const browser=await browserType.launch(),evidence=[];
async function closeOverlay(page,selector){
 // Closing a screen traverses browser history asynchronously; settle it before
 // opening another screen so the test does not race its own back navigation.
 await Promise.all([page.waitForEvent('framenavigated',frame=>frame===page.mainFrame()),page.evaluate(()=>ST.closeModal())]);
 await page.locator(selector).waitFor({state:'detached'});
}
try{
for(const width of [360,430,700,701,768,1440,1699])for(const managed of [false,true]){
 const page=await browser.newPage({viewport:{width,height:1000},hasTouch:width<=700}),errors=[],writes=[];
 page.setDefaultTimeout(10000);
 page.on('pageerror',e=>errors.push(e.message));
 const sessions=Array.from({length:8},(_,i)=>({session_id:'s'+i,session_number:i+1,workout_type:1,date:'2026-11-21'}));
 const state={selected_type:1,version:1,workout_types:[{workout_type:1,title:'Верх',active:true,sort_order:1}],
  exercise_catalog:guides.map((g,i)=>({exercise_id:g.code,exercise_name:g.name,full_name:g.full_name,active:true,source:'base',sort_order:i+1,guide:g.guide})),
  sessions,session_exercises:sessions.flatMap(s=>guides.map((g,i)=>({session_id:s.session_id,exercise_id:g.code,exercise_name:g.name,sort_order:i+1}))),
  sets:sessions.flatMap(s=>guides.flatMap(g=>Array.from({length:4},(_,i)=>({session_id:s.session_id,exercise_id:g.code,set_number:i+1,role:i?'work':'warmup',plan_weight:35,plan_reps:15,fact_weight:'',fact_reps:'',rpe:''}))))};
 await page.route('**/*',async route=>{
  const url=new URL(route.request().url());if(url.hostname!=='127.0.0.1')return route.abort();
  if(['/scale-fixture','/training'].includes(url.pathname))return route.fulfill({contentType:'text/html',body:'<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{margin:0;background:#f5f5f7}main{max-width:1420px;margin:auto}</style><main><script>window.EdabalansIdentity={source:"native",email:"scale@example.test"};window.EdabalansAppContext='+JSON.stringify(managed?{mode:'admin',targetUserId:'fixture',accountUrl:'/lk'}:{accountUrl:'/lk'})+';</script>'+html+'</main>'});
  if(url.pathname==='/api/apps/strength'){
   const data=route.request().method()==='POST'?JSON.parse(route.request().postData()):Object.fromEntries(url.searchParams);
   if(route.request().method()==='POST')writes.push(data);
   return route.fulfill({json:{ok:true,version:1,user:{user_id:'fixture',email:'scale@example.test',can_coach:true,can_calculate_progression:true},workout:state}});
  }
  const asset=new URL(url.pathname.replace(/^\/assets\//,''),staticRoot);
  if(!asset.href.startsWith(staticRoot.href))return route.abort();
   try{return route.fulfill({contentType:({'.html':'text/html','.css':'text/css','.js':'text/javascript','.mjs':'text/javascript','.woff2':'font/woff2','.svg':'image/svg+xml','.png':'image/png','.webp':'image/webp'})[path.extname(asset.pathname)]||'application/octet-stream',body:await readFile(asset)});}catch{return route.abort();}
 });
 await page.goto('http://127.0.0.1:8823/scale-fixture');await page.locator('.st-view-toggle').waitFor();await page.evaluate(()=>document.fonts.ready);
 for(const view of ['training','exercise']){
  if(await page.locator('#strength-app').getAttribute('data-journal-view')!==view)await page.locator('.st-view-toggle').click();
  const sizes={};
  for(const scale of [100,60,50,150]){
   await page.locator('.st-scale-button').selectOption(String(scale));
   await page.waitForTimeout(120);
   sizes[scale]=await page.evaluate(()=>{
    const root=document.querySelector('#strength-app'),axis=root.querySelector('[data-axis]'),row=root.querySelector('.st-history-row'),card=row.querySelector('article');
    const box=card.getBoundingClientRect(),input=card.querySelector('input[data-field="planWeight"]').getBoundingClientRect();
    const frame=axis.getBoundingClientRect(),dates=root.querySelectorAll('.st-date-cell'),cards=row.querySelectorAll('article');
    return {width:box.width,height:box.height,inputWidth:input.width,inputHeight:input.height,capacity:frame.width/box.width,
     aligned:[...dates].every((e,i)=>Math.abs(e.getBoundingClientRect().left-cards[i].getBoundingClientRect().left)<1),
     overflow:document.documentElement.scrollWidth>innerWidth,
     right:Math.abs(axis.scrollWidth-axis.clientWidth-axis.scrollLeft)<2};
   });
   assert.equal(sizes[scale].aligned,true,'dates align with cards');assert.equal(sizes[scale].overflow,false,'page fits viewport');
   await page.screenshot({path:path.join(out,`${engine}-${width}-${managed?'managed':'owner'}-${view}-${scale}.png`)});
  }
  for(const scale of [60,50,150])for(const dimension of ['width','height','inputWidth','inputHeight'])
   assert(Math.abs(sizes[scale][dimension]-sizes[100][dimension]*scale/100)<(dimension==='height'?4:2),`${engine} ${width} ${view} ${dimension} scales once at${scale}: ${JSON.stringify(sizes)}`);
  assert(sizes[60].capacity>sizes[100].capacity*1.6,'60% reveals more workouts horizontally');
  assert(sizes[60].height<sizes[100].height*.62,'60% reveals more exercises vertically');
  let dateBase,tutorialBase;
  for(const scale of [100,60,150]){
   await page.locator('.st-scale-button').selectOption(String(scale));
   const card=page.locator('.st-history-row').first().locator('article').last();
   const button=card.locator('.st-rpe-button').first();await button.click();
   const anchor=await button.boundingBox(),menu=await page.locator('.st-rpe-floating').boundingBox();
   assert(menu&&menu.x>=0&&menu.y>=0&&menu.x+menu.width<=width+1&&menu.y+menu.height<=1001,'RPE menu stays inside viewport');
   assert(anchor.x+anchor.width/2>=menu.x-5&&anchor.x+anchor.width/2<=menu.x+menu.width+5,'RPE menu remains horizontally anchored to tapped approach');
   assert(Math.min(Math.abs(menu.y-anchor.y-anchor.height),Math.abs(menu.y+menu.height-anchor.y))<=14*scale/100+2,'RPE menu opens beside the tapped approach');
   if(!managed&&scale!==100)await page.screenshot({path:path.join(out,`${engine}-${width}-${view}-${scale}-rpe.png`)});
   await page.evaluate(()=>ST.openDatePicker(7));
   const modal=page.locator('.st-modal');await modal.waitFor();
   const bounds=await modal.boundingBox(),title=await modal.locator('.st-modal-title').boundingBox();
   assert(bounds.x>=0&&bounds.x+bounds.width<=width+1,'date dialog fits viewport');
   const dateProfile={width:bounds.width,height:bounds.height,titleHeight:title.height};
   if(scale===100)dateBase=dateProfile;
   else for(const dimension of Object.keys(dateBase))assert(Math.abs(dateProfile[dimension]-dateBase[dimension])<2,'date dialog keeps its100% '+dimension);
   if(!managed&&scale!==100)await page.screenshot({path:path.join(out,`${engine}-${width}-${view}-${scale}-date.png`)});
   await closeOverlay(page,'.st-modal');
   await page.locator('.st-help').click();
   const tutorial=page.locator('.st-tutorial-frame iframe');await tutorial.contentFrame().locator('body').waitFor();
   const tutorialWidth=await tutorial.evaluate(e=>e.contentWindow.innerWidth);
   if(scale===100)tutorialBase=tutorialWidth;
   else assert(Math.abs(tutorialWidth-tutorialBase)<=1,'fullscreen help keeps its100% viewport');
   if(!managed&&scale!==100)await page.screenshot({path:path.join(out,`${engine}-${width}-${view}-${scale}-help.png`)});
   await closeOverlay(page,'.st-tutorial-frame');
  }
  await page.locator('.st-scale-button').selectOption('60');
  evidence.push({width,managed,view,sizes});
 }
 await page.evaluate(()=>ST.setMainTab('stats'));
 assert.equal(await page.locator('#strength-app').evaluate(e=>Number(e.style.zoom)),1,'statistics keeps its own scale');
 if(!managed)await page.screenshot({path:path.join(out,`${engine}-${width}-stats.png`)});
 await page.evaluate(()=>ST.setMainTab('training'));
 await page.waitForFunction(()=>!new URL(location.href).searchParams.has('view')&&document.querySelector('.st-scale-button'));
 await page.reload();
 assert.equal(await page.locator('.st-scale-button').inputValue(),'60','scale persists after reload');
 assert.deepEqual(writes,[],'zoom and cancelled dialogs never alter workouts');assert.deepEqual(errors,[]);
 await page.close();
}
await writeFile(path.join(out,'measurements.json'),JSON.stringify(evidence,null,2));
}catch(error){console.error(error);throw error;}finally{await browser.close();}
console.log('Canvas scale passed: '+evidence.length+' viewport/role/view combinations in '+engine);
