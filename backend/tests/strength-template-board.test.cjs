const {test}=require('node:test');
const assert=require('node:assert/strict');
const {move,search}=require('../app/static/strength-template-board.js');
test('reorder into exact slots, append, and cancel no-op without mutating input',()=>{
 const lists={1:['a','b','c'],2:[]};
 assert.deepEqual(move(lists,1,1,'c','a'),{1:['c','a','b'],2:[]});
 assert.deepEqual(move(lists,1,1,'a',null),{1:['b','c','a'],2:[]});
 assert.equal(move(lists,1,1,'b','c'),null);
 assert.equal(move(lists,1,1,'b','b'),null);
 assert.equal(move(lists,1,1,'b','missing'),null);
 assert.deepEqual(lists,{1:['a','b','c'],2:[]});
});
test('cross-template move inserts between existing exercises and merges a duplicate',()=>{
 assert.deepEqual(move({1:['a','b'],2:['x','y']},1,2,'a','y'),{1:['b'],2:['x','a','y']});
 assert.deepEqual(move({1:['a','b'],2:['a','x','y']},1,2,'a','y'),{1:['b'],2:['x','a','y']});
 assert.deepEqual(move({1:['a'],2:[]},1,2,'a',null),{1:[],2:['a']});
 assert.equal(move({1:['a'],2:[]},1,2,'unknown',null),null);
 assert.equal(move({1:['a'],2:[]},1,3,'a',null),null);
});
test('search matches full names and aliases, normalizes ё, excludes selected and archived items',()=>{
 const data=[{exercise_id:'a',source:'base',exercise_name:'Жим',full_name:'Жим штанги лёжа',short_name:'Грудь'},
  {exercise_id:'b',source:'base',exercise_name:'Жим ногами',full_name:'Жим ногами в тренажёре'},
  {exercise_id:'c',source:'custom',exercise_name:'Жим скрытый',catalog_active:false}];
 assert.deepEqual(search(data,'ЛЕЖА жим',[]).map(i=>i.exercise_id),['a']);
 assert.deepEqual(search(data,'грудь',[]).map(i=>i.exercise_id),['a']);
 assert.deepEqual(search(data,'жим',['a']).map(i=>i.exercise_id),['b']);
 assert.deepEqual(search(data,'нет такого',[]),[]);
});

test('only the base catalogue and own custom exercises can be selected; history remains intact',()=>{
 const data=[{exercise_id:'base',source:'base',full_name:'Тяга блока'},
  {exercise_id:'custom-own',source:'custom',exercise_name:'Моя тяга'},
  {exercise_id:'legacy',source:'history',exercise_name:'Тяга из истории'},
  {exercise_id:'hidden',source:'custom',exercise_name:'Тяга удалённая',catalog_active:false},
  {exercise_id:'unknown',exercise_name:'Тяга без источника'}];
 const before=structuredClone(data);
 assert.deepEqual(search(data,'тяга',[]).map(i=>i.exercise_id),['custom-own','base']);
 assert.deepEqual(search(data,'',[]).map(i=>i.exercise_id),['custom-own','base']);
 assert.deepEqual(data,before);
});
