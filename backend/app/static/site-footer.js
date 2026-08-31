(function () {
  'use strict';

  var STYLE_ID = 'edabalans-footer-style';
  var MOUNT_SELECTOR = '[data-edabalans-site-footer],[data-edabalans-footer]';
  var LINKS = {
    telegram: 'https://t.me/FitnessSergey',
    max: 'https://max.ru/u/f9LHodD0cOJjmbADdxMaO0UzEfR_55NRvOSwSuS3C6mWE5T27DPcpczbvEw',
    telegramChannel: 'https://t.me/Fitness_Talks',
    offer: 'https://go.похудение-это-есть.рф/legal/offer',
    privacy: 'https://go.похудение-это-есть.рф/legal/privacy',
    disclaimer: 'https://go.похудение-это-есть.рф/legal/disclaimer'
  };

  var CSS = [
    '.eb-footer{box-sizing:border-box;width:100%;background:transparent;color:inherit;font-family:inherit;font-size:14px;line-height:1.55}',
    '.eb-footer *{box-sizing:border-box}',
    '.eb-footer__inner{position:relative;width:min(1200px,100%);margin:0 auto;padding:26px 24px 32px}',
    '.eb-footer__inner:before{content:"";position:absolute;inset:0 24px auto;height:1px;background:currentColor;opacity:.18}',
    '.eb-footer__row{display:grid;grid-template-columns:minmax(260px,1fr) auto;gap:16px 32px;align-items:start}',
    '.eb-footer__owner,.eb-footer__contacts{margin:0;color:inherit}',
    '.eb-footer__rights{display:block;margin-top:3px;opacity:.66}',
    '.eb-footer__contacts{text-align:right}',
    '.eb-footer__links{display:flex;justify-content:flex-end;gap:7px 16px;flex-wrap:wrap}',
    '.eb-footer__links a{font-weight:600}',
    '.eb-footer a{color:inherit;text-decoration:none;border-bottom:1px solid currentColor}',
    '.eb-footer a:hover{opacity:.72}',
    '.eb-footer a:focus-visible{outline:2px solid currentColor;outline-offset:3px}',
    '.eb-footer__documents{display:flex;gap:8px 18px;flex-wrap:wrap;margin-top:15px;opacity:.72}',
    '.eb-footer--private{color:var(--ed-app-muted,#7b8094);font:13px/1.55 Inter,Arial,sans-serif}',
    '.eb-footer--private .eb-footer__inner{width:min(1080px,100%);padding:22px 20px 30px}',
    '.eb-footer--private .eb-footer__inner:before{inset-inline:20px}',
    '@media(max-width:640px){.eb-footer__inner{padding:23px 20px 28px}.eb-footer__inner:before{inset-inline:20px}.eb-footer__row{grid-template-columns:1fr;gap:12px}.eb-footer__owner,.eb-footer__contacts{text-align:center}.eb-footer__links,.eb-footer__documents{justify-content:center}}'
  ].join('');

  function link(url, text) {
    return '<a href="' + url + '" target="_blank" rel="noopener">' + text + '</a>';
  }

  function publicMarkup() {
    return '<footer class="eb-footer eb-footer--public" aria-label="Подвал сайта">' +
      '<div class="eb-footer__inner">' +
        '<div class="eb-footer__row">' +
          '<p class="eb-footer__owner">© ' + new Date().getFullYear() + ' ИП Воронцов Сергей Сергеевич · ИНН 230409966750' +
            '<span class="eb-footer__rights">Копирование материалов запрещено.</span>' +
          '</p>' +
          '<div class="eb-footer__contacts"><div class="eb-footer__links" aria-label="Контакты">' +
            link(LINKS.telegram, 'Telegram') +
            link(LINKS.max, 'MAX') +
            link(LINKS.telegramChannel, 'Telegram-канал') +
          '</div></div>' +
        '</div>' +
        '<nav class="eb-footer__documents" aria-label="Юридические документы">' +
          link(LINKS.offer, 'Оферта') +
          link(LINKS.privacy, 'Политика обработки персональных данных') +
        '</nav>' +
      '</div>' +
    '</footer>';
  }

  function privateMarkup() {
    return '<footer class="eb-footer eb-footer--private" aria-label="Подвал личного кабинета">' +
      '<div class="eb-footer__inner">' +
        '<div class="eb-footer__row">' +
          '<p class="eb-footer__owner">© ' + new Date().getFullYear() + ' Воронцов Сергей' +
            '<span class="eb-footer__rights">Копирование материалов запрещено.</span>' +
          '</p>' +
          '<div class="eb-footer__contacts"><div class="eb-footer__links" aria-label="Контакты">' +
            link(LINKS.telegram, 'Telegram') +
            link(LINKS.max, 'MAX') +
          '</div></div>' +
        '</div>' +
        '<nav class="eb-footer__documents" aria-label="Документы личного кабинета">' +
          link(LINKS.disclaimer, 'Образовательный дисклеймер') +
          link(LINKS.privacy, 'Политика обработки персональных данных') +
        '</nav>' +
      '</div>' +
    '</footer>';
  }

  function ensureStyle() {
    if (document.getElementById(STYLE_ID)) return;
    var style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = CSS;
    document.head.appendChild(style);
  }

  function modeFor(root, requestedMode) {
    if (requestedMode === 'private') return 'private';
    if (requestedMode === 'public') return 'public';
    return root.getAttribute('data-edabalans-footer') === 'private' ? 'private' : 'public';
  }

  function mount(root, requestedMode) {
    if (!root) return;
    ensureStyle();
    var mode = modeFor(root, requestedMode);
    if (root.getAttribute('data-edabalans-footer-mounted') === mode) return;
    root.setAttribute('data-edabalans-footer-mounted', mode);
    root.innerHTML = mode === 'private' ? privateMarkup() : publicMarkup();
  }

  function boot(scope) {
    var root = scope && scope.querySelectorAll ? scope : document;
    if (root.matches && root.matches(MOUNT_SELECTOR)) mount(root);
    Array.prototype.forEach.call(root.querySelectorAll(MOUNT_SELECTOR), function (item) {
      mount(item);
    });
  }

  function observe() {
    if (!document.documentElement || window.EdabalansFooterObserver) return;
    window.EdabalansFooterObserver = new MutationObserver(function (records) {
      records.forEach(function (record) {
        Array.prototype.forEach.call(record.addedNodes, function (node) {
          if (node.nodeType === 1) boot(node);
        });
      });
    });
    window.EdabalansFooterObserver.observe(document.documentElement, {childList: true, subtree: true});
  }

  window.EdabalansFooter = {boot: boot, mount: mount};
  window.EdabalansSiteFooter = window.EdabalansFooter;
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { boot(); observe(); });
  } else {
    boot();
    observe();
  }
}());
