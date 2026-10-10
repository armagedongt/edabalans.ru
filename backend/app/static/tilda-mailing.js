(function () {
  'use strict';
  const $ = id => document.getElementById(id);
  const names = {draft:'Готово к отправке',excluded:'Исключено',pending:'В очереди',retry:'Повтор доставки',sent:'Отправлено',failed:'Ошибка',superseded:'Данные входа изменились'};
  let selected = 0, current = null, recipientData = [];
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  async function api(path = '', options = {}) {
    const r = await fetch('/admin/api/tilda-mailing' + path, {credentials:'same-origin',cache:'no-store',...options,headers:{'Content-Type':'application/json'}});
    if(r.status === 401) { location.href = '/admin?next=/admin/tilda-mailing'; throw new Error('Войдите в админку'); }
    const body = await r.json();
    if(!r.ok) throw new Error(typeof body.detail === 'string' ? body.detail : 'Не удалось выполнить действие');
    return body;
  }
  function failure(e) { $('mailing-status').textContent = e.message; $('mailing-status').className = 'mailing-error'; }
  async function refresh() {
    const data = await api(); selected = data.selected; recipientData = data.recipients;
    $('mailing-status').className = data.blockers.length ? 'mailing-error' : '';
    $('mailing-status').textContent = `Получателей: ${data.recipients.length}. Выбрано: ${selected}. ` + data.blockers.join('; ');
    $('launch').disabled = !selected || data.blockers.length > 0;
    $('launch').textContent = `Отправить выбранные письма (${selected})`;
    $('recipients').innerHTML = data.recipients.map(r => `<button class="mailing-recipient" data-id="${esc(r.id)}" type="button">${esc(r.name)}<small>${esc(r.email)}</small><small>${esc(names[r.status] || r.status)}${r.error ? ' · '+esc(r.error) : ''}</small></button>`).join('') || 'Подготовленных писем пока нет.';
  }
  $('recipients').addEventListener('click', async e => {
    const button = e.target.closest('[data-id]'); if(!button) return;
    try {
      const data = await api('/'+button.dataset.id); current = data.id;
      $('editor').hidden = false; $('subject').value = data.subject; $('body').value = data.text;
      $('included').checked = data.included; $('save').disabled = !data.editable;
      $('subject').readOnly = !data.editable; $('body').readOnly = !data.editable; $('included').disabled = !data.editable;
      $('editor-title').textContent = recipientData.find(r => r.id === current)?.email || 'Письмо';
      $('editor-status').textContent = '';
      $('editor-title').scrollIntoView({behavior:'instant',block:'start'});
    } catch(e) { failure(e); }
  });
  $('letter-form').addEventListener('submit', async e => {
    e.preventDefault(); $('save').disabled = true;
    try { await api('/'+current,{method:'PUT',body:JSON.stringify({subject:$('subject').value,text:$('body').value,included:$('included').checked})}); $('editor-status').textContent = 'Сохранено. Письмо не отправлено.'; await refresh(); }
    catch(e) { failure(e); } finally { $('save').disabled = false; }
  });
  $('copy').addEventListener('click', async () => {
    try { await navigator.clipboard.writeText($('subject').value+'\n\n'+$('body').value); $('editor-status').textContent = 'Письмо скопировано'; } catch(e) { failure(e); }
  });
  $('refresh').addEventListener('click', () => refresh().catch(failure));
  $('launch').addEventListener('click', async () => {
    if(!confirm(`Отправить ${selected} подготовленных писем на почту? Это запустит рассылку.`)) return;
    $('launch').disabled = true;
    try { const result = await api('/launch',{method:'POST',body:JSON.stringify({expected_count:selected,confirm_send:true})}); await refresh(); $('mailing-status').textContent = `В очередь поставлено ${result.queued} писем. Статусы обновляются кнопкой «Обновить статусы».`; $('editor').hidden = true; current = null; }
    catch(e) { failure(e); await refresh().catch(failure); }
  });
  refresh().catch(failure);
}());
