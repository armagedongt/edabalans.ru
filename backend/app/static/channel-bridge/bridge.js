(function () {
  'use strict';

  const target = JSON.parse(document.getElementById('destination').textContent);
  const status = document.getElementById('status');
  const button = document.getElementById('open-post');
  const app = window.Telegram && window.Telegram.WebApp;
  let opened = false;
  button.href = target;

  function openPost(event) {
    if (!app || !app.initData || typeof app.openTelegramLink !== 'function') return;
    if (event) event.preventDefault();
    if (opened) return;
    try {
      app.openTelegramLink(target);
    } catch (_) {
      status.textContent = 'Нажмите кнопку, чтобы открыть закреп.';
      // Keep a normal link when this client cannot handle the SDK command.
      button.removeEventListener('click', openPost);
      return;
    }
    opened = true;
    // Since Bot API 7.0 openTelegramLink leaves the Mini App alive. Explicitly
    // close it after submitting the navigation command so no panel remains.
    try { app.close(); } catch (_) { /* The post navigation already succeeded. */ }
  }

  button.addEventListener('click', openPost);
  if (!app || !app.initData) {
    status.textContent = 'Откройте закреп канала по кнопке ниже.';
    return;
  }
  app.ready();

  const controller = new AbortController();
  const timer = setTimeout(function () { controller.abort(); }, 3000);
  fetch('/apps/channel-bridge/verify', {
    method: 'POST',
    credentials: 'omit',
    cache: 'no-store',
    referrerPolicy: 'no-referrer',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ init_data: app.initData }),
    signal: controller.signal
  }).then(function (response) {
    if (!response.ok) throw new Error('Verification unavailable');
    return response.json();
  }).then(function (data) {
    if (data.destination !== target) throw new Error('Unexpected destination');
    if (!opened) openPost();
  }).catch(function () {
    if (!opened) status.textContent = 'Нажмите кнопку, чтобы открыть закреп.';
  }).finally(function () { clearTimeout(timer); });
}());
