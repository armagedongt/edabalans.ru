import assert from 'node:assert/strict';
import {readFile,mkdir,writeFile} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
import path from 'node:path';
const {chromium}=await import(pathToFileURL(path.join(process.env.CODEX_NODE_MODULES,'playwright/index.mjs')).href);
const root=new URL('../../app/static/',import.meta.url),module=await readFile(new URL('app-client-picker.mjs',root),'utf8');
const output=process.env.QA_OUT;assert(output);await mkdir(output,{recursive:true});
const ids=[1,2,3,4].map(n=>'00000000-0000-4000-8000-'+String(n).padStart(12,'0'));
const clients=[['Анна','anna@example.test',true,1],['Борис','boris@example.test',true,45],['Виктор','viktor@example.test',false,0],['Поздний','late@example.test',false,0]].map(([display_name,email,used,days],i)=>({user_id:ids[i],display_name,email,has_opened_app:used,first_opened_at:used?'2026-01-01T00:00:00Z':null,last_opened_at:used?new Date(Date.now()-days*86400000).toISOString():null}));
const browser=await chromium.launch(),evidence=[];
try{for(const width of [360,430,768,1440]){
 const page=await browser.newPage({viewport:{width,height:900}}),requests=[],errors=[];let reads=0,lateRelease,lateGate=null;
 page.on('pageerror',e=>errors.push(e.message));
 await page.route('http://127.0.0.1:8828/**',async route=>{
  const url=new URL(route.request().url());
  if(url.pathname==='/training')return route.fulfill({contentType:'text/html',body:'<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/assets/site-typography.css"><style>body{margin:0;padding:14px;background:#f5f5f7;font:14px var(--ed-font-body,Arial)}.st-top-email{display:inline-block}</style><div id="strength-app"><span class="st-top-email">owner@example.test</span></div><script type="module">import {mount} from "/assets/app-client-picker.mjs";window.canSwitch=true;window.EdabalansAppContext={canSwitchClient:()=>window.canSwitch};mount(document.querySelector("#strength-app"),"strength",{can_manage:true,actor:{user_id:"owner",email:"owner@example.test"}},location.origin);</script></html>'});
  if(url.pathname==='/assets/app-client-picker.mjs')return route.fulfill({contentType:'text/javascript',body:module});
  if(url.pathname==='/api/apps/manager/users'){
   const params=url.searchParams,scope=params.get('scope'),q=params.get('q').toLowerCase(),favorites=params.getAll('favorite_ids');requests.push({scope,q,app:params.get('app_code')});
   if(q==='поздний'&&lateGate)await lateGate;
   const users=clients.filter(u=>(scope==='all'||favorites.includes(u.user_id)||(u.has_opened_app&&(scope!=='active'||Date.parse(u.last_opened_at)>=Date.now()-30*86400000)))&&(!q||(u.display_name+' '+u.email).toLowerCase().includes(q))).sort((a,b)=>Number(favorites.includes(b.user_id))-Number(favorites.includes(a.user_id))||(Date.parse(b.last_opened_at)||0)-(Date.parse(a.last_opened_at)||0));
   return route.fulfill({json:{ok:true,users,more:false}});
  }
  if(url.pathname.startsWith('/admin/api/apps/strength/')){reads++;return route.fulfill({json:{has_state:true}});}
  const asset=new URL(url.pathname.replace('/assets/',''),root);if(!asset.href.startsWith(root.href))return route.abort();
  try{return route.fulfill({contentType:path.extname(asset.pathname)==='.css'?'text/css':'font/woff2',body:await readFile(asset)});}catch{return route.abort();}
 });
 await page.goto('http://127.0.0.1:8828/training');await page.getByRole('button',{name:'Выбрать клиента',exact:true}).click();
 const dialog=page.getByRole('dialog',{name:'Выбрать клиента'}),rows=dialog.locator('.ed-client-row');
 await rows.filter({hasText:'anna@example.test'}).waitFor();assert.equal(await rows.count(),2);assert((await rows.first().innerText()).includes('Анна'));
 assert((await rows.first().innerText()).includes('Открывал'));assert.equal(requests[0].app,'strength');assert.equal(requests[0].q,'');assert.equal(requests[0].scope,'used');
 await dialog.getByRole('button',{name:'Активные · 30 дней',exact:true}).click();await page.waitForFunction(()=>document.querySelectorAll('.ed-client-row').length===1);assert((await rows.innerText()).includes('Анна'));
 await dialog.getByRole('button',{name:'Все клиенты',exact:true}).click();await dialog.getByText('Введите имя или email для поиска по всей базе.',{exact:true}).waitFor();assert.equal(await rows.count(),0);
 const input=dialog.getByRole('searchbox');await input.fill('Виктор');await rows.filter({hasText:'viktor@example.test'}).waitFor();assert((await rows.innerText()).includes('Ещё не открывал'));
 await dialog.getByRole('button',{name:'Добавить в избранное: Виктор',exact:true}).click();await dialog.getByRole('button',{name:'Убрать из избранного: Виктор',exact:true}).waitFor();assert.equal(reads,0,'favorite does not open or switch the account');
 await input.fill('');await dialog.getByRole('button',{name:'Уже заходили',exact:true}).click();await page.waitForFunction(()=>document.querySelectorAll('.ed-client-row').length===3);assert((await rows.first().innerText()).includes('Виктор'));
 const favoritesToggle=dialog.getByRole('button',{name:'Избранное',exact:true}),own=dialog.getByRole('button',{name:'Мои данные',exact:true});
 const ownBox=await own.boundingBox(),favoritesBox=await favoritesToggle.boundingBox();assert(Math.abs(ownBox.width-favoritesBox.width)<1);assert.equal(ownBox.y,favoritesBox.y);
 for(const star of await dialog.locator('.ed-client-favorite').all()){const target=await star.boundingBox();assert(target.width>=48&&target.height>=48,'stars are easy to tap');}
 const identity=rows.filter({hasText:'anna@example.test'}).locator('.ed-client-identity'),activity=rows.filter({hasText:'anna@example.test'}).locator('.ed-client-activity');
 const identityBox=await identity.boundingBox(),activityBox=await activity.boundingBox();assert(activityBox.y>=identityBox.y+identityBox.height,'date stays on the second line');
 assert.equal(await identity.evaluate(el=>getComputedStyle(el).whiteSpace),'nowrap');
 await favoritesToggle.click();assert.equal(await rows.filter({hasText:'viktor@example.test'}).isVisible(),false);assert.equal(await rows.filter({hasText:'anna@example.test'}).isVisible(),true);assert.equal(await rows.filter({hasText:'boris@example.test'}).isVisible(),true);
 await favoritesToggle.click();await rows.filter({hasText:'viktor@example.test'}).waitFor();
 await page.evaluate(()=>document.fonts.ready);await page.screenshot({path:path.join(output,`${width}-favorites.png`)});
 assert.equal(await dialog.evaluate(el=>el.scrollWidth>el.clientWidth),false);
 const box=await dialog.boundingBox();assert(box.x>=0&&box.y>=0&&box.x+box.width<=width&&box.y+box.height<=900);
 await dialog.getByRole('button',{name:'Закрыть',exact:true}).click();await page.reload();await page.getByRole('button',{name:'Выбрать клиента',exact:true}).click();await rows.filter({hasText:'viktor@example.test'}).waitFor();assert((await rows.first().innerText()).includes('Виктор'));
 await page.evaluate(()=>window.canSwitch=false);await rows.filter({hasText:'anna@example.test'}).click();await dialog.getByText('Сначала сохраните текущие изменения или дождитесь сохранения.',{exact:true}).waitFor();assert.equal(reads,0);
 await dialog.getByRole('button',{name:'Убрать из избранного: Виктор',exact:true}).click();await page.waitForFunction(()=>document.querySelectorAll('.ed-client-row').length===2);assert.equal(await rows.filter({hasText:'viktor@example.test'}).count(),0);
 lateGate=new Promise(resolve=>{lateRelease=resolve;});await dialog.getByRole('button',{name:'Все клиенты',exact:true}).click();await input.fill('Поздний');await page.waitForRequest(r=>r.url().includes('q=')&&decodeURIComponent(r.url()).includes('Поздний'));
 await dialog.getByRole('button',{name:'Уже заходили',exact:true}).click();await input.fill('');await rows.filter({hasText:'anna@example.test'}).waitFor();lateRelease();await page.waitForTimeout(80);assert.equal(await rows.filter({hasText:'late@example.test'}).count(),0);
 await page.evaluate(()=>window.canSwitch=true);await rows.filter({hasText:'anna@example.test'}).click();await page.waitForURL('**/training?app_user='+ids[0]);assert.equal(reads,1);
 assert.deepEqual(errors,[]);evidence.push({width,requests:requests.length});await page.close();
}await writeFile(path.join(output,'evidence.json'),JSON.stringify(evidence,null,2));console.log('Client picker: real usage, active30, separate global search, persistent favorites, stale requests and unsaved guard PASS');}
finally{await browser.close();}
