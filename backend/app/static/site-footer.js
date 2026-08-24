(function () {
  'use strict';

  var STYLE_ID = 'edabalans-site-footer-style';
  var MOUNT_SELECTOR = '[data-edabalans-site-footer]';

  var LINKS = {
    intensiveTelegram: 'https://t.me/Fitness_Talks_bot?start=527c52b9-6c37-4fd8-95f5-eb213cd4dd14',
    telegramChannel: 'https://t.me/Fitness_Talks',
    telegram: 'https://t.me/FitnessSergey',
    max: 'https://max.ru/u/f9LHodD0cOJjmbADdxMaO0UzEfR_55NRvOSwSuS3C6mWE5T27DPcpczbvEw',
    offer: 'https://go.похудение-это-есть.рф/legal/offer',
    privacy: 'https://go.похудение-это-есть.рф/legal/privacy',
    consent: 'https://go.похудение-это-есть.рф/legal/consent',
    disclaimer: 'https://go.похудение-это-есть.рф/legal/disclaimer'
  };

  var CSS = [
    '.eb-site-footer{box-sizing:border-box;width:100%;background:transparent;color:inherit;font-family:inherit;font-size:14px;line-height:1.5}',
    '.eb-site-footer *{box-sizing:border-box}',
    '.eb-site-footer__inner{position:relative;width:min(1200px,100%);margin:0 auto;padding:30px 24px 34px}',
    '.eb-site-footer__inner:before{content:"";position:absolute;inset:0 24px auto;height:1px;background:currentColor;opacity:.2}',
    '.eb-site-footer__main{display:grid;grid-template-columns:minmax(300px,1fr) auto;gap:28px;align-items:start}',
    '.eb-site-footer__owner{margin:0;font-size:14px}',
    '.eb-site-footer__rights{display:block;margin-top:4px;opacity:.62}',
    '.eb-site-footer__actions{display:grid;grid-template-columns:repeat(2,220px);gap:10px;align-items:start;justify-content:end}',
    '.eb-site-footer__action-group{width:100%}',
    '.eb-site-footer__action{min-height:42px;display:inline-flex;align-items:center;justify-content:center;padding:9px 16px;border:1px solid currentColor;border-radius:10px;background:transparent;color:inherit;font:inherit;font-weight:600;line-height:1;text-decoration:none;cursor:pointer}',
    '.eb-site-footer__action[hidden]{display:none!important}',
    '.eb-site-footer__action-group>.eb-site-footer__action{width:100%}',
    '.eb-site-footer__action:hover{opacity:.72}',
    '.eb-site-footer__action:focus-visible,.eb-site-footer a:focus-visible{outline:2px solid currentColor;outline-offset:3px}',
    '.eb-site-footer__action:after{content:"+";margin-left:8px;font-size:18px;font-weight:400;line-height:0}',
    '.eb-site-footer__action[aria-expanded="true"]:after{content:"−"}',
    '.eb-site-footer__panel[hidden]{display:none!important}',
    '.eb-site-footer__panel{width:100%;padding:0 14px 12px;border:1px solid currentColor;border-radius:10px;background:transparent}',
    '.eb-site-footer__panel-close{width:100%;min-height:41px;display:flex;align-items:center;justify-content:space-between;padding:8px 2px;border:0;border-bottom:1px solid currentColor;background:transparent;color:inherit;font:inherit;font-weight:600;cursor:pointer}',
    '.eb-site-footer__panel-close:after{content:"−";margin-left:8px;font-size:18px;font-weight:400}',
    '.eb-site-footer__panel-options{display:grid;gap:0}',
    '.eb-site-footer__option{display:flex;flex-direction:column;align-items:flex-start;padding:9px 2px 7px;color:inherit;text-align:left;text-decoration:none;border-bottom:1px solid currentColor}',
    '.eb-site-footer__option:last-child{border-bottom:0}',
    '.eb-site-footer__option small{margin-top:2px;font:inherit;font-size:12px;opacity:.62}',
    '.eb-site-footer__option--disabled{border-bottom-style:dashed;opacity:.38;cursor:not-allowed}',
    '.eb-site-footer__documents a{color:inherit;text-decoration:none;border-bottom:1px solid currentColor}',
    '.eb-site-footer__documents{display:flex;gap:9px 20px;flex-wrap:wrap;margin-top:24px;padding-top:17px;position:relative;opacity:.66}',
    '.eb-site-footer__documents:before{content:"";position:absolute;inset:0 0 auto;height:1px;background:currentColor;opacity:.28}',
    '@media(max-width:840px){.eb-site-footer__inner{padding:26px 20px 30px}.eb-site-footer__inner:before{inset-inline:20px}.eb-site-footer__main{grid-template-columns:1fr;gap:20px}.eb-site-footer__owner{text-align:center}.eb-site-footer__actions{grid-template-columns:repeat(2,minmax(0,1fr));justify-content:stretch;width:min(450px,100%);margin:0 auto}.eb-site-footer__documents{justify-content:center}}',
    '@media(max-width:520px){.eb-site-footer__actions{grid-template-columns:1fr;width:min(300px,100%)}.eb-site-footer__documents{display:grid;justify-items:center;gap:11px}.eb-site-footer__documents a{width:max-content;max-width:100%}}'
  ].join('');

  function link(url, text) {
    return '<a href="' + url + '" target="_blank" rel="noopener">' + text + '</a>';
  }

  function optionLink(url, text, note) {
    return '<a class="eb-site-footer__option" href="' + url + '" target="_blank" rel="noopener"><span>' + text + '</span>' +
      (note ? '<small>' + note + '</small>' : '') + '</a>';
  }

  function markup(index) {
    var intensiveId = 'edabalans-site-footer-intensive-' + index;
    var contactsId = 'edabalans-site-footer-contacts-' + index;
    return '<footer class="eb-site-footer" aria-label="Подвал сайта">' +
      '<div class="eb-site-footer__inner">' +
        '<div class="eb-site-footer__main">' +
          '<p class="eb-site-footer__owner">© ' + new Date().getFullYear() + ' ИП Воронцов Сергей Сергеевич · ИНН 230409966750' +
            '<span class="eb-site-footer__rights">Все права защищены · Копирование материалов запрещено</span>' +
          '</p>' +
          '<div class="eb-site-footer__actions">' +
            '<div class="eb-site-footer__action-group">' +
              '<button class="eb-site-footer__action" type="button" data-panel="' + intensiveId + '" aria-expanded="false" aria-controls="' + intensiveId + '">Бесплатный интенсив</button>' +
              '<section class="eb-site-footer__panel" id="' + intensiveId + '" aria-label="Выбор мессенджера для бесплатного интенсива" hidden>' +
                '<button class="eb-site-footer__panel-close" type="button" data-close-panel>Бесплатный интенсив</button>' +
                '<div class="eb-site-footer__panel-options">' +
                  optionLink(LINKS.intensiveTelegram, 'Telegram', 'Понадобится VPN') +
                  '<span class="eb-site-footer__option eb-site-footer__option--disabled" aria-disabled="true"><span>MAX</span><small>Пока недоступно</small></span>' +
                '</div>' +
              '</section>' +
            '</div>' +
            '<div class="eb-site-footer__action-group">' +
              '<button class="eb-site-footer__action" type="button" data-panel="' + contactsId + '" aria-expanded="false" aria-controls="' + contactsId + '">Контакты</button>' +
              '<section class="eb-site-footer__panel" id="' + contactsId + '" aria-label="Контакты" hidden>' +
                '<button class="eb-site-footer__panel-close" type="button" data-close-panel>Контакты</button>' +
                '<nav class="eb-site-footer__panel-options" aria-label="Способы связи">' +
                  optionLink(LINKS.telegram, 'Написать в Telegram') +
                  optionLink(LINKS.max, 'Написать в MAX') +
                  optionLink(LINKS.telegramChannel, 'Telegram-канал') +
                  '<span class="eb-site-footer__option eb-site-footer__option--disabled" aria-disabled="true"><span>MAX-канал</span><small>В разработке</small></span>' +
                '</nav>' +
              '</section>' +
            '</div>' +
          '</div>' +
        '</div>' +
        '<nav class="eb-site-footer__documents" aria-label="Юридические документы">' +
          link(LINKS.offer, 'Оферта') +
          link(LINKS.privacy, 'Политика обработки данных') +
          link(LINKS.consent, 'Согласие на обработку данных') +
          link(LINKS.disclaimer, 'Образовательный дисклеймер') +
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

  function mount(root, index) {
    if (root.getAttribute('data-edabalans-site-footer-mounted') === 'true') return;
    root.setAttribute('data-edabalans-site-footer-mounted', 'true');
    root.innerHTML = markup(index);
    var buttons = Array.prototype.slice.call(root.querySelectorAll('.eb-site-footer__action[data-panel]'));
    var panels = Array.prototype.slice.call(root.querySelectorAll('.eb-site-footer__panel'));
    var closeButtons = Array.prototype.slice.call(root.querySelectorAll('[data-close-panel]'));

    function closeAll() {
      buttons.forEach(function (item) {
        item.hidden = false;
        item.setAttribute('aria-expanded', 'false');
      });
      panels.forEach(function (item) { item.hidden = true; });
    }

    buttons.forEach(function (button) {
      var panel = root.querySelector('#' + button.getAttribute('data-panel'));
      button.addEventListener('click', function () {
        var shouldOpen = button.getAttribute('aria-expanded') !== 'true';
        closeAll();
        if (!shouldOpen) return;
        button.hidden = true;
        button.setAttribute('aria-expanded', 'true');
        panel.hidden = false;
        panel.querySelector('[data-close-panel]').focus();
      });
    });

    closeButtons.forEach(function (closeButton) {
      closeButton.addEventListener('click', function () {
        var panel = closeButton.closest('.eb-site-footer__panel');
        var button = root.querySelector('[aria-controls="' + panel.id + '"]');
        closeAll();
        button.focus();
      });
      closeButton.addEventListener('keydown', function (event) {
        if (event.key !== 'Escape') return;
        var panel = closeButton.closest('.eb-site-footer__panel');
        var button = root.querySelector('[aria-controls="' + panel.id + '"]');
        closeAll();
        button.focus();
      });
    });
  }

  function boot() {
    var roots = Array.prototype.slice.call(document.querySelectorAll(MOUNT_SELECTOR));
    if (!roots.length) return;
    ensureStyle();
    roots.forEach(mount);
  }

  window.EdabalansSiteFooter = {boot: boot};
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
}());
