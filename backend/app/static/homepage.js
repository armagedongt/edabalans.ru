(function () {
  'use strict';

  var script = document.currentScript;
  var appHost = script && script.src
    ? new URL(script.src, window.location.href).origin
    : 'https://app.edabalans.ru';
  var mount = document.querySelector('[data-edabalans-homepage]');

  if (!mount || mount.dataset.edabalansLoaded === 'true') return;
  mount.dataset.edabalansLoaded = 'true';
  mount.setAttribute('aria-busy', 'true');
  mount.innerHTML = '<div role="status" style="min-height:100vh;display:grid;place-items:center;text-align:center;color:#239fe9;font-family:Arial,sans-serif"><div><div aria-hidden="true" style="font-size:24px;line-height:1;letter-spacing:6px">•••</div><div style="margin-top:10px;font-size:14px">Загрузка</div></div></div>';

  function absolute(value, baseUrl) {
    if (!value || value.charAt(0) === '#') return value;
    return new URL(value, baseUrl).href;
  }

  function rewriteCss(source) {
    return String(source || '').replace(
      /url\(\s*(['"]?)\/(?!\/)/g,
      'url($1' + appHost + '/'
    );
  }

  function rewriteInlineScript(source) {
    return String(source || '').replace(
      /(['"`])\/api\//g,
      '$1' + appHost + '/api/'
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
    ['data-media-src', 'data-static-src'].forEach(function (attribute) {
      if (element.hasAttribute(attribute)) {
        element.setAttribute(attribute, absolute(element.getAttribute(attribute), baseUrl));
      }
    });
    ['data-pricing-endpoint', 'data-checkout-endpoint'].forEach(function (attribute) {
      if (element.hasAttribute(attribute)) {
        element.setAttribute(attribute, absolute(element.getAttribute(attribute), baseUrl));
      }
    });
    if (element.hasAttribute('href')) {
      var href = element.getAttribute('href');
      if (/^\/(?:preview|blog|assets)\//.test(href || '') || href === '/site-footer.js') {
        element.setAttribute('href', absolute(href, baseUrl));
      }
    }
  }

  function appendScript(sourceScript, baseUrl) {
    return new Promise(function (resolve, reject) {
      var executable = document.createElement('script');
      Array.prototype.forEach.call(sourceScript.attributes, function (attribute) {
        if (attribute.name !== 'src') executable.setAttribute(attribute.name, attribute.value);
      });
      if (sourceScript.src || sourceScript.getAttribute('src')) {
        executable.src = absolute(sourceScript.getAttribute('src'), baseUrl);
        executable.async = false;
        executable.onload = resolve;
        executable.onerror = function () {
          reject(new Error('Не удалось загрузить ' + executable.src));
        };
      } else {
        executable.textContent = rewriteInlineScript(sourceScript.textContent);
      }
      document.body.appendChild(executable);
      if (!executable.src) resolve();
    });
  }

  function prepareTildaShell() {
    var record = mount.closest('.t-rec');
    var container = mount.closest('.t123__centeredContainer');
    mount.style.width = '100%';
    mount.style.maxWidth = 'none';
    mount.style.margin = '0';
    mount.style.padding = '0';
    if (container) {
      container.style.width = '100%';
      container.style.maxWidth = 'none';
      container.style.margin = '0';
      container.style.padding = '0';
    }
    if (record) {
      record.style.width = '100%';
      record.style.maxWidth = 'none';
      record.style.margin = '0';
      record.style.padding = '0';
    }
  }

  function showFailure(error) {
    mount.removeAttribute('aria-busy');
    mount.innerHTML = '<div style="max-width:760px;margin:40px auto;padding:20px;border:1px solid #d9eaf4;border-radius:16px;background:#fff;color:#334;line-height:1.5">Не удалось загрузить страницу. Обновите её ещё раз.</div>';
    if (window.console && console.error) console.error('[edabalans homepage]', error);
  }

  prepareTildaShell();
  fetch(appHost + '/preview/homepage-mobile?theme=blue-mist&embed=tilda', {
    credentials: 'omit',
    mode: 'cors',
    cache: 'no-store'
  }).then(function (response) {
    if (!response.ok) throw new Error('homepage ' + response.status);
    return response.text().then(function (html) {
      return {html: html, baseUrl: response.url};
    });
  }).then(function (result) {
    var parsed = new DOMParser().parseFromString(result.html, 'text/html');
    var scripts = Array.prototype.slice.call(parsed.querySelectorAll('script'));
    var headAssets = Array.prototype.slice.call(
      parsed.head.querySelectorAll('style,link[rel="stylesheet"]')
    );

    headAssets.forEach(function (asset, index) {
      if (asset.tagName === 'STYLE') {
        var style = document.createElement('style');
        style.id = 'edabalans-homepage-style-' + index;
        style.textContent = rewriteCss(asset.textContent);
        document.head.appendChild(style);
      } else {
        var link = document.createElement('link');
        link.id = 'edabalans-homepage-style-' + index;
        link.rel = 'stylesheet';
        link.href = absolute(asset.getAttribute('href'), result.baseUrl);
        document.head.appendChild(link);
      }
    });

    scripts.forEach(function (item) { item.remove(); });
    parsed.body.querySelectorAll('*').forEach(function (element) {
      prepareElement(element, result.baseUrl);
    });
    Array.prototype.forEach.call(parsed.body.attributes, function (attribute) {
      if (attribute.name.indexOf('data-') === 0) {
        document.body.setAttribute(attribute.name, attribute.value);
      }
    });

    var fragment = document.createDocumentFragment();
    while (parsed.body.firstChild) fragment.appendChild(parsed.body.firstChild);
    mount.replaceChildren(fragment);
    mount.removeAttribute('aria-busy');

    return scripts.reduce(function (chain, item) {
      return chain.then(function () { return appendScript(item, result.baseUrl); });
    }, Promise.resolve());
  }).catch(showFailure);
})();
