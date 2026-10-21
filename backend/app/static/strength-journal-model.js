(function(root){
  'use strict';
  function empty(value){ return value === '' || value === null || value === undefined; }
  function completion(set){
    if(['planWeight','planReps','factWeight','factReps'].some(function(key){return empty(set[key]);})) return 'neutral';
    if(Number(set.factWeight)<Number(set.planWeight)) return 'under';
    if(Number(set.factWeight)>Number(set.planWeight)) return 'over';
    if(Number(set.factReps)<Number(set.planReps)) return 'under';
    return Number(set.factReps)>Number(set.planReps) ? 'over' : 'done';
  }
  function pastePlan(existing, source){
    var length=Math.max(source.length,existing.length);
    return Array.from({length:length},function(_,index){
      var old=existing[index] || {};
      return Object.assign({factWeight:'',factReps:'',rpe:'',completed:false},old,{
        set_number:index+1,planWeight:source[index] ? source[index].weight : '',planReps:source[index] ? source[index].reps : ''
      });
    }).filter(function(set,index){return index<source.length || !empty(set.factWeight) || !empty(set.factReps) || !empty(set.rpe) || set.completed;});
  }
  function parseRussianDate(value){
    value=String(value || '').trim();
    if(!value)return '';
    var parts=/^(\d{2})\.(\d{2})\.(\d{4})$/.exec(value);
    if(!parts || Number(parts[3])<1)return null;
    var iso=parts[3]+'-'+parts[2]+'-'+parts[1],date=new Date(iso+'T00:00:00Z');
    return !Number.isNaN(date.getTime()) && date.toISOString().slice(0,10)===iso ? iso : null;
  }
  var api={completion:completion,pastePlan:pastePlan,parseRussianDate:parseRussianDate};
  if(typeof module!=='undefined' && module.exports) module.exports=api;
  else root.StrengthJournalModel=api;
})(typeof window!=='undefined' ? window : globalThis);
