(function () {
  'use strict';

  const target = JSON.parse(document.getElementById('destination').textContent);
  const status = document.getElementById('status');
  const button = document.getElementById('open-post');
  const app = window.Telegram && window.Telegram.WebApp;
  let navigationRequested = false;
  button.href = target;

  function openPost(event) {
    if (!app || !app.initData || typeof app.openTelegramLink !== 'function') return;
    if (event) event.preventDefault();
    try {
      // Android guards SDK link commands without a recent in-app tap. Its
      // WebView handles ordinary t.me navigation through the native client.
      if (!event && (app.platform === 'android' || app.platform === 'android_x')) {
        window.location.replace(target);
      } else {
        app.openTelegramLink(target);
      }
    } catch (_) {
      status.textContent = 'Если канал не открылся, нажмите «Открыть канал».';
      // Keep a normal link when this client cannot handle the SDK command.
      button.removeEventListener('click', openPost);
      return;
    }
    navigationRequested = true;
    // Desktop was verified by the owner. On mobile, let Telegram finish the
    // navigation; an immediate close can discard it or hide the fallback card.
    if (app.platform === 'tdesktop' || app.platform === 'macos') {
      try { app.close(); } catch (_) { /* Keep the channel link usable. */ }
    }
  }

  button.addEventListener('click', openPost);
  if (!app || !app.initData) {
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
    if (!navigationRequested) openPost();
  }).catch(function () {
    if (!navigationRequested) status.textContent = 'Если канал не открылся, нажмите «Открыть канал».';
  }).finally(function () { clearTimeout(timer); });
}());
