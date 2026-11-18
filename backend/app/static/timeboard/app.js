const root = document.querySelector('#week-board-final');
const $ = selector => root.querySelector(selector);
const sheet = $('.sheet');
const dialog = $('.editor');
const content = $('.editor-content');
const icons = {outside:'📍',training:'🏋️',work:'💼',posts:'✍️',finance:'💳',history:'📓'};
const flags = {'':'Без цвета',blue:'Синий',green:'Зелёный',red:'Красный'};
const weekdays = ['Пн','Вт','Ср','Чт','Пт','Сб','Вс'];
const fields = {date:'Дата',cat:'Категория',title:'Действие',time:'Время',duration:'Минуты',note:'Комментарий',url:'Ссылка',flag:'Цвет',phase:'Цикл',done:'Выполнено'};
const periods = {'':'Нет метки',period:'Месячные',ovulation:'Овуляция'};
const dateFormat = new Intl.DateTimeFormat('ru', {day:'numeric',month:'short',timeZone:'UTC'});
const shortDate = key => key.slice(8)+'.'+key.slice(5,7);
const dayKey = day => day.toISOString().slice(0,10);
const todayKey = () => new Intl.DateTimeFormat('sv-SE', {timeZone:'Europe/Moscow',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
const dateAt = key => new Date(key+'T12:00:00Z');
const plusDays = (day,n) => new Date(day.getTime()+n*86_400_000);
const monday = key => {
  const day = dateAt(key);
  return plusDays(day,-((day.getUTCDay()+6)%7));
};

let state = {revision:0,categories:{},entries:[]};
let canEdit = false;
let week = monday(todayKey());
let mode = matchMedia('(max-width:650px)').matches ? 'compact' : 'table';
let expanded = null;
let columns = Object.keys(icons);
let widths = Object.fromEntries(columns.map(key=>[key,1]));
let drag;
let pending;
let submitting = false;

function safe(value='') {
  const escaped = {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'};
  return String(value ?? '').replace(/[&<>"']/g, char=>escaped[char]);
}

function button(label, attrs='', cls='') {
  return '<button type="button" class="'+cls+'" '+attrs+'>'+label+'</button>';
}

function status(message) {
  const output = dialog.open ? $('#editor-status') : $('#status');
  output.textContent = message;
}

async function request(path, packet) {
  const options = packet === undefined ? {} : {
    method:'POST',
    headers:{'Content-Type':'application/json','X-Timeboard-Request':'1'},
    body:JSON.stringify(packet),
  };
  const response = await fetch('api/'+path, options);
  if (response.status === 401) throw Error('Сессия закончилась. Войдите для правок.');
  const data = await response.json().catch(()=>null);
  if (!response.ok || !data) throw Error(typeof data?.detail==='string' ? data.detail : 'Не удалось получить ответ сервера.');
  return data;
}

async function reload() {
  state = await request('state');
  render();
}

function entriesFor(key, cat) {
  return state.entries.filter(entry => entry.date === key && (cat ? entry.cat === cat : entry.cat !== 'sonya'))
    .sort((a,b)=>(a.time || '99').localeCompare(b.time || '99'));
}

function setWidths() {
  sheet.style.setProperty('--columns',columns.map(key=>'minmax(0,'+widths[key]+'fr)').join(' '));
}

function header() {
  return '<div class="head"><div>Дата</div><div>График</div>'+columns.map((key,index)=>{
    const label = safe(state.categories[key]);
    const handle = index < columns.length-1 ? button('','data-resize="'+index+'" aria-label="Ширина столбца '+label+'"','resize') : '';
    return '<div class="column-label" tabindex="0" data-column="'+index+'" title="'+label+' · перетащите заголовок">'+label+handle+'</div>';
  }).join('')+'</div>';
}

function row(key,index) {
  const heart = entriesFor(key,'sonya').find(entry=>entry.phase)?.phase;
  const expandedFor = view => String(expanded?.key===key && expanded.view===view);
  const cycle = heart==='period' ? ' cycle' : heart==='ovulation' ? ' peak' : '';
  const date = button('<span>'+shortDate(key)+'</span><small>'+weekdays[index]+'</small>',
    'data-key="'+key+'" data-view="all" aria-label="Планы дня, '+shortDate(key)+'" aria-expanded="'+expandedFor('all')+'"',
    'tile date'+(index>4?' weekend':''));
  const companion = button('<span class="heart" aria-hidden="true">'+(heart?'♥':'♡')+'</span>',
    'data-key="'+key+'" data-view="sonya" aria-label="График Сони, '+shortDate(key)+'" aria-expanded="'+expandedFor('sonya')+'"',
    'tile sonya'+cycle);
  const data = columns.map(cat=>column(key,cat)).join('');
  return '<div class="row" data-row="'+key+'"><div>'+date+'</div><div>'+companion+'</div>'+
    (mode==='table'?data:'<div class="icons">'+data+'</div>')+'</div>'+
    (expanded?.key===key ? details(key,expanded.view) : '');
}

function column(key,cat) {
  const entries = entriesFor(key,cat);
  const first = entries[0];
  const label = safe(state.categories[cat])+', '+shortDate(key);
  const attrs = 'data-key="'+key+'" data-view="'+cat+'" aria-label="'+label+'"';
  if (mode==='compact') {
    return first ? button(icons[cat]+(entries.length>1?' <small>'+entries.length+'</small>':''),attrs,
      'emoji flag-'+(entries.find(entry=>entry.flag)?.flag||'')) : '';
  }
  const count = entries.length>1 ? button('+'+(entries.length-1),attrs,'count') : '';
  if (!canEdit) {
    return '<div>'+ (first ? '<div class="cell flag-'+first.flag+'">'+
      button(safe(first.title),attrs+' title="'+safe(first.title)+'"','read-cell')+count+'</div>' : '')+'</div>';
  }
  return '<div><div class="cell flag-'+(first?.flag||'')+'"><input data-inline data-key="'+key+'" data-cat="'+cat+'" data-id="'+(first?.id||'')+
    '" maxlength="160" aria-label="'+label+'" placeholder="Введите текст" value="'+safe(first?.title)+'">'+count+'</div></div>';
}

function entryCard(entry) {
  const timing = [entry.time,entry.duration && entry.duration+' мин'].filter(Boolean).join(' · ');
  const palette = Object.entries(flags).map(([color,label])=>button(color?'':'×',
    'data-flag="'+color+'" data-id="'+entry.id+'" aria-label="'+label+'" aria-pressed="'+(entry.flag===color)+'"',
    'swatch flag-'+color)).join('');
  const actions = canEdit ? '<div class="record-actions">'+button('Изменить','data-edit="'+entry.id+'"')+
    '<div class="palette" role="group" aria-label="Цвет записи">'+palette+'</div></div>' : '';
  return '<article class="record flag-'+entry.flag+'"><small>'+safe(state.categories[entry.cat])+'</small>'+
    '<p>'+safe(entry.title)+(entry.done?' ✓':'')+'</p>'+(timing?'<small>'+safe(timing)+'</small>':'')+
    (entry.note?'<p>'+safe(entry.note)+'</p>':'')+
    (entry.url?'<a href="'+safe(entry.url)+'" rel="noreferrer noopener">'+safe(entry.url)+'</a>':'')+actions+'</article>';
}

function details(key,view) {
  const title = view==='all' ? 'Планы дня' : state.categories[view];
  const entries = entriesFor(key,view==='all'?null:view);
  const actions = canEdit ? button('+ Запись','data-add data-key="'+key+'" data-cat="'+(view==='all'?'outside':view)+'"') : '';
  return '<section class="detail"><div class="detail-head"><strong>'+shortDate(key)+' · '+safe(title)+'</strong><div class="group">'+
    actions+button('Свернуть','data-collapse')+'</div></div><div class="cards">'+
    (entries.length?entries.map(entryCard).join(''):'<p class="details-empty">Записей нет</p>')+'</div></section>';
}

function render() {
  $('.scroll').classList.toggle('compact',mode==='compact');
  $('[data-reset]').hidden = mode==='compact';
  root.querySelectorAll('[data-mode]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.mode===mode)));
  $('#week-label').textContent = dateFormat.format(week)+' – '+dateFormat.format(plusDays(week,6));
  sheet.innerHTML = (mode==='table'?header():'')+weekdays.map((_,index)=>row(dayKey(plusDays(week,index)),index)).join('');
  setWidths();
}

function openDialog(title,body) {
  $('#editor-title').textContent = title;
  $('#editor-status').textContent = '';
  content.innerHTML = body;
  pending = null;
  if (!dialog.open) dialog.showModal();
}

function selectOptions(values,selected) {
  return Object.entries(values).map(([key,label])=>'<option value="'+key+'" '+(key===selected?'selected':'')+'>'+safe(label)+'</option>').join('');
}

function editEntry(key,cat,entry) {
  const e = entry || {date:key,cat};
  openDialog(entry?'Редактировать запись':'Новая запись',
    '<form id="entry-form" data-id="'+(entry?.id||'')+'"><div class="form-grid">'+
    '<label>Дата<input name="date" type="date" required value="'+safe(e.date)+'"></label>'+
    '<label>Категория<select name="cat">'+selectOptions(state.categories,e.cat)+'</select></label>'+
    '<label>Время<input name="time" type="time" value="'+safe(e.time)+'"></label>'+
    '<label>Минуты<input name="duration" type="number" min="1" max="1440" value="'+safe(e.duration)+'"></label>'+
    '<label class="wide">Действие<input name="title" required maxlength="160" value="'+safe(e.title)+'"></label>'+
    '<label class="wide">Комментарий<textarea name="note">'+safe(e.note)+'</textarea></label>'+
    '<label class="wide">Ссылка<input name="url" type="url" value="'+safe(e.url)+'"></label>'+
    '<label>Цвет<select name="flag">'+selectOptions(flags,e.flag||'')+'</select></label>'+
    '<label data-phase '+(e.cat==='sonya'?'':'hidden')+'>Цикл<select name="phase">'+selectOptions(periods,e.phase||'')+'</select></label>'+
    '<label>Выполнено<select name="done">'+selectOptions({'false':'Нет','true':'Да'},String(e.done??false))+'</select></label></div>'+
    '<div class="group"><button class="primary" type="submit">Сохранить</button>'+
    (entry ? button('Удалить','data-remove="'+entry.id+'"') : '')+'</div></form>');
  $('[name=title]').focus();
}

function openImport() {
  openDialog('Вставить изменения',
    '<label>Пакет JSON<textarea class="payload" id="packet" spellcheck="false"></textarea></label>'+
    '<p class="note">Записи, которые вы примените, будут видны по открытой ссылке.</p>'+
    '<div class="group import-actions">'+button('Вставить из буфера','data-paste')+button('Проверить','data-preview','primary')+
    '</div><div class="import-preview"></div>');
}

function showChanges(changes) {
  const labels = {add:'Добавить',update:'Изменить',remove:'Удалить'};
  const preview = $('.import-preview');
  const list = changes.map(({op,before,after})=>{
    const entry = after ?? before;
    const properties = Object.keys(fields).filter(key=>op==='update' ? before[key]!==after[key] : entry[key]);
    return '<li><strong>'+labels[op]+' · '+safe(entry.title)+'</strong><ul>'+properties.map(key=>{
      const format = item=>safe(key==='cat'?state.categories[item]:key==='flag'?flags[item]:key==='phase'?periods[item]:item ?? '—');
      return '<li>'+fields[key]+' · '+(op==='update'?format(before[key])+' → ':'')+format(entry[key])+'</li>';
    }).join('')+'</ul></li>';
  }).join('');
  preview.innerHTML = '<ol>'+list+'</ol>'+button('Применить','data-apply','primary');
}

async function previewImport() {
  pending = null;
  $('.import-preview').replaceChildren();
  const editor = $('#packet');
  let packet;
  const original = editor.value;
  try {
    const source = editor.value.trim().replace(/^```(?:json)?\s*([\s\S]+?)\s*```$/i,'$1');
    packet = JSON.parse(source);
  } catch {
    throw Error('Вставьте целый JSON из ChatGPT.');
  }
  const preview = await request('preview',packet);
  if (dialog.open && $('#packet')===editor && editor.value===original) {
    const first = preview.changes[0];
    pending = {packet,target:first.after || first.before};
    showChanges(preview.changes);
  }
}

async function apply(operations, target, closeEditor=false) {
  const packet = Array.isArray(operations) ? {v:1,baseRevision:state.revision,ops:operations} : operations;
  const result = await request('apply',packet);
  if (target) {
    week = monday(target.date);
    expanded = {key:target.date,view:target.cat==='sonya'?'sonya':'all'};
  }
  if (closeEditor) dialog.close();
  try {
    await reload();
  } catch {
    status('Изменения сохранены. Обновите страницу, чтобы увидеть их.');
    return;
  }
  status('Применено изменений: '+result.applied);
}

async function run(task) {
  if (submitting) return;
  submitting = true;
  sheet.inert = true;
  content.inert = true;
  try {
    await task();
  } catch(error) {
    status(error.message);
  } finally {
    sheet.inert = false;
    content.inert = false;
    submitting = false;
  }
}

function setWeek(day) {
  week = day;
  expanded = null;
  render();
}

$('#previous').onclick = ()=>setWeek(plusDays(week,-7));
$('#next').onclick = ()=>setWeek(plusDays(week,7));
$('#today').onclick = ()=>setWeek(monday(todayKey()));

root.addEventListener('click',event=>{
  const b = event.target.closest('button');
  if (!b) return;
  const d = b.dataset;
  if (d.mode) {
    mode = d.mode;
    render();
  } else if ('reset' in d) {
    widths = Object.fromEntries(columns.map(key=>[key,1]));
    setWidths();
  } else if ('collapse' in d) {
    expanded = null;
    render();
  } else if (d.view) {
    expanded = expanded?.key===d.key && expanded.view===d.view ? null : {key:d.key,view:d.view};
    render();
  } else if ('closeEditor' in d) {
    dialog.close();
  } else if (canEdit && 'add' in d) {
    editEntry(d.key || todayKey(),d.cat || 'outside');
  } else if (canEdit && d.edit) {
    editEntry(null,null,state.entries.find(entry=>entry.id===d.edit));
  } else if (canEdit && 'flag' in d) {
    run(()=>apply([{op:'update',id:d.id,flag:d.flag}]));
  } else if (canEdit && d.remove) {
    if (confirm('Удалить запись?')) run(()=>apply([{op:'remove',id:d.remove}],null,true));
  } else if (canEdit && 'import' in d) {
    openImport();
  } else if ('paste' in d) {
    run(async()=>{
      const field = $('#packet');
      try {
        field.value = await navigator.clipboard.readText();
        field.dispatchEvent(new Event('input',{bubbles:true}));
      } catch {
        status('Нажмите на поле и выберите «Вставить».');
      }
      field.focus();
    });
  } else if ('preview' in d) {
    run(previewImport);
  } else if ('apply' in d && pending) {
    const {packet,target} = pending;
    run(()=>apply(packet,target,true));
  }
});

root.addEventListener('input',event=>{
  if (event.target.id !== 'packet') return;
  pending = null;
  $('.import-preview').replaceChildren();
  status('');
});

root.addEventListener('change',event=>{
  const field = event.target;
  if (field.name==='cat' && field.form?.id==='entry-form') {
    $('[data-phase]').hidden = field.value!=='sonya';
  } else if (canEdit && field.hasAttribute('data-inline')) {
    const {id,key,cat} = field.dataset;
    const title = field.value.trim();
    if (!title) {
      field.value = field.defaultValue;
      return;
    }
    run(async()=>{
      try {
        await apply([id?{op:'update',id,title}:{op:'add',date:key,cat,title}]);
      } catch(error) {
        field.value = field.defaultValue;
        throw error;
      }
    });
  }
});

root.addEventListener('submit',event=>{
  const form = event.target;
  if (!canEdit || form.id!=='entry-form') return;
  event.preventDefault();
  const values = Object.fromEntries(new FormData(form));
  const data = {...values,time:values.time||null,duration:values.duration?Number(values.duration):null,
    done:values.done==='true',phase:values.cat==='sonya'?values.phase:''};
  const op = form.dataset.id ? {op:'update',id:form.dataset.id,...data} : {op:'add',...data};
  run(()=>apply([op],data,true));
});

function resize(index, fraction) {
  const first = columns[index];
  const second = columns[index+1];
  const total = widths[first]+widths[second];
  const min = Math.min(58*columns.length/(sheet.clientWidth-140),total/2);
  widths[first] = Math.max(min,Math.min(total-min,fraction));
  widths[second] = total-widths[first];
  setWidths();
}

function moveColumn(from,to) {
  if (from===to || to<0 || to>=columns.length) return;
  columns.splice(to,0,columns.splice(from,1)[0]);
  render();
  $('[data-column="'+to+'"]').focus({preventScroll:true});
}

sheet.addEventListener('keydown',event=>{
  const d = event.target.dataset;
  if ('inline' in d && event.key==='Enter') event.target.blur();
  if (!['ArrowLeft','ArrowRight'].includes(event.key)) return;
  const direction = event.key==='ArrowRight'?1:-1;
  if ('resize' in d) {
    event.preventDefault();
    const index = Number(d.resize);
    resize(index,widths[columns[index]]+direction*.1);
  } else if ('column' in d && event.altKey) {
    event.preventDefault();
    const index = Number(d.column);
    moveColumn(index,index+direction);
  }
});

sheet.addEventListener('pointerdown',event=>{
  if (event.button!==0) return;
  const handle = event.target.closest('[data-resize]');
  const column = event.target.closest('[data-column]');
  if (handle) {
    const index = Number(handle.dataset.resize);
    drag = {resize:index,start:widths[columns[index]],x:event.clientX};
    handle.setPointerCapture(event.pointerId);
  } else if (column && event.pointerType==='mouse') {
    drag = {column:Number(column.dataset.column),x:event.clientX,target:null};
    column.setPointerCapture(event.pointerId);
  }
});

sheet.addEventListener('pointermove',event=>{
  if (!drag) return;
  if ('resize' in drag) {
    resize(drag.resize,drag.start+(event.clientX-drag.x)*columns.length/(sheet.clientWidth-140));
    return;
  }
  const target = document.elementFromPoint(event.clientX,event.clientY)?.closest('[data-column]');
  sheet.querySelector('.is-target')?.classList.remove('is-target');
  drag.target = target && Math.abs(event.clientX-drag.x)>4 ? Number(target.dataset.column) : null;
  if (drag.target!==null && drag.target!==drag.column) target.classList.add('is-target');
});

sheet.addEventListener('pointerup',()=>{
  if (drag && 'column' in drag && drag.target!==null) moveColumn(drag.column,drag.target);
  drag = null;
});
sheet.addEventListener('lostpointercapture',()=>{
  drag = null;
  sheet.querySelector('.is-target')?.classList.remove('is-target');
});

function offerLegacyExport() {
  try {
    const value = localStorage.getItem('edabalans.timeboard.v1');
    if (!value || !JSON.parse(value).length) return;
    const control = $('#legacy-export');
    control.hidden = false;
    control.onclick = ()=>{
      const url = URL.createObjectURL(new Blob([value],{type:'application/json'}));
      Object.assign(document.createElement('a'),{href:url,download:'timeboard-browser-backup.json'}).click();
      setTimeout(()=>URL.revokeObjectURL(url),1000);
    };
  } catch {
    // Ignore unavailable browser storage. Server data is independent.
  }
}

run(async()=>{
  const [board,session] = await Promise.all([request('state'),request('session')]);
  state = board;
  canEdit = session.canEdit;
  $('#login').hidden = canEdit;
  $('[data-import]').hidden = !canEdit;
  $('[data-add]').hidden = !canEdit;
  offerLegacyExport();
  render();
});
