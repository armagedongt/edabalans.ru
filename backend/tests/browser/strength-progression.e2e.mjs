import assert from 'node:assert/strict';
import {readFile,mkdir,writeFile} from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
const {chromium}=await import(pathToFileURL(path.join(process.env.CODEX_NODE_MODULES,'playwright/index.mjs')).href);
const staticRoot=new URL('../../app/static/',import.meta.url),html=await readFile(new URL('apps/strength.html',staticRoot),'utf8');
const guides=JSON.parse(await readFile(new URL('../../app/strength_exercise_guides.json',import.meta.url),'utf8'));
const output=process.env.QA_OUT;assert(output);await mkdir(output,{recursive:true});
const browser=await chromium.launch(),evidence=[];
try{
for(const width of [360,430,700,701,768,1440])for(const role of (width===430?['user','owner','managed','deleted','stale-messenger']:['user','owner','managed'])){
 const admin=role!=='user',managed=role==='managed'||role==='deleted'||role==='stale-messenger';
 const page=await browser.newPage({viewport:{width,height:900}}),errors=[],writes=[];page.on('pageerror',error=>errors.push(error.message));
 let linkedPlatform=null,failState=false,deliveryCount=0,linkRequests=0,reads=0,oldRelease;
 const oldGate=new Promise(resolve=>{oldRelease=resolve;});
 let version=1,moduleHold=null,moduleRelease;const state={sessions:[1,2,3].map(n=>({session_id:'s'+n,session_number:n,workout_type:1,date:'2026-10-'+String(n*7).padStart(2,'0')})),
  workout_types:[{workout_type:1,title:'Верх',sort_order:1,active:true}],
  exercise_catalog:guides.map((g,i)=>({exercise_id:g.code,exercise_name:g.name,short_name:g.short_name,full_name:g.full_name,source:'base',active:i<2,sort_order:i+1,media_url:g.media_url,guide:g.guide,training:g.training})),
  session_exercises:[1,2,3].map(n=>({session_id:'s'+n,exercise_id:'bench-press',exercise_name:'Жим штанги лёжа',sort_order:1})),
  sets:[1,2,3].flatMap(n=>(n===1?[1,2,3,4,5,6]:[1,2,3,4]).map(j=>({session_id:'s'+n,exercise_id:'bench-press',set_number:j,role:j===1?'warmup':'work',plan_weight:n===3?'':j===1?20:60,plan_reps:n===3?'':10,
    fact_weight:n===3?(j===1?25:j===2?999:''):j===1?20:60,fact_reps:n===3?(j===1?20:j===2?8:''):10,rpe:n===3?(j===1?7:j===2?9:''):8})))};
 await page.route('http://127.0.0.1:8828/**',async route=>{
  const url=new URL(route.request().url());
  if(url.pathname==='/strength-progression-local')return route.fulfill({contentType:'text/html; charset=utf-8',body:'<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{margin:0;background:#f5f5f7}</style><script>window.EdabalansIdentity={source:"native",email:"synthetic@example.test"};window.EdabalansAppContext='+JSON.stringify(managed?{mode:'admin',targetUserId:'demo',accountUrl:'/lk'}:{accountUrl:'/lk'})+';</script>'+html});
  if(url.pathname==='/api/apps/strength'){
   const request=route.request(),data=request.method()==='POST'?JSON.parse(request.postData()):Object.fromEntries(url.searchParams);
   const response={ok:true,version,user:{user_id:'demo',email:'synthetic@example.test',can_coach:admin,can_calculate_progression:admin}};
   if(data.action==='messengerState' && role==='stale-messenger' && ++reads===1){await oldGate;return route.fulfill({json:{ok:false,error:'Ошибка закрытого окна'}});}
   if(data.action==='messengerState')return route.fulfill({json:failState?{ok:false,error:'Проверка недоступна'}:{ok:true,destination:linkedPlatform,require_link:!linkedPlatform,require_preferred:false,linked:{telegram:{linked:linkedPlatform==='telegram'},max:{linked:linkedPlatform==='max'}},bot_links:{telegram:'https://t.me/test_bot',max:'https://max.ru/test_bot'}}});
   if(data.action==='createMessengerLink'){linkRequests++;return route.fulfill({json:{ok:true,deep_link:'https://'+(data.platform==='telegram'?'t.me':'max.ru')+'/test_bot?start=synthetic',expires_at:new Date(Date.now()+900000).toISOString()}});}
   if(data.action==='getWorkout')response.workout={...structuredClone(state),selected_type:1,version};
   if(data.action==='saveSession'){
    writes.push(structuredClone(data));version++;response.version=version;response.session=data.session;
    state.sets=state.sets.filter(row=>row.session_id!==data.session.session_id);
    if(data.session.deleted)state.sessions=state.sessions.filter(row=>row.session_id!==data.session.session_id);
    for(const ex of (data.session.exercises||[]))for(const row of ex.sets)state.sets.push({...row,session_id:data.session.session_id,exercise_id:ex.exercise_id});
   }
   return route.fulfill({json:response});
  }
  if(url.pathname==='/api/apps/strength/send-plan'){deliveryCount++;return route.fulfill({json:{ok:true,platform:linkedPlatform,message_ids:['synthetic']}});}
  if(url.pathname==='/assets/strength-progression-model.mjs'&&moduleHold)await moduleHold;
  const asset=new URL(url.pathname.replace(/^\/assets\//,''),staticRoot);
  if(!asset.href.startsWith(staticRoot.href))return route.abort();
  try{return route.fulfill({contentType:({'.css':'text/css','.js':'text/javascript','.mjs':'text/javascript','.woff2':'font/woff2','.svg':'image/svg+xml','.gif':'image/gif','.png':'image/png'})[path.extname(asset.pathname)]||'application/octet-stream',body:await readFile(asset)});}catch{return route.abort();}
 });
 await page.goto('http://127.0.0.1:8828/strength-progression-local');
 const card=()=>page.locator('article[data-session-index="2"][data-exercise-id="bench-press"]');await card().waitFor();
 if(admin)assert.equal(await page.locator('article[data-session-index="2"][data-exercise-id="'+guides[1].code+'"]').getByRole('button',{name:'Рассчитать прогрессию',exact:true}).isDisabled(),true,'virtual historical exercise does not offer a silent no-op calculation');

 if(role==='deleted'){
  moduleHold=new Promise(resolve=>{moduleRelease=resolve;});
  await card().getByRole('button',{name:'Рассчитать прогрессию',exact:true}).click();
  page.on('dialog',dialog=>dialog.accept());await page.evaluate(()=>ST.deleteSession(2));
  await page.waitForTimeout(900);moduleRelease();await page.waitForTimeout(400);
  assert.equal(await page.locator('.st-modal-bg').count(),0);
  assert.equal(await page.evaluate(()=>document.body.style.overflow),'');
  assert.equal(await card().count(),0);
  evidence.push({width,role});await page.close();continue;
 }
 if(role==='stale-messenger'){
  linkedPlatform='telegram';await page.evaluate(()=>ST.sendTelegram(0,''));
  while(reads===0)await page.waitForTimeout(10);
  await page.evaluate(()=>ST.closeModal());await page.locator('.st-modal-bg').waitFor({state:'detached'});
  await page.evaluate(()=>ST.sendTelegram(1,''));
  await page.getByRole('button',{name:'Отправить',exact:true}).waitFor();
  oldRelease();await page.waitForTimeout(300);
  assert.equal(await page.getByRole('button',{name:'Отправить',exact:true}).isVisible(),true);
  assert((await page.locator('#st-delivery-messenger').innerText()).includes('подключён'));
  evidence.push({width,role});await page.close();continue;
 }
 await card().getByRole('button',{name:'Информация об упражнении',exact:true}).click();
 const dialog=page.getByRole('dialog');await dialog.waitFor();
 await assert.equal(await dialog.locator('.st-guide-training dd').first().textContent(),'6–15 повторений');
 assert((await dialog.locator('.st-guide-training').innerText()).includes('2,5 кг'));
 assert(await dialog.locator('.st-guide-demo').evaluate(el=>el.nextElementSibling.matches('.st-guide-training')));
 assert.equal(await dialog.locator('.st-guide-training p').count(),0);
 await page.screenshot({path:path.join(output,`${width}-${role}-guide.png`)});
 assert.equal(await dialog.locator('.st-guide-body').evaluate(el=>el.scrollWidth>el.clientWidth),false);
 await dialog.getByRole('button',{name:'Закрыть информацию об упражнении'}).click();
 if(width===430&&!admin){
  for(const [id,expected] of [
   ['plank',['20–45 секунд','5 с']],
   ['incline-dumbbell-press',['6–15 повторений','1 кг']],
   ['assisted-pull-up',['8–15 повторений','Одна ступень уменьшения помощи']],
   ['one-arm-dumbbell-row',['8–15 повторений']]
  ]){
   await page.evaluate(value=>window.ST.openExerciseInfo(value),id);
   await dialog.waitFor();const text=await dialog.locator('.st-guide-training').innerText();
   for(const value of expected)assert(text.includes(value),id+': '+value);
   await page.screenshot({path:path.join(output,`430-user-guide-${id}.png`)});
   await dialog.getByRole('button',{name:'Закрыть информацию об упражнении'}).click();
  }
 }
 if(!admin){
  assert.equal(await page.locator('.st-progression-trigger').count(),0);
  await page.evaluate(()=>{window.ST.calculateProgression(2,'bench-press');window.ST.applyProgression(2,'bench-press');});
  assert.equal(writes.length,0);
 }else{
  if(width===430){
   moduleHold=new Promise(resolve=>{moduleRelease=resolve;});
   await card().getByRole('button',{name:'Рассчитать прогрессию',exact:true}).click();
   const input=card().locator('[data-field="planReps"]').nth(1);await input.fill('12');await input.dispatchEvent('input');await input.blur();await page.waitForTimeout(850);
   const before=writes.length;moduleRelease();
   await dialog.locator('.st-progression-error').waitFor();
   assert((await dialog.locator('.st-progression-error').innerText()).includes('Данные изменились'));
   await page.waitForTimeout(850);assert.equal(writes.length,before,'editing while the module loads prevents automatic overwrite');
   await dialog.getByRole('button',{name:'Закрыть',exact:true}).click();
   await page.getByRole('button',{name:'Отменить действие',exact:true}).click();await page.waitForTimeout(850);
  }
  for(const view of ['training','exercise']){
   if(view==='exercise')await page.locator('.st-view-toggle').click();
   const control=card().getByRole('button',{name:/Рассчитать прогрессию|Пересчитать прогрессию/});
   const before=writes.length;await control.click();
   await card().locator('.st-progression-info').waitFor();await page.waitForTimeout(850);
   assert.equal(writes.length,before+1,'one calculation click fills and saves the plan');
   assert.equal(await card().getByRole('button',{name:/Применить в план/}).count(),0);
   const saved=writes.at(-1).session.exercises[0].sets;
   assert.equal(saved[1].plan_reps,11);assert.equal(saved[1].fact_weight,999);assert.equal(saved[1].fact_reps,8);assert.equal(saved[1].rpe,9);assert.equal(saved[0].role,'warmup');
   assert.equal(saved[0].plan_weight,'');assert.equal(saved[0].plan_reps,'');assert.equal(saved[0].fact_weight,25);assert.equal(saved[0].fact_reps,20);assert.equal(saved[0].rpe,7);
   const box=await control.boundingBox(),last=await card().locator('.st-grid-set').last().boundingBox();assert(box.y>=last.y+last.height+60,'calculation sits after spare set space');
   const noteBox=await card().getByRole('button',{name:'Примечание к упражнению'}).boundingBox(),cardBox=await card().boundingBox();
   assert(noteBox.y-box.y-box.height<=8,'calculation touches the note area');assert(cardBox.y+cardBox.height-noteBox.y-noteBox.height<=8,'note is at the card bottom');
   await page.screenshot({path:path.join(output,`${width}-${role}-${view}-calculated.png`)});
   if(view==='training'){
    await page.getByRole('button',{name:'Отменить действие',exact:true}).click();await page.waitForTimeout(850);
    const undone=writes.at(-1).session.exercises[0].sets;
    assert(undone.every(row=>row.plan_weight===''&&row.plan_reps===''),'undo restores the destination plan before calculation');
    assert.equal(undone[1].fact_weight,999);assert.equal(undone[1].fact_reps,8);assert.equal(undone[1].rpe,9);
    assert.equal(await card().locator('[data-field="planReps"]').nth(1).inputValue(),'');
   }else{
    await card().getByRole('button',{name:'Информация о расчёте прогрессии',exact:true}).click();
    assert.equal(await card().locator('.st-progression-details').count(),0,'details do not expand the exercise card');
    const step=dialog.locator('[data-calc-field="load_step"]');await step.fill('0');await dialog.getByRole('button',{name:'Рассчитать прогрессию',exact:true}).click();
    await dialog.locator('.st-progression-error').waitFor();assert((await dialog.locator('.st-progression-error').innerText()).includes('шаг'));
    await page.screenshot({path:path.join(output,`${width}-${role}-error.png`)});
    const afterFailure=writes.length;await page.waitForTimeout(850);assert.equal(writes.length,afterFailure);
    await step.fill('2.5');await dialog.getByRole('button',{name:'Рассчитать прогрессию',exact:true}).click();await page.waitForTimeout(850);
    await dialog.getByRole('button',{name:'Закрыть',exact:true}).click();
   }
  }
 }


 if(role==='user'){
  await page.evaluate(()=>ST.sendTelegram(0,''));
  await page.getByRole('link',{name:'Подключить Telegram',exact:true}).waitFor();
  assert.equal(await page.getByRole('button',{name:'Отправить',exact:true}).isVisible(),false);
  assert.equal(deliveryCount,0);
  await page.getByRole('button',{name:'Проверить подключение',exact:true}).click();
  await page.getByRole('link',{name:'Подключить Telegram',exact:true}).waitFor();
  assert.equal(linkRequests,2,'checking status preserves valid one-time links instead of invalidating them');
  await page.screenshot({path:path.join(output,`${width}-messenger-unlinked.png`)});
  for(const platform of ['telegram','max']){
   linkedPlatform=platform;
   await page.getByRole('button',{name:'Проверить подключение',exact:true}).click();
   await page.getByRole('link',{name:platform==='telegram'?'Telegram':'MAX',exact:true}).waitFor();
   assert.equal(await page.getByRole('button',{name:'Отправить',exact:true}).isEnabled(),true);
  }
  await page.screenshot({path:path.join(output,`${width}-messenger-linked.png`)});
  await page.getByRole('button',{name:'Отправить',exact:true}).click();
  await page.waitForFunction(()=>document.body.innerText.includes('отправлен в MAX'));
  assert.equal(deliveryCount,1);
  await page.evaluate(()=>ST.sendTelegram(0,''));
  await page.getByRole('button',{name:'Проверить подключение',exact:true}).waitFor();
  failState=true;await page.getByRole('button',{name:'Проверить подключение',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('#st-delivery-messenger').textContent.includes('Проверка недоступна'));
  assert.equal(await page.getByRole('button',{name:'Отправить',exact:true}).isVisible(),false);
  await page.getByRole('button',{name:'Отменить',exact:true}).click();
 }
 await card().getByRole('button',{name:'Примечание к упражнению'}).click();
 assert.equal(await page.locator('#st-coach-note-text').evaluate(el=>el.readOnly),!admin);
 for(const field of ['#st-coach-note-text','#st-note-text'])assert((await page.locator(field).boundingBox()).height<=82);
 await page.locator('#st-note-text').fill(Array(8).fill('Комментарий').join('\n'));await page.locator('#st-note-text').dispatchEvent('input');
 assert((await page.locator('#st-note-text').boundingBox()).height>82);
 await page.screenshot({path:path.join(output,`${width}-${role}-comments.png`)});
 await page.getByRole('button',{name:'Закрыть',exact:true}).click();
 for(const action of [()=>page.locator('.st-view-toggle').click(),()=>page.evaluate(()=>ST.setScale(110)),async()=>{await page.evaluate(()=>ST.openTemplates());await page.getByRole('button',{name:'Готово',exact:true}).click();}]){
  await page.locator('[data-axis]').evaluate(el=>{el.scrollLeft=0;});await action();
  assert(await page.locator('[data-axis]').evaluate(el=>Math.abs(el.scrollWidth-el.clientWidth-el.scrollLeft)<2),'interaction returns to latest workout');
 }
 assert.deepEqual(errors,[]);assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
 evidence.push({width,role,writes:writes.length});await page.close();
}
await writeFile(path.join(output,'evidence.json'),JSON.stringify(evidence,null,2));console.log('Strength controls: 6 widths, 3 roles, comments, messenger, bottom actions, latest scroll and async cancellation PASS');
}finally{await browser.close();}
