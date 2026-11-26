function heartIcon() {
  return '<svg class="heart" aria-hidden="true" viewBox="0 0 24 24"><path class="heart-shape" d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.8-8.6a5.5 5.5 0 0 0 0-7.8Z"/><path class="heart-crack" d="m13 3-3 6 4 4-4 8"/></svg>';
}

const days = document.querySelector('#days'), dialog = document.querySelector('#editor'), status = document.querySelector('#status');
const noteDialog = document.querySelector('#note-editor'), noteForm = document.querySelector('#note-form'), noteText = document.querySelector('#note-text');
let data = [], past = false, editingDate = null;
const drafts = new Map();
const mobile = () => matchMedia('(pointer:coarse)').matches;
const today = () => new Intl.DateTimeFormat('sv-SE',{timeZone:'Europe/Moscow',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
const label = key => new Intl.DateTimeFormat('ru',{day:'2-digit',month:'2-digit',weekday:'short',timeZone:'Europe/Moscow'}).format(new Date(key+'T12:00:00Z'));
function el(tag,text,cls) {
  const node = document.createElement(tag);
  if (text) node.textContent = text;
  if (cls) node.className = cls;
  return node;
}
function draftFor(key) {
  if (!drafts.has(key)) {
    const current = data.find(day=>day.date===key)?.comments[0];
    const text = current?.note || '';
    drafts.set(key,{text,saved:text,version:current?.version || current?.createdAt || null,id:null,pending:false});
  }
  return drafts.get(key);
}
function changeDraft(draft,text) {
  if (draft.text!==text) draft.id = null;
  draft.text = text; status.textContent = '';
}
function commentField(day) {
  const draft = draftFor(day.date);
  if (mobile()) {
    const cell = el('button',draft.saved,'note-cell'); cell.type = 'button';
    cell.setAttribute('aria-label','Примечание Сони · '+label(day.date));
    cell.onclick = () => openNote(day.date);
    return cell;
  }
  const form = el('form',null,'inline-note'), input = el('textarea'), save = el('button','Сохранить');
  input.rows = 1; input.maxLength = 2000; input.value = draft.text;
  input.setAttribute('aria-label','Примечание Сони · '+label(day.date));
  input.disabled = save.disabled = draft.pending;
  save.type = 'submit'; save.hidden = draft.text===draft.saved;
  function fit() {input.style.height='36px'; input.style.height=Math.min(160,Math.max(36,input.scrollHeight+2))+'px';}
  input.onfocus = fit;
  input.onblur = () => {input.style.height='36px';};
  input.oninput = () => {changeDraft(draft,input.value); save.hidden=draft.text===draft.saved; fit();};
  form.onsubmit = event => {event.preventDefault(); saveNote(day.date,form);};
  form.append(input,save); return form;
}
function createDay(day) {
  const row = el('div',null,'day'); row.dataset.date = day.date;
  const weekend = [0,6].includes(new Date(day.date+'T12:00Z').getUTCDay());
  const date = el('button',label(day.date),'date'+(weekend?' weekend':''));
  const heart = el('button',null,'heart-button '+day.phase); heart.innerHTML=heartIcon();
  heart.setAttribute('aria-label','Расписание '+label(day.date));
  date.onclick = heart.onclick = () => openDay(day);
  const content = el('div',null,'day-content'), events = el('div',null,'events');
  for (const meeting of day.meetings) {
    const button = el('button','Наша встреча'+(meeting.time?' · '+meeting.time:''),'meeting');
    button.onclick = () => openDay(day,true); events.append(button);
  }
  if (events.childElementCount) content.append(events);
  content.append(commentField(day)); row.append(date,heart,content); return row;
}
function render() {
  days.replaceChildren(...data.filter(day=>past || day.date>=today()).map(createDay));
}
function refreshRow(key) {
  const day = data.find(item=>item.date===key);
  if (day) days.querySelector('[data-date="'+key+'"]')?.replaceWith(createDay(day));
}
function openDay(day,meetingOnly=false) {
  document.querySelector('#date-title').textContent=label(day.date);
  const schedule=document.querySelector('#schedule'); schedule.hidden=meetingOnly;
  schedule.replaceChildren(el('h3','Работа и расписание'));
  if (!day.schedule.length) schedule.append(el('p','График не указан'));
  for (const record of day.schedule) schedule.append(el('p',[record.title,record.time && !record.note?.includes(record.time)?record.time:null,record.note].filter(Boolean).join(' · ')));
  const meetings=document.querySelector('#meetings'); meetings.hidden=!meetingOnly; meetings.replaceChildren();
  for (const meeting of day.meetings) {
    meetings.append(el('h3','Наша встреча'+(meeting.time?' · '+meeting.time:'')));
    if (meeting.comment) meetings.append(el('p',meeting.comment));
  }
  dialog.showModal();
}
function openNote(key) {
  editingDate=key;
  document.querySelector('#note-title').textContent=label(key);
  document.querySelector('#note-error').textContent='';
  noteText.value=draftFor(key).text;
  noteDialog.showModal(); noteText.focus();
}
function cancelNote() {
  if (editingDate && draftFor(editingDate).pending) return;
  if (editingDate) {const draft=draftFor(editingDate); draft.text=draft.saved; draft.id=null;}
  const key=editingDate; noteDialog.close(); editingDate=null; if(key) refreshRow(key);
}
async function saveNote(key,form) {
  const draft=draftFor(key), note=draft.text.trim();
  if (draft.pending) return;
  if (note===draft.saved) {draft.text=draft.saved; if(noteDialog.open) {noteDialog.close(); editingDate=null;} refreshRow(key); return;}
  draft.pending=true; draft.id=draft.id || crypto.randomUUID().replaceAll('-','');
  const errorOutput=noteDialog.open?document.querySelector('#note-error'):status;
  errorOutput.textContent='';
  for (const control of form.querySelectorAll('textarea,button')) control.disabled=true;
  try {
    const response=await fetch('api/comments',{method:'POST',headers:{'Content-Type':'application/json','X-Sonya-Request':'1'},body:JSON.stringify({id:draft.id,date:key,note,expectedVersion:draft.version})});
    const result=await response.json().catch(()=>null);
    if (!response.ok || !result) throw Error(typeof result?.detail==='string'?result.detail:'Не удалось сохранить примечание');
    draft.saved=draft.text=result.note; draft.version=result.version; draft.id=null;
    data.find(day=>day.date===key).comments=[{note:result.note,version:result.version}];
    status.textContent='Сохранено';
    if (noteDialog.open && editingDate===key) {noteDialog.close(); editingDate=null;}
  } catch(error) {errorOutput.textContent=error.message;}
  finally {
    draft.pending=false;
    for (const control of form.querySelectorAll('textarea,button')) control.disabled=false;
    refreshRow(key);
  }
}
noteForm.onsubmit=event=>{event.preventDefault(); const draft=draftFor(editingDate); changeDraft(draft,noteText.value); saveNote(editingDate,noteForm);};
document.querySelector('#note-cancel').onclick=cancelNote;
noteDialog.addEventListener('cancel',event=>{if(editingDate && draftFor(editingDate).pending) event.preventDefault();else cancelNote();});
document.querySelector('#past').onclick=()=>{past=!past; document.querySelector('#past').textContent=past?'Скрыть прошедшее':'Прошедшее'; render();};
document.querySelector('#close').onclick=()=>dialog.close();
for (const modal of [dialog,noteDialog]) modal.addEventListener('click',event=>{
  if (event.target!==modal) return;
  const bounds=modal.getBoundingClientRect();
  if (event.clientX<bounds.left || event.clientX>bounds.right ||
      event.clientY<bounds.top || event.clientY>bounds.bottom) {
    if (modal===noteDialog) cancelNote(); else modal.close();
  }
});
fetch('api/state').then(async response=>{if(!response.ok)throw Error('Не удалось загрузить календарь'); data=(await response.json()).days; render();}).catch(error=>{status.textContent=error.message;});
