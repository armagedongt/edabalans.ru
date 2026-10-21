(async function () {
  'use strict';
  const app = window.WebApp;
  const root = document.getElementById('max-app-root');
  let target = 'https://max.ru/id230409966750_biz';
  let button;
  function record() {
    if (!app || !app.initData) return;
    fetch('/apps/channel-bridge/max/event', {method: 'POST', keepalive: true,
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({init_data: app.initData, event: 'channel_open_requested'})}).catch(() => {});
  }
  function open(event) {
    if (!app || !app.initData || typeof app.openMaxLink !== 'function') return;
    event?.preventDefault();
    try { app.openMaxLink(target); record(); } catch (_) { /* Keep the normal link available. */ }
  }
  try {
    const card = await fetch('/apps/channel-bridge/card', {cache: 'no-store'});
    if (!card.ok) throw new Error('Card unavailable');
    const doc = new DOMParser().parseFromString(await card.text(), 'text/html');
    document.head.appendChild(doc.querySelector('style'));
    root.replaceWith(doc.querySelector('main'));
    button = document.getElementById('open-post');
    button.href = target;
    button.addEventListener('click', open);
    if (!app || !app.initData) return;
    app.ready?.();
    const response = await fetch('/apps/channel-bridge/max/verify', {method: 'POST',
      headers: {'Content-Type': 'application/json'}, body: JSON.stringify({init_data: app.initData})});
    if (!response.ok) throw new Error('Verification unavailable');
    const data = await response.json();
    if (!/^https:\/\/max\.ru\/id230409966750_biz(?:\/[1-9][0-9]*)?$/.test(data.destination)) throw new Error('Invalid destination');
    target = data.destination;
    button.href = target;
    open();
  } catch (_) {
    if (button) document.getElementById('status').textContent = 'Если канал не открылся, нажмите «Открыть канал».';
    else { root.textContent = ''; const link = document.createElement('a'); link.href = target; link.textContent = 'Открыть канал'; root.appendChild(link); }
  }
}());
