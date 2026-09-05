(function () {
  'use strict';

  var script = document.currentScript;
  var appHost = script && script.src
    ? new URL(script.src, window.location.href).origin
    : 'https://app.edabalans.ru';
  var mount = document.querySelector('[data-edabalans-intensive]');
  var attributionKeys = ['utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term', 'yclid', 'alias'];
  var currentParams = new URLSearchParams(window.location.search);

  if (!mount || mount.dataset.edabalansLoaded === 'true') return;
  mount.dataset.edabalansLoaded = 'true';
  mount.setAttribute('aria-busy', 'true');

  function absolute(value, baseUrl) {
    if (!value || value.charAt(0) === '#') return value;
    return new URL(value, baseUrl).href;
  }

  function attributed(value, baseUrl) {
    if (!value || value.charAt(0) === '#') return value;
    var target = new URL(value, baseUrl);
    attributionKeys.forEach(function (key) {
      var sourceValue = currentParams.get(key);
      if (sourceValue && !target.searchParams.has(key)) target.searchParams.set(key, sourceValue);
    });
    return target.href;
  }

  function rewriteCss(source) {
    return String(source || '').replace(
      /url\(\s*(['"]?)\/(?!\/)/g,
      'url($1' + appHost + '/'
    );
  }

  function rewriteSrcset(value, baseUrl) {
    return String(value || '').split(',').map(function (candidate) {
      var parts = candidate.trim().split(/\s+/);
      if (!parts[0]) return '';
      parts[0] = absolute(parts[0], baseUrl);
      return parts.join(' ');
    }).filter(Boolean).join(', ');
  }

  function prepareElement(element, baseUrl) {
    ['src', 'poster'].forEach(function (attribute) {
      if (element.hasAttribute(attribute)) {
        element.setAttribute(attribute, absolute(element.getAttribute(attribute), baseUrl));
      }
    });
    if (element.hasAttribute('srcset')) {
      element.setAttribute('srcset', rewriteSrcset(element.getAttribute('srcset'), baseUrl));
    }
    if (element.hasAttribute('href')) {
      element.setAttribute('href', attributed(element.getAttribute('href'), baseUrl));
    }
    if (element.hasAttribute('style')) {
      element.setAttribute('style', rewriteCss(element.getAttribute('style')));
    }
    if (element.hasAttribute('data-nav')) {
      try {
        var nav = JSON.parse(element.getAttribute('data-nav'));
        nav.forEach(function (item) {
          if (item && item.href) item.href = attributed(item.href, baseUrl);
        });
        element.setAttribute('data-nav', JSON.stringify(nav));
      } catch (_error) {}
    }
  }

  function prepareTildaShell() {
    var record = mount.closest('.t-rec');
    var container = mount.closest('.t123__centeredContainer');
    [mount, container, record].forEach(function (element) {
      if (!element) return;
      element.style.width = '100%';
      element.style.maxWidth = 'none';
      element.style.margin = '0';
      element.style.padding = '0';
    });
  }

  function appendHeadAssets(parsed, baseUrl) {
    Array.prototype.forEach.call(
      parsed.head.querySelectorAll('style,link[rel="stylesheet"]'),
      function (asset, index) {
        var id = 'edabalans-intensive-style-' + index;
        if (document.getElementById(id)) return;
        if (asset.tagName === 'STYLE') {
          var style = document.createElement('style');
          style.id = id;
          style.textContent = rewriteCss(asset.textContent);
          document.head.appendChild(style);
          return;
        }
        var link = document.createElement('link');
        link.id = id;
        link.rel = 'stylesheet';
        link.href = absolute(asset.getAttribute('href'), baseUrl);
        document.head.appendChild(link);
      }
    );
  }

  function loadSharedScript(id, path, ready) {
    if (ready()) return Promise.resolve();
    var existing = document.getElementById(id);
    if (existing) {
      return new Promise(function (resolve) {
        existing.addEventListener('load', resolve, {once: true});
        setTimeout(resolve, 1000);
      });
    }
    return new Promise(function (resolve, reject) {
      var shared = document.createElement('script');
      shared.id = id;
      shared.src = appHost + path;
      shared.onload = resolve;
      shared.onerror = reject;
      document.body.appendChild(shared);
    });
  }

  function showFailure(error) {
    mount.removeAttribute('aria-busy');
    mount.innerHTML = '<div style="max-width:760px;margin:40px auto;padding:20px;border:1px solid #d9eaf4;border-radius:16px;background:#fff;color:#334;line-height:1.5">Не удалось загрузить интенсив. Обновите страницу ещё раз.</div>';
    if (window.console && console.error) console.error('[edabalans intensive]', error);
  }

  function ensureMetrika() {
    window.ym = window.ym || function () {
      (window.ym.a = window.ym.a || []).push(arguments);
    };
    window.ym.l = window.ym.l || Date.now();
    if (document.querySelector('script[src*="mc.yandex.ru/metrika/tag.js"]')) return;
    var metrika = document.createElement('script');
    metrika.async = true;
    metrika.dataset.edabalansIntensiveMetrika = 'true';
    metrika.src = 'https://mc.yandex.ru/metrika/tag.js';
    document.head.appendChild(metrika);
    window.ym(97331502, 'init', {clickmap: true, trackLinks: true, accurateTrackBounce: true, webvisor: true});
  }

  function goal(code, payload, callback) {
    ensureMetrika();
    window.ym(97331502, 'reachGoal', code, payload, callback);
  }

  function attributionPayload() {
    var payload = {page_id: 'intensive_menu', embedded_in: 'tilda'};
    attributionKeys.forEach(function (key) {
      var value = currentParams.get(key);
      if (value) payload[key] = value;
    });
    return payload;
  }

  function bindMenuAnalytics() {
    var payload = attributionPayload();
    goal('intensive_home_open', payload);
    goal('intensive_menu_open', payload);
    Array.prototype.forEach.call(mount.querySelectorAll('.home-action'), function (link) {
      link.addEventListener('click', function (event) {
        event.preventDefault();
        var destination = link.href;
        var navigated = false;
        function navigate() {
          if (navigated) return;
          navigated = true;
          window.location.href = destination;
        }
        goal('intensive_masterclass_click', Object.assign({}, payload, {target_url: destination}), navigate);
        setTimeout(navigate, 800);
      });
    });
  }

  prepareTildaShell();
  fetch(appHost + '/intensive', {credentials: 'omit', mode: 'cors', cache: 'no-store'})
    .then(function (response) {
      if (!response.ok) throw new Error('intensive ' + response.status);
      return response.text().then(function (html) {
        return {html: html, baseUrl: response.url};
      });
    })
    .then(function (result) {
      var parsed = new DOMParser().parseFromString(result.html, 'text/html');
      var sourceRoot = parsed.querySelector('.intensive-page');
      if (!sourceRoot) throw new Error('intensive root not found');

      appendHeadAssets(parsed, result.baseUrl);
      Array.prototype.forEach.call(sourceRoot.querySelectorAll('[data-view]'), function (view) {
        if (view.getAttribute('data-view') !== 'menu') view.remove();
      });
      sourceRoot.dataset.activeView = 'menu';
      Array.prototype.forEach.call(sourceRoot.querySelectorAll('*'), function (element) {
        prepareElement(element, result.baseUrl);
      });

      mount.replaceChildren(sourceRoot);
      mount.removeAttribute('aria-busy');

      return Promise.all([
        loadSharedScript('edabalans-intensive-header', '/site-header.js', function () { return Boolean(window.EdabalansSiteHeader); }).catch(function () {}),
        loadSharedScript('edabalans-intensive-footer', '/site-footer.js', function () { return Boolean(window.EdabalansFooter); }).catch(function () {})
      ]).then(function () {
        if (window.EdabalansSiteHeader) window.EdabalansSiteHeader.boot(mount);
        if (window.EdabalansFooter) window.EdabalansFooter.boot(mount);
        bindMenuAnalytics();
      });
    })
    .catch(showFailure);
}());
