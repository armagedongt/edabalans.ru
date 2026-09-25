(function () {
  'use strict';
  if (window.EdabalansProductPopup) return;
  var products = {masterclass: 'program', calories: 'calories', training: 'training', recipes: 'recipes', consultation: 'consultation'};
  var dialog, opener;
  function request(path) {
    return fetch((window.EdabalansAppHost || '') + path, {credentials: 'same-origin'}).then(function (response) {
      if (!response.ok) throw new Error('Не удалось загрузить описание курса. Попробуйте ещё раз.');
      return response.json();
    });
  }
  function close() { if (dialog && dialog.open) dialog.close(); }
  function mountApp(code, offer) {
    close();
    // A normal navigation disposes the previous course and its timers/listeners.
    var path = offer ? '/lk?buy=' + encodeURIComponent(code) :
      code === 'masterclass-course' ? '/lk?course_day=1' :
      code === 'calories-course' ? '/lk?calories_stage=1' : '/' + encodeURIComponent(code);
    location.assign(path);
  }
  function show(code) {
    if (!products[code]) return Promise.resolve();
    if (!dialog) {
      dialog = document.createElement('dialog');
      dialog.className = 'edb-product-popup';
      dialog.setAttribute('aria-labelledby', 'edb-product-popup-title');
      document.body.appendChild(dialog);
      dialog.addEventListener('close', function () { if (opener && opener.isConnected) opener.focus(); });
      dialog.addEventListener('click', function (event) { if (event.target === dialog) close(); });
    }
    opener = document.activeElement;
    dialog.innerHTML = '<header><h2 id="edb-product-popup-title">Описание курса</h2><button type="button" aria-label="Закрыть">×</button></header><div class="edb-product-popup-body"><p role="status">Загрузка…</p></div><footer><span class="edb-product-popup-state" role="status"></span><div><button data-product-open disabled>Открыть курс</button><button data-product-buy disabled>Купить курс</button></div></footer>';
    dialog.querySelector('header button').onclick = close;
    dialog.dataset.product = code;
    if (!dialog.open) dialog.showModal();
    return Promise.all([request('/api/public-site/content/' + products[code]), request('/api/account-auth/account')]).then(function (results) {
      if (!dialog.open || dialog.dataset.product !== code) return;
      var presentation = results[0], account = results[1];
      var course = (account.courses || []).find(function (item) { return item.product_code === code; });
      dialog.querySelector('h2').textContent = course ? course.title : presentation.title;
      var body = dialog.querySelector('.edb-product-popup-body');
      body.innerHTML = presentation.html;
      if (window.EdabalansProgramCard) window.EdabalansProgramCard.enhance(body, products[code]);
      var status = dialog.querySelector('.edb-product-popup-state');
      if (!course || !course.ready) { status.textContent = course && course.maintenance ? 'На ремонте' : 'Скоро'; return; }
      if (account.state !== 'ready' || (account.legal && account.legal.required)) { status.textContent = 'Завершите настройку личного кабинета'; return; }
      if (course.owned) {
        var open = dialog.querySelector('[data-product-open]');
        open.disabled = !course.app;
        if (!course.app) status.textContent = 'Курс откроется после завершения Мастер-класса';
        open.onclick = function () { mountApp(course.app, false); };
        return;
      }
      return request('/api/masterclass/account-offers?email=' + encodeURIComponent(account.email || '')).then(function (offers) {
        if (!dialog.open || dialog.dataset.product !== code) return;
        var buy = dialog.querySelector('[data-product-buy]');
        buy.disabled = (offers.focusable_product_codes || []).indexOf(code) < 0;
        buy.onclick = function () { mountApp(code, true); };
      });
    }).catch(function (error) {
      if (dialog.open && dialog.dataset.product === code) dialog.querySelector('.edb-product-popup-state').textContent = error.message;
    });
  }
  document.addEventListener('click', function (event) {
    var link = event.target.closest('a[href]');
    if (!link || event.defaultPrevented || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || event.button !== 0) return;
    var url = new URL(link.href, location.href), code = url.searchParams.get('product');
    if (url.pathname !== '/lk' || !products[code] || [location.hostname, 'edabalans.ru', 'app.edabalans.ru'].indexOf(url.hostname) < 0) return;
    event.preventDefault(); show(code);
  });
  window.EdabalansProductPopup = {show: show};
}());
