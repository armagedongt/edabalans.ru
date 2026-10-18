(function () {
  'use strict';
  const DAY = 86400000;
  function due(last, now) { return last === null || (Number.isFinite(last) && now - last >= DAY); }
  function progress(start, end, edge, exclusions) {
    const clamp = (value, max) => Math.max(0, Math.min(value, max));
    let total = end - start, reached = clamp(edge - start, total);
    exclusions.forEach(box => { total -= box.height; reached -= clamp(edge - box.top, box.height); });
    return total > 0 ? clamp(reached, total) / total : 0;
  }
  function cookieDomain(host) {
    return ['edabalans.ru','xn-----jlceacr3bggd8ajed5a6kl.xn--p1ai'].find(root => host === root || host.endsWith('.'+root));
  }
  function subscriptionAnchor(article) {
    const id = article.dataset.subscriptionBeforeHeading;
    if (!id) return undefined;
    return Array.from(article.querySelectorAll(':scope > h2')).find(node => node.id === id);
  }
  function messengerDestination(value, host) {
    if (typeof value !== 'string') return null;
    try {
      const url = new URL(value);
      return url.protocol === 'https:' && url.host === host && !url.username && !url.password && url.pathname !== '/' ? url.href : null;
    } catch (_) { return null; }
  }
  if (typeof module !== 'undefined') { module.exports = {due,progress,cookieDomain,subscriptionAnchor,messengerDestination}; return; }
  const popup = document.getElementById('reader-popup'), article = document.getElementById('article');
  const homepage = document.getElementById('reader-channel-homepage');
  if (!homepage && (!popup || !article || typeof popup.showModal !== 'function')) return;
  if (homepage) {
    const source = new URLSearchParams(location.search).get('from');
    const channelEntry = source === 'tg' || source === 'max';
    fetch('/blog/reader/context'+(channelEntry ? '?from='+source : ''),{credentials:'same-origin',cache:'no-store'})
      .then(response => { if (!response.ok) throw new Error('reader context unavailable'); return response.json(); })
      .catch(() => ({show_subscription:!channelEntry}))
      .then(context => {
        if (context.show_subscription === false) return;
        if (typeof context.copy_html === 'string') homepage.querySelector('.reader-channel-copy').innerHTML = context.copy_html;
        const telegram = messengerDestination(context.telegram && context.telegram.url, 't.me');
        const max = messengerDestination(context.max && context.max.url, 'max.ru');
        if (telegram) homepage.querySelector('.reader-bot-telegram').href = telegram;
        if (max) homepage.querySelector('.reader-bot-max').href = max;
        homepage.hidden = false;
        const section = homepage.closest('[data-homepage-block="free-intensive"]');
        if (section) section.hidden = false;
      });
    return;
  }
  // Provenance takes precedence even if a stale client context says otherwise.
  if (article.querySelector('[data-channel-origin="telegram"]')) { popup.remove(); return; }
  const key = 'edabalans_subscription_popup_at';
  let allowed = false, shown = false, clicked = false;
  let inline = null, returnFocus = null;
  function lastShown() {
    const item = document.cookie.split('; ').find(value => value.startsWith(key+'='));
    if (!item) return null;
    const value = item.slice(key.length+1);
    return /^\d+$/.test(value) && Number.isSafeInteger(Number(value)) ? Number(value) : NaN;
  }
  function persistShown(now) {
    const domain = cookieDomain(location.hostname);
    document.cookie = key+'='+now+'; Path=/; Max-Age=86400; SameSite=Lax'+
      (location.protocol === 'https:' ? '; Secure' : '')+(domain ? '; Domain='+domain : '');
    // If storage is disabled, do not promise a once-per-day interval we cannot keep.
    return lastShown() === now;
  }
  function contentsOpen() {
    return document.querySelector('#reader-sheet[open], .toc-mobile[open], .toc-popover:not([hidden])');
  }
  function readingProgress() {
    const rect = article.getBoundingClientRect();
    const start = rect.top+scrollY, end = rect.bottom+scrollY;
    const boxes = Array.from(article.querySelectorAll('.blog-cta, .reader-related, .reader-telegram-source')).filter(node => !node.hidden);
    const exclusions = boxes.map(node => {
      const r = node.getBoundingClientRect(), css = getComputedStyle(node);
      const before = parseFloat(css.marginTop)||0, after = parseFloat(css.marginBottom)||0;
      return {top:r.top+scrollY-before,height:r.height+before+after};
    });
    return progress(start,end,scrollY+innerHeight,exclusions);
  }
  function onScroll() {
    if (!allowed || shown || clicked || document.visibilityState !== 'visible' || contentsOpen()) return;
    if (readingProgress()<.5 || !due(lastShown(),Date.now())) return;
    const now = Date.now();
    if (!persistShown(now)) return;
    returnFocus = document.activeElement;
    popup.showModal();
    shown = true;
  }
  popup.querySelector('.reader-close').addEventListener('click', () => popup.close());
  popup.addEventListener('close', () => { if (returnFocus && returnFocus.isConnected) returnFocus.focus({preventScroll:true}); });
  function stopAfterClick(event) { if (event.target.closest('a')) { clicked = true; popup.close(); } }
  popup.addEventListener('click',stopAfterClick);
  document.addEventListener('click',event => { if (event.target.closest('#reader-menu, .toc-mobile, .toc-dock')) popup.close(); });
  // Real context only. No demo selector, account login or guessed identity.
  const source = new URLSearchParams(location.search).get('from');
  const channelEntry = source === 'tg' || source === 'max';
  fetch('/blog/reader/context'+(channelEntry ? '?from='+source : ''),{credentials:'same-origin',cache:'no-store'})
    .then(response => { if (!response.ok) throw new Error('reader context unavailable'); return response.json(); })
    .catch(() => ({show_subscription:!channelEntry}))
    .then(context => {
      allowed = context.show_subscription !== false;
      if (!allowed) return;
      if (typeof context.copy_html === 'string') popup.querySelector('.reader-channel-copy').innerHTML = context.copy_html;
      const telegram = messengerDestination(context.telegram && context.telegram.url, 't.me');
      const max = messengerDestination(context.max && context.max.url, 'max.ru');
      if (telegram) popup.querySelector('.reader-bot-telegram').href = telegram;
      if (max) popup.querySelector('.reader-bot-max').href = max;
      // An absent or edited heading disables the curated slot; never guess a new placement.
      const anchor = subscriptionAnchor(article);
      if (anchor) {
        inline = popup.querySelector('.reader-channel').cloneNode(true);
        inline.id = 'reader-channel-inline';
        anchor.before(inline);
        inline.addEventListener('click',stopAfterClick);
      }
      window.addEventListener('scroll',onScroll,{passive:true});
      document.addEventListener('visibilitychange',onScroll);
      onScroll();
    });
}());
