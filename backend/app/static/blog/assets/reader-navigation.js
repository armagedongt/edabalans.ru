(function () {
  'use strict';
  var bottom = document.querySelector('.reader-bottom');
  var top = document.getElementById('reader-top');
  if (!bottom || !top) return;
  bottom.hidden = false;
  top.addEventListener('click', function () {
    window.scrollTo({top: 0, behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth'});
  });
  var links = Array.from(document.querySelectorAll('[data-site-menu] .site-menu-contents a'));
  var headings = links.map(function (link) {
    return document.getElementById(link.getAttribute('href').slice(1));
  }).filter(Boolean);
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
