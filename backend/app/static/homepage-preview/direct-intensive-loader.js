(function () {
  'use strict';

  var script = document.currentScript;
  var host = document.getElementById('edb-direct-intensive-host');
  var appHost = script && script.src
    ? new URL(script.src, window.location.href).origin
    : 'https://edabalans.ru';

  if (!host || host.dataset.edabalansLoaded === 'true') return;
  host.dataset.edabalansLoaded = 'true';
  host.setAttribute('aria-busy', 'true');

  [host, host.closest('.t123__centeredContainer'), host.closest('.t-rec')].forEach(function (element) {
    if (!element) return;
    element.style.width = '100%';
    element.style.maxWidth = 'none';
    element.style.margin = '0';
    element.style.padding = '0';
  });

  fetch(appHost + '/preview/direct-intensive?variant=motivation-hero', {
    credentials: 'omit',
    mode: 'cors',
    cache: 'no-store'
  })
    .then(function (response) {
      if (!response.ok) throw new Error('landing ' + response.status);
      return response.text();
    })
    .then(function (source) {
      var parsed = new DOMParser().parseFromString(source, 'text/html');
      var landing = parsed.getElementById('edb-direct-intensive-v1');
      var style = parsed.getElementById('edb-direct-intensive-v1-styles');
      if (!landing || !style) throw new Error('landing source is incomplete');

      if (!document.getElementById(style.id)) {
        document.head.appendChild(document.importNode(style, true));
      }
      landing.style.width = '100vw';
      landing.style.maxWidth = '100vw';
      landing.style.marginLeft = 'calc(50% - 50vw)';
      landing.style.marginRight = '0';
      host.replaceWith(document.importNode(landing, true));

      Array.prototype.forEach.call(parsed.querySelectorAll('script'), function (sourceScript) {
        var executable = document.createElement('script');
        executable.textContent = sourceScript.textContent;
        document.body.appendChild(executable);
      });
    })
    .catch(function (error) {
      host.removeAttribute('aria-busy');
      host.innerHTML = '<div style="max-width:760px;margin:40px auto;padding:20px;border:1px solid #d9eaf4;border-radius:16px;background:#fff;color:#334;line-height:1.5">Не удалось загрузить интенсив. Обновите страницу ещё раз.</div>';
      if (window.console && console.error) console.error('[edabalans direct intensive]', error);
    });
})();
