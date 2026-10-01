(function () {
  'use strict';
  const DAY = 86400000;
  function eligible(identity, subscription, fromTelegram = false) {
    return !fromTelegram && !(identity === true && subscription === 'subscribed');
  }
  function due(last, now) {
    return last === null || (Number.isFinite(last) && now - last >= DAY);
  }
  function parseLastShown(value) {
    if (value === null) return null;
    return /^\d+$/.test(value) && Number.isSafeInteger(Number(value)) ? Number(value) : NaN;
  }
  function readingProgress(start, end, edge, exclusions) {
    const clamp = (value, max) => Math.max(0, Math.min(value, max));
    let total = end - start;
    let reached = clamp(edge - start, total);
    exclusions.forEach(box => {
      total -= box.height;
      reached -= clamp(edge - box.top, box.height);
    });
    return total > 0 ? clamp(reached, total) / total : 0;
  }
  if (typeof module !== 'undefined') { module.exports = {eligible, due, parseLastShown, readingProgress}; return; }
  const select = document.getElementById('reader-visitor');
  const inline = document.getElementById('reader-channel-inline');
  const popup = document.getElementById('reader-popup');
  const sheet = document.getElementById('reader-sheet');
  const menu = document.getElementById('reader-menu');
  const show = document.getElementById('reader-show-popup');
  const origin = document.getElementById('reader-origin-telegram');
  const sourcePlaque = document.getElementById('reader-telegram-source');
  let state = 'unknown';
  let clicked = false;
  let shownThisPage = false;
  // Preview-specific persistence cannot affect the production blog.
  const key = 'edabalans-reader-preview-popup-at';
  function permitted() { return eligible(state !== 'unknown', state === 'unsubscribed' ? 'not_subscribed' : state, origin.checked); }
  function lastShown() {
    try { return parseLastShown(localStorage.getItem(key)); }
    catch (_) { return NaN; }
  }
  function contentsOpen() {
    const oldMobile = document.querySelector('.toc-mobile');
    const oldDesktop = document.querySelector('.toc-popover');
    return sheet.open || !!(oldMobile && oldMobile.open) || !!(oldDesktop && !oldDesktop.hidden);
  }
  function openPopup(manual) {
    if (!permitted() || clicked || contentsOpen()) return;
    if (!manual && (shownThisPage || !due(lastShown(), Date.now()))) return;
    if (!popup.open) popup.showModal();
    shownThisPage = true;
    if (!manual) { try { localStorage.setItem(key, String(Date.now())); } catch (_) {} }
  }
  function updatePresentation() {
    state = select.value;
    inline.hidden = !permitted();
    sourcePlaque.hidden = !origin.checked;
    popup.close();
    show.disabled = !permitted();
  }
  select.addEventListener('change', updatePresentation);
  origin.addEventListener('change', updatePresentation);
  show.addEventListener('click', () => openPopup(true));
  popup.querySelector('button').addEventListener('click', () => popup.close());
  function suppressAfterClick(event) {
    if (event.target.closest('a')) { clicked = true; popup.close(); show.disabled = true; }
  }
  popup.addEventListener('click', suppressAfterClick);
  inline.addEventListener('click', suppressAfterClick);
  document.addEventListener('keydown', event => { if (event.key === 'Escape') popup.close(); });
  document.addEventListener('click', event => { if (event.target.closest('.toc-mobile, .toc-dock')) popup.close(); });
  document.addEventListener('mouseover', event => { if (event.target.closest('.toc-dock')) popup.close(); });
  menu.addEventListener('click', () => { popup.close(); sheet.showModal(); });
  sheet.querySelector('.reader-close').addEventListener('click', () => sheet.close());
  sheet.addEventListener('close', () => menu.focus());
  sheet.addEventListener('click', event => { if (event.target.closest('a')) sheet.close(); });
  document.getElementById('reader-top').addEventListener('click', () => window.scrollTo({top:0, behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth'}));
  const links = Array.from(document.querySelectorAll('.reader-sidebar a, #reader-sheet ol a'));
  const headings = Array.from(document.querySelectorAll('#article > h2'));
  function onScroll() {
    document.querySelector('.reader-bottom').classList.toggle('reader-scrolled', window.scrollY > 300);
    if (contentsOpen()) popup.close();
    let current = headings[0];
    headings.forEach(h => { if (h.getBoundingClientRect().top <= 150) current = h; });
    links.forEach(a => {
      if (current && a.getAttribute('href') === '#' + current.id) a.setAttribute('aria-current', 'location');
      else a.removeAttribute('aria-current');
    });
    // Only the article body, not related cards or footer, participates in this demo threshold.
    const article = document.getElementById('article');
    const start = article.getBoundingClientRect().top + window.scrollY;
    const end = article.querySelector('.blog-cta-intensive').getBoundingClientRect().top + window.scrollY;
    const exclusions = Array.from(article.querySelectorAll('.reader-related, #reader-channel-inline')).filter(el => !el.hidden).map(el => {
      const rect = el.getBoundingClientRect();
      const css = getComputedStyle(el);
      const before = parseFloat(css.marginTop) || 0;
      const after = parseFloat(css.marginBottom) || 0;
      return {top: rect.top + window.scrollY - before, height: rect.height + before + after};
    });
    const progress = readingProgress(start, end, window.scrollY + window.innerHeight, exclusions);
    if (document.visibilityState === 'visible' && progress >= .5) openPopup(false);
  }
  window.addEventListener('scroll', onScroll, {passive:true});
  onScroll();
}());
