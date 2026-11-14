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
    ':root{--eb-footer-gap:48px;--eb-footer-text-gap:29px}',
    '.eb-footer--public{padding-top:var(--eb-footer-gap)}',
    '.eb-footer{box-sizing:border-box;width:100%;background:transparent;color:inherit;font:var(--ed-text-weight,400) var(--type-body,var(--ed-text-size,16px))/var(--ed-text-leading,1.55) var(--ed-font-body,Manrope,Arial,sans-serif)}',
    'body:has(#article:not([hidden], [hidden] *)) .eb-footer{font-size:var(--ed-article-size,17px)}',
    '.eb-footer *{box-sizing:border-box}',
    '.eb-footer__inner{container:eb-footer / inline-size;position:relative;width:min(var(--eb-footer-width,var(--content-frame,760px)),calc(100% - var(--eb-footer-gutter,40px)));margin:0 auto;padding:var(--eb-footer-text-gap) 0 24px}',
    '.eb-footer__inner:before{content:"";position:absolute;top:0;left:0;right:0;height:1px;background:linear-gradient(90deg,transparent,rgba(67,112,140,.25) 12%,rgba(67,112,140,.25) 88%,transparent);pointer-events:none}',
    '.eb-footer__inner:after{content:"";position:absolute;top:1px;left:0;right:0;height:14px;background:radial-gradient(ellipse at 50% 0,rgba(35,77,106,.09),transparent 72%);pointer-events:none}',
    '.eb-footer a{color:inherit;text-decoration:underline;text-underline-offset:4px;text-decoration-thickness:1px;border:0}',
    '.eb-footer a:hover{opacity:.72}',
    '.eb-footer a:focus-visible{outline:2px solid currentColor;outline-offset:3px}',
    '.eb-footer--private{color:var(--ed-app-muted,#7b8094);font-family:var(--ed-font-body, Manrope, Arial, sans-serif)}',
    '.eb-footer__row{display:grid;gap:3px;text-align:center;align-items:start}',
    '.eb-footer__row p{margin:0;font:inherit;color:inherit}',
    '.eb-footer__row .eb-footer__owner,.eb-footer__documents{font-size:var(--ed-label-size,14px)}',
    '.eb-footer__inn,.eb-footer__contact-pair{white-space:nowrap}',
    '.eb-footer__details,.eb-footer__rights-short{display:block}',
    '.eb-footer__rights{display:none}',
    '.eb-footer__row .eb-footer__read,.eb-footer__documents{margin-top:16px}',
    '.eb-footer__row :is(.eb-footer__read,.eb-footer__write){font-size:clamp(var(--ed-label-size,14px),5.5cqi,1em);white-space:nowrap}',
    '.eb-footer__documents{display:grid;gap:3px;text-wrap:balance}',
    '.eb-footer__document-pair{display:flex;flex-direction:column;align-items:center;gap:3px}',
    '.eb-footer__desktop{display:none}',
    '@container eb-footer (min-width:660px){' +
      '.eb-footer__row{grid-template-columns:minmax(0,1fr) max-content;grid-template-areas:"owner read" "documents write" "documents rights";column-gap:12px;text-align:left;font-size:var(--ed-label-size,14px)}' +
      '.eb-footer__owner{grid-area:owner}.eb-footer__details{display:inline;font-size:inherit}.eb-footer__rights-short{display:none}' +
      '.eb-footer__read{grid-area:read}.eb-footer__write{grid-area:write}.eb-footer__rights{grid-area:rights;display:block}' +
      '.eb-footer__read,.eb-footer__write,.eb-footer__rights{text-align:right}' +
      '.eb-footer__row :is(.eb-footer__read,.eb-footer__write){font-size:inherit}' +
      '.eb-footer__row .eb-footer__read{margin-top:0}' +
      '.eb-footer__mobile{display:none}.eb-footer__desktop{display:inline}.eb-footer__document-pair .eb-footer__offer{display:contents}' +
      '.eb-footer__documents{grid-area:documents;margin-top:0}.eb-footer__document-pair{flex-direction:row;justify-content:flex-start;flex-wrap:wrap;gap:0 .35em}' +
    '}'
  ].join('');

  function link(url, text) {
    return '<a href="' + url + '" target="_blank" rel="noopener">' + text + '</a>';
  }

  function contactPair(telegram, max) {
    return '<span class="eb-footer__contact-pair">' + link(telegram, 'Telegram') +
      ' / ' + link(max, 'MAX') + '</span>';
  }

  function footerMarkup(mode) {
    return '<footer class="eb-footer eb-footer--' + mode + '" aria-label="Подвал сайта">' +
      '<div class="eb-footer__inner"><div class="eb-footer__row">' +
        '<p class="eb-footer__owner">© ' + new Date().getFullYear() + ' ИП Воронцов Сергей ' +
          '<span class="eb-footer__details"><span class="eb-footer__inn">ИНН 230409966750</span>' +
          '<span class="eb-footer__mobile"> — ' + link(LINKS.offer, 'Оферта') + '</span>' +
          '<span class="eb-footer__rights-short">Копирование запрещено</span></span></p>' +
        '<p class="eb-footer__read">Читать мой канал: ' + contactPair(LINKS.telegramChannel, LINKS.maxChannel) + '</p>' +
        '<p class="eb-footer__write">Написать мне лично: ' + contactPair(LINKS.telegram, LINKS.max) + '</p>' +
        '<p class="eb-footer__rights">Копирование материалов запрещено</p>' +
        '<div class="eb-footer__documents">' +
          link(LINKS.privacy, 'Политика обработки <span class="eb-footer__mobile">перс.</span><span class="eb-footer__desktop">персональных</span> данных') +
          '<div class="eb-footer__document-pair"><span class="eb-footer__desktop eb-footer__offer">' + link(LINKS.offer, 'Оферта') + '</span>' +
            '<span class="eb-footer__desktop" aria-hidden="true">/</span>' + link(LINKS.disclaimer, 'Образовательный дисклеймер') + '</div>' +
        '</div>' +
      '</div></div>' +
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
    root.innerHTML = footerMarkup(mode);
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
