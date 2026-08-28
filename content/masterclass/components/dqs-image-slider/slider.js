// Каноническое поведение всех галерей материалов, включая slider(...).
(function (global) {
  'use strict';

  function bindGallery(scope) {
    (scope || document).querySelectorAll('[data-gallery]').forEach(function (root) {
      if (root.dataset.galleryBound === 'true') return;
      var track = root.querySelector('.gallery-track');
      var slides = root.querySelectorAll('.gallery-slide');
      var counter = root.querySelector('.gallery-counter');
      var dots = root.querySelectorAll('.gallery-dot');
      var index = 0;
      var startX = 0;
      if (!track || !slides.length) return;

      function show(next) {
        index = (next + slides.length) % slides.length;
        track.style.transform = 'translateX(-' + (index * 100) + '%)';
        if (counter) counter.textContent = (index + 1) + ' / ' + slides.length;
        dots.forEach(function (dot, dotIndex) {
          dot.classList.toggle('active', dotIndex === index);
        });
        var active = dots[index];
        if (active && active.scrollIntoView) {
          active.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' });
        }
      }

      var previous = root.querySelector('.gallery-prev');
      var next = root.querySelector('.gallery-next');
      if (previous) previous.onclick = function () { show(index - 1); };
      if (next) next.onclick = function () { show(index + 1); };
      dots.forEach(function (dot) {
        dot.onclick = function () { show(Number(dot.dataset.slide)); };
      });
      var windowElement = root.querySelector('.gallery-window');
      if (windowElement) {
        windowElement.addEventListener('pointerdown', function (event) { startX = event.clientX; });
        windowElement.addEventListener('pointerup', function (event) {
          var shift = event.clientX - startX;
          if (Math.abs(shift) > 45) show(index + (shift < 0 ? 1 : -1));
        });
      }
      root.dataset.galleryBound = 'true';
      show(0);
    });
  }

  global.bindGallery = bindGallery;
})(window);
