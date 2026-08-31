(function () {
  var root = document.documentElement;
  var themeButton = document.querySelector('.theme-toggle');
  var storageKey = 'edabalans-blog-theme';
  var saved = null;
  try { saved = localStorage.getItem(storageKey); } catch (_) {}
  var preferredDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
  var initial = saved === 'dark' || saved === 'light' ? saved : (preferredDark ? 'dark' : 'light');

  function applyTheme(theme) {
    var dark = theme === 'dark';
    root.dataset.theme = dark ? 'dark' : 'light';
    if (!themeButton) return;
    var label = dark ? 'Включить светлую тему' : 'Включить тёмную тему';
    themeButton.setAttribute('aria-label', label);
    themeButton.setAttribute('title', label);
  }

  applyTheme(initial);
  if (themeButton) {
    themeButton.addEventListener('click', function () {
      var next = root.dataset.theme === 'dark' ? 'light' : 'dark';
      applyTheme(next);
      try { localStorage.setItem(storageKey, next); } catch (_) {}
    });
  }

  var cards = Array.prototype.slice.call(document.querySelectorAll('.articles-section > .article-grid .article-card'));
  var categoryButtons = Array.prototype.slice.call(document.querySelectorAll('[data-category-filter]'));
  var pagination = document.querySelector('.pagination');
  var emptyState = document.querySelector('.empty-state');
  var pageSize = 3;
  var activeCategory = 'all';
  var activePage = 1;

  function filteredCards() {
    return cards.filter(function (card) {
      return activeCategory === 'all' || card.dataset.category === activeCategory;
    });
  }

  function renderPagination(pageCount) {
    if (!pagination) return;
    pagination.innerHTML = '';
    if (pageCount <= 1) return;
    for (var page = 1; page <= pageCount; page += 1) {
      var button = document.createElement('button');
      button.className = 'page-link';
      button.type = 'button';
      button.textContent = String(page);
      button.dataset.pageLink = String(page);
      if (page === activePage) button.setAttribute('aria-current', 'page');
      pagination.appendChild(button);
    }
    if (activePage < pageCount) {
      var next = document.createElement('button');
      next.className = 'page-link next';
      next.type = 'button';
      next.textContent = 'Следующая';
      next.dataset.pageNext = 'true';
      pagination.appendChild(next);
    }
  }

  function showSelection(updateHistory) {
    if (!cards.length) return;
    var selected = filteredCards();
    var pageCount = Math.max(1, Math.ceil(selected.length / pageSize));
    activePage = Math.min(Math.max(activePage, 1), pageCount);
    cards.forEach(function (card) { card.hidden = true; });
    selected.slice((activePage - 1) * pageSize, activePage * pageSize).forEach(function (card) { card.hidden = false; });
    if (emptyState) emptyState.hidden = selected.length !== 0;
    renderPagination(pageCount);
    if (updateHistory) {
      var params = new URLSearchParams();
      if (activeCategory !== 'all') params.set('category', activeCategory);
      if (activePage > 1) params.set('page', String(activePage));
      history.pushState({}, '', (params.toString() ? '?' + params.toString() : location.pathname) + '#articles');
      document.getElementById('articles').scrollIntoView();
    }
  }

  if (cards.length) {
    var params = new URLSearchParams(location.search);
    var requestedCategory = params.get('category');
    if (requestedCategory && categoryButtons.some(function (button) { return button.dataset.categoryFilter === requestedCategory; })) activeCategory = requestedCategory;
    var requestedPage = Number(params.get('page') || 1);
    if (Number.isInteger(requestedPage) && requestedPage > 0) activePage = requestedPage;
    categoryButtons.forEach(function (button) {
      button.classList.toggle('active', button.dataset.categoryFilter === activeCategory);
      button.addEventListener('click', function () {
        activeCategory = button.dataset.categoryFilter;
        activePage = 1;
        categoryButtons.forEach(function (candidate) { candidate.classList.toggle('active', candidate === button); });
        showSelection(true);
      });
    });
    if (pagination) {
      pagination.addEventListener('click', function (event) {
        var target = event.target.closest('[data-page-link], [data-page-next]');
        if (!target) return;
        activePage = target.dataset.pageNext ? activePage + 1 : Number(target.dataset.pageLink);
        showSelection(true);
      });
    }
    showSelection(false);
  }

  var tocButton = document.querySelector('.toc-button');
  var tocPopover = document.querySelector('.toc-popover');
  function closeToc() {
    if (!tocButton || !tocPopover) return;
    tocButton.setAttribute('aria-expanded', 'false');
    tocPopover.hidden = true;
  }
  if (tocButton && tocPopover) {
    tocButton.addEventListener('click', function () {
      var open = tocButton.getAttribute('aria-expanded') === 'true';
      tocButton.setAttribute('aria-expanded', String(!open));
      tocPopover.hidden = open;
    });
    tocPopover.addEventListener('click', function (event) { if (event.target.closest('a')) closeToc(); });
    document.addEventListener('click', function (event) { if (!tocPopover.hidden && !event.target.closest('.toc-dock')) closeToc(); });
    document.addEventListener('keydown', function (event) { if (event.key === 'Escape') { closeToc(); tocButton.focus(); } });
  }

  var tocLinks = Array.prototype.slice.call(document.querySelectorAll('.toc-popover a, .toc-mobile a'));
  var mobileToc = document.querySelector('.toc-mobile');
  if (mobileToc) mobileToc.addEventListener('click', function (event) { if (event.target.closest('a')) mobileToc.open = false; });
  var tocHeadings = tocLinks.map(function (link) {
    return document.getElementById(decodeURIComponent(link.getAttribute('href').slice(1)));
  }).filter(Boolean);
  function updateTocCurrent() {
    if (!tocHeadings.length) return;
    var current = tocHeadings[0];
    var atPageEnd = window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 4;
    tocHeadings.forEach(function (heading) {
      if (heading.getBoundingClientRect().top <= 140) current = heading;
    });
    if (atPageEnd) current = tocHeadings[tocHeadings.length - 1];
    tocLinks.forEach(function (link) {
      if (link.getAttribute('href') === '#' + current.id) link.setAttribute('aria-current', 'location');
      else link.removeAttribute('aria-current');
    });
  }
  if (tocHeadings.length) {
    updateTocCurrent();
    window.addEventListener('scroll', updateTocCurrent, { passive: true });
  }
}());
