const {test}=require('node:test'),assert=require('node:assert/strict');
const {completion,pastePlan,blankSets,parseRussianDate}=require('../app/static/strength-journal-model.js');
const plan={planWeight:60,planReps:8,factWeight:60,factReps:8};
test('completion compares weight before repetitions and leaves partial records neutral',()=>{
  for(const [weight,reps,expected] of [[60,8,'done'],[60,9,'over'],[61,6,'over'],[59,20,'under'],[60,7,'under'],['',8,'neutral'],[60,'','neutral']]){
    assert.equal(completion({...plan,factWeight:weight,factReps:reps}),expected);
  }
  assert.equal(completion({planWeight:0,planReps:10,factWeight:0,factReps:10}),'done');
});
test('paste replaces plan without mutating source or losing fact, effort or notes',()=>{
  const existing=[{planWeight:10,planReps:1,factWeight:20,factReps:5,rpe:9},{planWeight:11,planReps:2,factWeight:'',factReps:'',rpe:''}];
  const before=structuredClone(existing),copied=[{weight:30,reps:8}];
  const result=pastePlan(existing,copied);
  assert.equal(result.length,1);assert.equal(result[0].planWeight,30);assert.equal(result[0].planReps,8);
  assert.equal(result[0].factWeight,20);assert.equal(result[0].factReps,5);assert.equal(result[0].rpe,9);
  assert.deepEqual(existing,before);assert.deepEqual(copied,[{weight:30,reps:8}]);
});
test('paste never deletes already entered facts from extra sets',()=>{
  const result=pastePlan([{factWeight:10,factReps:1},{factWeight:20,factReps:2,rpe:7}], [{weight:30,reps:8}]);
  assert.equal(result.length,2);assert.equal(result[1].factWeight,20);assert.equal(result[1].planWeight,'');
});

test('a blank workout inherits every set role and count but no plan, fact or effort',()=>{
  const source=[{role:'warmup',planWeight:20,factWeight:20,rpe:10},{role:'work',planReps:8},
    {role:'warmup'},{role:'work'},{role:'work'}],before=structuredClone(source);
  const next=blankSets(source);
  assert.equal(next.length,5);assert.deepEqual(next.map(row=>row.role),source.map(row=>row.role));
  for(const [i,row] of next.entries()){
    assert.equal(row.set_number,i+1);assert.equal(row.completed,false);
    for(const key of ['planWeight','planReps','factWeight','factReps','rpe'])assert.equal(row[key],'');
  }
  next[0].role='work';assert.deepEqual(source,before);
  assert.equal(blankSets([]).length,4);assert(blankSets([]).every(row=>row.role==='work'));
  assert.equal(blankSets([{}])[0].role,'work','legacy unmarked sets stay working');
});

test('manual paste overwrites inherited roles with the copied plan and preserves extra facts',()=>{
  const existing=[{role:'warmup',factWeight:30,factReps:8,rpe:8},{role:'work'},
    {role:'warmup',factWeight:20,factReps:12,rpe:7}],before=structuredClone(existing);
  const copied=[{weight:40,reps:10,role:'work'},{weight:20,reps:10,role:'warmup'}],source=structuredClone(copied);
  const result=pastePlan(existing,copied);
  assert.deepEqual(result.map(row=>row.role),['work','warmup','warmup']);
  assert.equal(result[0].planWeight,40);assert.equal(result[0].factWeight,30);assert.equal(result[0].rpe,8);
  assert.equal(result[2].planWeight,'');assert.equal(result[2].factWeight,20);
  assert.deepEqual(existing,before);assert.deepEqual(copied,source);
});

test('Russian date entry preserves a real calendar date and rejects impossible input',()=>{
  assert.equal(parseRussianDate('21.10.2026'),'2026-10-21');
  assert.equal(parseRussianDate('29.02.2024'),'2024-02-29');
  assert.equal(parseRussianDate('  '),'');
  for(const value of ['29.02.2025','31.04.2026','00.10.2026','21.13.2026','21.10.0000','2026-10-21','1.2.2026','01.02.2026<script>'])assert.equal(parseRussianDate(value),null,value);
});
