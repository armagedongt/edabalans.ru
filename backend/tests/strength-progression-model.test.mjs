import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createCases} from './fixtures/strength-progression-cases.mjs';
import {recommend} from '../app/static/strength-progression-model.mjs';
import {cardRequest} from '../app/static/strength-progression-model.mjs';
import {readFileSync} from 'node:fs';
const sample=id=>createCases().find(c=>c.id===id);

const catalog=JSON.parse(readFileSync(new URL('../app/strength_exercise_guides.json',import.meta.url),'utf8'));
function journal(){
  const c=sample('bench');
  return [...c.history.map((h,i)=>({session_id:h.id,number:i+1,date:h.date,workoutType:i%2+1,
    exercises:[{id:'bench-press',sets:h.sets.map((row,n)=>({role:row.role,planWeight:c.baseline[n].w,planReps:c.baseline[n].r,factWeight:row.w,factReps:row.r,rpe:row.rpe}))}]})),
    {session_id:'target',number:3,date:'',exercises:[{id:'bench-press',sets:c.baseline.map(row=>({role:row.role,planWeight:'',planReps:'',factWeight:'',factReps:'',rpe:''}))}]}];
}
const benchProfile=()=>structuredClone(catalog.find(row=>row.code==='bench-press').training);

test('all 50 reference profiles have explicit units, valid ranges and documented step conditions',()=>{
  assert.equal(catalog.length,50);assert.equal(new Set(catalog.map(row=>row.code)).size,50);
  for(const {code,training:p} of catalog){
    assert(p,code);assert(p.rep_range[0]>0&&p.rep_range[1]>=p.rep_range[0],code);
    assert(p.load_unit&&p.load_label&&p.step_note,code);
    assert(p.load_step===null||p.load_step>0,code);
    if(p.mode==='duration')assert(p.time_step>0);
  }
  assert.deepEqual(catalog.find(row=>row.code==='back-squat').training.rep_range,[6,15]);
  assert.deepEqual(catalog.find(row=>row.code==='deadlift').training.rep_range,[6,12]);
});

test('card request uses earlier facts across templates, never the destination fact, without mutation',()=>{
  const sessions=journal();sessions[2].exercises[0].sets[1].factWeight=999;
  const before=structuredClone(sessions),r=cardRequest(sessions,2,'bench-press',benchProfile());
  assert.equal(r.input.history.length,2);assert(!r.input.history.some(row=>row.id==='target'));
  assert.equal(r.input.baseline[1].w,sample('bench').baseline[1].w);
  assert(recommend(r.input).changed.length>0);assert.deepEqual(sessions,before);
  assert.notEqual(r.fingerprint,cardRequest([...sessions.slice(0,2),{...sessions[2],exercises:[{id:'bench-press',sets:sessions[2].exercises[0].sets.map(row=>({...row,factWeight:''}))}]}],2,'bench-press',benchProfile()).fingerprint);
});

test('card request excludes later dates and planned-only empty records',()=>{
  const sessions=journal();sessions[2].date=sessions[0].date;
  const r=cardRequest(sessions,2,'bench-press',benchProfile());assert.equal(r.input.history.length,1);
  assert.equal(r.sourceIds[0].number,1);
  const futureEmpty={session_id:'empty',date:'2027-01-01',exercises:[{id:'bench-press',sets:[{planWeight:500,planReps:20}]}]};
  sessions.splice(1,0,futureEmpty);assert.equal(cardRequest(sessions,3,'bench-press',benchProfile()).input.history.length,1);
});

test('a partly entered destination plan is not silently completed from history',()=>{
  const sessions=journal();sessions[2].exercises[0].sets[1].planWeight=80;
  assert.throws(()=>cardRequest(sessions,2,'bench-press',benchProfile()),/базовый план/);
});

test('equipment step and special conditions are explicit rather than inferred from comments',()=>{
  const sessions=journal(),profile=benchProfile();profile.load_step=0;
  assert.throws(()=>cardRequest(sessions,2,'bench-press',profile),/шаг/);
  profile.load_step=2.5;profile.last_reduced=true;
  assert.throws(()=>cardRequest(sessions,2,'bench-press',profile),/базовый план/);
  profile.last_reduced=false;profile.changed_conditions=true;
  assert.equal(recommend(cardRequest(sessions,2,'bench-press',profile).input).code,'conditions');
  profile.changed_conditions=false;profile.hold=true;
  assert.equal(recommend(cardRequest(sessions,2,'bench-press',profile).input).code,'coach');
});

test('same-day facts retain journal order rather than random UUID order',()=>{
  const sessions=journal();sessions[0].session_id='z-older';sessions[1].session_id='a-newer';
  sessions[0].date=sessions[1].date='2026-10-21';sessions[2].date='2026-10-22';
  for(const row of sessions[0].exercises[0].sets){row.planReps=row.factReps=10;row.rpe=8;}
  for(const row of sessions[1].exercises[0].sets){row.planReps=row.factReps=15;row.rpe=8;}
  const request=cardRequest(sessions,2,'bench-press',benchProfile());
  assert.deepEqual(request.sourceIds.map(row=>row.number),[1,2]);
  assert.equal(request.input.baseline[1].r,15);
  const result=recommend(request.input);assert.deepEqual(result.used,request.input.history.map(row=>row.id));
  assert.equal(result.next[1].w,request.input.baseline[1].w);
  assert.equal(result.next[1].r,15);
});

test('range conflicts are explicit while an underperformed fact remains valid input',()=>{
  const sessions=journal(),profile=benchProfile();
  const source=sessions[1].exercises[0].sets;
  source[1].planReps=source[1].factReps=25;
  assert.throws(()=>cardRequest(sessions,2,'bench-press',profile),/диапазон/);
  source[1].planReps=15;
  assert.throws(()=>cardRequest(sessions,2,'bench-press',profile),/диапазон/);
  source[1].factReps=5;
  assert.doesNotThrow(()=>cardRequest(sessions,2,'bench-press',profile));
  source[0].planReps=source[0].factReps=99;
  assert.doesNotThrow(()=>cardRequest(sessions,2,'bench-press',profile));
});
test('all 20 experiments are deterministic, immutable and preserve warm-ups and set count',()=>{
  for(const input of createCases()){
    const before=structuredClone(input),a=recommend(input),b=recommend(input);
    assert.deepEqual(a,b);assert.deepEqual(input,before);assert.equal(a.next.length,input.baseline.length);
    input.baseline.forEach((row,i)=>{if(row.role==='warmup')assert.deepEqual(a.next[i],row);});
    for(const i of a.changed){const row=a.next[i],[lo,hi]=input.profile.timeRange||input.profile.range;
      assert(row.r>=lo&&row.r<=hi);assert.equal(row.role,'work');
      if(row.w!==input.baseline[i].w)assert(input.profile.loads.includes(row.w));
    }
  }
});
test('weight forecast and queue are explicit, not a fixed reset to the range floor',()=>{
  const a=recommend(sample('squat'));assert.deepEqual(a.changed,[2]);assert.deepEqual([a.next[2].w,a.next[2].r],[105,13]);
  const b=recommend(sample('leg-press'));assert.equal(b.changed.length,3);assert(b.changed.every(i=>b.next[i].w===202.5&&b.next[i].r===15));
  const c=recommend(sample('rdl'));assert.equal(c.code,'one-real-step');assert.equal(c.changed.length,1);assert.equal(c.next[2].r,10);
});
test('all high effort holds; ready first position outranks unavailable penultimate',()=>{
  assert.equal(recommend(sample('triceps')).code,'all-high-rpe');
  assert.deepEqual(recommend(sample('biceps')).changed,[1]);
  const c=sample('bench');c.history.at(-1).sets[0].rpe=10;assert.equal(recommend(c).code,'progress');
});

test('warm-up numbers, missing facts and RPE never open, block or receive progression',()=>{
  const c=sample('bench'),expected=recommend(c);
  assert(expected.changed.length>0);
  c.baseline[0]={w:'',r:'',role:'warmup'};
  c.history.forEach(h=>h.sets[0]={w:'',r:'',rpe:10,role:'warmup'});
  const result=recommend(c);
  assert.deepEqual(result.changed,expected.changed);
  assert.deepEqual(result.next[0],c.baseline[0]);
  for(const i of result.changed)assert.equal(result.next[i].role,'work');
  const onlyWarmups=sample('bench');onlyWarmups.baseline.forEach(row=>row.role='warmup');
  assert.equal(recommend(onlyWarmups).code,'no-work');
});
test('unknown effort has a two-success gate and adds one rep to only one working set',()=>{
  const c=sample('bridge'),r=recommend(c);assert.equal(r.code,'conservative-reps');assert.equal(r.changed.length,1);
  const i=r.changed[0];assert.equal(i,2,'equal readiness keeps penultimate working position');assert.equal(r.next[i].r,c.baseline[i].r+1);assert.equal(r.next[i].w,c.baseline[i].w);
  assert.equal(recommend(sample('leg-curl')).code,'no-rpe-history');
});
test('partial, intentionally reduced and changed conditions never invent facts or erase baseline',()=>{
  for(const [id,code] of [['leg-extension','partial'],['abduction','reduced'],['pulldown','conditions']]){
    const c=sample(id),r=recommend(c);assert.equal(r.code,code);assert.deepEqual(r.next,c.baseline);
  }
});
test('isolated and repeated strong misses are distinguished without automatic deload',()=>{
  assert.equal(recommend(sample('adduction')).code,'possible-outlier');
  assert.equal(recommend(sample('row')).code,'repeated-drop');
});

test('earlier warm-ups are not counted as a second working-performance drop',()=>{
  const c=sample('row');assert.equal(recommend(c).code,'repeated-drop');
  c.history.at(-2).sets.forEach(row=>row.role='warmup');
  assert.notEqual(recommend(c).code,'repeated-drop');
  assert.equal(recommend(c).changed.length,0);
});
test('assistance, own weight and duration never use an invented effective external load',()=>{
  for(const id of ['pullup','gravitron']){const c=sample(id),r=recommend(c);assert(r.changed.length>0);assert(r.next.every((row,i)=>row.w===c.baseline[i].w));}
  const r=recommend(sample('plank'));assert.equal(r.code,'time');assert.equal(r.next[r.changed[0]].r,35);
  assert.equal(recommend(sample('incline')).code,'no-candidate');
});
test('future facts are excluded and at most five original records enter context',()=>{
  const c=sample('bench');for(let i=0;i<8;i++){const h=structuredClone(c.history[0]);h.id='old-'+i;h.date='2026-09-'+String(i+10).padStart(2,'0');c.history.unshift(h);}
  const future=structuredClone(c.history[0]);future.id='future';future.date='2027-01-01';c.history.push(future);
  const r=recommend(c);assert.equal(r.used.length,5);assert(!r.used.includes('future'));
});
test('an empty earlier record does not double the budget of one informative workout',()=>{
  const c=sample('bench');c.history[0].sets=[];const r=recommend(c);
  assert.equal(r.changed.length,1);assert(r.budget<=.015);
});
test('a historical warm-up is not a second confirmed working performance without RPE',()=>{
  const c=sample('bridge');c.history[0].sets.forEach(row=>row.role='warmup');
  assert.equal(recommend(c).changed.length,0);
});
test('duration needs a configured step and a ready position, not a different ready set',()=>{
  const c=sample('plank');delete c.profile.timeStep;assert.equal(recommend(c).code,'configuration');
  c.profile.timeStep=5;c.baseline=c.baseline.slice(0,2);c.baseline[0].r=60;
  c.history.forEach(h=>{h.sets=h.sets.slice(0,2);h.sets[0].r=60;h.sets[0].rpe=8;h.sets[1].rpe=9;});
  assert.equal(recommend(c).changed.length,0);
});
test('repetition counts are whole numbers rather than fractional targets',()=>{
  const c=sample('bench');c.baseline[1].r=10.5;c.history.at(-1).sets[1].r=10.5;
  assert.equal(recommend(c).code,'configuration');
  const badFact=sample('bench');badFact.history.at(-1).sets[1].r=10.5;
  assert.equal(recommend(badFact).code,'partial','a valid integer baseline must not mask invalid factual repetitions');
  assert.equal(recommend(badFact).changed.length,0);
});
test('an RPE9 position cannot use the above-budget real-step exception',()=>{
  const c=sample('squat');c.profile.loads=[80,100,110];c.profile.range=[8,15];
  c.baseline=[{w:100,r:15,role:'work'},{w:80,r:15,role:'work'}];
  c.history.forEach(h=>h.sets=[{w:100,r:15,role:'work',rpe:9},{w:80,r:15,role:'work',rpe:8}]);
  const r=recommend(c);assert.equal(r.granularity,false);assert.equal(r.changed.length,0);
});
