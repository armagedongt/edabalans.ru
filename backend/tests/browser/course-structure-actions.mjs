import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const html=readFileSync(new URL('../../app/static/masterclass-first-days-preview.html',import.meta.url),'utf8');
const original=html.slice(html.indexOf('function api('),html.indexOf('function serverDay('));
assert.ok(original.includes('refreshCourseStructure'));
for(const route of ['masterclass','calories','recipes']){
  const calls=[],updates=[];
  let fail=false;
  const context={identity:{email:'fixture@example.test',sessionToken:'fixture'},
    APP_HOST:'https://edabalans.ru',serverCourse:{structure_version:8},
    days:[{steps:[{id:'stable-original'}]}],currentStep:0,
    timezoneName:()=> 'UTC',encodeURIComponent,
    manifestFetch:async()=>({revision:9}),
    buildFromManifest:manifest=>updates.push(['manifest',manifest.revision]),
    applyCourse:payload=>{updates.push(['state',payload.structure_version]);context.serverCourse=payload},
    renderMenu:()=>updates.push(['menu']),renderDay:()=>updates.push(['day']),
    fetch:async(url,options)=>{
      calls.push({url,options});
      if(fail&&options.body){fail=false;return {ok:false,status:409,json:async()=>({detail:{reason:'structure_changed'}})}}
      return {ok:true,json:async()=>({structure_version:9})};
    }
  };
  vm.createContext(context);
  vm.runInContext(original.replaceAll('/api/masterclass/course',`/api/${route}/course`),context);
  const path=`/api/${route}/course/days/1/steps/0/complete`;
  await context.api(path,{method:'POST',body:JSON.stringify({email:context.identity.email})});
  let sent=JSON.parse(calls[0].options.body);
  assert.equal(sent.structure_version,8);assert.equal(sent.step_id,'stable-original');
  fail=true;
  await assert.rejects(context.api(path,{method:'POST',body:JSON.stringify({email:context.identity.email})}),/Программа обновилась/);
  assert.equal(calls.filter(call=>call.options.body).length,2,'No blind retry of an old positional action');
  assert.equal(calls.at(-1).url.startsWith(`https://edabalans.ru/api/${route}/course?`),true);
  assert.deepEqual(updates,[['manifest',9],['state',9],['menu'],['day']]);
  assert.equal(context.currentStep,-1);
}
console.log('Course action IDs, versions and stale-state recovery: 3 course surfaces passed');
