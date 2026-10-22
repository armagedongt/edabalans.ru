import assert from 'node:assert/strict';
import {readFile,mkdir,writeFile} from 'node:fs/promises';
import path from 'node:path';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE_URL || 'playwright');
const root=new URL('../../app/static/',import.meta.url),out=process.env.QA_OUT;assert(out);await mkdir(out,{recursive:true});
const standalone=await readFile(new URL('standalone-app.html',root),'utf8');
const guide=JSON.parse(await readFile(new URL('../../app/strength_exercise_guides.json',import.meta.url),'utf8'))[0];
const browser=await chromium.launch();const results=[];
const cases=[...[360,430,768,1440].flatMap(width=>['direct','cabinet'].map(mode=>[width,mode,''])),...[ 'initial-network','initial-timeout','session-timeout','catalog-failure'].map(failure=>[430,'direct',failure])];
for(const [width,mode,failure] of cases){
 console.log('Strength entry case:',JSON.stringify({width,mode,failure}));
 const context=await browser.newContext({viewport:{width,height:900}}),page=await context.newPage();let releaseInitial,releaseCatalog;
 let failedOnce=false,catalogFailures=2;
 const initialGate=new Promise(r=>{releaseInitial=r;}),catalogGate=new Promise(r=>{releaseCatalog=r;});const reads=[],errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/*',async route=>{
  const u=new URL(route.request().url());if(u.hostname!=='127.0.0.1')return route.abort();
  if(u.pathname==='/training'){
   const body=mode==='direct'?standalone.replaceAll('{{APP_CODE}}','strength').replaceAll('{{APP_TITLE}}','Силовые тренировки').replaceAll('{{APP_FAVICON}}','/assets/strength-favicon.svg').replace('{{PWA_HEAD}}',''):'<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><div data-edabalans-app="account" data-edabalans-manual="true"><div data-edabalans-app="strength" data-edabalans-manual="true"></div></div><script src="/embed.js" data-edabalans-loader-only="true"></script><script>window.EdabalansIdentity={source:"native",email:"example@example.test"};window.EdabalansEmbed.load(document.querySelector(\'[data-edabalans-app="strength"]\'));</script>';
   return route.fulfill({contentType:'text/html',body});
  }
  if(u.pathname==='/api/account-auth/session'){if(failure==='session-timeout'&&!failedOnce){failedOnce=true;return;}return route.fulfill({json:{authenticated:true,email:'example@example.test'}});}
  if(u.pathname==='/api/apps/strength'){
   assert.equal(route.request().method(),'GET','entry performs no writes');const action=u.searchParams.get('action');reads.push(Object.fromEntries(u.searchParams));
   const user={user_id:'fixture',email:'example@example.test'};
   if(action==='openUser')return route.fulfill({json:{ok:true,user}});
   if(u.searchParams.has('catalog_only')){if(failure==='catalog-failure'&&catalogFailures>0){catalogFailures--;failedOnce=true;return route.fulfill({status:503,json:{ok:false,error:'Временно не удалось загрузить каталог'}});}await catalogGate;}else{if((failure==='initial-network'||failure==='initial-timeout')&&!failedOnce){failedOnce=true;if(failure==='initial-network')return route.abort('failed');return;}await initialGate;}
   const type=u.searchParams.has('initial')?2:Number(u.searchParams.get('type'));
   return route.fulfill({json:{ok:true,user,workout:{selected_type:type,version:1,workout_types:[{workout_type:1,title:'Верх',active:true},{workout_type:2,title:'Низ',active:true}],exercise_catalog:[{exercise_id:guide.code,exercise_name:guide.name,short_name:guide.short_name,source:'base',active:true,sort_order:1,guide:guide.guide,media_url:guide.media_url}],sessions:u.searchParams.has('catalog_only')?[]:[{session_id:'last',session_number:7,workout_type:2,date:'2026-10-21'}],session_exercises:[{session_id:'last',exercise_id:guide.code,exercise_name:guide.name,sort_order:1}],sets:[{session_id:'last',exercise_id:guide.code,set_number:1,plan_weight:60,plan_reps:10}]}}});
  }
  const pathname=u.pathname.replace(/^\/(assets\/)?/,'');const asset=new URL(pathname,root);if(!asset.href.startsWith(root.href))return route.abort();
  try{return route.fulfill({contentType:({'.css':'text/css','.js':'text/javascript','.html':'text/html','.png':'image/png','.svg':'image/svg+xml','.woff2':'font/woff2'})[path.extname(pathname)]||'application/octet-stream',body:await readFile(asset)});}catch{return route.abort();}
 });
 if(failure.includes('timeout'))await page.clock.install();
 await page.goto('http://127.0.0.1:8823/training');await page.waitForFunction(()=>document.querySelector('[aria-busy=true]'));
 if(failure&&failure!=='catalog-failure'){
  if(failure.includes('timeout'))await page.clock.fastForward(15001);
  await page.locator('.ed-loading-retry').waitFor();
  assert((await page.locator('.ed-loading-error').textContent()).length>0);
  releaseInitial();await page.locator('.ed-loading-retry').click();
 }
 if(!failure||failure==='catalog-failure'){
 assert.equal(await page.locator('.ed-loading-screen').count(),1);
 assert(await page.locator('.ed-loading-screen').isVisible());
 assert.equal(await page.locator('.ed-loading-dots i').count(),3);
 assert.equal(await page.locator('#strength-app').evaluate(el=>getComputedStyle(el).visibility),'hidden');
 assert.equal(await page.locator('.standalone-loading').count(),0);
 if(width===430&&!failure)await page.screenshot({path:`${out}/${mode}-shared-loader.png`});
 }
 releaseInitial();
 try{await page.locator('.st-history-row').waitFor();}
 catch(error){
  const snapshot=await page.evaluate(()=>({body:document.body.innerText.slice(0,1500),visibility:document.querySelector('#strength-app')?getComputedStyle(document.querySelector('#strength-app')).visibility:null})).catch(()=>null);
  console.error('Strength entry readiness failure:',JSON.stringify({width,mode,failure,errors,reads,snapshot}));throw error;
 }
 await page.locator('.ed-loading-screen').waitFor({state:'detached'});
 assert.equal(await page.locator('.st-type.active').textContent(),'Низ');assert(await page.locator('[data-field=planWeight]').first().isVisible());
 assert.equal(reads.filter(r=>r.initial==='1').length,(failure==='initial-network'||failure==='initial-timeout')?2:1);assert.equal(reads.filter(r=>r.type==='2'&&!r.initial).length,0);
 assert.equal(await page.locator('#strength-app').evaluate(el=>getComputedStyle(el).visibility),'visible');
 if(failure==='catalog-failure'){
  await page.getByRole('button',{name:'Верх',exact:true}).click();
  await page.getByRole('button',{name:'Повторить',exact:true}).click();
 }
 releaseCatalog();await page.waitForTimeout(80);
 if(failure==='catalog-failure')await page.locator('.st-template-loading').waitFor({state:'detached'});
 assert(reads.some(r=>r.catalog_only==='1'));assert.deepEqual(errors,[]);
 results.push({width,mode,failure,initialTemplates:reads.filter(r=>r.initial).length,backgroundCatalogues:reads.filter(r=>r.catalog_only).length});
 await context.close();
}
await writeFile(out+'/report.json',JSON.stringify(results,null,2));await browser.close();console.log('PASS: direct/cabinet loader waits for first journal; other templates load later');
