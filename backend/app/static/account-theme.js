(function () {
  'use strict';
  if (window.EdabalansAccountTheme) return;
  window.EdabalansAccountTheme = true;
  var key = 'edabalans-account-theme-v1';
  var selected = new URL(location.href).searchParams.get('theme');
  if (selected !== 'dark' && selected !== 'light') {
    try { selected = localStorage.getItem(key); } catch (_) {}
  }
  document.documentElement.dataset.accountTheme = selected === 'dark' ? 'dark' : 'light';

  var moon = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 15.2A8.5 8.5 0 0 1 8.8 4a8.5 8.5 0 1 0 11.2 11.2Z"/></svg>';
  var sun = '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5"/></svg>';
  var button = document.createElement('button');
  button.type = 'button';
  button.className = 'account-theme-toggle';
  function update() {
    var dark = document.documentElement.dataset.accountTheme === 'dark';
    button.innerHTML = dark ? sun : moon;
    button.setAttribute('aria-label', dark ? 'Включить светлую тему' : 'Включить тёмную тему');
    button.setAttribute('aria-pressed', String(dark));
    button.title = button.getAttribute('aria-label');
  }
  button.onclick = function () {
    var next = document.documentElement.dataset.accountTheme === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.accountTheme = next;
    try { localStorage.setItem(key, next); } catch (_) {}
    // The URL selects the initial theme; a user's click takes precedence.
    var url = new URL(location.href);
    url.searchParams.delete('theme');
    history.replaceState(history.state, '', url);
    update();
  };
  var mobile = matchMedia('(max-width: 900px)');
  function place() {
    var course = document.querySelector(':is(#masterclass-course-app,#calories-course-app,#recipes-course-app) .content');
    var target = course && mobile.matches
      ? document.querySelector(':is(#masterclass-course-app,#calories-course-app,#recipes-course-app) .preview-sidebar-header')
      : course || document.querySelector('.account-shell');
    if (!target || button.parentElement === target) return;
    if (course && mobile.matches) target.insertBefore(button, target.querySelector('.close-menu'));
    else target.prepend(button);
  }
  update();
  function start() {
    place();
    mobile.addEventListener('change', place);
    new MutationObserver(place).observe(document.body, {childList: true, subtree: true});
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, {once: true});
  else start();
}());
