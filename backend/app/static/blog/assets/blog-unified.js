(function () {
  'use strict';
  var search = document.querySelector('.blog-search');
  var menu = document.querySelector('[data-site-menu-toggle]');
  var utilities = document.querySelector('.blog-header-utilities');
  var panel = document.querySelector('[data-site-menu]');
  var compactHeader = utilities && menu && panel ? window.matchMedia('(max-width: 1000px)') : null;
  if (utilities && menu && panel) {
    function placeUtilities() {
      if (search) search.open = false;
      if (compactHeader.matches) panel.querySelector('.site-menu-brand').after(utilities);
      else menu.before(utilities);
    }
    placeUtilities();
    compactHeader.addEventListener('change', placeUtilities);
  }
  if (search) {
    search.querySelector('summary').addEventListener('click', function () {
      if (!search.open && menu && (!compactHeader || !compactHeader.matches) && menu.getAttribute('aria-expanded') === 'true') menu.click();
    });
    search.addEventListener('toggle', function () {
      if (search.open) search.querySelector('input').focus();
    });
    if (menu) menu.addEventListener('click', function () { search.open = false; });
    document.addEventListener('click', function (event) {
      if (!search.contains(event.target)) search.open = false;
    });
    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape' && search.open) {
        search.open = false;
        search.querySelector('summary').focus();
      }
    });
  }
  var fold = document.querySelector('.starter-fold');
  if (fold) fold.addEventListener('toggle', function () {
    fold.querySelector('.fold-action').textContent = fold.open ? 'Свернуть' : 'Раскрыть';
  });

  var key = 'edabalans-blog-read-v1';
  function readSlugs() {
    try {
      var value = JSON.parse(localStorage.getItem(key) || '[]');
      return Array.isArray(value) ? value.filter(function (slug) { return typeof slug === 'string'; }) : [];
    } catch (_) { return []; }
  }
  function showReadMarks() {
    var read = readSlugs();
    document.querySelectorAll('.article-card .card-link, .starter-card .card-link').forEach(function (link) {
      var slug = new URL(link.href).pathname.split('/').pop();
      var mark = link.querySelector('.read-mark');
      if (read.indexOf(slug) !== -1 && !mark) {
        mark = document.createElement('span');
        mark.className = 'read-mark';
        mark.textContent = '✓ Прочитано';
        link.querySelector('.card-body').appendChild(mark);
      }
    });
  }
  showReadMarks();
  window.addEventListener('pageshow', showReadMarks);
  window.addEventListener('storage', function (event) { if (event.key === key) showReadMarks(); });
  var body = document.body.dataset.page === 'article' && document.getElementById('article');
  var canonical = document.querySelector('link[rel=canonical]');
  if (!body || !canonical) return;
  var path = new URL(canonical.href).pathname;
  if (!/^\/blog\/[^/]+$/.test(path)) return;
  var slug = path.split('/').pop();
  function trackRead() {
    // Depth is measured against the article body, excluding related cards/footer.
    var rect = body.getBoundingClientRect();
    if (rect.height <= 0 || window.innerHeight < rect.top + rect.height * 0.75) return;
    var read = readSlugs();
    if (read.indexOf(slug) === -1) {
      read.push(slug);
      try { localStorage.setItem(key, JSON.stringify(read)); } catch (_) {}
    }
    window.removeEventListener('scroll', trackRead);
    window.removeEventListener('resize', trackRead);
  }
  window.addEventListener('scroll', trackRead, {passive: true});
  window.addEventListener('resize', trackRead);
  window.addEventListener('load', trackRead, {once: true});
}());
