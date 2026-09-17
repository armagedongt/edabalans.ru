(function () {
  'use strict';
  var host = document.querySelector('[data-edabalans-404]');
  if (!host || host.dataset.loading || host.dataset.mounted) return;
  host.dataset.loading = 'true';
  var origin = 'https://edabalans.ru';
  fetch(origin + '/public-site-errors/404-fragment.html', {credentials: 'omit', cache: 'no-store', referrerPolicy: 'no-referrer'})
    .then(function (response) {
      if (!response.ok) throw new Error('404 fragment unavailable');
      return response.text();
    })
    .then(function (html) {
      host.innerHTML = html;
      host.dataset.mounted = 'true';
      var robots = document.querySelector('meta[name="robots"]');
      if (!robots) { robots = document.createElement('meta'); robots.name = 'robots'; document.head.appendChild(robots); }
      robots.content = 'noindex,nofollow';
      ['site-header.js', 'site-footer.js'].forEach(function (name) {
        var script = document.createElement('script');
        script.src = origin + '/' + name;
        document.head.appendChild(script);
      });
    })
    .catch(function () { delete host.dataset.loading; });
})();
