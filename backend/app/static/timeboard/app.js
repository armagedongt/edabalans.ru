const KEY='edabalans.timeboard.v1';
const categories=[{id:'tasks',label:'Дела',icon:'✓'},{id:'meetings',label:'Встречи',icon:'↗'},{id:'consultations',label:'Консультации',icon:'◷'}];
const $=s=>document.querySelector(s);
const dateKey=d=>`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
function plusDays(d,n){const v=new Date(d);v.setDate(v.getDate()+n);return v;}
const initialDay=new Date();initialDay.setHours(12,0,0,0);
let firstDay=plusDays(initialDay,-14), dayCount=45, entries=[], editing=null, dragged=null, toastTimer;
let storageOkay=true;
try{const stored=localStorage.getItem(KEY);if(stored){const data=JSON.parse(stored);if(!Array.isArray(data)||!data.every(e=>e&&typeof e.id==='string'&&typeof e.title==='string'&&typeof e.date==='string'&&categories.some(c=>c.id===e.category)))throw Error('invalid');entries=data;}}catch{storageOkay=false;}
function notify(message){$('#toast').textContent=message;$('#toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').hidden=true,4500);}
function save(next){if(!storageOkay){notify('Хранилище недоступно. Записи не изменены.');return false;}try{localStorage.setItem(KEY,JSON.stringify(next));entries=next;$('#save-status').textContent='Все изменения сохранены';return true;}catch{notify('Не удалось сохранить. Записи не изменены. Скачайте резервную копию.');return false;}}
function el(tag,cls,text){const node=document.createElement(tag);if(cls)node.className=cls;if(text!==undefined)node.textContent=text;return node;}
function openEditor(date=dateKey(new Date()),category='tasks',entry=null){editing=entry?.id??null;const form=$('#entry-form');form.reset();form.elements.title.setCustomValidity('');for(const [key,value] of Object.entries({title:'',date,category,time:'',duration:'',notes:'',...entry})){const field=form.elements.namedItem(key);if(field){if(field.type==='checkbox')field.checked=Boolean(value);else field.value=value??'';}}$('#dialog-title').textContent=entry?'Редактировать запись':'Новая запись';$('#delete-entry').hidden=!entry;$('#editor').showModal();form.elements.title.focus();}
function card(entry){
  const node=el('article',`card${entry.done?' done':''}`);
  node.draggable=true;
  node.addEventListener('dragstart',event=>{dragged=entry.id;event.dataTransfer.setData('text/plain',entry.id);event.dataTransfer.effectAllowed='move';});
  node.addEventListener('dragend',()=>{dragged=null;document.querySelectorAll('.drag-over').forEach(n=>n.classList.remove('drag-over'));});
  const check=el('input','card-check');check.type='checkbox';check.checked=Boolean(entry.done);check.setAttribute('aria-label',`Выполнено: ${entry.title}`);
  check.addEventListener('change',()=>{save(entries.map(e=>e.id===entry.id?{...e,done:check.checked}:e));render();});
  const title=el('button','card-title',entry.title);title.type='button';title.addEventListener('click',()=>openEditor(entry.date,entry.category,entry));
  const line=el('div','card-line');line.append(check,title);node.append(line);
  const meta=[entry.time,categories.find(c=>c.id===entry.category)?.label,entry.duration?`${entry.duration} мин`:null].filter(Boolean).join(' · ');
  node.append(el('div','card-meta',meta));
  if(entry.notes)node.append(el('p','card-notes',entry.notes));
  return node;
}
function dayColumn(d){
  const key=dateKey(d),isToday=key===dateKey(new Date());
  const column=el('section',`day-column${isToday?' today':''}`);column.dataset.date=key;
  const heading=el('header','day-head');
  const date=el('h2','',new Intl.DateTimeFormat('ru',{day:'numeric',month:'long'}).format(d));
  heading.append(date,el('span','weekday',isToday?'Сегодня':new Intl.DateTimeFormat('ru',{weekday:'short'}).format(d)));
  const list=el('div','day-list');
  const query=$('#search').value.trim().toLocaleLowerCase('ru');
  const items=entries.filter(e=>e.date===key&&`${e.title} ${e.notes||''}`.toLocaleLowerCase('ru').includes(query)).sort((a,b)=>(a.time||'99').localeCompare(b.time||'99'));
  for(const entry of items)list.append(card(entry));
  const add=el('button','add-entry','+ Добавить');add.setAttribute('aria-label',`Добавить запись: ${key}`);add.onclick=()=>openEditor(key);
  list.append(add);column.append(heading,list);
  column.addEventListener('dragover',event=>{if(!dragged)return;event.preventDefault();event.dataTransfer.dropEffect='move';column.classList.add('drag-over');});
  column.addEventListener('dragleave',event=>{if(!column.contains(event.relatedTarget))column.classList.remove('drag-over');});
  column.addEventListener('drop',event=>{event.preventDefault();column.classList.remove('drag-over');if(!dragged)return;if(save(entries.map(e=>e.id===dragged?{...e,date:key}:e)))render();dragged=null;});
  return column;
}
function render(){
  const scroller=$('#board-scroll'),left=scroller.scrollLeft;
  const positions=new Map([...document.querySelectorAll('.day-column')].map(column=>[column.dataset.date,column.querySelector('.day-list').scrollTop]));
  $('#board').replaceChildren(...Array.from({length:dayCount},(_,i)=>dayColumn(plusDays(firstDay,i))));
  scroller.scrollLeft=left;
  for(const column of document.querySelectorAll('.day-column'))column.querySelector('.day-list').scrollTop=positions.get(column.dataset.date)||0;
}
function goToday(){
  const key=dateKey(new Date());
  if(!document.querySelector(`[data-date="${key}"]`)){firstDay=plusDays(new Date(),-14);dayCount=45;render();}
  const column=document.querySelector(`[data-date="${key}"]`);
  $('#board-scroll').scrollLeft=column.offsetLeft-$('#board').offsetLeft;
}
$('#new-entry').onclick=()=>openEditor();
$('#today').onclick=goToday;
$('#search').addEventListener('input',render);
for(const id of ['close-editor','cancel-editor'])$('#'+id).onclick=()=>$('#editor').close();
$('#board-scroll').addEventListener('scroll',()=>{
  const scroller=$('#board-scroll');
  if(scroller.scrollLeft<260){
    const oldWidth=scroller.scrollWidth,left=scroller.scrollLeft;
    firstDay=plusDays(firstDay,-14);dayCount+=14;render();
    scroller.scrollLeft=left+scroller.scrollWidth-oldWidth;
  }else if(scroller.scrollLeft+scroller.clientWidth>scroller.scrollWidth-520){dayCount+=14;render();}
},{passive:true});
$('#board-scroll').addEventListener('wheel',event=>{
  if(event.ctrlKey||event.shiftKey||Math.abs(event.deltaX)>Math.abs(event.deltaY))return;
  const list=event.target.closest('.day-list');
  if(list&&((event.deltaY>0&&list.scrollTop+list.clientHeight<list.scrollHeight-1)||(event.deltaY<0&&list.scrollTop>0)))return;
  event.preventDefault();
  const amount=event.deltaY*(event.deltaMode===1?20:event.deltaMode===2?$('#board-scroll').clientWidth:1);
  $('#board-scroll').scrollLeft+=amount;
},{passive:false});
$('#entry-form').addEventListener('submit',event=>{event.preventDefault();const data=new FormData(event.currentTarget);const title=String(data.get('title')).trim();if(!title){event.currentTarget.elements.title.setCustomValidity('Введите название');event.currentTarget.elements.title.reportValidity();return;}const entry={id:editing||crypto.randomUUID(),title,date:String(data.get('date')),category:String(data.get('category')),time:String(data.get('time')),duration:data.get('duration')?Number(data.get('duration')):null,notes:String(data.get('notes')).trim(),done:data.has('done')};const next=editing?entries.map(e=>e.id===editing?entry:e):[...entries,entry];if(save(next)){$('#editor').close();render();}});
$('#entry-form').elements.title.addEventListener('input',event=>event.target.setCustomValidity(''));
$('#delete-entry').onclick=()=>{if(editing&&confirm('Удалить эту запись?')){if(save(entries.filter(e=>e.id!==editing))){$('#editor').close();render();}}};
$('#export').onclick=()=>{const blob=new Blob([JSON.stringify({version:1,exportedAt:new Date().toISOString(),entries},null,2)],{type:'application/json'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=`ritm-${dateKey(new Date())}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
render();goToday();if(!storageOkay){$('#save-status').textContent='Хранилище недоступно';notify('Не удалось прочитать сохранённые записи. Исходные данные в браузере не изменены.');}
