(function () {
  'use strict';
  if (window.EdabalansBrowserJourney || window.top !== window) return;
  const script = document.currentScript;
  const apiHost = script && script.src ? new URL(script.src).origin : location.origin;
  const roots = ['edabalans.ru', 'xn-----jlceacr3bggd8ajed5a6kl.xn--p1ai',
    'xn--d1acalydg7ar.xn--p1ai'];
  const allowed = host => roots.some(root => host === root || host.endsWith('.' + root));
  if (!allowed(location.hostname) || /^(?:\/(?:admin|crm|api|auth|health|ready|weather))(?:\/|$)/.test(location.pathname)) return;
  const query = new URLSearchParams(location.search);
  const incoming = query.get('visitor_transfer') || '';
  const source = query.get('source_context') || window.EdabalansCheckoutSourceContext || '';
  const personal = query.get('i') || query.get('token') || '';
  const readCookie = name => {
    const found = document.cookie.split(';').map(item => item.trim()).find(item => item.startsWith(name + '='));
    return found ? found.slice(name.length + 1) : '';
  };
  let context = readCookie('edabalans_visitor');
  let transfer = '';
  let initialized = false;
  let pageSent = false;
  const accepted = () => readCookie('edabalans_cookie_notice') === 'accepted-v1' ||
    Boolean(window.EdabalansCookieNotice && window.EdabalansCookieNotice.accepted());
  const attribution = {};
  ['utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term', 'yclid', 'alias'].forEach(key => {
    if (query.get(key)) attribution[key] = query.get(key).slice(0, 512);
  });
  function remember(value) {
    context = value;
    const root = roots.find(item => location.hostname === item || location.hostname.endsWith('.' + item));
    document.cookie = 'edabalans_visitor=' + value + '; Max-Age=31536000; Path=/; SameSite=Lax' +
      (root ? '; Domain=' + root : '') + (location.protocol === 'https:' ? '; Secure' : '');
  }
  let queue = Promise.resolve();
  function send(event, action) {
    const next = queue.then(() => perform(event, action));
    queue = next.catch(() => {});
    return next;
  }
  async function perform(event, action) {
    const abort = new AbortController();
    const timeout = setTimeout(() => abort.abort(), 1500);
    try {
      const response = await fetch(apiHost + '/api/public/browser-journey', {
        method: 'POST', credentials: 'omit', cache: 'no-store', signal: abort.signal,
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({context, transfer: initialized ? '' : incoming, source_context: initialized ? '' : source,
          personal_token: initialized ? '' : personal, event, accepted: accepted(), page_url: location.origin + location.pathname,
          attribution, action: action || null})
      });
      if (!response.ok) return;
      const result = await response.json();
      remember(result.context);
      transfer = result.transfer;
      initialized = true;
      if (incoming) {
        const clean = new URL(location.href);
        clean.searchParams.delete('visitor_transfer');
        history.replaceState(history.state, '', clean);
      }
      return true;
    } catch (_error) {} finally { clearTimeout(timeout); }
  }
  async function page() {
    if (pageSent || !accepted()) return;
    pageSent = Boolean(await send('page'));
  }
  const ready = send('init').then(page);
  function decorate(value) {
    const target = new URL(value, location.href);
    if (transfer && target.protocol === 'https:' && allowed(target.hostname)) {
      target.searchParams.set('visitor_transfer', transfer);
      if (target.hostname.startsWith('go.') || /^\/(go|r)\//.test(target.pathname)) target.searchParams.set('browser_context', context);
    }
    return target.href;
  }
  window.EdabalansBrowserJourney = Object.freeze({ready, context: () => context, transfer: () => transfer, decorate});
  document.addEventListener('edabalans:cookie-accepted', () => { ready.then(page); });
  document.addEventListener('click', event => {
    const anchor = event.target.closest && event.target.closest('a[href]');
    if (!anchor) return;
    let target;
    try { target = new URL(anchor.href, location.href); } catch (_error) { return; }
    if (transfer && target.protocol === 'https:' && allowed(target.hostname)) {
      anchor.href = decorate(target.href);
    }
    if (accepted()) void send('action', 'link:' + target.hostname + target.pathname.slice(0, 50));
  }, true);
  setInterval(() => { void send('init'); }, 5 * 60 * 1000);
})();
