(function () {
  'use strict';

  if (window.EdabalansContentGallery) return;

  function escapeHtml(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, function (char) {
      return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[char];
    });
  }

  function imageData(item, index) {
    return typeof item === 'string'
      ? {src: item, alt: 'Изображение ' + (index + 1)}
      : {src: String(item && item.src || ''), alt: String(item && item.alt || 'Изображение ' + (index + 1))};
  }

  function markup(items) {
    var images = (items || []).map(imageData).filter(function (item) { return item.src; });
    if (!images.length) return '';
    return '<section class="eb-content-gallery" data-eb-content-gallery>' +
      '<div class="eb-content-gallery__window"><div class="eb-content-gallery__track">' +
      images.map(function (item, index) {
        return '<figure class="eb-content-gallery__slide"><img src="' + escapeHtml(item.src) + '" alt="' + escapeHtml(item.alt) + '" loading="' + (index ? 'lazy' : 'eager') + '"></figure>';
      }).join('') +
      '</div>' +
      (images.length > 1 ? '<button class="eb-content-gallery__arrow eb-content-gallery__previous" type="button" aria-label="Предыдущее изображение">‹</button><button class="eb-content-gallery__arrow eb-content-gallery__next" type="button" aria-label="Следующее изображение">›</button>' : '') +
      '</div><div class="eb-content-gallery__footer"><span class="eb-content-gallery__counter">1 / ' + images.length + '</span></div>' +
      '<div class="eb-content-gallery__lightbox" aria-hidden="true"><img alt=""><button class="eb-content-gallery__arrow eb-content-gallery__previous" type="button" aria-label="Предыдущее изображение">‹</button><button class="eb-content-gallery__arrow eb-content-gallery__next" type="button" aria-label="Следующее изображение">›</button><button class="eb-content-gallery__close" type="button" aria-label="Закрыть">×</button></div></section>';
  }

  function bind(root) {
    (root || document).querySelectorAll('[data-eb-content-gallery]').forEach(function (gallery) {
      if (gallery.dataset.ebContentGalleryBound) return;
      gallery.dataset.ebContentGalleryBound = 'true';
      var track = gallery.querySelector('.eb-content-gallery__track');
      var slides = gallery.querySelectorAll('.eb-content-gallery__slide');
      var counter = gallery.querySelector('.eb-content-gallery__counter');
      var previous = gallery.querySelector('.eb-content-gallery__window .eb-content-gallery__previous');
      var next = gallery.querySelector('.eb-content-gallery__window .eb-content-gallery__next');
      var lightbox = gallery.querySelector('.eb-content-gallery__lightbox');
      var lightboxImage = lightbox.querySelector('img');
      var lightboxPrevious = lightbox.querySelector('.eb-content-gallery__previous');
      var lightboxNext = lightbox.querySelector('.eb-content-gallery__next');
      var close = gallery.querySelector('.eb-content-gallery__close');
      var index = 0;
      var touchStartX = 0;

      function show(value) {
        index = Math.max(0, Math.min(slides.length - 1, value));
        track.style.transform = 'translateX(-' + (index * 100) + '%)';
        counter.textContent = (index + 1) + ' / ' + slides.length;
        [previous, next, lightboxPrevious, lightboxNext].forEach(function (button) {
          if (!button) return;
          button.disabled = button.classList.contains('eb-content-gallery__previous') ? index === 0 : index === slides.length - 1;
        });
        if (lightbox.classList.contains('is-open')) {
          var image = slides[index].querySelector('img');
          lightboxImage.src = image.src;
          lightboxImage.alt = image.alt;
        }
      }

      function closeLightbox() {
        lightbox.classList.remove('is-open');
        lightbox.setAttribute('aria-hidden', 'true');
        document.body.classList.remove('eb-content-gallery-open');
      }

      function openLightbox(value) {
        show(value);
        lightbox.classList.add('is-open');
        lightbox.setAttribute('aria-hidden', 'false');
        document.body.classList.add('eb-content-gallery-open');
      }

      if (previous) previous.onclick = function () { show(index - 1); };
      if (next) next.onclick = function () { show(index + 1); };
      lightboxPrevious.onclick = function () { show(index - 1); };
      lightboxNext.onclick = function () { show(index + 1); };
      slides.forEach(function (slide, slideIndex) {
        slide.querySelector('img').onclick = function () { openLightbox(slideIndex); };
      });
      gallery.addEventListener('pointerdown', function (event) { touchStartX = event.clientX; });
      gallery.addEventListener('pointerup', function (event) {
        if (Math.abs(event.clientX - touchStartX) > 45) show(index + (event.clientX < touchStartX ? 1 : -1));
      });
      close.onclick = closeLightbox;
      lightbox.onclick = function (event) { if (event.target === lightbox) closeLightbox(); };
      document.addEventListener('keydown', function (event) {
        if (!lightbox.classList.contains('is-open')) return;
        if (event.key === 'Escape') closeLightbox();
        if (event.key === 'ArrowLeft') show(index - 1);
        if (event.key === 'ArrowRight') show(index + 1);
      });
      show(0);
    });
  }

  function addStyles() {
    if (document.getElementById('eb-content-gallery-styles')) return;
    var style = document.createElement('style');
    style.id = 'eb-content-gallery-styles';
    style.textContent = '.eb-content-gallery{margin:30px 0}.eb-content-gallery__window{position:relative;overflow:hidden;border-radius:20px;background:#eee8df;touch-action:pan-y}.eb-content-gallery__track{display:flex;transition:transform .28s ease}.eb-content-gallery__slide{flex:0 0 100%;margin:0!important}.eb-content-gallery__slide img{display:block;width:100%;height:auto;margin:0!important;cursor:zoom-in}.eb-content-gallery__arrow{position:absolute;top:50%;z-index:2;display:grid;place-items:center;width:44px;height:44px;border:0;border-radius:50%;background:#fffdf8e8;color:#24231f;box-shadow:0 5px 18px #261b1340;cursor:pointer;transform:translateY(-50%);font-size:23px}.eb-content-gallery__arrow:disabled{opacity:0;pointer-events:none}.eb-content-gallery__previous{left:12px}.eb-content-gallery__next{right:12px}.eb-content-gallery__footer{margin-top:9px;color:#716e67;font:600 12px/1.4 Inter,Arial,sans-serif;text-align:center}.eb-content-gallery__lightbox{position:fixed;inset:0;z-index:120100;display:none;align-items:center;justify-content:center;padding:22px;background:#171713e6}.eb-content-gallery__lightbox.is-open{display:flex}.eb-content-gallery__lightbox img{display:block;max-width:100%;max-height:92vh;object-fit:contain}.eb-content-gallery__close{position:absolute;top:18px;right:18px;width:42px;height:42px;border:0;border-radius:50%;background:#fff;color:#24231f;font-size:26px;cursor:pointer}.eb-content-gallery-open{overflow:hidden}@media(max-width:767px){.eb-content-gallery__arrow{display:none}}';
    document.head.appendChild(style);
  }

  addStyles();
  window.EdabalansContentGallery = {markup: markup, bind: bind};
}());
