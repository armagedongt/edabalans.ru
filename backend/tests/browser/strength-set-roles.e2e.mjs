import assert from 'node:assert/strict';
import {readFile, mkdir, writeFile} from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
const {chromium}=await import(pathToFileURL(path.join(process.env.CODEX_NODE_MODULES,'playwright/index.mjs')).href);
const staticRoot=new URL('../../app/static/',import.meta.url),html=await readFile(new URL('apps/strength.html',staticRoot),'utf8');
const output=process.env.QA_OUT;assert(output,'QA_OUT required');await mkdir(output,{recursive:true});
const browser=await chromium.launch(),evidence=[];
try {
for(const width of [360,430,700,701,768,1440]) for(const managed of [false,true]) {
  const page=await browser.newPage({viewport:{width,height:900},hasTouch:width<=700});
  page.on('pageerror',error=>console.error('Browser error:',error.message));
  let version=1;
  const state={version:1,workout_types:[{workout_type:1,title:'Верх',active:true,sort_order:1}],
    exercise_catalog:[{exercise_id:'bench',exercise_name:'Жим штанги лёжа',active:true,sort_order:1,source:'base'}],
    sessions:[{session_id:'a',session_number:1,workout_type:1,date:'2026-10-14'},{session_id:'b',session_number:2,workout_type:1,date:'2026-10-21'}],
    session_exercises:['a','b'].map(session_id=>({session_id,exercise_id:'bench',exercise_name:'Жим штанги лёжа',sort_order:1})),
    sets:['a','b'].flatMap(session_id=>[1,2].map(set_number=>({session_id,exercise_id:'bench',set_number,plan_weight:set_number===1?20:65,
      plan_reps:10,fact_weight:session_id==='a'?(set_number===1?20:60):'',fact_reps:session_id==='a'?10:'',rpe:session_id==='a'?8:'',role:set_number===1?'warmup':'work'})))};
  const writes=[];
  await page.route('http://127.0.0.1:8828/**',async route=>{
    const url=new URL(route.request().url());
    if(url.pathname==='/strength-role-local')return route.fulfill({contentType:'text/html; charset=utf-8',body:'<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{margin:0;background:#f5f5f7}</style><script>window.EdabalansIdentity={source:"native",email:"synthetic@example.test"};window.EdabalansAppContext='+JSON.stringify(managed?{mode:'admin',targetUserId:'fixture',accountUrl:'/lk'}:{accountUrl:'/lk'})+';</script>'+html});
    if(url.pathname==='/api/apps/strength'){
      const data=route.request().method()==='POST'?JSON.parse(route.request().postData()):Object.fromEntries(url.searchParams);
      const response={ok:true,user:{user_id:'fixture',email:'synthetic@example.test'},version};
      if(data.action==='getWorkout')response.workout={...structuredClone(state),selected_type:1,version};
      if(data.action==='saveSession'){
        writes.push(structuredClone(data));version++;
        const session=data.session;
        state.sets=state.sets.filter(row=>row.session_id!==session.session_id);
        for(const exercise of session.exercises)for(const row of exercise.sets)state.sets.push({...row,session_id:session.session_id,exercise_id:exercise.exercise_id});
        response.session=session;response.version=version;
      }
      return route.fulfill({json:response});
    }
    const asset=new URL(url.pathname.replace(/^\/assets\//,''),staticRoot);
    if(!asset.href.startsWith(staticRoot.href))return route.abort();
    try{return route.fulfill({contentType:({'.css':'text/css','.js':'text/javascript','.woff2':'font/woff2','.svg':'image/svg+xml'})[path.extname(asset.pathname)]||'application/octet-stream',body:await readFile(asset)});}catch{return route.abort();}
  });
  await page.goto('http://127.0.0.1:8828/strength-role-local');
  const card=()=>page.locator('article[data-session-index="1"][data-exercise-id="bench"]');
  await card().waitFor();
  for(const view of ['training','exercise']){
    if(view==='exercise')await page.locator('.st-view-toggle').click();
    const button=()=>card().locator('.st-modern-number').first();
    assert.equal(await button().getAttribute('aria-pressed'),'true');
    const geometry=await button().evaluate(el=>{
      const b=el.getBoundingClientRect(),input=el.closest('.st-grid-set').querySelector('input').getBoundingClientRect(),s=getComputedStyle(el);
      return {width:b.width,height:b.height,right:b.right,inputLeft:input.left,border:s.borderTopWidth,background:s.backgroundColor,weight:s.fontWeight,color:s.color};
    });
    assert(geometry.width>=23.9&&geometry.height>=29.9);assert(geometry.right<=geometry.inputLeft);
    assert.equal(geometry.border,'0px');assert.equal(geometry.background,'rgba(0, 0, 0, 0)');assert(Number(geometry.weight)>=800);
    // Use the edge of the invisible target, rather than the glyph itself.
    await button().click({position:{x:2,y:2}});
    await page.waitForFunction(()=>document.querySelector('article[data-session-index="1"] .st-modern-number')?.getAttribute('aria-pressed')==='false');
    await page.waitForTimeout(850);
    assert.equal(writes.at(-1).session.exercises[0].sets[0].role,'work');
    assert.equal(writes.at(-1).session.exercises[0].sets[0].plan_weight,20);
    if(!await page.getByRole('button',{name:'Отменить действие',exact:true}).count())throw new Error('Missing undo: '+await page.locator('#strength-app').innerText());
    await page.getByRole('button',{name:'Отменить действие',exact:true}).click();
    await page.waitForTimeout(850);
    assert.equal(await button().getAttribute('aria-pressed'),'true');
    // Existing plan/fact comparison remains blue, not a new colour scheme.
    const higher=card().locator('[data-field="planWeight"]').nth(1);
    assert.equal(await higher.evaluate(el=>getComputedStyle(el).backgroundColor),'rgb(233, 243, 255)');
    const file=`${width}-${managed?'admin':'user'}-${view}.png`;
    await page.screenshot({path:path.join(output,file)});
    evidence.push({width,managed,view,file,geometry});
  }
  await page.reload();await card().waitFor();
  assert.equal(await card().locator('.st-modern-number').first().getAttribute('aria-pressed'),'true','role survives reload');
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  await page.close();
}
await writeFile(path.join(output,'evidence.json'),JSON.stringify(evidence,null,2));
console.log('Set-role UI: user/admin, both views, 6 widths; save, reload, undo, target and plan colours PASS');
} finally {await browser.close();}
