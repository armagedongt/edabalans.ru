function heartIcon() {
  return '<svg class="heart" aria-hidden="true" viewBox="0 0 24 24"><path class="heart-shape" d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.8-8.6a5.5 5.5 0 0 0 0-7.8Z"/><path class="heart-crack" d="m13 3-3 6 4 4-4 8"/></svg>';
}

const days = document.querySelector('#days'), dialog = document.querySelector('#editor'), status = document.querySelector('#status');
let data = [], past = false, loadSequence = 0;
const drafts = new Map();
const today = () => new Intl.DateTimeFormat('sv-SE',{timeZone:'Europe/Moscow',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
const label = key => new Intl.DateTimeFormat('ru',{day:'2-digit',month:'2-digit',weekday:'short',timeZone:'Europe/Moscow'}).format(new Date(key+'T12:00:00Z'));
function el(tag,text,cls) {
  const node = document.createElement(tag);
  if (text) node.textContent = text;
  if (cls) node.className = cls;
  return node;
}
function draftFor(key) {
  if (!drafts.has(key)) drafts.set(key,{text:'',id:null,pending:false,message:'',error:false});
  return drafts.get(key);
}
function commentForm(day) {
  const draft = draftFor(day.date), form = el('form',null,'inline-note');
  const input = el('input'), save = el('button','Сохранить'), feedback = el('small',draft.message,'note-feedback'+(draft.error?' error':''));
  input.type = 'text'; input.maxLength = 2000; input.value = draft.text;
  input.placeholder = 'Примечание на этот день';
  input.setAttribute('aria-label','Примечание Сони · '+label(day.date));
  input.disabled = save.disabled = draft.pending;
  save.type = 'submit'; save.hidden = !draft.text.trim();
  save.setAttribute('aria-label','Сохранить примечание · '+label(day.date));
  feedback.setAttribute('role',draft.error?'alert':'status');
  input.oninput = () => {
    if (draft.text!==input.value) draft.id = null;
    draft.text = input.value; draft.message = ''; feedback.textContent = '';
    save.hidden = !input.value.trim();
  };
  form.onsubmit = event => {event.preventDefault(); saveComment(day.date,form);};
  form.append(input,save,feedback);
  return form;
}
function createDay(day) {
    const row = el('div',null,'day'); row.dataset.date = day.date;
    const weekend = [0,6].includes(new Date(day.date+'T12:00Z').getUTCDay());
    const date = el('button',label(day.date),'date'+(weekend?' weekend':''));
    const heart = el('button',null,'heart-button '+day.phase); heart.innerHTML = heartIcon();
    heart.setAttribute('aria-label','Расписание '+label(day.date));
    date.onclick = heart.onclick = () => openDay(day);
    const content = el('div',null,'day-content'), events = el('div',null,'events');
    for (const meeting of day.meetings) {
      const button = el('button','Наша встреча'+(meeting.time?' · '+meeting.time:''),'meeting');
      button.onclick = () => openDay(day); events.append(button);
    }
    if (events.childElementCount) content.append(events);
    for (const comment of day.comments) content.append(el('p',comment.note,'saved-note'));
    content.append(commentForm(day)); row.append(date,heart,content); return row;
}
function render() {
  days.replaceChildren(...data.filter(day=>past || day.date>=today()).map(createDay));
}

function openDay(day) {
  document.querySelector('#date-title').textContent = label(day.date);
  const schedule = document.querySelector('#schedule'); schedule.replaceChildren(el('h3','Работа и расписание'));
  if (!day.schedule.length) schedule.append(el('p','График не указан'));
  for (const record of day.schedule) schedule.append(el('p',[record.title,record.time && !record.note?.includes(record.time)?record.time:null,record.note].filter(Boolean).join(' · ')));
  const meetings = document.querySelector('#meetings'); meetings.replaceChildren();
  for (const meeting of day.meetings) {
    meetings.append(el('h3','Наша встреча'+(meeting.time?' · '+meeting.time:'')));
    if (meeting.comment) meetings.append(el('p',meeting.comment));
  }
  if (!dialog.open) dialog.showModal();
}
async function load() {
  const sequence = ++loadSequence;
  const response = await fetch('api/state');
  if (!response.ok) throw Error('Не удалось загрузить календарь');
  const snapshot = await response.json();
  // A late refresh from another saved row must not replace a newer snapshot.
  if (sequence===loadSequence) data = snapshot.days;
}
async function saveComment(key,form) {
  const draft = draftFor(key), note = draft.text.trim();
  if (draft.pending || !note) return;
  draft.pending = true; draft.error = false; draft.message = '';
  draft.id = draft.id || crypto.randomUUID().replaceAll('-','');
  for (const control of form.querySelectorAll('input,button')) control.disabled = true;
  try {
    const response = await fetch('api/comments',{method:'POST',headers:{'Content-Type':'application/json','X-Sonya-Request':'1'},body:JSON.stringify({id:draft.id,date:key,note})});
    if (!response.ok) {
      const error = await response.json().catch(()=>null);
      throw Error(typeof error?.detail==='string'?error.detail:'Не удалось сохранить примечание');
    }
    draft.text = ''; draft.id = null; draft.message = 'Сохранено';
    const day = data.find(day=>day.date===key);
    // Another row's refresh may already include this accepted comment.
    if (day && !day.comments.some(comment=>comment.note===note)) day.comments.push({note});
    try {await load();} catch {draft.message = 'Сохранено. Обновите страницу для актуального расписания.';}
  } catch(error) {
    draft.message = error.message; draft.error = true;
  } finally {
    draft.pending = false;
    const current = data.find(day=>day.date===key);
    if (current) days.querySelector('[data-date="'+key+'"]')?.replaceWith(createDay(current));
  }
}
document.querySelector('#past').onclick = () => {
  past = !past; document.querySelector('#past').textContent = past?'Скрыть прошедшее':'Прошедшее'; render();
};
document.querySelector('#close').onclick = () => dialog.close();
load().then(render).catch(error=>{status.textContent=error.message;});
