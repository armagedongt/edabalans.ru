(function () {
  'use strict';

  var APP_HOST = /^(localhost|127\.0\.0\.1)$/.test(location.hostname) || location.hostname.indexOf('go.') === 0
    ? location.origin
    : 'https://edabalans.ru';
  var STORAGE_IDENTITY = 'edabalans_identity_v1';
  var PUBLIC_ACCOUNT_URL = APP_HOST + '/lk';
  var appHtmlCache = {};
  var appHtmlRequests = {};
  var stylesheetRequests = {};
  var readyRequests = new WeakMap();
  var loadingScreens = new WeakMap();
  var roots = {
    account: 'account-app',
    sprints: 'sprints-app',
    'masterclass-course': 'masterclass-course-app',
    'calories-course': 'calories-course-app',
    'masterclass-sales': 'masterclass-sales-app',
    dqs: 'dqs-app',
    strength: 'strength-app',
    metabolism: 'metabolism-app',
    'onboarding-questionnaire': 'onboarding-questionnaire-app',
    'masterclass-offers': 'masterclass-offers-app',
    'recipes-part-1': 'recipes-part-1-app',
    'recipes-part-2': 'recipes-part-2-app',
    'recipes': 'recipes-app',
    'closing-review': 'closing-review-app',
    'personal-access': 'personal-access-app'
  };

  function normalizeEmail(value) {
    return String(value || '').trim().toLowerCase();
  }

  function validEmail(value) {
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
  }

  function escapeHtml(value) {
    return String(value || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  // Critical loader styles are synchronous: the loader must not wait for its own CSS.
  function ensureLoadingStyles() {
    if (document.getElementById('edabalans-loading-styles')) return;
    var style = document.createElement('style');
    style.id = 'edabalans-loading-styles';
    style.textContent = '.ed-loading{box-sizing:border-box;display:grid;place-items:center;min-height:260px;padding:24px;background:#fff;color:#46515b;font:600 15px/1.5 Manrope,Arial,sans-serif;text-align:center}' +
      '.ed-loading-screen{position:fixed;inset:0;z-index:2147483000;min-height:100dvh}.ed-loading-inline{position:absolute;inset:0;z-index:100}' +
      '.ed-loading-stage{min-height:46px;max-width:320px;margin:0 0 18px}.ed-loading-dots{display:flex;justify-content:center;align-items:center;gap:9px;height:22px}' +
      '.ed-loading-dots i{display:block;width:10px;height:10px;border-radius:50%;background:#27aff5;animation:ed-loading-pulse 1.1s ease-in-out infinite}.ed-loading-dots i:nth-child(2){animation-delay:.15s}.ed-loading-dots i:nth-child(3){animation-delay:.3s;background:#f39a2f}' +
      '.ed-loading-error{max-width:420px;margin:12px 0;color:#b42318}.ed-loading-retry{min-height:44px;padding:10px 22px;border:0;border-radius:12px;background:#27aff5;color:#fff;font:800 15px/1.4 Manrope,Arial,sans-serif;cursor:pointer}.ed-loading-retry:focus-visible{outline:3px solid #118ed8;outline-offset:3px}' +
      'body:has(>.ed-loading-screen){background:#fff!important}body:has(>.ed-loading-screen) [data-edabalans-app]{pointer-events:none}' +
      '@keyframes ed-loading-pulse{0%,70%,100%{transform:translateY(0);opacity:.45}35%{transform:translateY(-6px);opacity:1}}@media(prefers-reduced-motion:reduce){.ed-loading-dots i{animation:none;opacity:1}}';
    document.head.appendChild(style);
  }

  function loadingHtml(stage) {
    ensureLoadingStyles();
    return '<div class="ed-loading" role="status" aria-live="polite"><div><p class="ed-loading-stage">' + escapeHtml(stage) + '</p><div class="ed-loading-dots" aria-hidden="true"><i></i><i></i><i></i></div></div></div>';
  }

  function beginLoading(mount, stage) {
    var current = loadingScreens.get(mount);
    if (current) { current.overlay.querySelector('.ed-loading-stage').textContent = stage; return; }
    var inline = mount.getAttribute('data-edabalans-inline') === 'true' || Boolean(mount.closest('#inline-app-frame,#dqs-frame'));
    var parent = inline ? mount.parentElement : document.body;
    var overlay = document.createElement('div');
    overlay.innerHTML = loadingHtml(stage);
    overlay = overlay.firstElementChild;
    overlay.classList.add(inline ? 'ed-loading-inline' : 'ed-loading-screen');
    var state = {overlay: overlay, visibility: mount.style.visibility, parent: parent, position: parent.style.position, inline: inline};
    if (inline && getComputedStyle(parent).position === 'static') parent.style.position = 'relative';
    mount.style.visibility = 'hidden';
    mount.setAttribute('aria-busy', 'true');
    parent.appendChild(overlay);
    loadingScreens.set(mount, state);
  }

  function finishLoading(mount) {
    var state = loadingScreens.get(mount);
    if (!state) return;
    mount.style.visibility = state.visibility;
    mount.removeAttribute('aria-busy');
    state.overlay.remove();
    if (state.inline) state.parent.style.position = state.position;
    loadingScreens.delete(mount);
  }

  function failLoading(mount, error, retry) {
    beginLoading(mount, 'Не удалось загрузить страницу');
    var overlay = loadingScreens.get(mount).overlay;
    var dots = overlay.querySelector('.ed-loading-dots');
    if (dots) dots.remove();
    overlay.querySelectorAll('.ed-loading-error,.ed-loading-retry').forEach(function (item) { item.remove(); });
    var message = document.createElement('p');
    message.className = 'ed-loading-error';
    message.textContent = String(error.message || error);
    overlay.firstElementChild.appendChild(message);
    var button = document.createElement('button');
    button.type = 'button'; button.className = 'ed-loading-retry'; button.textContent = 'Повторить';
    button.onclick = function () { finishLoading(mount); retry(); };
    overlay.firstElementChild.appendChild(button);
  }

  function waitUntilReady(mount, request) { readyRequests.set(mount, request); }

  function appHtml(app) {
    if (appHtmlCache[app]) return Promise.resolve(appHtmlCache[app]);
    if (appHtmlRequests[app]) return appHtmlRequests[app];
    appHtmlRequests[app] = fetch(APP_HOST + '/apps/' + app + '.html', {cache: 'no-cache'}).then(function (response) {
      if (!response.ok) throw new Error('Не удалось загрузить приложение');
      return response.text();
    }).then(function (html) { appHtmlCache[app] = html; return html; }).finally(function () { delete appHtmlRequests[app]; });
    return appHtmlRequests[app];
  }

  function loadStylesheet(href) {
    var url = new URL(href, APP_HOST).href;
    if (stylesheetRequests[url]) return stylesheetRequests[url];
    var existing = Array.prototype.find.call(document.querySelectorAll('link[rel="stylesheet"]'), function (link) { return link.href === url; });
    if (existing && existing.sheet) return Promise.resolve();
    stylesheetRequests[url] = new Promise(function (resolve, reject) {
      var link = existing || document.createElement('link');
      link.rel = 'stylesheet'; link.href = url;
      link.addEventListener('load', resolve, {once: true});
      link.addEventListener('error', function () { link.remove(); delete stylesheetRequests[url]; reject(new Error('Не удалось загрузить оформление страницы')); }, {once: true});
      if (!existing) document.head.appendChild(link);
    });
    return stylesheetRequests[url];
  }
  function rememberNative(email) {
    try {
      localStorage.setItem(STORAGE_IDENTITY, JSON.stringify({
        email: email,
        sessionToken: '',
        expiresAt: 0,
        source: 'native',
        confirmedAt: new Date().toISOString()
      }));
    } catch (error) {}
    window.EdabalansIdentity = {email: email, sessionToken: '', source: 'native'};
  }

  function redirectToAccountLogin() {
    try {
      localStorage.removeItem(STORAGE_IDENTITY);
    } catch (error) {}
    window.EdabalansIdentity = null;
    var returnTo = location.pathname + location.search;
    var destination = PUBLIC_ACCOUNT_URL;
    if (returnTo && returnTo.indexOf('/lk') !== 0) {
      destination += '?next=' + encodeURIComponent(returnTo);
    }
    window.top.location.replace(destination);
  }

  function showStandaloneAccessError(mount, message) {
    finishLoading(mount);
    mount.innerHTML = '<div style="box-sizing:border-box;min-height:100vh;display:grid;place-items:center;padding:22px;background:#f4f4f6;font:16px/1.5 Arial,sans-serif;color:#17172b">' +
      '<div style="width:min(520px,100%);padding:26px;border-radius:22px;background:#fff;box-shadow:0 16px 50px rgba(15,23,42,.12)">' +
      '<h1 style="margin:0 0 12px;font-size:24px">Приложение не открылось</h1>' +
      '<p style="margin:0 0 18px">' + escapeHtml(message) + '</p>' +
      '<a href="' + escapeHtml(PUBLIC_ACCOUNT_URL) + '" style="display:block;padding:13px 18px;border-radius:12px;background:#239fe9;color:#fff;text-align:center;text-decoration:none;font-weight:700">Войти в личный кабинет</a>' +
      '</div></div>';
  }

  function nativeSession() {
    return fetch(APP_HOST + '/api/account-auth/session', {credentials: 'include'})
      .then(function (response) { if (!response.ok) throw new Error('Не удалось проверить вход'); return response.json(); });
  }

  function prefetchAppHtml(appCode) {
    if (!roots[appCode] || appHtmlCache[appCode]) return;
    appHtml(appCode).catch(function () {});
  }

  function telegramMiniAppSession(appCode) {
    var telegram = window.Telegram && window.Telegram.WebApp;
    var initData = telegram && String(telegram.initData || '');
    if (!initData) return Promise.resolve(null);
    try {
      telegram.ready();
      telegram.expand();
    } catch (error) {}
    return fetch(APP_HOST + '/api/account-auth/telegram-miniapp', {
      method: 'POST',
      credentials: 'include',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({init_data: initData, app_code: appCode})
    }).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (payload) {
        if (!response.ok) {
          throw new Error(payload.detail || 'Не удалось войти через Telegram');
        }
        return payload;
      });
    });
  }

  function maxMiniAppSession(appCode) {
    var max = window.WebApp;
    var initData = max && String(max.initData || '');
    if (!initData) return Promise.resolve(null);
    try {
      if (typeof max.ready === 'function') max.ready();
      if (typeof max.expand === 'function') max.expand();
    } catch (error) {}
    return fetch(APP_HOST + '/api/account-auth/max-miniapp', {
      method: 'POST',
      credentials: 'include',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({init_data: initData, app_code: appCode})
    }).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (payload) {
        if (!response.ok) {
          throw new Error(payload.detail || 'Не удалось войти через MAX');
        }
        return payload;
      });
    });
  }

  function ensureAppShellStylesheet() {
    if (document.getElementById('edabalans-app-shell-styles')) return;
    var link = document.createElement('link');
    link.id = 'edabalans-app-shell-styles';
    link.rel = 'stylesheet';
    link.href = APP_HOST + '/assets/app-shell.css';
    document.head.appendChild(link);
  }

  var footerRendererPromise;

  function ensureFooterRenderer() {
    if (window.EdabalansFooter) return Promise.resolve(window.EdabalansFooter);
    if (footerRendererPromise) return footerRendererPromise;
    footerRendererPromise = new Promise(function (resolve, reject) {
      var existing = document.getElementById('edabalans-footer-renderer');
      var script = existing || document.createElement('script');
      function failed(error) {
        footerRendererPromise = null;
        if (script.parentElement) script.parentElement.removeChild(script);
        reject(error);
      }
      function ready() {
        if (window.EdabalansFooter) resolve(window.EdabalansFooter);
        else failed(new Error('Не удалось загрузить общий подвал'));
      }
      script.addEventListener('load', ready, {once: true});
      script.addEventListener('error', failed, {once: true});
      if (!existing) {
        script.id = 'edabalans-footer-renderer';
        script.src = APP_HOST + '/site-footer.js';
        document.head.appendChild(script);
      }
    });
    return footerRendererPromise;
  }

  function legalFooterHost(mount) {
    var dqsMount = mount.querySelector('[data-edabalans-app="dqs"]');
    if (dqsMount) return dqsMount;
    var isCourse = ['masterclass-course', 'calories-course'].indexOf(
      mount.getAttribute('data-edabalans-app')
    ) >= 0;
    var courseMount = isCourse
      ? mount
      : mount.querySelector('[data-edabalans-app="masterclass-course"],[data-edabalans-app="calories-course"]');
    var courseMain = courseMount && courseMount.querySelector(':scope > .main');
    return courseMain || mount;
  }

  function ensureLegalFooter(mount) {
    if (mount.parentElement && mount.parentElement.closest('[data-edabalans-footer-owner]')) return;
    mount.setAttribute('data-edabalans-footer-owner', 'true');
    var footerLoadRetries = 0;
    function append() {
      var host = legalFooterHost(mount);
      var footer = mount.querySelector('[data-edabalans-footer="private"]');
      if (!footer) {
        footer = document.createElement('div');
        footer.setAttribute('data-edabalans-footer', 'private');
        host.appendChild(footer);
      }
      else if (footer.parentElement !== host) host.appendChild(footer);
      ensureFooterRenderer()
        .then(function (renderer) { renderer.mount(footer, 'private'); })
        .catch(function () {
          if (footerLoadRetries >= 1) return;
          footerLoadRetries += 1;
          setTimeout(append, 300);
        });
    }
    append();
    new MutationObserver(append).observe(mount, {childList: true, subtree: true});
  }

  function executeScripts(doc) {
    var scripts = doc.querySelectorAll('script');
    return Array.prototype.reduce.call(scripts, function (promise, source) {
      return promise.then(function () {
        return new Promise(function (resolve, reject) {
          var script = document.createElement('script');
          if (source.getAttribute('src')) {
            var sourcePath = source.getAttribute('src');
            script.src = sourcePath.charAt(0) === '/' ? APP_HOST + sourcePath : sourcePath;
            script.onload = resolve;
            script.onerror = reject;
          } else {
            script.text = source.textContent;
          }
          document.body.appendChild(script);
          if (!source.getAttribute('src')) resolve();
        });
      });
    }, Promise.resolve());
  }

  function jsonRequest(url, options) {
    return fetch(url, options).then(function (response) {
      return response.json().then(function (payload) {
        if (!response.ok) {
          throw new Error(payload.detail || payload.error || 'Не удалось выполнить запрос');
        }
        return payload;
      });
    });
  }

  function dqsLegalGate(mount) {
    var identity = window.EdabalansIdentity || {};
    var email = normalizeEmail(identity.email);
    if (!validEmail(email)) return Promise.resolve();
    return fetch(APP_HOST + '/api/apps/dqs/access?email=' + encodeURIComponent(email))
      .then(function (response) {
        return response.json().then(function (payload) {
          // The DQS fragment owns its existing login/access error flow. The
          // preflight only replaces the app when entitlement was confirmed.
          return response.ok ? payload : null;
        });
      })
      .then(function (status) {
        if (!status) return;
        var legal = status.legal;
        if (!legal || !legal.required) return;
        finishLoading(mount);
        return new Promise(function (resolve, reject) {
          var documents = legal.documents || [];
          var cards = documents.map(function (item) {
            var policy = item.code === 'personal_data_consent'
              ? ' · <a href="' + escapeHtml(APP_HOST + '/legal/privacy.html') + '" target="_blank" rel="noopener">Политика обработки данных ↗</a>'
              : '';
            return '<label class="edabalans-dqs-legal-card">' +
              '<input type="checkbox" data-edabalans-dqs-legal="' + escapeHtml(item.code) + '"' + (item.accepted ? ' checked disabled' : '') + '>' +
              '<span><strong>' + escapeHtml(item.title) + '</strong>' +
              '<span>' + escapeHtml(item.summary) + '</span>' +
              '<a href="' + escapeHtml(APP_HOST + item.url) + '" target="_blank" rel="noopener">Читать полностью ↗</a>' + policy + '</span></label>';
          }).join('');
          mount.innerHTML = '<style>' +
            '.edabalans-dqs-legal-shell{box-sizing:border-box;min-height:70vh;display:grid;place-items:center;padding:32px 18px;background:#f5f0e7;color:#25241f;font:16px/1.5 Inter,Arial,sans-serif}' +
            '.edabalans-dqs-legal-window{box-sizing:border-box;width:min(760px,100%);padding:28px;border:1px solid #e3a38f;border-radius:24px;background:#fffdf8;box-shadow:0 18px 50px rgba(80,53,27,.12)}' +
            '.edabalans-dqs-legal-window>p{margin:12px 0 22px;color:#684c43}' +
            '.edabalans-dqs-legal-list{display:grid;gap:12px}' +
            '.edabalans-dqs-legal-card{box-sizing:border-box;display:grid;grid-template-columns:26px 1fr;gap:12px;padding:18px;border:1px solid #ead4ca;border-radius:16px;background:#fff}' +
            '.edabalans-dqs-legal-card input{width:22px;height:22px;margin:2px 0 0;accent-color:#dc6748}' +
            '.edabalans-dqs-legal-card strong,.edabalans-dqs-legal-card span>span{display:block}' +
            '.edabalans-dqs-legal-card span>span{margin-top:6px;color:#716e67;font-size:15px}' +
            '.edabalans-dqs-legal-card a{display:inline-block;margin-top:10px;color:#94412d;font-size:14px;font-weight:800}' +
            '.edabalans-dqs-legal-action{width:100%;margin-top:18px;padding:14px 20px;border:0;border-radius:14px;background:#25241f;color:#fff;font-size:16px;font-weight:850;cursor:pointer}' +
            '.edabalans-dqs-legal-action:disabled{background:#d8d1c7;color:#817b73;cursor:default}' +
            '.edabalans-dqs-legal-error{min-height:21px;margin:10px 0 0;color:#9b3725;text-align:center;font-size:14px}' +
            '@media(max-width:600px){.edabalans-dqs-legal-shell{padding:14px}.edabalans-dqs-legal-window{padding:21px 16px}}' +
            '</style><section class="edabalans-dqs-legal-shell"><div class="edabalans-dqs-legal-window" role="dialog" aria-modal="true" aria-label="Подтверждение документов">' +
            '<p>Чтобы пользоваться личным кабинетом, прочитайте дисклеймер и политику обработки персональных данных.</p>' +
            '<div class="edabalans-dqs-legal-list">' + cards + '</div>' +
            '<button class="edabalans-dqs-legal-action" type="button" disabled>Принять и продолжить</button>' +
            '<p class="edabalans-dqs-legal-error" aria-live="polite"></p></div></section>';
          var boxes = Array.prototype.slice.call(mount.querySelectorAll('[data-edabalans-dqs-legal]'));
          var button = mount.querySelector('.edabalans-dqs-legal-action');
          var error = mount.querySelector('.edabalans-dqs-legal-error');
          function update() {
            button.disabled = !boxes.length || !boxes.every(function (box) { return box.checked; });
          }
          boxes.forEach(function (box) { box.addEventListener('change', update); });
          update();
          button.addEventListener('click', function () {
            button.disabled = true;
            error.textContent = 'Сохраняю подтверждение…';
            jsonRequest(APP_HOST + '/api/account/legal-acceptances', {
              method: 'POST',
              headers: {'Content-Type': 'application/json'},
              body: JSON.stringify({
                email: email,
                document_codes: documents.map(function (item) { return item.code; })
              })
            }).then(function (account) {
              if (account.legal && account.legal.required) {
                throw new Error('Подтверждение не сохранилось. Попробуйте ещё раз.');
              }
              resolve();
            }).catch(function (failure) {
              error.textContent = String(failure.message || failure);
              update();
            });
          });
        });
      });
  }

  function load(mount) {
    ensureAppShellStylesheet();
    var app = String(mount.getAttribute('data-edabalans-app') || '').toLowerCase();
    var adminUser = String(mount.getAttribute('data-edabalans-admin-user') || '');
    var placement = String(mount.getAttribute('data-edabalans-placement') || '');
    var placementToken = String(mount.getAttribute('data-edabalans-placement-token') || '');
    var accountOffer = mount.getAttribute('data-edabalans-account-offer') === 'true';
    var publicMasterclass = mount.getAttribute('data-edabalans-public-masterclass') === 'true';
    var focusProductCode = String(mount.getAttribute('data-edabalans-focus-product') || '');
    var accountUrl = String(
      mount.getAttribute('data-edabalans-account-url') ||
      (location.hostname === 'app.edabalans.ru' ? PUBLIC_ACCOUNT_URL : '/lk')
    );
    var linkToken = String(mount.getAttribute('data-edabalans-link-token') || new URLSearchParams(location.search).get('access_token') || '');
    if (!roots[app]) {
      mount.textContent = 'Неизвестное приложение: ' + app;
      return Promise.resolve();
    }
    beginLoading(mount, 'Загрузка страницы');
    readyRequests.delete(mount);
    var preflight = app === 'dqs' && !adminUser
      ? dqsLegalGate(mount)
      : Promise.resolve();
    return preflight.then(function () {
      beginLoading(mount, 'Загрузка страницы');
      return appHtml(app);
      })
      .then(function (html) {
        window.EdabalansAppHost = APP_HOST;
        window.EdabalansAppContext = adminUser
          ? {mode: 'admin', targetUserId: adminUser, app: app, placement: placement, placementToken: placementToken, accountUrl: accountUrl, linkToken: linkToken, accountOffer: accountOffer, publicMasterclass: publicMasterclass, focusProductCode: focusProductCode}
          : {mode: 'user', app: app, placement: placement, placementToken: placementToken, accountUrl: accountUrl, linkToken: linkToken, accountOffer: accountOffer, publicMasterclass: publicMasterclass, focusProductCode: focusProductCode};
        var doc = new DOMParser().parseFromString(html, 'text/html');
        var sourceRoot = doc.getElementById(roots[app]);
        mount.id = roots[app];
        mount.innerHTML = sourceRoot ? sourceRoot.innerHTML : '';
        Array.prototype.forEach.call(doc.querySelectorAll('style'), function (style) {
          var key = 'edabalans-style-' + app;
          if (!document.getElementById(key)) {
            var copy = document.createElement('style');
            copy.id = key;
            copy.textContent = style.textContent;
            document.head.appendChild(copy);
          }
        });
        if (mount.getAttribute('data-edabalans-inline') !== 'true') {
          ensureLegalFooter(mount);
        }
        // App-owned shared styles must also be mounted when HTML is embedded in /lk.
        beginLoading(mount, 'Загрузка оформления');
        var stylesheetLoads = Array.prototype.map.call(doc.querySelectorAll('link[rel="stylesheet"][href]'), function (source) { return loadStylesheet(source.getAttribute('href')); });
        return Promise.all(stylesheetLoads).then(function () { return executeScripts(doc); }).then(function () {
          beginLoading(mount, 'Загрузка материалов');
          return readyRequests.get(mount);
        }).then(function () {
          return document.fonts ? document.fonts.ready : null;
        }).then(function () { finishLoading(mount); });
      })
      .catch(function (error) {
        failLoading(mount, error, function () { load(mount); });
      });
  }

  function start(mounts) {
    mounts.forEach(load);
  }

  function boot() {
    var mounts = Array.prototype.slice.call(document.querySelectorAll('[data-edabalans-app]'))
      .filter(function (mount) { return mount.getAttribute('data-edabalans-manual') !== 'true'; });
    if (!mounts.length) return;
    beginLoading(mounts[0], 'Проверка авторизации');
    if (location.origin !== APP_HOST) {
      redirectToAccountLogin();
      return;
    }
    var appCode = String(mounts[0].getAttribute('data-edabalans-app') || '').toLowerCase();
    var telegram = window.Telegram && window.Telegram.WebApp;
    var hasTelegramInitData = Boolean(telegram && telegram.initData);
    var max = window.WebApp;
    var hasMaxInitData = Boolean(max && max.initData);
    prefetchAppHtml(appCode);
    if (hasTelegramInitData) {
      telegramMiniAppSession(appCode).then(function (telegramSession) {
        if (!telegramSession || !validEmail(telegramSession.email)) {
          showStandaloneAccessError(mounts[0], 'Telegram не привязан к личному кабинету');
          return;
        }
        rememberNative(normalizeEmail(telegramSession.email));
        start(mounts);
      }).catch(function (error) {
        showStandaloneAccessError(mounts[0], error.message || String(error));
      });
      return;
    }
    if (hasMaxInitData) {
      maxMiniAppSession(appCode).then(function (maxSession) {
        if (!maxSession || !validEmail(maxSession.email)) {
          showStandaloneAccessError(mounts[0], 'MAX не привязан к личному кабинету');
          return;
        }
        rememberNative(normalizeEmail(maxSession.email));
        start(mounts);
      }).catch(function (error) {
        showStandaloneAccessError(mounts[0], error.message || String(error));
      });
      return;
    }
    nativeSession().then(function (session) {
        if (!session.authenticated || !validEmail(session.email)) {
          redirectToAccountLogin();
          return;
        }
        rememberNative(normalizeEmail(session.email));
        start(mounts);
      }).catch(function (error) { failLoading(mounts[0], error, boot); });
  }

  window.EdabalansEmbed = {load: load, boot: boot, beginLoading: beginLoading, finishLoading: finishLoading, failLoading: failLoading, loadingHtml: loadingHtml, waitUntilReady: waitUntilReady};

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
}());
