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
    mount.innerHTML = '<div style="padding:30px;text-align:center;font-family:Arial,sans-serif">Загрузка…</div>';
    return fetch(APP_HOST + '/apps/' + app + '.html', {cache: 'no-cache'})
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
