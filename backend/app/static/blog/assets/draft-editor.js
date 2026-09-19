(function () {
  'use strict';
  var match = location.pathname.match(/\/blog\/drafts\/([^/]+)\/edit$/);
  var slug = match ? decodeURIComponent(match[1]) : '';
  var state = null;
  var dirty = false;
  var source = document.querySelector('#draft-markdown');
  var status = document.querySelector('#draft-status');
  var save = document.querySelector('#draft-save');
  var error = document.querySelector('#draft-error');
  var notice = document.querySelector('#draft-notice');

  function endpoint(suffix) { return '/admin/api/blog/articles/' + encodeURIComponent(slug) + (suffix || ''); }
  function request(value, method) {
    return fetch(endpoint(value.path), {
      method: method || 'GET',
      headers: value.body ? { 'Content-Type': 'application/json' } : undefined,
      body: value.body ? JSON.stringify(value.body) : undefined
    }).then(function (response) {
      return response.json().catch(function () { return { detail: 'Ошибка сервера' }; }).then(function (payload) {
        if (!response.ok) throw Object.assign(Error(typeof payload.detail === 'string' ? payload.detail : 'Не удалось выполнить запрос'), { status: response.status });
        return payload;
      });
    });
  }
  function clearMessages() { error.hidden = true; notice.hidden = true; }
  function showError(value) { error.hidden = false; error.textContent = value && value.message || String(value); }
  function setDirty(value) {
    dirty = value;
    save.disabled = !state || !dirty;
    status.textContent = dirty ? 'Есть несохранённые изменения' : state ? 'Версия ' + state.version + ' сохранена' : 'Загрузка…';
  }
  function showMeta(article) {
    document.querySelector('#draft-title').textContent = article.title;
    document.querySelector('#draft-meta').textContent = (article.visibility === 'internal' ? 'Служебная' : 'Публичная') + ' · На модерации · версия ' + article.version;
    document.querySelector('#open-preview').href = '/blog/drafts/' + encodeURIComponent(slug);
  }
  function preview(preserveNotice) {
    if (preserveNotice) error.hidden = true;
    else clearMessages();
    status.textContent = 'Собираю предпросмотр…';
    return request({ path: '/preview', body: { markdown: source.value } }, 'POST').then(function (result) {
      document.querySelector('#article').innerHTML = result.html;
      status.textContent = dirty ? 'Есть несохранённые изменения' : 'Версия ' + state.version + ' сохранена';
      return result;
    }).catch(function (value) {
      showError(value);
      status.textContent = dirty ? 'Изменения не сохранены' : 'Предпросмотр не собран';
      throw value;
    });
  }
  function load() {
    clearMessages();
    return request({ path: '' }).then(function (result) {
      state = result.article;
      source.value = state.markdown;
      showMeta(state);
      setDirty(false);
      return preview();
    }).catch(showError);
  }
  function saveText() {
    if (!state || !dirty) return;
    clearMessages();
    status.textContent = 'Сохраняю…';
    var submitted = source.value;
    request({ path: '/text', body: { expected_version: state.version, markdown: submitted } }, 'PATCH').then(function (result) {
      state = result.article;
      showMeta(state);
      if (source.value === submitted) setDirty(false);
      else setDirty(true);
      notice.hidden = false;
      notice.textContent = 'Редакция сохранена на модерации. Публичный блог не изменился.';
      preview(true).catch(function () {});
    }).catch(function (value) {
      showError(value);
      setDirty(true);
      status.textContent = value && value.status === 409 ? 'Конфликт версий — текст сохранён в поле' : 'Не удалось сохранить — текст остался в поле';
    });
  }

  source.addEventListener('input', function () { setDirty(true); });
  document.querySelector('#draft-preview').addEventListener('click', function () {
    preview().then(function () {
      notice.hidden = false;
      notice.textContent = dirty
        ? 'Предпросмотр обновлён. Изменения пока не сохранены.'
        : 'Предпросмотр обновлён по сохранённой версии.';
    }).catch(function () {});
  });
  save.addEventListener('click', saveText);
  window.addEventListener('beforeunload', function (event) { if (dirty) { event.preventDefault(); event.returnValue = ''; } });
  load();
}());
