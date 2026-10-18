(function () {
  'use strict';
  function boot() {
    document.querySelectorAll('[data-site-menu]').forEach(function (panel) {
      if (panel.dataset.siteMenuMounted) return;
      var toggle = document.querySelector('[aria-controls="' + panel.id + '"][data-site-menu-toggle]');
      if (!toggle) return;
      panel.dataset.siteMenuMounted = 'true';
      var contents = panel.querySelector('[data-site-menu-contents]');
      function setDisclosure(button, open) {
        button.setAttribute('aria-expanded', String(open));
        document.getElementById(button.getAttribute('aria-controls')).hidden = !open;
      }
      var disclosures = panel.querySelectorAll('.site-menu-disclosure > button');
      function setOpen(open) {
        toggle.setAttribute('aria-expanded', String(open));
        toggle.setAttribute('aria-label', open ? 'Закрыть меню' : (toggle.dataset.menuLabel || 'Открыть меню'));
        panel.classList.toggle('is-open', open);
        panel.setAttribute('aria-hidden', String(!open));
        panel.inert = !open;
        document.documentElement.classList.toggle('site-menu-open', open);
        if (open) {
          if (contents) setDisclosure(contents, true);
          panel.scrollTop = 0;
        } else {
          disclosures.forEach(function (button) { setDisclosure(button, false); });
          if (panel.contains(document.activeElement)) toggle.focus();
        }
      }
      toggle.addEventListener('click', function () { setOpen(toggle.getAttribute('aria-expanded') !== 'true'); });
      disclosures.forEach(function (button) {
        button.addEventListener('click', function () { setDisclosure(button, button.getAttribute('aria-expanded') !== 'true'); });
      });
      panel.querySelectorAll('a').forEach(function (link) { link.addEventListener('click', function () { setOpen(false); }); });
      document.addEventListener('click', function (event) {
        if (!panel.contains(event.target) && !toggle.contains(event.target)) setOpen(false);
      });
      document.addEventListener('keydown', function (event) {
        if (toggle.getAttribute('aria-expanded') !== 'true') return;
        if (event.key === 'Escape') { setOpen(false); toggle.focus(); }
        if (event.key !== 'Tab') return;
        var items = [toggle].concat(Array.from(panel.querySelectorAll('a,button')).filter(function (element) { return element.getClientRects().length > 0; }));
        var index = items.indexOf(document.activeElement);
        if (event.shiftKey && index <= 0) { event.preventDefault(); items[items.length - 1].focus(); }
        else if (!event.shiftKey && (index < 0 || index === items.length - 1)) { event.preventDefault(); toggle.focus(); }
      });
    });
  }
  window.EdabalansSiteMenu = {boot: boot};
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
}());
