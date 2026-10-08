(function () {
  'use strict';
  function esc(value) { return String(value || '').replace(/[&<>"']/g, function (c) { return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]; }); }
  function money(value) { return Number(value).toLocaleString('ru-RU') + ' ₽'; }
  window.EdabalansLegacyOffer = function (root, data, host) {
    if (data.state !== 'ready' || !data.legacy_portal || !data.legacy_portal.available) return;
    var holder = root.querySelector('[data-legacy-offer]');
    if (!holder) return;
    var timer;
    function request(path, body) {
      return fetch(host + path, {method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify(body || {})}).then(function (response) {
        return response.json().then(function (payload) { if (!response.ok) throw Error(typeof payload.detail === 'string' ? payload.detail : 'Не удалось обновить предложение'); return payload; });
      });
    }
    function load() {
      if (!holder.isConnected) return;
      return request('/api/account/legacy-offer/show').then(render).catch(function () { holder.hidden = true; });
    }
    function render(payload) {
      if (!holder.isConnected) return;
      clearInterval(timer);
      if (!payload.available) { holder.hidden = true; return; }
      var card = payload.offers[0], discount = payload.stage !== 'standard', offset = Date.parse(payload.server_now) - Date.now();
      holder.hidden = false;
      holder.className = 'legacy-upgrade account-card' + (payload.stage === 'first' ? ' legacy-upgrade-first' : '');
      holder.innerHTML = '<h2>Получите полный обновляемый пакет</h2><div class="legacy-upgrade-columns"><div><h3>У вас сейчас</h3><ul>' + payload.current.map(function (item) { return '<li>✓ <strong class="legacy-upgrade-product">' + esc(item.name) + '</strong>' + (item.edition === 'non_updating' ? ' — необновляемый доступ' : ' — обновляемый доступ') + '</li>'; }).join('') + '</ul></div><div><h3>После перехода</h3><ul>' + card.details.map(function (item) { return '<li>✓ <strong class="legacy-upgrade-product">' + esc(item.name) + '</strong>' + ' — обновляемый доступ</li>'; }).join('') + '<li>✓ Приложения внутри программ (DQS, калькулятор метаболизма и калькулятор рецептов)</li><li>✓ Новые материалы и дальнейшие обновления</li></ul></div></div><p class="legacy-upgrade-price">' + '<strong>Всего за ' + money(card.price) + '</strong>' + (discount ? ' <span>(обычная цена — <s>' + money(card.regular_price) + '</s>)</span>' : '') + '</p>' + (payload.stage === 'first' ? '<p><strong>Самая низкая цена — первые 10 минут.</strong><br>Предложение за ' + money(card.price) + ' действительно 10 минут.</p>' : '') + '<p data-legacy-countdown></p><p>Приложения открываются по мере прохождения соответствующих материалов. Доступные вам материалы можно продолжать изучать.</p><label class="legacy-upgrade-consent"><input type="checkbox" data-legacy-consent> <span>Принимаю <a href="https://похудение-это-есть.рф/legal/offer" target="_blank" rel="noopener">публичную оферту</a> и даю <a href="https://похудение-это-есть.рф/legal/consent" target="_blank" rel="noopener">согласие на обработку персональных данных</a>.</span></label><button class="account-open purchase" data-legacy-buy disabled>Получить полный пакет за ' + money(card.price) + '</button><p data-legacy-status role="status"></p>';
      var button = holder.querySelector('[data-legacy-buy]'), consent = holder.querySelector('[data-legacy-consent]'), status = holder.querySelector('[data-legacy-status]');
      consent.onchange = function () { button.disabled = !consent.checked; };
      button.onclick = function () {
        if (!consent.checked || button.disabled) return;
        button.disabled = true; status.textContent = 'Готовлю оплату…';
        request('/api/payments/robokassa/account-offers/checkout', {offer_code:card.code,expected_price:card.price}).then(function (result) {
          // A timer boundary may change the server price: show it before charging.
          if (Number(result.amount) !== Number(card.price)) { status.textContent = 'Цена изменилась. Проверьте новое предложение.'; load(); return; }
          var form = document.createElement('form'); form.method = result.payment_form.method || 'POST'; form.action = result.payment_form.action;
          Object.keys(result.payment_form.fields).forEach(function (name) { var input = document.createElement('input'); input.type='hidden'; input.name=name; input.value=String(result.payment_form.fields[name]); form.appendChild(input); });
          document.body.appendChild(form); form.submit();
        }).catch(function (error) { status.textContent = error.message; button.disabled = !consent.checked; if (error.message.indexOf('Цена изменилась') >= 0) load(); });
      };
      function tick() {
        if (!holder.isConnected) { clearInterval(timer); return; }
        if (!payload.expires_at) return;
        var seconds = Math.max(0, Math.ceil((Date.parse(payload.expires_at) - Date.now() - offset) / 1000));
        holder.querySelector('[data-legacy-countdown]').textContent = 'До изменения цены: ' + Math.floor(seconds / 3600) + ' ч ' + Math.floor(seconds % 3600 / 60) + ' мин ' + seconds % 60 + ' сек';
        if (!seconds) { clearInterval(timer); button.disabled=true; load(); }
      }
      tick(); if (payload.expires_at) timer = setInterval(tick, 1000);
    }
    load();
  };
}());
