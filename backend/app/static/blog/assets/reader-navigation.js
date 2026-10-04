(function () {
  'use strict';
  var sheet = document.getElementById('reader-sheet');
  var menu = document.getElementById('reader-menu');
  var bottom = document.querySelector('.reader-bottom');
  if (!sheet || !menu || !bottom || typeof sheet.showModal !== 'function') return;
  var navigation = sheet.querySelector('.reader-site-menu');
  var originalNav = document.getElementById('public-blog-nav');
  // Reuse the live destinations and labels, not a second contact/product catalogue.
  Array.from(originalNav.querySelectorAll(':scope > a')).slice(1).forEach(function (link) {
    navigation.insertBefore(link.cloneNode(true), sheet.querySelector('.reader-account'));
  });
  var contacts = sheet.querySelector('#reader-contacts div');
  originalNav.querySelectorAll('.nav-contact-panel a').forEach(function (link) {
    contacts.appendChild(link.cloneNode(true));
  });
  bottom.hidden = false;
  menu.addEventListener('click', function () { sheet.showModal(); });
  sheet.querySelector('.reader-close').addEventListener('click', function () { sheet.close(); });
  sheet.addEventListener('close', function () { menu.focus({preventScroll: true}); });
  sheet.addEventListener('click', function (event) {
    if (event.target.closest('a')) sheet.close();
  });
  document.getElementById('reader-top').addEventListener('click', function () {
    window.scrollTo({top: 0, behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth'});
  });
  var links = Array.from(document.querySelectorAll('.reader-sidebar a, #reader-sheet ol a'));
  var headings = Array.from(document.querySelectorAll('#article > h2'));
  function onScroll() {
    bottom.classList.toggle('reader-scrolled', window.scrollY > 300);
    var current = headings[0];
    headings.forEach(function (heading) { if (heading.getBoundingClientRect().top <= 150) current = heading; });
    links.forEach(function (link) {
      if (current && link.getAttribute('href') === '#' + current.id) link.setAttribute('aria-current', 'location');
      else link.removeAttribute('aria-current');
    });
  }
  window.addEventListener('scroll', onScroll, {passive: true});
  onScroll();
}());
