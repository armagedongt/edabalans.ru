const root = document.querySelector('#week-board-final');
const $ = selector => root.querySelector(selector);
const sheet = $('.sheet');
const dialog = $('.editor');
const content = $('.editor-content');
const icons = {outside:'📍',with_sonya:'💗',training:'🏋️',competitions:'🏁',work:'💼',posts:'✍️',finance:'💳',history:'📓'};
const taskTitleLimit = 30;
const taskCharacters = new Intl.Segmenter('ru',{granularity:'grapheme'});
const flags = {'':'Без цвета',blue:'Синий',green:'Зелёный',red:'Красный'};
const weekdays = ['Пн','Вт','Ср','Чт','Пт','Сб','Вс'];
const fields = {date:'Дата',cat:'Категория',title:'Действие',time:'Время',duration:'Минуты',note:'Комментарий',url:'Ссылка',flag:'Цвет',phase:'Цикл',sonyaRole:'Тип записи Сони',done:'Выполнено',sonyaComment:'Комментарий для Сони',shareWithSonya:'Показать встречу Соне',sonyaTimeConfirmed:'Время подтверждено',endDate:'Дата окончания'};
const periods = {'':'Нет метки',period:'Месячные',ovulation:'Овуляция'};
const sonyaRoles = {'':'Событие',weekly:'Обычный график',override:'Замена графика на день',indicator:'Индикатор',comment:'Комментарий Сони'};
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
let mode = 'titles';
let expanded = null;
const openTasks = new Set();
const openTaskGroups = new Set();
let showPast = false;
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
  if (response.status === 401) {
    location.replace('/admin?next=/timeboard/');
    throw Error('Сессия закончилась. Войдите снова.');
  }
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
    .sort((a,b)=>(cat?0:columns.indexOf(a.cat)-columns.indexOf(b.cat)) ||
      (a.time || '99').localeCompare(b.time || '99') || a.id.localeCompare(b.id));
}

function currentSonyaComments(key) {
  const current = new Map();
  for (const entry of state.entries) {
    if(entry.cat!=='sonya' || entry.sonyaRole!=='comment' || (key && entry.date!==key)) continue;
    const before=current.get(entry.date);
    if(!before || (Date.parse(entry.updatedAt || entry.createdAt) || 0)>=(Date.parse(before.updatedAt || before.createdAt) || 0)) current.set(entry.date,entry);
  }
  return [...current.values()];
}

function boardDates() {
  const dates = new Set(state.entries.map(entry=>entry.date));
  for (let day=dateAt(firstDay); dayKey(day)<=lastDay; day=plusDays(day,1)) dates.add(dayKey(day));
  return [...dates].sort();
}

function scrollToDate(key) {
  if (key<todayKey() && !showPast) {
    showPast = true;
    render();
  }
  sheet.querySelector('[data-row="'+key+'"]')?.scrollIntoView({block:'nearest'});
}

function setWidths() {
  root.style.setProperty('--columns',columns.map(key=>'minmax(0,'+widths[key]+'fr)').join(' '));
}

function header() {
  return '<div class="head"><div>Дата</div><div>Соня</div>'+columns.map((key,index)=>{
    const label = safe(state.categories[key]);
    const handle = index < columns.length-1 ? button('','data-resize="'+index+'" aria-label="Ширина столбца '+label+'"','resize') : '';
    return '<div class="column-label" tabindex="0" data-column="'+index+'" title="'+label+' · перетащите заголовок">'+label+handle+'</div>';
  }).join('')+'</div>';
}

function heartIcon() {
  return '<svg class="heart" aria-hidden="true" viewBox="0 0 24 24"><path class="heart-shape" d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.8-8.6a5.5 5.5 0 0 0 0-7.8Z"/><path class="heart-crack" d="m13 3-3 6 4 4-4 8"/></svg>';
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
  const unread = currentSonyaComments(key).some(entry=>!entry.done);
  const companion = button(heartIcon()+(unread?'<span class="sonya-unread" aria-hidden="true"></span>':''),
    'data-key="'+key+'" data-sonya aria-label="График Сони, '+shortDate(key)+(unread?', новый комментарий':'')+'" aria-haspopup="dialog"',
    'tile sonya'+cycle);
  const data = mode==='titles' ? titleTasks(key,isExpanded) : isExpanded && mode==='compact' ? compactDetails(key,expanded.view) :
    columns.map(cat=>column(key,cat,isExpanded)).join('');
  return '<div class="row'+(isExpanded?' expanded':'')+'" data-row="'+key+'"><div>'+date+'</div><div>'+companion+'</div>'+
    (mode==='table'?data:'<div class="'+(mode==='titles'?'task-list':isExpanded?'row-detail':'icons')+'">'+data+'</div>')+'</div>';
}

function column(key,cat,isExpanded) {
  const entries = entriesFor(key,cat).filter(entry=>isExpanded || !entry.done);
  const first = entries[0];
  const label = safe(state.categories[cat])+', '+shortDate(key);
  const attrs = 'data-key="'+key+'" data-view="'+cat+'" aria-label="'+label+'"';
  if (isExpanded) {
    const add = canEdit ?
      button('Добавить','data-add data-key="'+key+'" data-cat="'+cat+'" aria-label="Добавить запись · '+label+'"','row-add') : '';
    return '<div class="row-detail">'+entries.map(entry=>entryCard(entry,false)).join('')+add+'</div>';
  }
  if (mode==='compact') {
    return first ? button(icons[cat]+(entries.length>1?' <small>'+entries.length+'</small>':''),attrs,
      'emoji category-'+cat) : '';
  }
  const count = entries.length>1 ? button('+'+(entries.length-1),attrs,'count') : '';
  if (!canEdit) {
    return '<div>'+ (first ? '<div class="cell category-'+cat+'">'+
      button(safe(first.title),attrs+' title="'+safe(first.title)+'"','read-cell')+count+'</div>' : '')+'</div>';
  }
  const flag = first?.flag || '';
  const remove = first ? removeButton(first,'cell-remove') : '';
  return '<div><div class="cell category-'+cat+'"><input data-inline data-key="'+key+'" data-cat="'+cat+'" data-id="'+(first?.id||'')+
    '" data-current-flag="'+flag+'" maxlength="160" aria-label="'+label+'" placeholder="Введите текст" value="'+safe(first?.title)+'">'+
remove+count+'</div></div>';
}

function removeButton(entry,cls='') {
  return button('×','data-remove="'+entry.id+'" title="Удалить запись" aria-label="Удалить запись · '+safe(entry.title)+'"','remove-record '+cls);
}

function doneButton(entry) {
  if (entry.cat==='sonya') return '';
  const label = entry.done ? 'Вернуть в планы' : 'Отметить выполненным';
  return button('<span class="done-check" aria-hidden="true">✓</span><span>Выполнено</span>','data-complete="'+entry.id+'" aria-pressed="'+!!entry.done+'" title="'+label+'" aria-label="'+label+' · '+safe(entry.title)+'"','done-toggle');
}

function editButton(entry) {
  return button('✎','data-edit="'+entry.id+'" title="Изменить" aria-label="Изменить · '+safe(entry.title)+'"','edit-record');
}

function entryCard(entry,showCategory=true,showTitle=true,showActions=true) {
  const timing = [entry.duration && entry.duration+' мин'].filter(Boolean).join(' · ');
  const actions = canEdit && showActions ? editButton(entry)+removeButton(entry) : '';
  const completion = canEdit && showActions && mode!=='table' && entry.cat!=='sonya' ? '<div class="completion-actions">'+doneButton(entry)+'</div>' : '';
  const heading = (showCategory?'<small>'+safe(state.categories[entry.cat])+'</small>':'')+
    (showTitle?'<span>'+safe(taskHeading(entry).full)+(entry.done?' ✓':'')+'</span>':'')+actions;
  return '<article class="record category-'+entry.cat+(entry.done && entry.cat!=='sonya'?' is-completed':'')+'">'+(heading?'<div class="record-heading">'+heading+'</div>':'')+
    (timing || entry.note ? '<p>'+[timing,safe(entry.note)].filter(Boolean).join(' · ')+'</p>':'')+
    (entry.url?'<a class="record-link" href="'+safe(entry.url)+'" rel="noreferrer noopener">'+(entry.cat==='finance'?'Открыть кабинет':'Открыть ссылку')+'</a>':'')+completion+'</article>';
}

function isWeekReminder(entry) {
  return /^(?:Через 7 дней)(?: · |: )/.test(entry.title);
}

function taskHeading(entry) {
  const reminder = isWeekReminder(entry) ? 'за 7 дн.' :
    entry.title.startsWith('Завтра · ') ? 'завтра' : '';
  const title = entry.title.replace(/^(?:Через 7 дней(?: · |: )|Завтра · )/,'')
    .replace(/^(?:Встреча|Звонок|Созвон|Консультация) с /i,'');
  const parts = title.split(' · ');
  const timeIndex = entry.cat==='finance' ? Math.min(2,parts.length) : 1;
  let full = entry.time && !title.includes(entry.time) ?
    [...parts.slice(0,timeIndex),entry.time,...parts.slice(timeIndex)].join(' · ') : title;
  if (entry.cat==='finance') full = full.replace(/(\d) (?=\d{3}(?:[^\d]|$))/g,'$1\u202f')
    .replace(/(\d)\s+(₽|\$|RUB|USD|GEL)(?=$|[\s·])/g,'$1\u00a0$2');
  const characters = [...taskCharacters.segment(full)].map(item=>item.segment);
  const truncated = characters.length>taskTitleLimit;
  const text = truncated ? characters.slice(0,taskTitleLimit-1).join('')+'…' : full;
  return {full,text,truncated,reminder};
}

function titleTask(entry,dayOpen,showReminder=true) {
  const open = dayOpen || openTasks.has(entry.id);
  const heading = taskHeading(entry);
  const marker = showReminder ? heading.reminder : '';
  return '<div class="task category-'+entry.cat+(entry.done?' is-completed':'')+'"><div class="task-head">'+button(
    '<span aria-hidden="true">'+icons[entry.cat]+'</span><span class="task-text">'+safe(open?heading.full:heading.text)+'</span>'+
    (marker?'<small class="task-reminder">'+safe(marker)+'</small>':'')+
    (entry.done?'<span aria-label="Выполнено">✓</span>':''),
    'data-task="'+entry.id+'" title="'+safe(heading.full)+'" aria-label="'+safe(heading.full+(marker?' · '+marker:''))+'" aria-expanded="'+open+'" aria-controls="task-'+entry.id+'"','task-title')+(open && canEdit?editButton(entry)+removeButton(entry):'')+'</div>'+
    '<div id="task-'+entry.id+'"'+(open?'':' hidden')+'>'+ (open?entryCard(entry,false,false,false)+(canEdit?'<div class="completion-actions">'+doneButton(entry)+'</div>':''):'')+'</div></div>';
}

function taskGroup(key,kind,entries,dayOpen) {
  const groupKey = kind+'-'+key;
  const open = dayOpen || openTaskGroups.has(groupKey);
  const label = kind==='payments' ? 'Оплаты' : 'Напоминания за 7 дней';
  const icon = kind==='payments' ? '💳' : '🔔';
  const sameCategory = entries.every(entry=>entry.cat===entries[0].cat);
  const tint = sameCategory ? ' category-'+entries[0].cat : '';
  return '<div class="task task-group'+tint+'"><div class="task-head">'+button(
    '<span aria-hidden="true">'+icon+'</span><span class="task-text">'+label+'</span><small>· '+entries.length+'</small>',
    'data-entry-group="'+groupKey+'" aria-expanded="'+open+'" aria-controls="entry-group-'+groupKey+'"','task-title')+'</div>'+
    '<ol id="entry-group-'+groupKey+'" class="group-items"'+(open?'':' hidden')+'>'+
    (open?entries.map(entry=>'<li>'+titleTask(entry,dayOpen,false)+'</li>').join(''):'')+'</ol></div>';
}

function titleTasks(key,dayOpen) {
  const all = entriesFor(key);
  const entries = all.filter(entry=>!entry.done);
  const payments = entries.filter(entry=>entry.cat==='finance' && !isWeekReminder(entry) &&
    !entry.title.startsWith('Завтра · '));
  const upcoming = entries.filter(isWeekReminder);
  const emitted = new Set();
  return entries.map(entry=>{
    const kind = isWeekReminder(entry) ? 'week' : payments.includes(entry) ? 'payments' : null;
    const grouped = kind==='week' ? upcoming : payments;
    if (kind && grouped.length>=3) {
      if (emitted.has(kind)) return '';
      emitted.add(kind);
      return taskGroup(key,kind,grouped,dayOpen);
    }
    return titleTask(entry,dayOpen);
  }).join('')+(dayOpen?all.filter(entry=>entry.done).map(entry=>titleTask(entry,true)).join(''):'')+(canEdit?button('Добавить','data-add data-key="'+key+'" aria-label="Добавить запись, '+shortDate(key)+'"','row-add'):'');
}

function compactDetails(key,view) {
  const entries = entriesFor(key,view==='all'?null:view);
  const add = canEdit ? button('Добавить','data-add data-key="'+key+'" data-cat="'+(view==='all'?'outside':view)+'"','row-add') : '';
  return (entries.length?entries.map(entry=>entryCard(entry)).join(''):'<p class="details-empty">Записей нет</p>')+'<div class="row-actions">'+add+
    (view==='all'?'':button('Свернуть','data-collapse','row-add'))+'</div>';
}

function openSonya(key) {
  const dated = entriesFor(key,'sonya').filter(entry=>!['weekly','indicator','comment'].includes(entry.sonyaRole));
  const regular = state.entries.filter(entry=>entry.cat==='sonya' && entry.sonyaRole==='weekly' && entry.date<=key && weekday(entry.date)===weekday(key));
  const schedule = (dated.some(entry=>entry.sonyaRole==='override') ? [] : regular).concat(dated);
  const comments = currentSonyaComments(key);
  const line = entry=>[entry.title,entry.time && !entry.note?.includes(entry.time)?entry.time:null,entry.note].filter(Boolean).map(safe).join(' · ');
  const work = schedule.map(entry=>'<p>'+line(entry)+'</p>').join('') || '<p class="details-empty">График не указан</p>';
  const notes = comments.map(entry=>'<p>'+safe(entry.note || 'Примечание очищено').replace(/\n/g,'<br>')+'</p>'+(!entry.done && canEdit?button('Прочитано','data-comment-read="'+entry.id+'"'):'' )).join('') || '<p class="details-empty">Комментариев пока нет</p>';
  const add = canEdit ? button('Добавить запись Сони','data-add data-key="'+key+'" data-cat="sonya"') : '';
  openDialog('Соня · '+shortDate(key),'<div class="sonya-schedule"><section class="sonya-block"><h3>Работа и расписание</h3>'+work+'</section><section class="sonya-block sonya-notes"><h3>Комментарий Сони</h3>'+notes+'</section>'+add+'</div>','Закрыть');
  dialog.dataset.sonyaDate = key;
}

function render() {
  $('.scroll').classList.toggle('compact',mode!=='table');
  $('.scroll').classList.toggle('titles',mode==='titles');
  $('[data-reset]').hidden = mode!=='table';
  root.querySelectorAll('[data-mode]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.mode===mode)));
  const pastButton = $('[data-past]');
  pastButton.textContent = showPast ? 'Скрыть прошедшее' : 'Прошедшее';
  pastButton.setAttribute('aria-expanded',String(showPast));
  $('.column-heads').innerHTML = mode==='table'?header():'';
  sheet.innerHTML = boardDates().filter(key=>showPast || key>=todayKey()).map(row).join('');
  setWidths();
  const unread=currentSonyaComments().filter(e=>!e.done);
  const notice=$('[data-sonya-comments]');notice.hidden=!unread.length;notice.textContent='Комментарии Сони · '+unread.length;
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
    '<label class="wide">Комментарий для Сони<textarea name="sonyaComment">'+safe(e.sonyaComment)+'</textarea></label>'+
    '<label>Дата окончания встречи<input type="date" name="endDate" value="'+safe(e.endDate)+'"></label>'+
    '<label>Показывать Соне<select name="shareWithSonya">'+selectOptions({'false':'Только если категория «С Соней»','true':'Да'},String(e.shareWithSonya??false))+'</select></label>'+
    '<label>Время для Сони подтверждено<select name="sonyaTimeConfirmed">'+selectOptions({'false':'Нет','true':'Да'},String(e.sonyaTimeConfirmed??false))+'</select></label>'+
    '<input type="hidden" name="flag" value="'+safe(e.flag||'')+'">'+
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
    .map(key=>[key,to[key]===undefined ? (key==='endDate'?null:({shareWithSonya:false,sonyaTimeConfirmed:false}[key] ?? '')) : to[key]]));
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

$('#today').onclick = ()=>{
  showPast = false;
  render();
  scrollToDate(todayKey());
};
new ResizeObserver(entries=>{
  root.style.setProperty('--board-top-height',entries[0].borderBoxSize[0].blockSize+'px');
}).observe($('.board-top'));
dialog.addEventListener('cancel',event=>{
  if (submitting) event.preventDefault();
});
dialog.addEventListener('click',event=>{
  if (event.target!==dialog || submitting) return;
  const bounds=dialog.getBoundingClientRect();
  if (event.clientX<bounds.left || event.clientX>bounds.right ||
      event.clientY<bounds.top || event.clientY>bounds.bottom) dialog.close();
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
  } else if (d.entryGroup) {
    const wasOpen = b.getAttribute('aria-expanded')==='true';
    expanded = null;
    if (wasOpen) openTaskGroups.delete(d.entryGroup);
    else openTaskGroups.add(d.entryGroup);
    render();
    sheet.querySelector('[data-entry-group="'+d.entryGroup+'"]')?.focus({preventScroll:true});
  } else if (d.task) {
    const parentGroup = b.closest('.task-group')?.querySelector('[data-entry-group]');
    if (parentGroup) openTaskGroups.add(parentGroup.dataset.entryGroup);
    const wasOpen = b.getAttribute('aria-expanded')==='true';
    expanded = null;
    if (wasOpen) openTasks.delete(d.task);
    else openTasks.add(d.task);
    render();
    sheet.querySelector('[data-task="'+d.task+'"]')?.focus({preventScroll:true});
  } else if (canEdit && d.complete) {
    const entry = state.entries.find(item=>item.id===d.complete && item.cat!=='sonya');
    if (entry) run(()=>apply([{op:'update',id:entry.id,done:!entry.done}],null));
  } else if ('sonyaComments' in d) {
    const comments=currentSonyaComments().filter(e=>!e.done).sort((a,b)=>b.date.localeCompare(a.date));
    openDialog('Комментарии Сони',comments.map(e=>'<h3>'+safe(shortDate(e.date))+'.'+e.date.slice(0,4)+'</h3>'+entryCard(e)+button('Прочитано','data-comment-read="'+e.id+'"')).join(''),'Закрыть');
  } else if (canEdit && d.commentRead) {
    run(()=>apply([{op:'update',id:d.commentRead,done:true}],null,true));
  } else if ('past' in d) {
    showPast = !showPast;
    render();
    if (showPast) sheet.querySelector('.row')?.scrollIntoView({block:'start'});
    else scrollToDate(todayKey());
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

  } else if (canEdit && d.remove) {
    if (confirm('Удалить запись?')) run(()=>apply([{op:'remove',id:d.remove}],null,!!$('#entry-form')));
    else b.closest('.cell')?.querySelector('[data-inline]')?.focus();
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
  const flag = picker?.value ?? currentFlag;
  if (!title) {
    field.value = field.defaultValue;
    if (picker) picker.value = currentFlag;
    return;
  }
  if (title===field.defaultValue && flag===currentFlag) return;
  run(async()=>{
    try {
      await apply([id?{op:'update',id,title,flag}:{op:'add',date:key,cat,title,flag}]);
    } catch(error) {
      field.value = field.defaultValue;
      if (picker) picker.value = currentFlag;
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
    done:values.done==='true',shareWithSonya:values.shareWithSonya==='true',sonyaTimeConfirmed:values.sonyaTimeConfirmed==='true',endDate:values.endDate||null,phase:values.cat==='sonya'?values.phase:'',
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

root.addEventListener('keydown',event=>{
  const d = event.target.dataset;
  if ('inline' in d && event.key==='Enter') event.target.blur();
  if ('inline' in d && event.key==='Escape') {
    event.target.value = event.target.defaultValue;
    const picker = event.target.closest('.cell').querySelector('[data-inline-flag]');
    if (picker) picker.value = d.currentFlag;
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

root.addEventListener('pointerdown',event=>{
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

root.addEventListener('pointermove',event=>{
  if (!drag) return;
  if ('resize' in drag) {
    resize(drag.resize,drag.start+(event.clientX-drag.x)*columns.length/columnAreaWidth());
    return;
  }
  const target = document.elementFromPoint(event.clientX,event.clientY)?.closest('[data-column]');
  root.querySelector('.is-target')?.classList.remove('is-target');
  drag.target = target && Math.abs(event.clientX-drag.x)>4 ? Number(target.dataset.column) : null;
  if (drag.target!==null && drag.target!==drag.column) target.classList.add('is-target');
});

root.addEventListener('pointerup',()=>{
  if (drag && 'column' in drag && drag.target!==null) moveColumn(drag.column,drag.target);
  drag = null;
});
root.addEventListener('lostpointercapture',()=>{
  drag = null;
  root.querySelector('.is-target')?.classList.remove('is-target');
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

setInterval(()=>{
  if(canEdit && !dialog.open && !submitting && document.visibilityState==='visible' &&
     !document.activeElement?.matches('input,textarea,select') && !drag) run(reload);
},60000);
