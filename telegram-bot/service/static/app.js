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

const moduleKind = {
  entry:'Вход', event:'Событие', technical:'Система', system:'Система', condition:'Условие',
  message:'Сообщение', photo:'Фото', video:'Видео', video_note:'Кружок', voice:'Голосовое',
  delay:'Ожидание', wait_button:'Ожидание кнопки', db_read:'Чтение БД', db_write:'Запись БД',
  goto:'Переход', sequence:'Другой модуль', module_exit:'Выход', stop:'Завершение', error:'Ошибка', module:'Модуль',
};
const nodeOrder = nodes => [...nodes].sort((a,b) => (a.position ?? 100000) - (b.position ?? 100000) || String(a.label).localeCompare(String(b.label), 'ru'));
const technicalRows = node => Object.entries(node.details || {}).map(([key,value]) => `<div class="detail-row"><b>${esc(key)}</b><span>${esc(typeof value === 'object' ? JSON.stringify(value, null, 2) : value)}</span></div>`).join('');
function validationBlock(data) {
  const errors=data.issues.filter(issue=>issue.severity==='error').length, warnings=data.issues.length-errors;
  return `<span class="map-status ${errors?'bad':'ok'}">${errors?`${errors} ошибок`:'Проверка пройдена'}${warnings?` · ${warnings} замечаний`:''}</span>`;
}
function issuesBlock(data) {
  if (!data.issues.length) return '';
  return `<details class="card map-issues" ${data.issues.some(issue=>issue.severity==='error')?'open':''}><summary>Результат автоматической проверки: ${data.issues.length}</summary>${data.issues.map(issue=>`<div class="issue ${esc(issue.severity)}"><b>${issue.severity==='error'?'Ошибка':'Замечание'}</b> · ${esc(issue.sequence_name||'')} ${esc(issue.message)}</div>`).join('')}</details>`;
}
function renderModuleOverview(data) {
  const modules=data.nodes.filter(node=>node.kind==='module');
  const byId=new Map(data.nodes.map(node=>[node.id,node]));
  const events=data.nodes.filter(node=>node.kind==='event');
  root.innerHTML=`<div class="help-card"><b>Один источник логики</b><span>Эти карточки строятся из исполняемого графа бота. В админке можно читать архитектуру и редактировать содержание сообщений, но нельзя переставлять условия, задержки и переходы.</span></div>${events.length?`<section class="module-events"><span class="eyebrow">СИСТЕМНЫЕ СОБЫТИЯ</span>${events.map(node=>`<article><b>${esc(node.label)}</b><span>${esc(node.subtitle||'')}</span></article>`).join('')}</section>`:''}<div class="grid module-cards">${modules.map(node=>{const outgoing=data.edges.filter(edge=>edge.source===node.id).map(edge=>`${edge.label} → ${byId.get(edge.target)?.label||edge.target}`);const incoming=data.edges.filter(edge=>edge.target===node.id).map(edge=>`${byId.get(edge.source)?.label||edge.source} → ${edge.label}`);return `<article class="card module-card"><span class="eyebrow">ГЛОБАЛЬНЫЙ МОДУЛЬ</span><h3>${esc(node.label)}</h3><p class="meta">${esc(node.subtitle||'')}</p>${incoming.length?`<div class="module-links"><b>Вход</b>${incoming.map(value=>`<span>${esc(value)}</span>`).join('')}</div>`:''}${outgoing.length?`<div class="module-links"><b>Выход</b>${outgoing.map(value=>`<span>${esc(value)}</span>`).join('')}</div>`:''}<div class="card-footer"><code>${esc(node.module_code||'')}</code><button class="action" data-module="${esc(node.module_code)}">Открыть последовательность</button></div></article>`;}).join('')}</div>${issuesBlock(data)}`;
  root.querySelectorAll('[data-module]').forEach(button=>button.onclick=()=>modulesView(null,button.dataset.module));
}
function renderModuleSequence(data) {
  const ordered=nodeOrder(data.nodes), byId=new Map(data.nodes.map(node=>[node.id,node]));
  const incoming=ordered.filter(node=>['entry','event'].includes(node.kind));
  const outputs=ordered.filter(node=>['module_exit','stop','error','sequence'].includes(node.kind));
  const rows=ordered.map((node,index)=>{
    const branches=data.edges.filter(edge=>edge.source===node.id);
    const editable=node.content?`<button class="action alt edit-module-message" data-node="${esc(node.id)}">Редактировать текст</button>`:'';
    const openTarget=!node.content&&node.sequence_code?`<button class="action alt open-module-target" data-code="${esc(node.sequence_code)}">Открыть модуль</button>`:'';
    return `<article class="logic-row ${esc(node.kind)}" data-logic-node="${esc(node.id)}"><div class="logic-index">${index+1}</div><div class="logic-main"><div class="logic-heading"><span class="logic-kind">${esc(moduleKind[node.kind]||node.kind)}</span>${node.content?'<span class="editable-mark">редактируемое содержание</span>':''}</div><h3>${esc(node.label)}</h3><p>${esc(node.subtitle||'')}</p>${branches.length?`<div class="logic-branches">${branches.map(edge=>`<div class="logic-branch ${esc(edge.branch||'default')}"><b>${esc(edge.label||'Далее')}</b><span>→ ${esc(byId.get(edge.target)?.label||edge.target)}</span></div>`).join('')}</div>`:''}<div class="logic-actions">${editable}${openTarget}${Object.keys(node.details||{}).length?`<details class="technical-details"><summary>Технические детали</summary>${technicalRows(node)}</details>`:''}</div></div></article>`;
  }).join('');
  const summary=(label,nodes,empty)=>`<section class="module-summary-block"><b>${label}</b>${nodes.length?nodes.map(node=>`<span class="summary-chip ${esc(node.kind)}">${esc(node.label)}</span>`).join(''):`<span class="meta">${empty}</span>`}</section>`;
  root.innerHTML=`<div class="module-toolbar"><div><button class="back-link" id="modules-home">← Все модули</button><h2>${esc(data.title)}</h2><p class="meta">${esc(data.description||(data.level==='sequence'?`Версия ${data.version} · ${data.version_status}`:'Текстовая проекция текущего исполняемого графа'))}</p>${data.status?`<span class="map-module-status">${esc(data.status)}</span>`:''}</div>${validationBlock(data)}</div><div class="module-summary">${summary('Входы',incoming,'отдельный вход не описан')}${summary('Выходы',outputs,'явный выход не описан')}</div><div class="module-text-workspace"><section><div class="section-heading"><div><span class="eyebrow">ЛОГИКА · ТОЛЬКО ЧТЕНИЕ</span><h2>Последовательность</h2></div></div><div class="logic-list">${rows||'<div class="empty">В модуле пока нет шагов</div>'}</div></section><aside class="telegram-pane" id="module-editor"><div class="empty">Нажмите «Редактировать текст» у сообщения. Условия, порядок и переходы меняются только через каноническую логику, код графа и тесты.</div></aside></div>${issuesBlock(data)}`;
  document.querySelector('#modules-home').onclick=()=>modulesView();
  root.querySelectorAll('.edit-module-message').forEach(button=>button.onclick=()=>{const node=byId.get(button.dataset.node),host=document.querySelector('#module-editor');root.querySelectorAll('.logic-row').forEach(row=>row.classList.toggle('selected',row.dataset.logicNode===node.id));renderTelegramEditor(host,node.content,async(changes,buttonText)=>{await api(`/admin/content/${node.content.id}`,{method:'PATCH',body:JSON.stringify(changes)});if(buttonText&&node.step_id){const updated=await api(`/admin/steps/${node.step_id}/presentation`,{method:'PATCH',body:JSON.stringify({button_text:buttonText})});node.configuration=updated.configuration;}Object.assign(node.content,changes);},node);});
  root.querySelectorAll('.open-module-target').forEach(button=>button.onclick=()=>modulesView(null,button.dataset.code));
}
function renderModules(data) { data.level==='overview'?renderModuleOverview(data):renderModuleSequence(data); }
async function modulesView(sequenceCode=null,moduleCode=null) { busy(); const query=moduleCode?`?module_code=${encodeURIComponent(moduleCode)}`:sequenceCode?`?sequence_code=${encodeURIComponent(sequenceCode)}`:''; const data=await api(`/admin/map${query}`); title.textContent=(sequenceCode||moduleCode)?data.title:'Модули'; renderModules(data); }

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
function renderTelegramEditor(host, content, onSave, presentation=null) {
  const media = content.media_kind ? `<div class="tg-media">${esc(content.media_kind.toUpperCase())}<small>${content.media_path ? 'файл прикреплён' : 'медиа будет добавлено позже'}</small></div>` : '';
  const firstButton = presentation?.configuration?.buttons?.[0];
  const help = presentation?.configuration?.editorial_help;
  const triggerHelp = help ? `<section class="trigger-help"><b>Зачем и когда отправляется</b><dl><dt>Сигнал</dt><dd>${esc(help.trigger)}</dd><dt>Условие</dt><dd>${esc(help.condition)}</dd><dt>Кому</dt><dd>${esc(help.recipient)}</dd><dt>Цель</dt><dd>${esc(help.purpose)}</dd></dl></section>` : '';
  const buttonEditor = firstButton ? `<label class="editor-label">ТЕКСТ КНОПКИ<input id="button-text" maxlength="64" value="${esc(firstButton.text || '')}"></label>` : '';
  host.innerHTML = `<div class="tg-top"><div class="tg-avatar">е</div><div><b>Еда — это баланс</b><small>бот</small></div></div>${triggerHelp}<div class="editor-label">ТЕКСТ СООБЩЕНИЯ — НАЖМИТЕ В ПОЛЕ НИЖЕ</div><div class="tg-chat"><div class="tg-bubble">${media}<div id="tg-editor" class="tg-text" contenteditable="true">${telegram(content.body_source || '')}</div><time>сейчас ✓✓</time></div></div>${buttonEditor}<div class="composer-tools" id="format-tools">${editorToolbar()}</div><div class="composer-actions"><label class="file-action">＋ Загрузить медиа<input id="media-file" type="file" accept="image/*,video/mp4,audio/*"></label><select id="media-kind" title="Как отправить прикреплённый файл"><option value="" ${!content.media_kind?'selected':''}>Без медиа</option><option value="photo" ${content.media_kind==='photo'?'selected':''}>Фото</option><option value="video" ${content.media_kind==='video'?'selected':''}>Обычное видео</option><option value="video_note" ${content.media_kind==='video_note'?'selected':''}>Видеокружок</option><option value="voice" ${content.media_kind==='voice'?'selected':''}>Голосовое</option></select><button class="action" id="save-message">Сохранить сообщение</button></div><div class="meta composer-status" id="composer-status">Текст, медиа и подпись кнопки сохраняются только после кнопки «Сохранить сообщение»</div>`;
  const editor = host.querySelector('#tg-editor'); bindToolbar(host.querySelector('#format-tools'), editor);
  host.querySelector('#media-file').onchange = async event => {
    const file = event.target.files[0]; if (!file) return; const status = host.querySelector('#composer-status'); status.textContent = 'Загружаю файл…';
    try { const result = await upload(file); content.media_kind = result.media_kind; content.media_path = result.media_path; host.querySelector('#media-kind').value=result.media_kind; status.textContent = `Прикреплён: ${result.filename}. Выберите способ отправки и сохраните.`; }
    catch (error) { status.textContent = error.message; }
  };
  host.querySelector('#save-message').onclick = async event => { content.media_kind=host.querySelector('#media-kind').value||null; await onSave({body_source:editor.innerHTML, media_kind:content.media_kind, media_path:content.media_path || null}, host.querySelector('#button-text')?.value.trim() || null); toast(event.currentTarget); };
}

async function sequences() {
  busy(); const list = await api('/admin/sequences');
  root.innerHTML = `<div class="help-card"><b>Три последовательных модуля</b><span>Start содержит источники и развилки. Welcome содержит навигацию, кружок, кнопку, подписку, четыре дня и три промежуточных поста. Через 12 часов после Дня 4 основная рассылка начинает с проверки покупки.</span></div><div class="grid sequence-cards">${list.map(item => `<article class="card"><span class="eyebrow">${item.item_type==='module'?'ГЛОБАЛЬНЫЙ МОДУЛЬ':item.status === 'published' ? 'АКТИВНАЯ ЦЕПОЧКА' : 'ЗАГОТОВКА'}</span><h3>${esc(item.name)}</h3><p class="meta">${esc(item.description || 'Описание будет добавлено')}</p><div class="card-footer"><span>${item.steps} блоков · версия ${item.version}</span><button class="action" data-code="${esc(item.code)}" data-kind="${esc(item.item_type||'sequence')}">Открыть</button></div></article>`).join('')}</div>`;
  root.querySelectorAll('[data-code]').forEach(button => button.onclick = () => button.dataset.kind==='module' ? modulesView(null,button.dataset.code) : sequence(button.dataset.code));
}
async function sequence(code) {
  busy(); const data = await api(`/admin/sequences/${code}`); title.textContent = data.name;
  root.innerHTML = `<section class="rule-card"><div class="sequence-actions"><button class="back-link" id="back">← Цепочки</button><button class="action" id="show-logic">Показать логику модуля</button></div><div><span>ЗАПУСК</span><p>${esc(data.rule.start)}</p></div><div><span>ОСТАНОВКА</span><p>${esc(data.rule.stop)}</p></div><div><span>ДАЛЬШЕ</span><p>${esc(data.rule.next)}</p></div></section><div class="sequence-workspace"><section class="flow-list" id="flow-list">${data.steps.map(step => { const human = humanStep(step), delay = delayDisplay(step.delay_seconds); return `<article class="flow-node ${step.kind.toLowerCase()} ${step.enabled ? '' : 'disabled'}" data-step="${step.id}"><div class="node-head"><span class="node-number">${step.position}</span><span class="node-kind">${esc(step.kind)}</span>${delay ? `<b>${delay.value} ${delay.unit}</b>` : ''}</div><h3>${esc(human.title)}</h3><p>${esc(human.note)}</p>${conditionBranches(step)}</article>`; }).join('')}</section><aside class="telegram-pane" id="step-pane"><div class="empty">Нажмите на текстовый блок — справа откроется редактор. Логика и переходы доступны для чтения в разделе «Модули».</div></aside></div>`;
  document.querySelector('#back').onclick = () => show('sequences'); document.querySelector('#show-logic').onclick = () => modulesView(null,code); const pane = document.querySelector('#step-pane');
  const selectStep = step => {
    document.querySelectorAll('.flow-node').forEach(node => node.classList.toggle('selected', node.dataset.step === step.id));
    if (step.content) renderTelegramEditor(pane, step.content, async (changes, buttonText) => { await api(`/admin/content/${step.content.id}`, {method:'PATCH', body:JSON.stringify(changes)}); if(buttonText){const updated=await api(`/admin/steps/${step.id}/presentation`, {method:'PATCH', body:JSON.stringify({button_text:buttonText})});step.configuration=updated.configuration;} Object.assign(step.content, changes); const node = document.querySelector(`[data-step="${step.id}"] p`); if (node) node.textContent = firstLine(changes.body_source); }, step);
    else if (step.kind === 'DELAY') {
      const delay = delayDisplay(step.delay_seconds); pane.innerHTML = `<div class="setting-pane"><span class="eyebrow">ЗАДЕРЖКА · ТОЛЬКО ЧТЕНИЕ</span><h2>${esc(humanStep(step).title)}</h2><p>${delay.value} ${delay.unit}. Для изменения логики сообщите новую задержку — она будет изменена в графе и тестах одновременно.</p></div>`;
    } else { const human = humanStep(step); pane.innerHTML = `<div class="setting-pane"><span class="eyebrow">${esc(step.kind)} · ТОЛЬКО ЧТЕНИЕ</span><h2>${esc(human.title)}</h2><p>${esc(human.note)}</p>${conditionBranches(step)}<pre>${esc(JSON.stringify(step.configuration, null, 2))}</pre></div>`; }
  };
  document.querySelectorAll('.flow-node').forEach(node => { const step = data.steps.find(item => item.id === node.dataset.step); node.onclick = () => selectStep(step); });
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
  const draw = () => {
    const query = document.querySelector('#contact-q').value.toLowerCase();
    const filtered = rows.filter(row => `${row.name} ${row.username} ${row.telegram_user_id}`.toLowerCase().includes(query)).sort((a,b) => Number(b.id === pinned) - Number(a.id === pinned));
    document.querySelector('#contacts').innerHTML = filtered.map(contact => {
      const progress = contact.total ? Math.min(100, Math.round(contact.sent / contact.total * 100)) : 0;
      return `<article class="contact-row ${contact.id === pinned ? 'pinned' : ''}"><button class="pin" data-pin="${contact.id}" title="Закрепить">${contact.id === pinned ? '★' : '☆'}</button><div><h3>${esc(contact.name || contact.username || contact.telegram_user_id)}</h3><span class="meta">@${esc(contact.username || 'без username')} · ${esc(contact.run_status || 'цепочка не запущена')}</span><div class="progress"><i style="width:${progress}%"></i></div><small>${contact.sent || 0} из ${contact.total || 0} сообщений · шаг ${esc(contact.current_step || '—')}</small></div><div class="contact-actions"><button class="action speed" data-id="${contact.id}">Тест цепочки</button><button class="action alt message" data-id="${contact.id}">Написать</button></div></article>`;
    }).join('') || '<div class="empty">Ничего не найдено</div>';
    document.querySelectorAll('[data-pin]').forEach(button => button.onclick = () => { pinned = button.dataset.pin; localStorage.setItem('telegramPinnedContact', pinned); draw(); });
    document.querySelectorAll('.speed').forEach(button => button.onclick = () => openAcceleratedTest(button.dataset.id));
    document.querySelectorAll('.message').forEach(button => button.onclick = () => openMessage(button.dataset.id));
  };
  const addStartPreviewButtons = () => document.querySelectorAll('.contact-row').forEach(row => { const actions=row.querySelector('.contact-actions'), id=row.querySelector('.speed')?.dataset.id; if(!actions||!id||actions.querySelector('.start-preview'))return; const button=document.createElement('button'); button.className='action alt start-preview'; button.textContent='Что ответит Start'; button.onclick=()=>openStartPreview(id); actions.append(button); });
  const listObserver = new MutationObserver(addStartPreviewButtons); listObserver.observe(document.querySelector('#contacts'), {childList:true});
  document.querySelector('#contact-q').oninput = () => { draw(); addStartPreviewButtons(); }; draw(); addStartPreviewButtons();
}
function openAcceleratedTest(contactId) {
  const modal=document.createElement('div');modal.className='modal-backdrop';
  modal.innerHTML=`<form class="modal"><button type="button" class="modal-close">×</button><span class="eyebrow">ТЕСТ ЦЕПОЧКИ</span><h2>Запустить для выбранного пользователя</h2><label class="test-field">Цепочка<select id="test-sequence"><option value="welcome_intensive">Welcome и интенсив</option><option value="prepurchase_nurture">Рассылка до покупки</option></select></label><label class="test-check"><input id="test-accelerated" type="checkbox" checked> Ускорить интервалы: 24 часа ≈ 2 минуты</label><label class="test-check"><input id="test-reset" type="checkbox" checked> Очистить только прежний технический прогресс цепочек</label><p class="meta">Покупки, доступы, CRM-карточка и теги не удаляются. Post-purchase ускоряется отдельной галочкой в админке Мастер-класса.</p><button class="action">Запустить тест</button></form>`;
  document.body.append(modal);modal.querySelector('.modal-close').onclick=()=>modal.remove();modal.onclick=event=>{if(event.target===modal)modal.remove();};
  modal.querySelector('form').onsubmit=async event=>{event.preventDefault();const button=event.submitter;button.disabled=true;try{await api(`/admin/contacts/${contactId}/accelerated-run`,{method:'POST',body:JSON.stringify({sequence_code:modal.querySelector('#test-sequence').value,time_scale:modal.querySelector('#test-accelerated').checked?1/720:1,reset_technical_state:modal.querySelector('#test-reset').checked})});modal.remove();}catch(error){button.disabled=false;button.textContent=error.message;}};
}
async function openStartPreview(contactId) {
  const data=await api(`/admin/contacts/${contactId}/start-preview`), facts=data.facts, decision=data.decision;
  const rows=[['Мастер-класс',facts.has_masterclass?'куплен':'не куплен'],['День 4',facts.day_four_sent?'отправлен':'не отправлен'],['Welcome run',facts.has_active_welcome_run?'active/waiting':'нет'],['Welcome запускался',facts.welcome_ever_started?'да':'нет'],['Следующее действие',decision.label]];
  const modal=document.createElement('div'); modal.className='modal-backdrop'; modal.innerHTML=`<section class="modal"><button type="button" class="modal-close">×</button><span class="eyebrow">ПРОВЕРКА /START</span><h2>${esc(decision.label)}</h2><p class="meta">Это предпросмотр по текущим данным. Он ничего не отправляет и не меняет.</p>${rows.map(([key,value])=>`<div class="detail-row"><b>${esc(key)}</b><span>${esc(value)}</span></div>`).join('')}${data.next_action_at?`<div class="detail-row"><b>Следующее сообщение</b><span>${esc(dateText(data.next_action_at))}</span></div>`:''}</section>`; document.body.append(modal); modal.querySelector('.modal-close').onclick=()=>modal.remove(); modal.onclick=event=>{if(event.target===modal)modal.remove();};
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
  busy(); const [rows, tags, unresolved] = await Promise.all([api('/admin/tracking-links'), api('/admin/tags'), api('/admin/utm/unresolved')]);
  const clicks=rows.reduce((n,row)=>n+row.clicks,0), starts=rows.reduce((n,row)=>n+row.unique_starts,0);
  root.innerHTML = `<div class="help-card"><b>Как это работает</b><span>Один набор источников и тегов хранится как правило. У правила может быть несколько опубликованных адресов: новый короткий код и старые LeadTeh-коды. Статистика объединяется по правилу, старые коды не переиспользуются.</span></div><div class="metrics"><article><span>Правил</span><b>${rows.length}</b></article><article><span>Переходов через go</span><b>${clicks}</b></article><article><span>Уникальных стартов</span><b>${starts}</b></article><article><span>Неразобранных UTM</span><b>${unresolved.length}</b></article></div><div class="link-tabs"><button class="active" data-link-tab="bot">Ссылки на бота</button><button data-link-tab="channel">Ссылки на канал</button><button data-link-tab="utm">Неразобранные UTM</button><button data-link-tab="events">События</button></div><section id="link-panel"></section>`;
  const panel=document.querySelector('#link-panel'); let tab='bot';
  const bindTagPicker=form=>{
    const input=form.querySelector('#tag-search'), suggestions=form.querySelector('#tag-suggestions'), selectedHost=form.querySelector('#selected-tags'), createButton=form.querySelector('#create-tag');
    const selectedIds=new Set();
    const normalized=value=>String(value||'').trim().toLocaleLowerCase('ru');
    const selectedTags=()=>tags.filter(tag=>selectedIds.has(tag.id));
    const matches=()=>{const query=normalized(input.value);return tags.filter(tag=>!selectedIds.has(tag.id)&&(!query||normalized(tag.name).includes(query))).slice(0,8);};
    const draw=()=>{
      const query=input.value.trim(), found=matches(), exact=tags.some(tag=>normalized(tag.name)===normalized(query));
      selectedHost.innerHTML=selectedTags().map(tag=>`<button type="button" class="selected-tag" data-remove-tag="${esc(tag.id)}">${esc(tag.name)} <span>×</span></button>`).join('')||'<small>Теги пока не выбраны</small>';
      suggestions.innerHTML=found.map(tag=>`<button type="button" data-add-tag="${esc(tag.id)}">${esc(tag.name)}</button>`).join('')||(query?'<small>Совпадений нет</small>':'<small>Начните вводить название тега</small>');
      suggestions.hidden=document.activeElement!==input&&!query;
      createButton.hidden=!query||exact;
      createButton.textContent=query?`＋ Создать новый тег «${query}»`:'＋ Создать новый тег';
      selectedHost.querySelectorAll('[data-remove-tag]').forEach(button=>button.onclick=()=>{selectedIds.delete(button.dataset.removeTag);draw();});
      suggestions.querySelectorAll('[data-add-tag]').forEach(button=>button.onclick=()=>{selectedIds.add(button.dataset.addTag);input.value='';input.focus();draw();});
    };
    input.oninput=draw; input.onfocus=draw;
    input.onkeydown=event=>{if(event.key!=='Enter')return;const found=matches();if(found.length){event.preventDefault();selectedIds.add(found[0].id);input.value='';draw();}};
    createButton.onclick=async()=>{const name=input.value.trim();if(!name)return;if(!confirm(`Создать новый тег «${name}»?`))return;const result=await api('/bot-api/tags',{method:'POST',body:JSON.stringify({name})});if(!tags.some(tag=>tag.id===result.id))tags.push({id:result.id,name:result.name});selectedIds.add(result.id);input.value='';draw();};
    draw();
    return selectedIds;
  };
  const copyButtons=()=>panel.querySelectorAll('[data-copy]').forEach(button=>button.onclick=async()=>{await navigator.clipboard.writeText(button.dataset.copy);toast(button,'Скопировано');});
  const catalog=kind=>{const filtered=rows.filter(row=>row.target_kind===kind);panel.innerHTML=`<form class="rule-builder" id="rule-form"><div><label>Название правила</label><input name="name" required placeholder="Например: Главная ссылка Пикабу"></div><div class="tag-picker"><label for="tag-search">Теги первого касания</label><div class="tag-combobox"><input id="tag-search" type="text" autocomplete="off" placeholder="Начните вводить название тега"><div class="tag-suggestions" id="tag-suggestions" hidden></div></div><div class="selected-tags" id="selected-tags"></div><small>Введите название и выберите подсказку. Новый тег создавайте только если подходящего действительно нет.</small><button type="button" class="back-link create-tag" id="create-tag" hidden>＋ Создать новый тег</button></div><button class="action">Создать правило и короткий код</button></form><div class="link-table">${filtered.map(row=>`<article class="rule-row"><div class="rule-main"><span class="eyebrow">${kind==='channel_invite'?'КАНАЛ':'БОТ'} · ${esc(row.status)}</span><h3>${esc(row.name)}</h3><div class="tag-chips">${row.tags.map(tag=>`<i>${esc(tag.name)}</i>`).join('') || '<small>без тегов</small>'}</div><small>${dateText(row.created_at)} · ${row.clicks} переходов · ${row.unique_starts} пользователей запустили бота</small></div><div class="alias-list">${row.aliases.map(alias=>`<div><code>${esc(alias.token)}</code><span>${esc(alias.kind)} · ${esc(alias.status)} · ${alias.clicks} / ${alias.starts}</span>${alias.direct_url?`<button class="copy" data-copy="${esc(alias.direct_url)}">t.me</button>`:''}${alias.go_url?`<button class="copy" data-copy="${esc(alias.go_url)}">go</button><button class="copy" data-copy="${esc(alias.warning_url)}">go + VPN</button>`:''}${kind==='channel_invite'&&!alias.direct_url?`<button class="action invite" data-alias="${alias.id}">Создать invite</button>`:''}</div>`).join('')}</div><form class="alias-form" data-rule="${row.id}"><input name="token" placeholder="Старый код или пусто для нового"><select name="alias_kind"><option value="legacy">Старый код</option><option value="short">Новый короткий</option></select><button class="action alt">Добавить адрес к этому правилу</button></form></article>`).join('') || '<div class="empty">Правил этого типа пока нет</div>'}</div>`;
    const form=panel.querySelector('#rule-form'),selectedTagIds=bindTagPicker(form);
    form.onsubmit=async event=>{event.preventDefault();const name=new FormData(event.target).get('name'),tag_ids=[...selectedTagIds];await api('/bot-api/link-rules',{method:'POST',body:JSON.stringify({name,target_kind:kind,tag_ids})});links();};
    panel.querySelectorAll('.alias-form').forEach(form=>form.onsubmit=async event=>{event.preventDefault();const values=Object.fromEntries(new FormData(form));if(!values.token)delete values.token;await api(`/bot-api/link-rules/${form.dataset.rule}/aliases`,{method:'POST',body:JSON.stringify(values)});links();});
    panel.querySelectorAll('.invite').forEach(button=>button.onclick=async()=>{await api(`/bot-api/link-aliases/${button.dataset.alias}/channel-invite`,{method:'POST'});links();});copyButtons();};
  const utm=()=>{panel.innerHTML=`<div class="help-card"><b>UTM не угадываются автоматически</b><span>Система сохраняет сырой параметр. Вы один раз связываете точное значение с существующим тегом CRM; только после этого такое же значение распознаётся автоматически.</span></div><form class="utm-reader" id="utm-reader"><input name="url" placeholder="Вставьте полный URL с UTM-метками" required><button class="action">Разобрать</button></form><div id="utm-result"></div><h2>Пришли, но ещё не разобраны</h2><div class="unresolved-list">${unresolved.map(group=>`<article class="card"><b>${Object.entries(group.parameters).map(([k,v])=>`${esc(k)}=${esc(v)}`).join(' · ')}</b><span class="meta">${group.count} событий · последнее ${dateText(group.last_seen_at)}</span></article>`).join('')||'<div class="empty">Неразобранных UTM пока нет</div>'}</div><button class="action alt" id="apply-utm">Предпросмотр применения правил к прошлым событиям</button>`;panel.querySelector('#utm-reader').onsubmit=async event=>{event.preventDefault();const parsed=await api('/bot-api/utm/parse',{method:'POST',body:JSON.stringify({url:new FormData(event.target).get('url')})});const host=panel.querySelector('#utm-result');host.innerHTML=parsed.parameters.map(item=>`<form class="utm-map" data-name="${esc(item.name)}" data-value="${esc(item.raw_value)}"><code>${esc(item.name)}=${esc(item.raw_value)}</code><select name="tag_id" required><option value="">Выберите существующий тег</option>${tags.map(tag=>`<option value="${esc(tag.id)}" ${item.mapping?.tag_id===tag.id?'selected':''}>${esc(tag.name)}</option>`).join('')}</select><button class="action">${item.mapping?'Изменить правило':'Сохранить правило'}</button></form>`).join('')||'<div class="empty">UTM-параметров в ссылке нет</div>';host.querySelectorAll('.utm-map').forEach(form=>form.onsubmit=async e=>{e.preventDefault();await api('/bot-api/utm/rules',{method:'POST',body:JSON.stringify({parameter_name:form.dataset.name,raw_value:form.dataset.value,tag_id:new FormData(form).get('tag_id')})});toast(form.querySelector('button'));});};panel.querySelector('#apply-utm').onclick=async event=>{const result=await api('/bot-api/utm/apply',{method:'POST',body:JSON.stringify({preview:true})});event.currentTarget.textContent=`Будут обновлены: события ${result.events}, ожидающие старты ${result.pending_sessions}`;};};
  const events=async()=>{const data=await api('/bot-api/tracking-events');panel.innerHTML=`<div class="help-card"><b>Хронология атрибуции</b><span>Здесь видны открытия go-ссылок, первый и повторный Start, неизвестные коды и входы через invite-ссылки канала. Переходы прямо по t.me до Start Telegram не сообщает — и они здесь не считаются.</span></div><div class="event-list">${data.map(row=>`<article><b>${esc(row.type)}</b><span>${dateText(row.occurred_at)}</span><code>${esc(row.telegram_user_id||row.user_id||'без пользователя')}</code></article>`).join('')||'<div class="empty">Событий пока нет</div>'}</div>`;};
  const draw=()=>tab==='bot'?catalog('bot_start'):tab==='channel'?catalog('channel_invite'):tab==='utm'?utm():events();document.querySelectorAll('[data-link-tab]').forEach(button=>button.onclick=()=>{tab=button.dataset.linkTab;document.querySelectorAll('[data-link-tab]').forEach(x=>x.classList.toggle('active',x===button));draw();});draw();
}

const views = {modules:()=>modulesView(), sequences, library, contacts, broadcasts, links};
async function show(view) { document.querySelectorAll('nav button').forEach(button => button.classList.toggle('active', button.dataset.view === view)); title.textContent = {modules:'Модули',sequences:'Цепочки',library:'Библиотека сообщений',contacts:'Пользователи и тестирование',broadcasts:'Разовые рассылки',links:'Ссылки и источники'}[view]; try { await views[view](); } catch (error) { fail(error); } }
document.querySelectorAll('nav button').forEach(button => button.onclick = () => show(button.dataset.view));
document.querySelector('#logout').onclick = async () => { await fetch('/bot-api/logout', {method:'POST'}); location.replace('/bot'); };
api('/health').then(value => document.querySelector('#health').textContent = value.status === 'ok' ? '● работает' : 'ошибка');
show('modules');
