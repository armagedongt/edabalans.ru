(function () {
  'use strict';

  var componentOrigin = document.currentScript && document.currentScript.src
    ? new URL(document.currentScript.src, location.href).origin : location.origin;
  var publicOrigin = componentOrigin.replace('://admin.', '://');
  var publicRoot = publicOrigin === location.origin ? '' : publicOrigin;

  var STYLE_ID = 'edabalans-footer-style';
  var MOUNT_SELECTOR = '[data-edabalans-site-footer],[data-edabalans-footer]';
  var LINKS = {
    telegram: 'https://t.me/FitnessSergey',
    max: 'https://max.ru/u/f9LHodD0cOJjmbADdxMaO0UzEfR_55NRvOSwSuS3C6mWE5T27DPcpczbvEw',
    telegramChannel: 'https://t.me/Fitness_Talks',
    maxChannel: 'https://max.ru/id230409966750_biz',
    offer: publicRoot + '/legal/offer',
    privacy: publicRoot + '/legal/privacy',
    disclaimer: publicRoot + '/legal/disclaimer'
  };

  var CSS = [
    '.eb-footer{box-sizing:border-box;width:100%;background:var(--surface-soft,#f3f9fc);box-shadow:0 -7px 22px rgba(35,77,106,.07);color:inherit;font-family:inherit;font-size:12px;line-height:1.55}',
    '.eb-footer *{box-sizing:border-box}',
    '.eb-footer__inner{position:relative;width:min(var(--eb-footer-width,var(--content-frame,760px)),calc(100% - var(--eb-footer-gutter,40px)));margin:0 auto;padding:24px 0}',
    '.eb-footer__row{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:12px 24px;align-items:start}',
    '.eb-footer__owner,.eb-footer__contacts{margin:0;color:inherit}',
    '.eb-footer__rights{display:block;margin:12px 0 0;font-size:10px;text-align:center;opacity:.66}.eb-footer__inn{display:block;white-space:nowrap}',
    '.eb-footer__contacts{text-align:right}',
    '.eb-footer__links{display:flex;justify-content:flex-end;gap:7px 16px;flex-wrap:wrap}',
    '.eb-footer__links a{font-weight:600}',
    '.eb-footer__contact-lines{display:grid;gap:3px}.eb-footer__contact-lines p{margin:0}.eb-footer__contact-pair{display:inline-block;white-space:nowrap}',
    '.eb-footer a{color:inherit;text-decoration:underline;text-underline-offset:4px;text-decoration-thickness:1px;border:0}',
    '.eb-footer a:hover{opacity:.72}',
    '.eb-footer a:focus-visible{outline:2px solid currentColor;outline-offset:3px}',
    '.eb-footer__documents{display:flex;flex-direction:column;align-items:center;gap:4px;margin-top:12px;font-size:11px;opacity:.8}.eb-footer__documents a{white-space:nowrap}',
    '.eb-footer--private{background:var(--ed-app-card,#f3f9fc);color:var(--ed-app-muted,#7b8094);font-family:var(--ed-font-body, Manrope, Arial, sans-serif)}',
    '@media(max-width:640px){.eb-footer__row{grid-template-columns:1fr;gap:12px}.eb-footer__owner,.eb-footer__contacts{text-align:center}.eb-footer__links{justify-content:center}}'
  ].join('');

  function link(url, text) {
    return '<a href="' + url + '" target="_blank" rel="noopener">' + text + '</a>';
  }

  function contactsMarkup() {
    return '<div class="eb-footer__contacts eb-footer__contact-lines" aria-label="Каналы и личная связь">' +
      '<p>Читать мой канал: <span class="eb-footer__contact-pair">' + link(LINKS.telegramChannel, 'Telegram') + ' / ' + link(LINKS.maxChannel, 'MAX') + '</span></p>' +
      '<p>Написать мне лично: <span class="eb-footer__contact-pair">' + link(LINKS.telegram, 'Telegram') + ' / ' + link(LINKS.max, 'MAX') + '</span></p></div>';
  }

  function publicMarkup() {
    return '<footer class="eb-footer eb-footer--public" aria-label="Подвал сайта">' +
      '<div class="eb-footer__inner">' +
        '<div class="eb-footer__row">' +
          '<p class="eb-footer__owner">© ' + new Date().getFullYear() + ' ИП Воронцов Сергей Сергеевич <span class="eb-footer__inn">ИНН 230409966750</span>' +
          '</p>' +
          contactsMarkup() +
        '</div>' +
        '<nav class="eb-footer__documents" aria-label="Юридические документы">' +
          link(LINKS.privacy, 'Политика обработки персональных данных') +
          link(LINKS.offer, 'Оферта') +
        '</nav>' +
        '<p class="eb-footer__rights">Копирование материалов запрещено.</p>' +
      '</div>' +
    '</footer>';
  }

  function privateMarkup() {
    return '<footer class="eb-footer eb-footer--private" aria-label="Подвал личного кабинета">' +
      '<div class="eb-footer__inner">' +
        '<div class="eb-footer__row">' +
          '<p class="eb-footer__owner">© ' + new Date().getFullYear() + ' Воронцов Сергей' +
          '</p>' +
          contactsMarkup() +
        '</div>' +
        '<nav class="eb-footer__documents" aria-label="Документы личного кабинета">' +
          link(LINKS.privacy, 'Политика обработки персональных данных') +
          link(LINKS.disclaimer, 'Образовательный дисклеймер') +
        '</nav>' +
        '<p class="eb-footer__rights">Копирование материалов запрещено.</p>' +
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

  function prepareMedia(scope) {
    var root = scope && scope.querySelectorAll ? scope : document;
    var images = [];
    var frames = [];
    if (root.matches && root.matches('img')) images.push(root);
    if (root.matches && root.matches('iframe')) frames.push(root);
    images = images.concat(Array.prototype.slice.call(root.querySelectorAll('img')));
    frames = frames.concat(Array.prototype.slice.call(root.querySelectorAll('iframe')));
    images.forEach(function (image) {
      if (!image.hasAttribute('loading')) image.setAttribute('loading', 'lazy');
      if (!image.hasAttribute('decoding')) image.setAttribute('decoding', 'async');
    });
    frames.forEach(function (frame) {
      if (
        frame.hasAttribute('src') &&
        frame.getAttribute('src') !== 'about:blank' &&
        !frame.hasAttribute('loading')
      ) {
        frame.setAttribute('loading', 'lazy');
      }
    });
  }

  function boot(scope) {
    var root = scope && scope.querySelectorAll ? scope : document;
    prepareMedia(root);
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

  window.EdabalansFooter = {boot: boot, mount: mount, prepareMedia: prepareMedia};
  window.EdabalansSiteFooter = window.EdabalansFooter;
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { boot(); observe(); });
  } else {
    boot();
    observe();
  }
}());
