const root = document.querySelector('#week-board-final');
const $ = selector => root.querySelector(selector);
const sheet = $('.sheet');
const dialog = $('.editor');
const content = $('.editor-content');
const icons = {outside:'📍',training:'🏋️',work:'💼',posts:'✍️',finance:'💳',history:'📓'};
const flags = {'':'Без цвета',blue:'Синий',green:'Зелёный',red:'Красный'};
const weekdays = ['Пн','Вт','Ср','Чт','Пт','Сб','Вс'];
const fields = {date:'Дата',cat:'Категория',title:'Действие',time:'Время',duration:'Минуты',note:'Комментарий',url:'Ссылка',flag:'Цвет',phase:'Цикл',sonyaRole:'Тип записи Сони',done:'Выполнено'};
const periods = {'':'Нет метки',period:'Месячные',ovulation:'Овуляция'};
const sonyaRoles = {'':'Событие',weekly:'Обычный график',override:'Замена графика на день',indicator:'Индикатор'};
const shortDate = key => key.slice(8)+'.'+key.slice(5,7);
const dayKey = day => day.toISOString().slice(0,10);
const todayKey = () => new Intl.DateTimeFormat('sv-SE', {timeZone:'Europe/Moscow',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
const dateAt = key => new Date(key+'T12:00:00Z');
const plusDays = (day,n) => new Date(day.getTime()+n*86_400_000);
const firstDay = '2026-10-22';
const lastDay = '2027-02-11';
const weekday = key => (dateAt(key).getUTCDay()+6)%7;

let state = {revision:0,categories:{},entries:[]};
let canEdit = false;
let mode = matchMedia('(max-width:800px)').matches ? 'compact' : 'table';
let expanded = null;
let columns = Object.keys(icons);
let widths = Object.fromEntries(columns.map(key=>[key,1]));
let drag;
let pending;
let submitting = false;
const history = {undo:[],redo:[]};

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
  if (!response.ok || !data) {
    const error = Error(typeof data?.detail==='string' ? data.detail : 'Не удалось получить ответ сервера.');
    error.status = response.status;
    throw error;
  }
  return data;
}

async function reload() {
  const current = await request('state');
  if (current.revision!==state.revision) history.undo.length = history.redo.length = 0;
  state = current;
  render();
}

function entriesFor(key, cat) {
  return state.entries.filter(entry => entry.date === key && (cat ? entry.cat === cat : entry.cat !== 'sonya'))
    .sort((a,b)=>(a.time || '99').localeCompare(b.time || '99') || a.id.localeCompare(b.id));
}

function boardDates() {
  const dates = new Set(state.entries.map(entry=>entry.date));
  for (let day=dateAt(firstDay); dayKey(day)<=lastDay; day=plusDays(day,1)) dates.add(dayKey(day));
  return [...dates].sort();
}

function scrollToDate(key) {
  sheet.querySelector('[data-row="'+key+'"]')?.scrollIntoView({block:'nearest'});
}

function setWidths() {
  sheet.style.setProperty('--columns',columns.map(key=>'minmax(0,'+widths[key]+'fr)').join(' '));
}

function header() {
  return '<div class="head"><div>Дата</div><div>Соня</div>'+columns.map((key,index)=>{
    const label = safe(state.categories[key]);
    const handle = index < columns.length-1 ? button('','data-resize="'+index+'" aria-label="Ширина столбца '+label+'"','resize') : '';
    return '<div class="column-label" tabindex="0" data-column="'+index+'" title="'+label+' · перетащите заголовок">'+label+handle+'</div>';
  }).join('')+'</div>';
}

function row(key) {
  const index = weekday(key);
  const sonya = entriesFor(key,'sonya');
  const heart = (sonya.find(entry=>entry.phase && entry.sonyaRole!=='indicator') ||
    sonya.find(entry=>entry.phase))?.phase;
  const isExpanded = expanded?.key===key;
  const dayExpanded = isExpanded && (mode==='table' || expanded.view==='all');
  const cycle = heart==='period' ? ' cycle' : heart==='ovulation' ? ' peak' : '';
  const date = button('<span>'+shortDate(key)+'</span><small>'+weekdays[index]+'</small>',
    'data-key="'+key+'" data-view="all" aria-label="Планы дня, '+shortDate(key)+'" aria-expanded="'+dayExpanded+'"',
    'tile date'+(index>4?' weekend':''));
  const companion = button('<span class="heart" aria-hidden="true">'+(heart?'♥':'♡')+'</span>',
    'data-key="'+key+'" data-sonya aria-label="График Сони, '+shortDate(key)+'" aria-haspopup="dialog"',
    'tile sonya'+cycle);
  const data = isExpanded && mode==='compact' ? compactDetails(key,expanded.view) :
    columns.map(cat=>column(key,cat,isExpanded)).join('');
  return '<div class="row'+(isExpanded?' expanded':'')+'" data-row="'+key+'"><div>'+date+'</div><div>'+companion+'</div>'+
    (mode==='table'?data:'<div class="'+(isExpanded?'row-detail':'icons')+'">'+data+'</div>')+'</div>';
}

function column(key,cat,isExpanded) {
  const entries = entriesFor(key,cat);
  const first = entries[0];
  const label = safe(state.categories[cat])+', '+shortDate(key);
  const attrs = 'data-key="'+key+'" data-view="'+cat+'" aria-label="'+label+'"';
  if (isExpanded) {
    const add = canEdit ?
      button('+','data-add data-key="'+key+'" data-cat="'+cat+'" aria-label="Добавить запись · '+label+'"','row-add') : '';
    return '<div class="row-detail">'+entries.map(entry=>entryCard(entry,false)).join('')+add+'</div>';
  }
  if (mode==='compact') {
    return first ? button(icons[cat]+(entries.length>1?' <small>'+entries.length+'</small>':''),attrs,
      'emoji flag-'+(entries.find(entry=>entry.flag)?.flag||'')) : '';
  }
  const count = entries.length>1 ? button('+'+(entries.length-1),attrs,'count') : '';
  if (!canEdit) {
    return '<div>'+ (first ? '<div class="cell flag-'+first.flag+'">'+
      button(safe(first.title),attrs+' title="'+safe(first.title)+'"','read-cell')+count+'</div>' : '')+'</div>';
  }
  const flag = first?.flag || '';
  return '<div><div class="cell flag-'+flag+'"><input data-inline data-key="'+key+'" data-cat="'+cat+'" data-id="'+(first?.id||'')+
    '" data-current-flag="'+flag+'" maxlength="160" aria-label="'+label+'" placeholder="Введите текст" value="'+safe(first?.title)+'">'+
    '<label class="cell-color" title="Цвет важности"><span aria-hidden="true"></span><select data-inline-flag aria-label="Цвет важности · '+label+'">'+
    selectOptions(flags,flag)+'</select></label>'+count+'</div></div>';
}

function entryCard(entry,showCategory=true) {
  const timing = [entry.time,entry.duration && entry.duration+' мин'].filter(Boolean).join(' · ');
  const palette = Object.entries(flags).map(([color,label])=>button(color?'':'×',
    'data-flag="'+color+'" data-id="'+entry.id+'" aria-label="'+label+'" aria-pressed="'+(entry.flag===color)+'"',
    'swatch flag-'+color)).join('');
  const actions = canEdit ? '<div class="record-actions">'+button('Изменить','data-edit="'+entry.id+'"')+
    '<div class="palette" role="group" aria-label="Цвет записи">'+palette+'</div></div>' : '';
  return '<article class="record flag-'+entry.flag+'">'+(showCategory?'<small>'+safe(state.categories[entry.cat])+'</small>':'')+
    '<p>'+safe(entry.title)+(entry.done?' ✓':'')+'</p>'+(timing?'<small>'+safe(timing)+'</small>':'')+
    (entry.note?'<p>'+safe(entry.note)+'</p>':'')+
    (entry.url?'<a href="'+safe(entry.url)+'" rel="noreferrer noopener">'+safe(entry.url)+'</a>':'')+actions+'</article>';
}

function compactDetails(key,view) {
  const entries = entriesFor(key,view==='all'?null:view);
  const add = canEdit ? button('+ Запись','data-add data-key="'+key+'" data-cat="'+(view==='all'?'outside':view)+'"','row-add') : '';
  return (entries.length?entries.map(entry=>entryCard(entry)).join(''):'<p class="details-empty">Записей нет</p>')+add+
    (view==='all'?'':button('Свернуть','data-collapse','row-add'));
}

function openSonya(key) {
  const dated = entriesFor(key,'sonya').filter(entry=>!['weekly','indicator'].includes(entry.sonyaRole));
  const regular = state.entries.filter(entry=>entry.sonyaRole==='weekly' && entry.date<=key &&
    weekday(entry.date)===weekday(key));
  const overridden = dated.some(entry=>entry.sonyaRole==='override');
  const cards = entries => '<div class="cards">'+entries.map(entry=>entryCard(entry)).join('')+'</div>';
  const add = canEdit ? button('+ Запись Сони','data-add data-key="'+key+'" data-cat="sonya"') : '';
  openDialog('Соня · '+shortDate(key),
    '<div class="sonya-schedule">'+
    (dated.length ? '<h3>На эту дату</h3>'+cards(dated) : '')+
    (regular.length ? '<h3>'+(overridden?'Обычно в этот день':'Обычный график')+'</h3>'+cards(regular) : '')+
    (!dated.length && !regular.length ? '<p class="details-empty">График не указан</p>' : '')+
    add+'</div>', 'Закрыть');
  dialog.dataset.sonyaDate = key;
}

function render() {
  $('.scroll').classList.toggle('compact',mode==='compact');
  $('[data-reset]').hidden = mode==='compact';
  root.querySelectorAll('[data-mode]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.mode===mode)));
  sheet.innerHTML = (mode==='table'?header():'')+boardDates().map(row).join('');
  setWidths();
}

function openDialog(title,body,closeLabel='Отменить') {
  delete dialog.dataset.sonyaDate;
  $('#editor-title').textContent = title;
  $('#editor-status').textContent = '';
  content.innerHTML = body;
  $('[data-close-editor]').textContent = closeLabel;
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
    '<label data-sonya-role '+(e.cat==='sonya'?'':'hidden')+'>График<select name="sonyaRole">'+selectOptions(sonyaRoles,e.sonyaRole||'')+'</select></label>'+
    '<label>Выполнено<select name="done">'+selectOptions({'false':'Нет','true':'Да'},String(e.done??false))+'</select></label></div>'+
    '<div class="group"><button class="primary" type="submit">Применить</button>'+
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
      const values = {cat:state.categories,flag:flags,phase:periods,sonyaRole:sonyaRoles};
      const format = item=>safe(values[key]?.[item ?? ''] ?? item ?? '—');
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
  if (packet?.baseRevision>state.revision) await reload();
  const dates = new Set(boardDates());
  if (Array.isArray(packet?.ops) && packet.ops.some(op=>op?.date && !dates.has(op.date))) {
    throw Error('В пакете есть новая дата. Добавьте её через Codex.');
  }
  const preview = await request('preview',packet);
  if (dialog.open && $('#packet')===editor && editor.value===original) {
    const first = preview.changes[0];
    pending = {packet,target:first.after || first.before};
    showChanges(preview.changes);
  }
}

async function apply(operations, target, closeEditor=false, recordHistory=true) {
  const packet = Array.isArray(operations) ? {v:1,baseRevision:state.revision,ops:operations} : operations;
  if (packet.baseRevision!==state.revision) await reload();
  const result = await request('apply',packet);
  const entries = new Map(state.entries.map(entry=>[entry.id,entry]));
  for (const {before,after} of result.changes) {
    if (after) entries.set(after.id,after);
    else entries.delete(before.id);
  }
  state = {...state,revision:result.revision,entries:[...entries.values()]};
  if (recordHistory) {
    history.undo.push(result.changes);
    history.redo.length = 0;
  }
  if (target && target.cat!=='sonya') expanded = {key:target.date,view:'all'};
  if (closeEditor) dialog.close();
  render();
  if (target) scrollToDate(target.date);
  if (dialog.open && dialog.dataset.sonyaDate) openSonya(dialog.dataset.sonyaDate);
  status('Применено изменений: '+result.applied);
}

function historyOperation(from,to) {
  if (!to) return {op:'remove',id:from.id};
  if (!from) return {op:'add',...to};
  const changed = Object.fromEntries(Object.keys(fields).filter(key=>from[key]!==to[key])
    .map(key=>[key,to[key]===undefined ? '' : to[key]]));
  return {op:'update',id:to.id,...changed};
}

function updateHistoryButtons() {
  for (const direction of Object.keys(history)) {
    $('[data-history="'+direction+'"]').disabled = submitting || !history[direction].length;
  }
}

function replay(direction) {
  const changes = history[direction].at(-1);
  if (!canEdit || dialog.open || !changes) return;
  const undo = direction==='undo';
  run(async()=>{
    const ops = changes.map(({before,after})=>historyOperation(undo ? after : before,undo ? before : after));
    const {before,after} = changes[0];
    await apply(ops,(undo ? before : after) || before || after,false,false);
    history[direction].pop();
    history[undo?'redo':'undo'].push(changes);
    status(undo?'Правка отменена':'Правка повторена');
  });
}

async function run(task) {
  if (submitting) return;
  submitting = true;
  sheet.inert = true;
  content.inert = true;
  updateHistoryButtons();
  try {
    await task();
  } catch(error) {
    if (error.status===409) {
      try {
        await reload();
      } catch {
        // Preserve the original revision-conflict message.
      }
    }
    status(error.message);
  } finally {
    sheet.inert = false;
    content.inert = false;
    submitting = false;
    updateHistoryButtons();
  }
}

$('#today').onclick = ()=>scrollToDate(todayKey());
dialog.addEventListener('cancel',event=>{
  if (submitting) event.preventDefault();
});

document.addEventListener('keydown',event=>{
  if (!canEdit || dialog.open || event.defaultPrevented || event.altKey ||
      !(event.ctrlKey || event.metaKey) ||
      event.target.closest?.('input,textarea,select,[contenteditable]')) return;
  const key = event.code==='KeyZ' ? 'z' : event.code==='KeyY' ? 'y' : event.key.toLowerCase();
  const direction = key==='y' || (key==='z' && event.shiftKey) ? 'redo' : key==='z' ? 'undo' : null;
  if (!direction || !history[direction].length) return;
  event.preventDefault();
  if (!event.repeat) replay(direction);
});

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
  } else if ('sonya' in d) {
    openSonya(d.key);
  } else if (d.view) {
    const sameView = mode==='table' || expanded?.view===d.view;
    expanded = expanded?.key===d.key && sameView ? null : {key:d.key,view:d.view};
    render();
  } else if ('closeEditor' in d) {
    if (!submitting) dialog.close();
  } else if (d.history) {
    replay(d.history);
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
    $('[data-sonya-role]').hidden = field.value!=='sonya';
  } else if (canEdit && field.hasAttribute('data-inline-flag')) saveCell(field.closest('.cell'));
});

function saveCell(cell) {
  const field = cell.querySelector('[data-inline]');
  const picker = cell.querySelector('[data-inline-flag]');
  const {id,key,cat,currentFlag} = field.dataset;
  const title = field.value.trim();
  const flag = picker.value;
  if (!title) {
    field.value = field.defaultValue;
    picker.value = currentFlag;
    return;
  }
  if (title===field.defaultValue && flag===currentFlag) return;
  run(async()=>{
    try {
      await apply([id?{op:'update',id,title,flag}:{op:'add',date:key,cat,title,flag}]);
    } catch(error) {
      field.value = field.defaultValue;
      picker.value = currentFlag;
      throw error;
    }
  });
}

sheet.addEventListener('focusout',event=>{
  const cell = event.target.matches('[data-inline],[data-inline-flag]') && event.target.closest('.cell');
  if (canEdit && cell && !cell.contains(event.relatedTarget)) saveCell(cell);
});

root.addEventListener('submit',event=>{
  const form = event.target;
  if (!canEdit || form.id!=='entry-form') return;
  event.preventDefault();
  const values = Object.fromEntries(new FormData(form));
  if (!boardDates().includes(values.date)) {
    status('Этой даты ещё нет на доске. Новые даты добавляются через Codex.');
    return;
  }
  const data = {...values,time:values.time||null,duration:values.duration?Number(values.duration):null,
    done:values.done==='true',phase:values.cat==='sonya'?values.phase:'',
    sonyaRole:values.cat==='sonya'?values.sonyaRole:''};
  const op = form.dataset.id ? {op:'update',id:form.dataset.id,...data} : {op:'add',...data};
  run(()=>apply([op],data,true));
});

function resize(index, fraction) {
  const first = columns[index];
  const second = columns[index+1];
  const total = widths[first]+widths[second];
  const min = Math.min(58*columns.length/columnAreaWidth(),total/2);
  widths[first] = Math.max(min,Math.min(total-min,fraction));
  widths[second] = total-widths[first];
  setWidths();
}

function columnAreaWidth() {
  const [date,sonya] = $('.head').children;
  return sheet.clientWidth-date.offsetWidth-sonya.offsetWidth;
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
  if ('inline' in d && event.key==='Escape') {
    event.target.value = event.target.defaultValue;
    event.target.closest('.cell').querySelector('[data-inline-flag]').value = d.currentFlag;
    event.target.blur();
  }
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
    resize(drag.resize,drag.start+(event.clientX-drag.x)*columns.length/columnAreaWidth());
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
  $('#history-actions').hidden = !canEdit;
  offerLegacyExport();
  render();
  scrollToDate(todayKey());
});
