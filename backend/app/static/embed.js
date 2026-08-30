(function () {
  'use strict';

  var APP_HOST = /^(localhost|127\.0\.0\.1)$/.test(location.hostname)
    ? location.origin
    : 'https://app.edabalans.ru';
  var STORAGE_IDENTITY = 'edabalans_identity_v1';
  var STORAGE_RETURN_PATH = 'edabalans_return_path_v1';
  var PUBLIC_ACCOUNT_URL = 'https://xn-----jlceacr3bggd8ajed5a6kl.xn--p1ai/lk';
  var TILDA_PROFILE_READER = 'https://members.tildaapi.com/frontend/js/tilda-members-init.min.js';
  var profileReaderPromise = null;
  var roots = {
    account: 'account-app',
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
  function detectTildaMemberEmail() {
    try {
      if (typeof window.tma__getProfileObjFromLS !== 'function') return '';
      var profile = window.tma__getProfileObjFromLS();
      var email = normalizeEmail(profile && profile.login);
      return validEmail(email) ? email : '';
    } catch (error) {
      return '';
    }
  }

  function waitForTildaEmail(onFound, onMissing) {
    var attempts = 0;
    var maxAttempts = 25;
    var timer = setInterval(function () {
      var email = detectTildaMemberEmail();
      attempts += 1;
      if (email) {
        clearInterval(timer);
        onFound(email);
        return;
      }
      if (attempts >= maxAttempts) {
        clearInterval(timer);
        onMissing();
      }
    }, 200);
  }

  function remember(email) {
    try {
      localStorage.setItem(STORAGE_IDENTITY, JSON.stringify({
        email: email,
        sessionToken: '',
        expiresAt: 0,
        source: 'tilda',
        confirmedAt: new Date().toISOString()
      }));
      localStorage.setItem('dqs_email', email);
    } catch (error) {}
    window.EdabalansIdentity = {email: email, sessionToken: '', source: 'tilda'};
    var marker = document.getElementById('edabalans-member-email');
    if (!marker) {
      marker = document.createElement('input');
      marker.id = 'edabalans-member-email';
      marker.name = 'member_email';
      marker.type = 'hidden';
      document.body.appendChild(marker);
    }
    marker.value = email;
  }

  function redirectToTildaLogin() {
    try {
      var returnPath = location.pathname + location.search + location.hash;
      if (returnPath.charAt(0) === '/' && returnPath.indexOf('//') !== 0 && returnPath.indexOf('/members/login') !== 0) {
        sessionStorage.setItem(STORAGE_RETURN_PATH, returnPath);
      }
      localStorage.removeItem(STORAGE_IDENTITY);
      localStorage.removeItem('dqs_email');
    } catch (error) {}
    window.EdabalansIdentity = null;
    location.replace('/members/login');
  }

  function ensureTildaProfileReader() {
    if (typeof window.tma__getProfileObjFromLS === 'function') return Promise.resolve();
    if (profileReaderPromise) return profileReaderPromise;
    profileReaderPromise = new Promise(function (resolve) {
      var existing = document.getElementById('tilda-membersarea-js') || document.getElementById('edabalans-tilda-profile-reader');
      if (existing) {
        existing.addEventListener('load', resolve, {once: true});
        setTimeout(resolve, 600);
        return;
      }
      var script = document.createElement('script');
      script.id = 'edabalans-tilda-profile-reader';
      script.src = TILDA_PROFILE_READER;
      script.async = true;
      script.onload = resolve;
      script.onerror = resolve;
      document.head.appendChild(script);
    });
    return profileReaderPromise;
  }

  function restoreReturnPath() {
    var returnPath = '';
    try {
      returnPath = String(sessionStorage.getItem(STORAGE_RETURN_PATH) || '');
      sessionStorage.removeItem(STORAGE_RETURN_PATH);
    } catch (error) {}
    if (!returnPath || returnPath.charAt(0) !== '/' || returnPath.indexOf('//') === 0 || returnPath.indexOf('://') >= 0) return false;
    var currentPath = location.pathname + location.search + location.hash;
    if (returnPath === currentPath) return false;
    location.replace(returnPath);
    return true;
  }

  function hideTildaUserbar() {
    if (document.getElementById('edabalans-hide-tilda-userbar')) return;
    var style = document.createElement('style');
    style.id = 'edabalans-hide-tilda-userbar';
    style.textContent = '.tlk-userbar,.tlk-userbar__popup,.tlk-userbar__user-icon,.t-userbar,[class^="tlk-userbar"],[class*=" tlk-userbar"]{display:none!important}';
    document.head.appendChild(style);
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
    var preflight = app === 'dqs' && !adminUser
      ? dqsLegalGate(mount)
      : Promise.resolve();
    return preflight.then(function () {
      mount.innerHTML = '<div style="padding:30px;text-align:center;font-family:Arial,sans-serif">Загрузка…</div>';
      return fetch(APP_HOST + '/apps/' + app + '.html', {cache: 'no-cache'});
    })
      .then(function (response) {
        if (!response.ok) throw new Error('Не удалось загрузить приложение');
        return response.text();
      })
      .then(function (html) {
        window.EdabalansAppHost = APP_HOST;
        window.EdabalansAppContext = adminUser
          ? {mode: 'admin', targetUserId: adminUser, app: app, placement: placement, placementToken: placementToken, accountUrl: accountUrl, linkToken: linkToken, accountOffer: accountOffer, focusProductCode: focusProductCode}
          : {mode: 'user', app: app, placement: placement, placementToken: placementToken, accountUrl: accountUrl, linkToken: linkToken, accountOffer: accountOffer, focusProductCode: focusProductCode};
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
        ensureLegalFooter(mount);
        return executeScripts(doc);
      })
      .catch(function (error) {
        mount.innerHTML = '<div style="padding:24px;color:#b42318;font-family:Arial,sans-serif">' + String(error.message || error) + '</div>';
      });
  }

  function start(mounts) {
    mounts.forEach(load);
  }

  function boot() {
    var mounts = Array.prototype.slice.call(document.querySelectorAll('[data-edabalans-app]'));
    if (!mounts.length) return;
    hideTildaUserbar();
    mounts[0].innerHTML = '<div style="padding:30px;text-align:center;font-family:Arial,sans-serif">Проверяю вход через Tilda…</div>';
    ensureTildaProfileReader().then(function () {
      var detected = detectTildaMemberEmail();
      if (detected) {
        remember(detected);
        if (restoreReturnPath()) return;
        start(mounts);
        return;
      }
      waitForTildaEmail(function (email) {
        remember(email);
        if (restoreReturnPath()) return;
        start(mounts);
      }, redirectToTildaLogin);
    });
  }

  window.EdabalansEmbed = {load: load, boot: boot};

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
}());
