(function () {
  'use strict';

  var STYLE_ID = 'edabalans-site-header-style';
  var MOUNT_SELECTOR = '[data-edabalans-site-header]';
  var CONTACTS = [
    ['https://t.me/FitnessSergey', 'Написать в ЛС в Telegram'],
    ['https://max.ru/u/f9LHodD0cOJjmbADdxMaO0UzEfR_55NRvOSwSuS3C6mWE5T27DPcpczbvEw', 'Написать в ЛС в MAX'],
    ['https://t.me/Fitness_Talks', 'Telegram-канал'],
    ['https://max.ru/id230409966750_biz', 'Канал в MAX']
  ];
  var DEFAULT_NAV = [
    ['/', 'Главная'],
    ['/blog', 'Блог'],
    ['/#intensive', 'Бесплатный интенсив'],
    ['/#masterclass', 'Мастер-класс']
  ];

  var CSS = [
    '.eb-site-header{position:relative;z-index:80;box-sizing:border-box;width:100%;font-family:Manrope,Arial,sans-serif}',
    '.eb-site-header *{box-sizing:border-box}',
    '.eb-site-header__desktop{display:none}',
    '.eb-site-header__mobile-toggle{position:fixed;z-index:92;top:14px;right:14px;display:grid;width:38px;height:38px;place-items:center;padding:0;border:1px solid rgba(18,24,31,.08);border-radius:13px;background:rgba(255,255,255,.94);box-shadow:0 11px 28px -12px rgba(18,24,31,.35),0 2px 8px rgba(18,24,31,.08);color:#17191e;cursor:pointer;backdrop-filter:blur(10px);transition:transform .18s ease,background .18s ease}',
    '.eb-site-header__mobile-toggle:hover,.eb-site-header__mobile-toggle:focus-visible{background:#fff;transform:translateY(-2px)}',
    '.eb-site-header__bars{display:grid;gap:5px}',
    '.eb-site-header__bars span{display:block;width:21px;height:2px;border-radius:5px;background:currentColor;transition:transform .2s ease,opacity .2s ease}',
    '.eb-site-header__mobile-toggle[aria-expanded="true"] .eb-site-header__bars span:nth-child(1){transform:translateY(7px) rotate(45deg)}',
    '.eb-site-header__mobile-toggle[aria-expanded="true"] .eb-site-header__bars span:nth-child(2){opacity:0}',
    '.eb-site-header__mobile-toggle[aria-expanded="true"] .eb-site-header__bars span:nth-child(3){transform:translateY(-7px) rotate(-45deg)}',
    '.eb-site-header__mobile-sheet{position:fixed;z-index:90;inset:0;display:grid;align-content:start;padding:78px 18px 28px;background:rgba(255,255,255,.97);opacity:0;pointer-events:none;transform:translateY(-10px);transition:opacity .2s ease,transform .2s ease;backdrop-filter:blur(14px)}',
    '.eb-site-header__mobile-sheet.is-open{opacity:1;pointer-events:auto;transform:translateY(0)}',
    '.eb-site-header__mobile-links{display:grid}',
    '.eb-site-header__mobile-links>a,.eb-site-header__mobile-contact-trigger{display:flex;width:100%;justify-content:space-between;padding:15px 3px;border:0;border-bottom:1px solid #e5e9ec;background:transparent;color:#17191e;font:800 18px/1.25 Manrope,Arial,sans-serif;text-align:left;text-decoration:none}',
    '.eb-site-header__mobile-links>a:after{color:#a7adb2;content:"→"}',
    '.eb-site-header__mobile-contact-trigger:after{color:#a7adb2;content:"+";font-size:22px;font-weight:500;line-height:1}',
    '.eb-site-header__mobile-contact-trigger[aria-expanded="true"]:after{content:"−"}',
    '.eb-site-header__mobile-contact-panel{display:grid;padding:7px 0 10px 13px;border-bottom:1px solid #e5e9ec}',
    '.eb-site-header__mobile-contact-panel[hidden]{display:none}',
    '.eb-site-header__mobile-contact-panel a{display:flex;min-height:42px;align-items:center;padding:8px 10px;border-radius:10px;color:#303a42;font-size:14px;font-weight:700;line-height:1.3;text-decoration:none}',
    '.eb-site-header__mobile-contact-panel a:hover,.eb-site-header__mobile-contact-panel a:focus-visible{color:#118ed8;background:#edf8ff}',
    '.eb-site-header__mobile-links .eb-site-header__account{margin-top:16px;padding:14px 16px;border:0;border-radius:13px;background:#e9f7fe;color:#237fae;font-size:15px}',
    '.eb-site-header__mobile-links .eb-site-header__account:after{content:"→"}',
    'body.eb-site-header-menu-open{overflow:hidden}',
    '@media(min-width:900px){.eb-site-header__mobile-toggle,.eb-site-header__mobile-sheet{display:none}.eb-site-header__desktop{display:block;padding:18px 12px 0;background:transparent}.eb-site-header__pill{display:grid;width:min(100%,1390px);min-height:68px;grid-template-columns:minmax(210px,1fr) auto minmax(210px,1fr);align-items:center;gap:20px;margin:0 auto;padding:9px 13px;border-radius:34px;background:#26a8ef;box-shadow:0 16px 34px -28px rgba(17,142,216,.8)}.eb-site-header__wordmark{padding-left:12px;color:#fff;font-family:Unbounded,Manrope,sans-serif;font-size:17px;font-weight:800;line-height:1;letter-spacing:-.055em;white-space:nowrap}.eb-site-header__nav{display:flex;align-items:center;justify-content:center;gap:4px}.eb-site-header__nav>a,.eb-site-header__contact-trigger{display:inline-flex;height:40px;align-items:center;justify-content:center;padding:0 12px;border:0;border-radius:14px;background:transparent;color:#fff;font:800 14px/1 Manrope,Arial,sans-serif;text-decoration:none;white-space:nowrap;transition:background .16s ease}.eb-site-header__nav>a:hover,.eb-site-header__nav>a:focus-visible,.eb-site-header__contact-trigger:hover,.eb-site-header__contact-trigger:focus-visible,.eb-site-header__contact-trigger[aria-expanded="true"]{background:rgba(255,255,255,.16)}.eb-site-header__contact{position:relative;display:flex;align-items:center}.eb-site-header__contact-trigger{gap:7px;cursor:pointer}.eb-site-header__chevron{width:7px;height:7px;border-right:1.8px solid currentColor;border-bottom:1.8px solid currentColor;transform:translateY(-2px) rotate(45deg);transition:transform .16s ease}.eb-site-header__contact-trigger[aria-expanded="true"] .eb-site-header__chevron{transform:translateY(2px) rotate(225deg)}.eb-site-header__contact-panel{position:absolute;z-index:95;top:calc(100% + 11px);left:50%;display:grid;width:270px;padding:7px;border:1px solid rgba(21,105,159,.13);border-radius:17px;background:rgba(255,255,255,.97);box-shadow:0 16px 32px -22px rgba(15,70,106,.55),0 5px 12px -8px rgba(15,70,106,.24);transform:translateX(-50%);backdrop-filter:blur(12px)}.eb-site-header__contact-panel[hidden]{display:none}.eb-site-header__contact-panel a{display:flex;min-height:41px;align-items:center;padding:9px 12px;border-radius:11px;color:#202a32;font-size:13px;font-weight:700;line-height:1.25;text-decoration:none}.eb-site-header__contact-panel a:hover,.eb-site-header__contact-panel a:focus-visible{color:#118ed8;background:#edf8ff}.eb-site-header__account{justify-self:end;padding:12px 18px;border:1px solid rgba(255,255,255,.55);border-radius:23px;background:rgba(255,255,255,.16);color:#fff;font-size:13px;font-weight:800;text-decoration:none}}',
    '@media(min-width:900px) and (max-width:1179px){.eb-site-header__pill{grid-template-columns:minmax(175px,1fr) auto minmax(175px,1fr);gap:8px;padding-inline:10px}.eb-site-header__wordmark{padding-left:5px;font-size:12px}.eb-site-header__nav{gap:0}.eb-site-header__nav>a,.eb-site-header__contact-trigger{height:36px;padding:0 7px;font-size:11.5px}.eb-site-header__account{padding:10px 12px;font-size:11px}}',
    '@media(prefers-reduced-motion:reduce){.eb-site-header__mobile-toggle,.eb-site-header__bars span,.eb-site-header__mobile-sheet,.eb-site-header__nav a,.eb-site-header__contact-trigger,.eb-site-header__chevron{transition:none}}'
  ].join('');

  function esc(value) {
    return String(value).replace(/[&<>"']/g, function (char) {
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char];
    });
  }

  function linksMarkup(items, className) {
    return items.map(function (item) {
      return '<a class="' + (className || '') + '" href="' + esc(item[0]) + '">' + esc(item[1]) + '</a>';
    }).join('');
  }

  function contactMarkup(classPrefix, panelId) {
    return '<div class="' + classPrefix + '">' +
      '<button class="' + classPrefix + '-trigger" type="button" aria-expanded="false" aria-haspopup="true" aria-controls="' + panelId + '">Контакты' +
        (classPrefix.indexOf('mobile') < 0 ? '<span class="eb-site-header__chevron" aria-hidden="true"></span>' : '') +
      '</button>' +
      '<div class="' + classPrefix + '-panel" id="' + panelId + '" hidden>' +
        CONTACTS.map(function (item) { return '<a href="' + esc(item[0]) + '" target="_blank" rel="noopener">' + esc(item[1]) + '</a>'; }).join('') +
      '</div>' +
    '</div>';
  }

  function parseNav(root) {
    var custom = root.getAttribute('data-nav');
    if (!custom) return DEFAULT_NAV;
    try {
      var parsed = JSON.parse(custom);
      if (Array.isArray(parsed)) return parsed.map(function (item) { return [item.href || '#', item.label || 'Ссылка']; });
    } catch (error) {}
    return DEFAULT_NAV;
  }

  function ensureStyle() {
    if (document.getElementById(STYLE_ID)) return;
    var style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = CSS;
    document.head.appendChild(style);
  }

  function bindDisclosure(root, triggerSelector, panelSelector, outsideRoot) {
    var trigger = root.querySelector(triggerSelector);
    var panel = root.querySelector(panelSelector);
    if (!trigger || !panel) return function () {};
    function setOpen(open) {
      trigger.setAttribute('aria-expanded', String(open));
      panel.hidden = !open;
    }
    trigger.addEventListener('click', function () { setOpen(trigger.getAttribute('aria-expanded') !== 'true'); });
    document.addEventListener('click', function (event) { if (outsideRoot && !outsideRoot.contains(event.target)) setOpen(false); });
    return setOpen;
  }

  function mount(root) {
    if (!root || root.getAttribute('data-edabalans-site-header-mounted') === 'true') return;
    ensureStyle();
    var uid = 'eb-site-header-' + Math.random().toString(36).slice(2, 8);
    var nav = parseNav(root);
    var accountUrl = root.getAttribute('data-account-url') || 'https://похудение-это-есть.рф/lk';
    var wordmark = root.getAttribute('data-wordmark') || 'ПОХУДЕНИЕ — ЭТО ЕСТЬ.РФ';
    root.classList.add('eb-site-header');
    root.setAttribute('data-edabalans-site-header-mounted', 'true');
    root.innerHTML = '<div class="eb-site-header__desktop"><div class="eb-site-header__pill">' +
      '<span class="eb-site-header__wordmark">' + esc(wordmark) + '</span>' +
      '<nav class="eb-site-header__nav" aria-label="Основная навигация">' + linksMarkup(nav) + contactMarkup('eb-site-header__contact', uid + '-desktop-contacts') + '</nav>' +
      '<a class="eb-site-header__account" href="' + esc(accountUrl) + '">Личный кабинет</a>' +
    '</div></div>' +
    '<button class="eb-site-header__mobile-toggle" type="button" aria-label="Открыть меню" aria-expanded="false" aria-controls="' + uid + '-mobile-menu"><span class="eb-site-header__bars" aria-hidden="true"><span></span><span></span><span></span></span></button>' +
    '<aside class="eb-site-header__mobile-sheet" id="' + uid + '-mobile-menu" aria-hidden="true" inert><nav class="eb-site-header__mobile-links" aria-label="Мобильная навигация">' +
      linksMarkup(nav) + contactMarkup('eb-site-header__mobile-contact', uid + '-mobile-contacts') + '<a class="eb-site-header__account" href="' + esc(accountUrl) + '">Личный кабинет</a>' +
    '</nav></aside>';

    var desktopContact = root.querySelector('.eb-site-header__contact');
    bindDisclosure(root, '.eb-site-header__contact-trigger', '.eb-site-header__contact-panel', desktopContact);
    var mobileContact = root.querySelector('.eb-site-header__mobile-contact');
    var setMobileContactOpen = bindDisclosure(root, '.eb-site-header__mobile-contact-trigger', '.eb-site-header__mobile-contact-panel', mobileContact);
    var toggle = root.querySelector('.eb-site-header__mobile-toggle');
    var sheet = root.querySelector('.eb-site-header__mobile-sheet');
    function setMenuOpen(open) {
      toggle.setAttribute('aria-expanded', String(open));
      toggle.setAttribute('aria-label', open ? 'Закрыть меню' : 'Открыть меню');
      sheet.classList.toggle('is-open', open);
      sheet.setAttribute('aria-hidden', String(!open));
      sheet.inert = !open;
      document.body.classList.toggle('eb-site-header-menu-open', open);
      if (!open) setMobileContactOpen(false);
    }
    toggle.addEventListener('click', function () { setMenuOpen(toggle.getAttribute('aria-expanded') !== 'true'); });
    Array.prototype.forEach.call(sheet.querySelectorAll('a'), function (link) { link.addEventListener('click', function () { setMenuOpen(false); }); });
    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape') setMenuOpen(false);
    });
  }

  function boot(scope) {
    var target = scope && scope.querySelectorAll ? scope : document;
    if (target.matches && target.matches(MOUNT_SELECTOR)) mount(target);
    Array.prototype.forEach.call(target.querySelectorAll(MOUNT_SELECTOR), mount);
  }

  window.EdabalansSiteHeader = {boot: boot, mount: mount};
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function () { boot(); });
  else boot();
}());
