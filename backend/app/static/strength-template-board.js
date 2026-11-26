(function(root,factory){
  var api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.StrengthTemplateBoard=api;
})(typeof globalThis!=='undefined'?globalThis:this,function(){
  'use strict';
  function move(lists,from,to,id,before){
    from=String(from);to=String(to);id=String(id);
    if(!lists[from]||!lists[to]||!lists[from].includes(id))return null;
    if(from===to&&before===id)return null;
    var result={};Object.keys(lists).forEach(function(key){result[key]=lists[key].slice();});
    result[from]=result[from].filter(function(value){return value!==id;});
    result[to]=result[to].filter(function(value){return value!==id;});
    var index=before==null?result[to].length:result[to].indexOf(String(before));
    if(index<0)return null;
    result[to].splice(index,0,id);
    return JSON.stringify(result)===JSON.stringify(lists)?null:result;
  }
  function search(catalog,query,excluded){
    var tokens=String(query||'').toLocaleLowerCase('ru').replace(/ё/g,'е').trim().split(/\s+/).filter(Boolean);
    return catalog.filter(function(item){
      var text=[item.exercise_name,item.full_name,item.short_name].join(' ').toLocaleLowerCase('ru').replace(/ё/g,'е');
      return item.catalog_active!==false&&!excluded.includes(String(item.exercise_id))&&tokens.every(function(token){return text.includes(token);});
    }).sort(function(a,b){return String(a.full_name||a.exercise_name).localeCompare(String(b.full_name||b.exercise_name),'ru');}).slice(0,15);
  }
  function mount(board,onMove){
    var drag=null,frame=0;
    function rows(list){return Array.from(list.querySelectorAll('[data-board-exercise]')).filter(function(row){return row.style.display!=='none';});}
    function restoreDuplicate(){if(drag&&drag.duplicate){drag.duplicate.style.display=drag.duplicateDisplay;drag.duplicate=null;}}
    function target(){
      if(!drag||!drag.started)return;
      restoreDuplicate();
      var list=document.elementsFromPoint(drag.x,drag.y).map(function(el){return el.closest('[data-board-list]');}).find(function(el){return el&&board.contains(el);});
      drag.target=null;
      if(!list)return;
      var duplicate=rows(list).find(function(row){return row.dataset.boardExercise===drag.id;});
      if(duplicate){drag.duplicate=duplicate;drag.duplicateDisplay=duplicate.style.display;duplicate.style.display='none';}
      var before=rows(list).find(function(row){var rect=row.getBoundingClientRect();return drag.y<rect.top+rect.height/2;});
      list.insertBefore(drag.slot,before||null);
      drag.target={type:list.dataset.boardList,before:before?before.dataset.boardExercise:null};
    }
    function tick(){
      if(!drag||!drag.started)return;
      var rect=board.getBoundingClientRect(),x=drag.x,y=drag.y;
      var dx=x<rect.left+36?-9:x>rect.right-36?9:0;
      var dy=y<rect.top+36?-9:y>rect.bottom-36?9:0;
      if(dx||dy){board.scrollLeft+=dx;board.scrollTop+=dy;target();}
      frame=requestAnimationFrame(tick);
    }
    function cleanup(){
      if(!drag)return;
      cancelAnimationFrame(frame);restoreDuplicate();
      drag.row.style.display=drag.display;
      if(drag.ghost)drag.ghost.remove();if(drag.slot)drag.slot.remove();
      drag.handle.setAttribute('aria-grabbed','false');
      if(drag.handle.hasPointerCapture(drag.pointer))drag.handle.releasePointerCapture(drag.pointer);
      drag=null;board.classList.remove('is-dragging');
    }
    function down(event){
      var handle=event.target.closest('[data-board-handle]');
      if(!handle||event.button!==0||drag)return;
      var row=handle.closest('[data-board-exercise]');
      drag={handle:handle,row:row,id:row.dataset.boardExercise,from:row.closest('[data-board-list]').dataset.boardList,
        pointer:event.pointerId,startX:event.clientX,startY:event.clientY,x:event.clientX,y:event.clientY,display:row.style.display};
      handle.setPointerCapture(event.pointerId);
    }
    function pointerMove(event){
      if(!drag||event.pointerId!==drag.pointer)return;
      drag.x=event.clientX;drag.y=event.clientY;
      if(!drag.started&&Math.hypot(drag.x-drag.startX,drag.y-drag.startY)<5)return;
      event.preventDefault();
      if(!drag.started){
        var rect=drag.row.getBoundingClientRect();drag.started=true;
        drag.ghost=drag.row.cloneNode(true);drag.ghost.classList.add('st-board-ghost');
        drag.ghost.removeAttribute('data-board-exercise');drag.ghost.setAttribute('aria-hidden','true');
        drag.ghost.style.width=rect.width+'px';drag.ghost.style.height=rect.height+'px';
        drag.ghost.querySelectorAll('button,input').forEach(function(el){el.tabIndex=-1;});
        document.body.appendChild(drag.ghost);
        drag.slot=document.createElement('div');drag.slot.className='st-template-drop-slot';drag.slot.style.height=rect.height+'px';
        drag.row.before(drag.slot);drag.row.style.display='none';drag.handle.setAttribute('aria-grabbed','true');board.classList.add('is-dragging');
        frame=requestAnimationFrame(tick);
      }
      drag.ghost.style.left=(drag.x-22)+'px';drag.ghost.style.top=(drag.y-18)+'px';target();
    }
    function up(event){
      if(!drag||event.pointerId!==drag.pointer)return;
      var value=drag.started&&drag.target?{from:drag.from,to:drag.target.type,id:drag.id,before:drag.target.before}:null;
      cleanup();if(value)onMove(value.from,value.to,value.id,value.before);
    }
    function cancel(event){if(!event||!drag||event.pointerId===drag.pointer)cleanup();}
    function key(event){
      if(event.key==='Escape'&&drag){event.preventDefault();event.stopPropagation();cleanup();return;}
      var handle=event.target.closest&&event.target.closest('[data-board-handle]');if(!handle||!board.contains(handle)||!['ArrowUp','ArrowDown','ArrowLeft','ArrowRight'].includes(event.key))return;
      var row=handle.closest('[data-board-exercise]'),list=row.closest('[data-board-list]'),items=rows(list),index=items.indexOf(row),to=list,before;
      if(event.key==='ArrowUp'){if(index===0)return;before=items[index-1];}
      if(event.key==='ArrowDown'){if(index===items.length-1)return;before=items[index+2];}
      if(event.key==='ArrowLeft'||event.key==='ArrowRight'){
        var lists=Array.from(board.querySelectorAll('[data-board-list]')),column=lists.indexOf(list)+(event.key==='ArrowLeft'?-1:1);
        if(column<0||column>=lists.length)return;to=lists[column];before=rows(to).filter(function(item){return item.dataset.boardExercise!==row.dataset.boardExercise;})[index];
      }
      event.preventDefault();onMove(list.dataset.boardList,to.dataset.boardList,row.dataset.boardExercise,before?before.dataset.boardExercise:null);
    }
    board.addEventListener('pointerdown',down);document.addEventListener('keydown',key,true);
    document.addEventListener('pointermove',pointerMove,{passive:false});document.addEventListener('pointerup',up);document.addEventListener('pointercancel',cancel);
    return function(){cleanup();board.removeEventListener('pointerdown',down);document.removeEventListener('keydown',key,true);document.removeEventListener('pointermove',pointerMove);document.removeEventListener('pointerup',up);document.removeEventListener('pointercancel',cancel);};
  }
  return {move:move,search:search,mount:mount};
});
