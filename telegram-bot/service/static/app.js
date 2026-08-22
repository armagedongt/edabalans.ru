const root = document.querySelector('#root');
const title = document.querySelector('#title');
const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const telegram = value => esc(value).replace(/&lt;(\/?)(b|strong|i|em|u|s|del|blockquote|code|pre)&gt;/gi, '<$1$2>').replace(/&lt;br\s*\/?&gt;/gi, '<br>').replace(/&lt;a href=(?:&quot;|&#39;)(https?:\/\/[^&]+?)(?:&quot;|&#39;)&gt;([\s\S]*?)&lt;\/a&gt;/gi, '<a href="$1" target="_blank" rel="noreferrer">$2</a>');
const firstLine = value => String(value || '').replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 78) || 'Без текста';
const dateText = value => value ? new Intl.DateTimeFormat('ru', {dateStyle:'short', timeStyle:'short'}).format(new Date(value)) : '—';

async function api(url, options = {}) {
  url = url.replace('/admin/', '/bot-api/');
  const response = await fetch(url, {headers:{'Content-Type':'application/json'}, ...options});
  if (response.status === 401) { location.replace('/bot'); throw new Error('Нужно войти заново'); }
  if (!response.ok) throw new Error(`${response.status}: ${await response.text()}`);
  return response.json();
}
async function upload(file) {
  const body = new FormData(); body.append('file', file);
  const response = await fetch('/bot-api/media', {method:'POST', body});
  if (response.status === 401) location.replace('/bot');
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}
function busy() { root.innerHTML = '<div class="empty">Загружаю…</div>'; }
function fail(error) { root.innerHTML = `<div class="error">${esc(error.message)}</div>`; }
function toast(button, text = 'Сохранено') { const previous = button.textContent; button.textContent = text; button.classList.add('saved'); setTimeout(() => { button.textContent = previous; button.classList.remove('saved'); }, 1400); }
function delayDisplay(seconds) { if (seconds == null) return null; return seconds < 3600 ? {value:Math.round(seconds / 60), unit:'мин.', multiplier:60} : {value:+(seconds / 3600).toFixed(2), unit:'ч.', multiplier:3600}; }

function graphLayout(data) {
  const ids = new Set(data.nodes.map(node => node.id));
  const incoming = new Map([...ids].map(id => [id, 0]));
  const outgoing = new Map([...ids].map(id => [id, []]));
  data.edges.forEach(edge => { if (ids.has(edge.source) && ids.has(edge.target)) { incoming.set(edge.target, (incoming.get(edge.target) || 0) + 1); outgoing.get(edge.source).push(edge.target); } });
  const rank = new Map(), pending = new Map(incoming), queue = [];
  incoming.forEach((value, id) => { if (!value) { rank.set(id, 0); queue.push(id); } });
  while (queue.length) {
    const id = queue.shift(), current = rank.get(id) || 0;
    (outgoing.get(id) || []).forEach(next => { rank.set(next, Math.max(rank.get(next) || 0, current + 1)); pending.set(next, pending.get(next) - 1); if (!pending.get(next)) queue.push(next); });
  }
  let fallback = Math.max(0, ...rank.values()) + 1;
  data.nodes.forEach(node => { if (!rank.has(node.id)) rank.set(node.id, fallback++); });
  const groups = new Map();
  data.nodes.forEach(node => { const value = rank.get(node.id); if (!groups.has(value)) groups.set(value, []); groups.get(value).push(node); });
  const positions = new Map();
  groups.forEach((nodes, value) => nodes.sort((a,b) => (a.position || 0) - (b.position || 0)).forEach((node, index) => positions.set(node.id, {x:40 + value * 290, y:40 + index * 125})));
  return {positions, width:Math.max(760, (Math.max(0, ...rank.values()) + 1) * 290 + 280), height:Math.max(520, ...[...groups.values()].map(group => group.length * 125 + 100))};
}
function graphDetails(node) {
  const rows = Object.entries(node.details || {}).map(([key,value]) => `<div class="detail-row"><b>${esc(key)}</b><span>${esc(typeof value === 'object' ? JSON.stringify(value, null, 2) : value)}</span></div>`).join('');
  return `<h3>${esc(node.label)}</h3><div class="meta">${esc(node.subtitle || node.kind)}</div>${rows}${node.sequence_code ? `<button class="action open-flow" data-code="${esc(node.sequence_code)}">Открыть подробную схему</button>` : ''}`;
}
function renderGraph(data) {
  const {positions, width, height} = graphLayout(data);
  const errors = data.issues.filter(issue => issue.severity === 'error').length, warnings = data.issues.length - errors;
  const edges = data.edges.map(edge => { const from = positions.get(edge.source), to = positions.get(edge.target); if (!from || !to) return ''; const x1=from.x+220,y1=from.y+38,x2=to.x,y2=to.y+38,middle=(x1+x2)/2; return `<g><path class="graph-edge ${esc(edge.branch || 'default')}" d="M${x1} ${y1} C${middle} ${y1},${middle} ${y2},${x2} ${y2}" marker-end="url(#arrow)"></path><text class="edge-label" x="${middle}" y="${(y1+y2)/2-6}">${esc(edge.label || '')}</text></g>`; }).join('');
  const nodes = data.nodes.map(node => { const point=positions.get(node.id), label=node.label.length>29?`${node.label.slice(0,28)}…`:node.label, sub=node.subtitle||node.kind; return `<g class="graph-node ${esc(node.kind)}" data-node="${esc(node.id)}" transform="translate(${point.x} ${point.y})"><rect width="220" height="76" rx="13"></rect><text x="14" y="29"><tspan class="node-title">${esc(label)}</tspan><tspan class="node-sub" x="14" dy="22">${esc(sub.length>32?`${sub.slice(0,31)}…`:sub)}</tspan></text></g>`; }).join('');
  root.innerHTML = `<div class="map-toolbar"><div><b>${esc(data.title)}</b><div class="meta">${data.level === 'overview' ? 'Собрана автоматически из рабочих маршрутов и цепочек' : `Версия ${esc(data.version)} · ${esc(data.version_status)}`}</div></div><div class="row">${data.level === 'sequence' ? '<button class="action alt" id="map-home">← Вся карта</button>' : ''}<button class="action alt" id="map-fit">Показать целиком</button><span class="map-status ${errors?'bad':'ok'}">${errors?`${errors} ошибок`:'Проверка пройдена'}${warnings?` · ${warnings} замечаний`:''}</span></div></div><div class="map-grid"><div class="map-canvas"><svg id="flow-map" viewBox="0 0 1100 680" aria-label="Интерактивная карта логики бота"><defs><marker id="arrow" markerWidth="10" markerHeight="8" refX="9" refY="4" orient="auto"><path d="M0,0 L10,4 L0,8 z"></path></marker></defs><g id="viewport"><g>${edges}</g><g>${nodes}</g></g></svg><div class="map-help">Колёсико — масштаб · потяните фон — перемещение · двойной клик по цепочке — открыть</div></div><aside class="card map-inspector" id="map-inspector"><h3>Выберите блок</h3><div class="meta">Здесь появятся назначение, хранение и место исполнения.</div></aside></div>${data.issues.length ? `<details class="card map-issues" ${errors?'open':''}><summary>Проверка карты: ${data.issues.length}</summary>${data.issues.map(issue => `<div class="issue ${esc(issue.severity)}"><b>${issue.severity==='error'?'Ошибка':'Замечание'}</b> · ${esc(issue.sequence_name || '')} ${esc(issue.message)}</div>`).join('')}</details>` : ''}`;
  const svg=document.querySelector('#flow-map'), viewport=document.querySelector('#viewport'), inspector=document.querySelector('#map-inspector');
  let state={x:20,y:20,s:Math.min(1,1000/width,610/height)}, drag=null; const apply=()=>viewport.setAttribute('transform',`translate(${state.x} ${state.y}) scale(${state.s})`); apply();
  svg.onwheel=event=>{event.preventDefault();const old=state.s;state.s=Math.max(.22,Math.min(2.5,state.s*(event.deltaY<0?1.12:.89)));const rect=svg.getBoundingClientRect(),mx=(event.clientX-rect.left)*(1100/rect.width),my=(event.clientY-rect.top)*(680/rect.height);state.x=mx-(mx-state.x)*(state.s/old);state.y=my-(my-state.y)*(state.s/old);apply();};
  svg.onpointerdown=event=>{if(event.target.closest('.graph-node'))return;drag={x:event.clientX,y:event.clientY,ox:state.x,oy:state.y};svg.setPointerCapture(event.pointerId);};
  svg.onpointermove=event=>{if(!drag)return;const rect=svg.getBoundingClientRect();state.x=drag.ox+(event.clientX-drag.x)*(1100/rect.width);state.y=drag.oy+(event.clientY-drag.y)*(680/rect.height);apply();}; svg.onpointerup=()=>drag=null;
  document.querySelector('#map-fit').onclick=()=>{state={x:20,y:20,s:Math.min(1,1000/width,610/height)};apply();};
  if (document.querySelector('#map-home')) document.querySelector('#map-home').onclick=()=>mapView();
  document.querySelectorAll('.graph-node').forEach(element=>{const node=data.nodes.find(item=>item.id===element.dataset.node);element.onclick=()=>{document.querySelectorAll('.graph-node').forEach(item=>item.classList.remove('selected'));element.classList.add('selected');inspector.innerHTML=graphDetails(node);const button=inspector.querySelector('.open-flow');if(button)button.onclick=()=>mapView(button.dataset.code);};element.ondblclick=()=>{if(node.sequence_code)mapView(node.sequence_code);};});
}
async function mapView(sequenceCode=null) { busy(); const data=await api(`/admin/map${sequenceCode?`?sequence_code=${encodeURIComponent(sequenceCode)}`:''}`); title.textContent=sequenceCode?data.title:'Карта бота'; renderGraph(data); }

function humanStep(step) {
  if (step.kind === 'DELAY') { const delay = delayDisplay(step.delay_seconds); return {title:`Подождать ${delay.value} ${delay.unit}`, note:'Следующий блок отправится после этой паузы'}; }
  if (step.kind === 'WAIT_BUTTON') return {title:'Ждать нажатия кнопки', note:'Цепочка продолжится после действия пользователя'};
  if (step.kind === 'CONDITION') {
    if (step.configuration.condition === 'has_product') return {title:'Проверить покупку мастер-класса', note:'Проверка выполняется по данным общей базы'};
    if (step.configuration.condition === 'subscription_check') return {title:'Проверить подписку на канал', note:step.configuration.enabled ? 'Проверка включена' : 'Пока работает как заглушка'};
    return {title:'Проверить условие', note:step.label};
  }
  if (step.kind === 'STOP') return {title:'Завершить цепочку', note:'После этого блока отправок не будет'};
  return {title:step.content?.title || step.label, note:firstLine(step.content?.body_source)};
}
function conditionBranches(step) {
  if (step.kind !== 'CONDITION') return '';
  if (step.configuration.condition === 'has_product') return '<div class="branch-grid"><span><b>Купил</b> → после покупки</span><span><b>Не купил</b> → продолжить</span></div>';
  if (step.configuration.condition === 'subscription_check') return '<div class="branch-grid"><span><b>Подписан</b> → продолжить</span><span><b>Не подписан</b> → напомнить</span></div>';
  const branches = step.configuration.branches || [];
  return branches.length ? `<div class="branch-grid">${branches.map(branch => `<span>${esc(branch)}</span>`).join('')}</div>` : '';
}

function editorToolbar() {
  return [['bold','B'],['italic','I'],['underline','U'],['strikeThrough','S'],['formatBlock','❝'],['link','Ссылка']].map(([command,label]) => `<button type="button" data-command="${command}">${label}</button>`).join('') + '<span class="toolbar-divider"></span>' + ['😊','🔥','✅','❤️'].map(value => `<button type="button" data-emoji="${value}">${value}</button>`).join('');
}
function bindToolbar(container, editor) {
  container.querySelectorAll('[data-command]').forEach(button => button.onclick = () => {
    editor.focus(); const command = button.dataset.command;
    if (command === 'link') { const href = prompt('Вставьте ссылку'); if (href) document.execCommand('createLink', false, href); }
    else if (command === 'formatBlock') document.execCommand('formatBlock', false, 'blockquote');
    else document.execCommand(command, false, null);
  });
  container.querySelectorAll('[data-emoji]').forEach(button => button.onclick = () => { editor.focus(); document.execCommand('insertText', false, button.dataset.emoji); });
}
function renderTelegramEditor(host, content, onSave) {
  const media = content.media_kind ? `<div class="tg-media">${esc(content.media_kind.toUpperCase())}<small>${content.media_path ? 'файл прикреплён' : 'медиа будет добавлено позже'}</small></div>` : '';
  host.innerHTML = `<div class="tg-top"><div class="tg-avatar">е</div><div><b>Еда — это баланс</b><small>бот</small></div></div><div class="tg-chat"><div class="tg-bubble">${media}<div id="tg-editor" class="tg-text" contenteditable="true">${telegram(content.body_source || '')}</div><time>сейчас ✓✓</time></div></div><div class="composer-tools" id="format-tools">${editorToolbar()}</div><div class="composer-actions"><label class="file-action">＋ Медиа<input id="media-file" type="file" accept="image/*,video/mp4,audio/*"></label><button class="action" id="save-message">Сохранить сообщение</button></div><div class="meta composer-status" id="composer-status">Можно редактировать прямо в сообщении выше</div>`;
  const editor = host.querySelector('#tg-editor'); bindToolbar(host.querySelector('#format-tools'), editor);
  host.querySelector('#media-file').onchange = async event => {
    const file = event.target.files[0]; if (!file) return; const status = host.querySelector('#composer-status'); status.textContent = 'Загружаю файл…';
    try { const result = await upload(file); content.media_kind = result.media_kind; content.media_path = result.media_path; status.textContent = `Прикреплён: ${result.filename}`; }
    catch (error) { status.textContent = error.message; }
  };
  host.querySelector('#save-message').onclick = async event => { await onSave({body_source:editor.innerHTML, media_kind:content.media_kind || null, media_path:content.media_path || null}); toast(event.currentTarget); };
}

async function sequences() {
  busy(); const list = await api('/admin/sequences');
  root.innerHTML = `<div class="grid sequence-cards">${list.map(sequence => `<article class="card"><span class="eyebrow">${sequence.status === 'published' ? 'АКТИВНАЯ ЦЕПОЧКА' : 'ЗАГОТОВКА'}</span><h3>${esc(sequence.name)}</h3><p class="meta">${esc(sequence.description || 'Описание будет добавлено')}</p><div class="card-footer"><span>${sequence.steps} блоков · версия ${sequence.version}</span><button class="action" data-seq="${esc(sequence.code)}">Открыть</button></div></article>`).join('')}</div>`;
  root.querySelectorAll('[data-seq]').forEach(button => button.onclick = () => sequence(button.dataset.seq));
}
async function sequence(code) {
  busy(); const data = await api(`/admin/sequences/${code}`); title.textContent = data.name;
  root.innerHTML = `<section class="rule-card"><div class="sequence-actions"><button class="back-link" id="back">← Цепочки</button><button class="action" id="show-map">Открыть схему</button></div><div><span>ЗАПУСК</span><p>${esc(data.rule.start)}</p></div><div><span>ОСТАНОВКА</span><p>${esc(data.rule.stop)}</p></div><div><span>ДАЛЬШЕ</span><p>${esc(data.rule.next)}</p></div></section><div class="sequence-workspace"><section class="flow-list" id="flow-list">${data.steps.map(step => { const human = humanStep(step), delay = delayDisplay(step.delay_seconds); return `<article class="flow-node ${step.kind.toLowerCase()} ${step.enabled ? '' : 'disabled'}" data-step="${step.id}"><div class="node-head"><span class="node-number">${step.position}</span><span class="node-kind">${esc(step.kind)}</span>${delay ? `<b>${delay.value} ${delay.unit}</b>` : ''}</div><h3>${esc(human.title)}</h3><p>${esc(human.note)}</p>${conditionBranches(step)}<div class="node-move"><button data-move="up" title="Выше">↑</button><button data-move="down" title="Ниже">↓</button></div></article>`; }).join('')}</section><aside class="telegram-pane" id="step-pane"><div class="empty">Нажмите на блок — здесь откроется сообщение или его настройки</div></aside></div>`;
  document.querySelector('#back').onclick = () => show('sequences'); document.querySelector('#show-map').onclick = () => mapView(code); const pane = document.querySelector('#step-pane');
  const selectStep = step => {
    document.querySelectorAll('.flow-node').forEach(node => node.classList.toggle('selected', node.dataset.step === step.id));
    if (step.content) renderTelegramEditor(pane, step.content, async changes => { await api(`/admin/content/${step.content.id}`, {method:'PATCH', body:JSON.stringify(changes)}); Object.assign(step.content, changes); const node = document.querySelector(`[data-step="${step.id}"] p`); if (node) node.textContent = firstLine(changes.body_source); });
    else if (step.kind === 'DELAY') {
      const delay = delayDisplay(step.delay_seconds); pane.innerHTML = `<div class="setting-pane"><span class="eyebrow">ЗАДЕРЖКА</span><h2>${esc(humanStep(step).title)}</h2><p>Укажите паузу перед следующим блоком.</p><div class="delay-editor"><input id="delay-value" type="number" min="0" step="0.25" value="${delay.value}"><select id="delay-unit"><option value="60" ${delay.multiplier===60?'selected':''}>минут</option><option value="3600" ${delay.multiplier===3600?'selected':''}>часов</option></select></div><button class="action" id="save-delay">Сохранить задержку</button></div>`;
      pane.querySelector('#save-delay').onclick = async event => { const seconds = Math.round(+pane.querySelector('#delay-value').value * +pane.querySelector('#delay-unit').value); await api(`/admin/steps/${step.id}`, {method:'PATCH', body:JSON.stringify({delay_seconds:seconds})}); toast(event.currentTarget); setTimeout(() => sequence(code), 500); };
    } else { const human = humanStep(step); pane.innerHTML = `<div class="setting-pane"><span class="eyebrow">${esc(step.kind)}</span><h2>${esc(human.title)}</h2><p>${esc(human.note)}</p>${conditionBranches(step)}<pre>${esc(JSON.stringify(step.configuration, null, 2))}</pre></div>`; }
  };
  document.querySelectorAll('.flow-node').forEach(node => { const step = data.steps.find(item => item.id === node.dataset.step); node.onclick = event => { if (!event.target.closest('[data-move]')) selectStep(step); }; node.querySelectorAll('[data-move]').forEach(button => button.onclick = async event => { event.stopPropagation(); const target = button.dataset.move === 'up' ? Math.max(1, step.position - 1) : step.position + 1; await api(`/admin/steps/${step.id}`, {method:'PATCH', body:JSON.stringify({position:target})}); sequence(code); }); });
  const firstMessage = data.steps.find(step => step.content); if (firstMessage) selectStep(firstMessage);
}

async function library() {
  busy(); const items = await api('/admin/content'); const scenarios = [...new Set(items.map(item => item.origin_scenario_name).filter(Boolean))].sort();
  root.innerHTML = `<div class="library-tools"><input id="q" placeholder="Найти текст, тему или фразу"><select id="scenario"><option value="">Все сценарии (${scenarios.length})</option>${scenarios.map(value => `<option>${esc(value)}</option>`).join('')}</select></div><div class="content-workspace"><section class="library-list" id="items"></section><aside class="telegram-pane" id="preview"><div class="empty">Выберите сообщение</div></aside></div>`;
  const list = document.querySelector('#items');
  const draw = () => { const query = document.querySelector('#q').value.toLowerCase(), scenario = document.querySelector('#scenario').value; const visible = items.filter(item => (!scenario || item.origin_scenario_name === scenario) && `${item.title} ${item.body_source} ${(item.labels || []).join(' ')}`.toLowerCase().includes(query)); list.innerHTML = `<div class="library-count">Показано ${visible.length} из ${items.length}</div>${visible.map(item => `<button class="library-item" data-item="${item.id}"><b>${esc(item.title)}</b><span>${esc(item.origin_scenario_name || item.origin_system || 'шаблон')}</span><small>${esc(firstLine(item.body_source))}</small></button>`).join('')}`; list.querySelectorAll('[data-item]').forEach(button => button.onclick = () => { const item = items.find(value => value.id === button.dataset.item); list.querySelectorAll('.library-item').forEach(row => row.classList.toggle('selected', row === button)); renderTelegramEditor(document.querySelector('#preview'), item, async changes => { await api(`/admin/content/${item.id}`, {method:'PATCH', body:JSON.stringify(changes)}); Object.assign(item, changes); button.querySelector('small').textContent = firstLine(item.body_source); }); }); };
  document.querySelector('#q').oninput = draw; document.querySelector('#scenario').onchange = draw; draw();
}

async function contacts() {
  busy(); const rows = await api('/admin/contacts'); let pinned = localStorage.getItem('telegramPinnedContact');
  root.innerHTML = `<div class="library-tools"><input id="contact-q" placeholder="Найти по имени, username или Telegram ID"><span class="meta">${rows.length} пользователей</span></div><div class="contact-list" id="contacts"></div>`;
  const draw = () => { const query = document.querySelector('#contact-q').value.toLowerCase(); const filtered = rows.filter(row => `${row.name} ${row.username} ${row.telegram_user_id}`.toLowerCase().includes(query)).sort((a,b) => Number(b.id === pinned) - Number(a.id === pinned)); document.querySelector('#contacts').innerHTML = filtered.map(contact => { const progress = contact.total ? Math.min(100, Math.round(contact.sent / contact.total * 100)) : 0; return `<article class="contact-row ${contact.id === pinned ? 'pinned' : ''}"><button class="pin" data-pin="${contact.id}" title="Закрепить">${contact.id === pinned ? '★' : '☆'}</button><div><h3>${esc(contact.name || contact.username || contact.telegram_user_id)}</h3><span class="meta">@${esc(contact.username || 'без username')} · ${esc(contact.run_status || 'цепочка не запущена')}</span><div class="progress"><i style="width:${progress}%"></i></div><small>${contact.sent || 0} из ${contact.total || 0} сообщений · шаг ${esc(contact.current_step || '—')}</small></div><div class="contact-actions"><button class="action speed" data-id="${contact.id}">Ускоренный тест</button><button class="action alt message" data-id="${contact.id}">Написать</button></div></article>`; }).join('') || '<div class="empty">Ничего не найдено</div>'; document.querySelectorAll('[data-pin]').forEach(button => button.onclick = () => { pinned = button.dataset.pin; localStorage.setItem('telegramPinnedContact', pinned); draw(); }); document.querySelectorAll('.speed').forEach(button => button.onclick = async () => { await api(`/admin/contacts/${button.dataset.id}/accelerated-run`, {method:'POST', body:JSON.stringify({})}); toast(button, 'Запущено'); }); document.querySelectorAll('.message').forEach(button => button.onclick = () => openMessage(button.dataset.id)); };
  document.querySelector('#contact-q').oninput = draw; draw();
}
function openMessage(contactId) {
  const modal = document.createElement('div'); modal.className = 'modal-backdrop'; modal.innerHTML = `<form class="modal"><button type="button" class="modal-close">×</button><span class="eyebrow">ЛИЧНОЕ СООБЩЕНИЕ</span><h2>Написать пользователю</h2><div class="simple-editor" contenteditable="true" id="personal-text"></div><button class="action">Отправить в Telegram</button></form>`; document.body.append(modal); modal.querySelector('.modal-close').onclick = () => modal.remove(); modal.querySelector('form').onsubmit = async event => { event.preventDefault(); const text = modal.querySelector('#personal-text').innerHTML; await api(`/admin/contacts/${contactId}/messages`, {method:'POST', body:JSON.stringify({text})}); modal.remove(); };
}

async function broadcasts() {
  busy(); const rows = await api('/admin/broadcasts');
  root.innerHTML = `<div class="broadcast-workspace"><section><div class="section-heading"><div><span class="eyebrow">РАЗОВЫЕ РАССЫЛКИ</span><h2>Сохранённые рассылки</h2></div><button class="action" id="new-broadcast">＋ Новая</button></div><div class="broadcast-list">${rows.map(row => `<article class="card broadcast-card" data-broadcast="${row.id}"><div><h3>${esc(row.title)}</h3><span class="meta">${esc(row.status)} · отправлено ${row.sent} · ошибок ${row.failed}</span></div>${row.status === 'draft' ? `<button class="action launch" data-id="${row.id}">Запустить</button>` : ''}</article>`).join('') || '<div class="empty">Рассылок пока нет</div>'}</div></section><aside class="telegram-pane" id="broadcast-editor"></aside></div>`;
  const editor = document.querySelector('#broadcast-editor'); const newBroadcast = () => { const content = {body_source:'', media_kind:null, media_path:null}; editor.innerHTML = `<div class="broadcast-fields"><input id="bc-title" placeholder="Название рассылки"><input id="bc-time" type="datetime-local"><span class="meta">Пустая дата — сохранить как черновик</span></div><div id="bc-telegram"></div>`; renderTelegramEditor(editor.querySelector('#bc-telegram'), content, async changes => { Object.assign(content, changes); const titleValue = editor.querySelector('#bc-title').value.trim(); if (!titleValue) throw new Error('Укажите название рассылки'); await api('/admin/broadcasts', {method:'POST', body:JSON.stringify({title:titleValue, text:content.body_source, media_kind:content.media_kind, media_path:content.media_path, scheduled_at:editor.querySelector('#bc-time').value || null})}); broadcasts(); }); };
  document.querySelector('#new-broadcast').onclick = newBroadcast; document.querySelectorAll('.broadcast-card').forEach(card => card.onclick = event => { if (event.target.closest('.launch')) return; const row = rows.find(value => value.id === card.dataset.broadcast); renderTelegramEditor(editor, row, async () => { throw new Error('Создайте новую версию рассылки'); }); }); document.querySelectorAll('.launch').forEach(button => button.onclick = async () => { if (confirm('Отправить рассылку активным тестовым контактам?')) { await api(`/admin/broadcasts/${button.dataset.id}/launch`, {method:'POST'}); broadcasts(); } }); newBroadcast();
}

async function links() {
  busy(); const [rows, serverPlatforms] = await Promise.all([api('/admin/tracking-links'), api('/admin/tracking-platforms')]); const localPlatforms = JSON.parse(localStorage.getItem('telegramPlatforms') || '[]'); const platforms = [...new Set([...serverPlatforms, ...localPlatforms])]; const clicks = rows.reduce((sum,row) => sum + row.clicks, 0), starts = rows.reduce((sum,row) => sum + row.unique_starts, 0), conversion = clicks ? (starts / clicks * 100).toFixed(1) : '0';
  root.innerHTML = `<div class="metrics"><article><span>Ссылок</span><b>${rows.length}</b></article><article><span>Переходов</span><b>${clicks}</b></article><article><span>Запустили бота</span><b>${starts}</b></article><article><span>Конверсия</span><b>${conversion}%</b></article></div><form class="link-builder" id="link-form"><div><label>Площадка</label><select name="platform" id="platform" required>${platforms.map(value => `<option>${esc(value)}</option>`).join('')}<option value="__new">＋ Добавить площадку</option></select></div><div><label>Пост / размещение</label><input name="placement" placeholder="Например: видео про завтрак" required></div><div><label>Кампания</label><input name="campaign" placeholder="Необязательно"></div><button class="action">Создать ссылку</button></form><div class="section-heading"><div><span class="eyebrow">ОТКУДА ПОДПИСКИ</span><h2>Переходы по ссылкам</h2></div><select id="link-filter"><option value="">Все площадки</option>${platforms.map(value => `<option>${esc(value)}</option>`).join('')}</select></div><div class="link-table" id="link-table"></div><p class="meta analytics-note">Покупки и выручка появятся здесь после связывания платёжных событий с источником пользователя.</p>`;
  const table = document.querySelector('#link-table'); const draw = () => { const platform = document.querySelector('#link-filter').value; table.innerHTML = rows.filter(row => !platform || row.platform === platform).map(row => `<article class="link-row"><div><b>${esc(row.platform)} · ${esc(row.placement)}</b><span>${esc(row.campaign || 'без кампании')} · ${dateText(row.created_at)}</span><code>${esc(row.url)}</code></div><div class="link-numbers"><span><b>${row.clicks}</b> переходов</span><span><b>${row.unique_starts}</b> запусков</span><span><b>${row.conversion}%</b> конверсия</span></div><button class="copy" data-url="${esc(row.url)}">Копировать</button></article>`).join('') || '<div class="empty">Ссылок пока нет</div>'; table.querySelectorAll('.copy').forEach(button => button.onclick = async () => { await navigator.clipboard.writeText(button.dataset.url); toast(button, 'Скопировано'); }); };
  document.querySelector('#link-filter').onchange = draw; document.querySelector('#platform').onchange = event => { if (event.target.value !== '__new') return; const value = prompt('Название новой площадки'); if (!value) { event.target.selectedIndex = 0; return; } localPlatforms.push(value); localStorage.setItem('telegramPlatforms', JSON.stringify([...new Set(localPlatforms)])); event.target.add(new Option(value, value, true, true), event.target.options.length - 1); };
  document.querySelector('#link-form').onsubmit = async event => { event.preventDefault(); const values = Object.fromEntries(new FormData(event.target)); const result = await api('/admin/tracking-links', {method:'POST', body:JSON.stringify(values)}); await navigator.clipboard.writeText(result.url).catch(() => {}); links(); }; draw();
}

const views = {map:()=>mapView(), sequences, library, contacts, broadcasts, links};
async function show(view) { document.querySelectorAll('nav button').forEach(button => button.classList.toggle('active', button.dataset.view === view)); title.textContent = {map:'Карта бота',sequences:'Цепочки',library:'Библиотека сообщений',contacts:'Пользователи и тестирование',broadcasts:'Разовые рассылки',links:'Ссылки и источники'}[view]; try { await views[view](); } catch (error) { fail(error); } }
document.querySelectorAll('nav button').forEach(button => button.onclick = () => show(button.dataset.view));
document.querySelector('#logout').onclick = async () => { await fetch('/bot-api/logout', {method:'POST'}); location.replace('/bot'); };
api('/health').then(value => document.querySelector('#health').textContent = value.status === 'ok' ? '● работает' : 'ошибка');
show('map');
