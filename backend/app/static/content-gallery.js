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
      ? {src: item, alt: ''}
      : {src: String(item && item.src || ''), alt: String(item && item.alt || '')};
  }

  function markup(items) {
    var images = (items || []).map(imageData).filter(function (item) { return item.src; });
    if (!images.length) return '';
    return '<section class="eb-content-gallery" data-eb-content-gallery>' +
      '<div class="eb-content-gallery__wrap">' +
      (images.length > 1 ? '<button class="eb-content-gallery__slider-previous" type="button" aria-label="Назад">‹</button>' : '') +
      '<div class="eb-content-gallery__slider"><div class="eb-content-gallery__track">' +
      images.map(function (item) {
        return '<img src="' + escapeHtml(item.src) + '" alt="' + escapeHtml(item.alt) + '">';
      }).join('') +
      '</div></div>' +
      (images.length > 1 ? '<button class="eb-content-gallery__slider-next" type="button" aria-label="Вперёд">›</button>' : '') +
      '</div><div class="eb-content-gallery__counter">Листайте → 1 / ' + images.length + '</div>' +
      '<div class="eb-content-gallery__lightbox" aria-hidden="true"><button class="eb-content-gallery__lightbox-close" type="button" aria-label="Закрыть">×</button><button class="eb-content-gallery__lightbox-previous" type="button" aria-label="Назад">‹</button><img class="eb-content-gallery__lightbox-image" src="" alt=""><button class="eb-content-gallery__lightbox-next" type="button" aria-label="Вперёд">›</button></div></section>';
  }

  function bind(root) {
    (root || document).querySelectorAll('[data-eb-content-gallery]').forEach(function (gallery) {
      if (gallery.dataset.ebContentGalleryBound) return;
      gallery.dataset.ebContentGalleryBound = 'true';
      var slider = gallery.querySelector('.eb-content-gallery__slider');
      var images = Array.from(gallery.querySelectorAll('.eb-content-gallery__track img'));
      var counter = gallery.querySelector('.eb-content-gallery__counter');
      var sliderPrevious = gallery.querySelector('.eb-content-gallery__slider-previous');
      var sliderNext = gallery.querySelector('.eb-content-gallery__slider-next');
      var lightbox = gallery.querySelector('.eb-content-gallery__lightbox');
      var lightboxImage = gallery.querySelector('.eb-content-gallery__lightbox-image');
      var close = gallery.querySelector('.eb-content-gallery__lightbox-close');
      var previous = gallery.querySelector('.eb-content-gallery__lightbox-previous');
      var next = gallery.querySelector('.eb-content-gallery__lightbox-next');
      var index = 0;
      var sliderIndex = 0;
      var touchStartX = 0;

      function updateSliderState() {
        var sliderRect = slider.getBoundingClientRect();
        var closestIndex = 0;
        var closestDistance = Infinity;
        images.forEach(function (image, imageIndex) {
          var rect = image.getBoundingClientRect();
          var distance = Math.abs(rect.left - sliderRect.left);
          if (distance < closestDistance) {
            closestDistance = distance;
            closestIndex = imageIndex;
          }
        });
        sliderIndex = closestIndex;
        counter.textContent = 'Листайте → ' + (sliderIndex + 1) + ' / ' + images.length;
        if (sliderPrevious) sliderPrevious.disabled = sliderIndex === 0;
        if (sliderNext) sliderNext.disabled = sliderIndex === images.length - 1;
      }

      function scrollToImage(imageIndex) {
        if (imageIndex < 0 || imageIndex >= images.length) return;
        var sliderRect = slider.getBoundingClientRect();
        var imageRect = images[imageIndex].getBoundingClientRect();
        slider.scrollTo({
          left: slider.scrollLeft + (imageRect.left - sliderRect.left),
          behavior: 'smooth'
        });
      }

      function updateLightbox() {
        lightboxImage.src = images[index].src;
        lightboxImage.alt = images[index].alt;
        previous.disabled = index === 0;
        next.disabled = index === images.length - 1;
      }

      function closeLightbox() {
        lightbox.classList.remove('active');
        lightbox.setAttribute('aria-hidden', 'true');
        document.body.style.overflow = '';
      }

      slider.addEventListener('scroll', updateSliderState, {passive: true});
      if (sliderPrevious) sliderPrevious.onclick = function () { scrollToImage(sliderIndex - 1); };
      if (sliderNext) sliderNext.onclick = function () { scrollToImage(sliderIndex + 1); };
      updateSliderState();

      images.forEach(function (image, imageIndex) {
        image.onclick = function () {
          index = imageIndex;
          updateLightbox();
          lightbox.classList.add('active');
          lightbox.setAttribute('aria-hidden', 'false');
          document.body.style.overflow = 'hidden';
        };
      });
      previous.onclick = function (event) {
        event.stopPropagation();
        if (index > 0) {
          index -= 1;
          updateLightbox();
        }
      };
      next.onclick = function (event) {
        event.stopPropagation();
        if (index < images.length - 1) {
          index += 1;
          updateLightbox();
        }
      };
      close.onclick = function (event) {
        event.stopPropagation();
        closeLightbox();
      };
      lightbox.onclick = function (event) {
        if (event.target === lightbox) closeLightbox();
      };
      lightbox.addEventListener('touchstart', function (event) {
        if (event.touches.length === 1) touchStartX = event.touches[0].clientX;
      }, {passive: true});
      lightbox.addEventListener('touchend', function (event) {
        if (event.changedTouches.length !== 1) return;
        var difference = event.changedTouches[0].clientX - touchStartX;
        if (Math.abs(difference) < 50) return;
        if (difference < 0 && index < images.length - 1) {
          index += 1;
          updateLightbox();
        }
        if (difference > 0 && index > 0) {
          index -= 1;
          updateLightbox();
        }
      }, {passive: true});
      document.addEventListener('keydown', function (event) {
        if (!lightbox.classList.contains('active')) return;
        if (event.key === 'ArrowRight' && index < images.length - 1) {
          index += 1;
          updateLightbox();
        }
        if (event.key === 'ArrowLeft' && index > 0) {
          index -= 1;
          updateLightbox();
        }
        if (event.key === 'Escape') closeLightbox();
      });
    });
  }

  function addStyles() {
    if (document.getElementById('eb-content-gallery-styles')) return;
    var style = document.createElement('style');
    style.id = 'eb-content-gallery-styles';
    style.textContent = '.eb-content-gallery__wrap{position:relative}.eb-content-gallery__slider{margin:16px 0 8px;overflow-x:auto;scroll-snap-type:x mandatory;-webkit-overflow-scrolling:touch;scrollbar-width:none;scroll-behavior:smooth}.eb-content-gallery__slider::-webkit-scrollbar{display:none}.eb-content-gallery__track{display:flex;gap:10px;padding:0 16px}.eb-content-gallery__track img{flex:0 0 85%;width:85%;height:auto;border-radius:12px;scroll-snap-align:start;display:block;cursor:zoom-in}.eb-content-gallery__counter{text-align:center;font-size:16px;line-height:1;opacity:.65;margin-bottom:16px}.eb-content-gallery__slider-previous,.eb-content-gallery__slider-next{position:absolute;top:50%;transform:translateY(-50%);z-index:3;width:46px;height:64px;border:0;border-radius:10px;background:rgba(0,0,0,.45);color:#fff;font-size:42px;cursor:pointer}.eb-content-gallery__slider-previous{left:18px}.eb-content-gallery__slider-next{right:18px}.eb-content-gallery__slider-previous:disabled,.eb-content-gallery__slider-next:disabled{opacity:0;pointer-events:none}.eb-content-gallery__lightbox{position:fixed;inset:0;z-index:999999;display:none;align-items:center;justify-content:center;background:rgba(0,0,0,.94);padding:15px;overflow:auto}.eb-content-gallery__lightbox.active{display:flex}.eb-content-gallery__lightbox-image{max-width:95vw;max-height:95vh;width:auto;height:auto;object-fit:contain;display:block}.eb-content-gallery__lightbox-close,.eb-content-gallery__lightbox-previous,.eb-content-gallery__lightbox-next{position:absolute;z-index:2;border:0;background:rgba(0,0,0,.35);color:#fff;cursor:pointer}.eb-content-gallery__lightbox-close{top:15px;right:15px;width:44px;height:44px;border-radius:50%;font-size:30px}.eb-content-gallery__lightbox-previous,.eb-content-gallery__lightbox-next{top:50%;transform:translateY(-50%);width:50px;height:70px;font-size:50px;border-radius:10px}.eb-content-gallery__lightbox-previous{left:10px}.eb-content-gallery__lightbox-next{right:10px}.eb-content-gallery__lightbox-previous:disabled,.eb-content-gallery__lightbox-next:disabled{opacity:0;pointer-events:none}@media(max-width:767px){.eb-content-gallery__slider-previous,.eb-content-gallery__slider-next,.eb-content-gallery__lightbox-previous,.eb-content-gallery__lightbox-next{display:none}}@media(min-width:768px){.eb-content-gallery__track img{flex:0 0 auto;width:auto;max-height:90vh;max-width:85vw;object-fit:contain}}';
    document.head.appendChild(style);
  }

  addStyles();
  window.EdabalansContentGallery = {markup: markup, bind: bind};
}());
