(function () {
  "use strict";

  function label(value) {
    var seconds = Math.max(0, Math.floor(Number(value) || 0));
    return Math.floor(seconds / 60) + ":" + String(seconds % 60).padStart(2, "0");
  }

  function chapters(root) {
    try {
      var parsed = JSON.parse(root.dataset.chapters || "[]");
      return Array.isArray(parsed) ? parsed.filter(function (item) {
        return Number.isFinite(item.at) && item.at >= 0 && typeof item.title === "string";
      }) : [];
    } catch (_error) {
      return [];
    }
  }

  function mountVideo(root) {
    var source = root.dataset.videoSrc;
    if (!source) return;

    var video = document.createElement("video");
    var play = document.createElement("button");
    video.src = source;
    video.className = "vp-video";
    video.playsInline = true;
    video.preload = "metadata";
    play.className = "vp-start";
    play.type = "button";
    play.setAttribute("aria-label", "Воспроизвести видео");
    play.textContent = "▶";

    function togglePlayback() {
      if (video.paused) video.play().catch(function () {});
      else video.pause();
    }

    play.addEventListener("click", togglePlayback);
    video.addEventListener("click", togglePlayback);
    video.addEventListener("play", function () { play.hidden = true; });
    video.addEventListener("pause", function () { play.hidden = video.ended; });
    root.prepend(video);
    root.append(play);
    root.querySelector(".vp-placeholder").hidden = true;
    root.addEventListener("edabalans:video-chapter-selected", function (event) {
      video.currentTime = event.detail.at;
      video.play().catch(function () {});
    });
  }

  function mount(root) {
    if (root.dataset.videoPlayerMounted) return;
    root.dataset.videoPlayerMounted = "true";
    var entries = chapters(root);
    root.classList.add("video-player");
    root.dataset.outlineOpen = "false";
    root.innerHTML = '<div class="vp-placeholder"><p>Предпросмотр навигации</p><h2>' + String(root.dataset.title || "Видео появится здесь") + '</h2></div><button class="vp-outline-toggle" type="button" aria-expanded="false">☰ Содержание</button><aside class="vp-outline" aria-label="Содержание видео"><header class="vp-outline-head"><div><small>Видео</small><strong>Содержание</strong></div><button class="vp-outline-close" type="button" aria-label="Закрыть содержание">×</button></header><div class="vp-outline-list">' + (entries.length ? entries.map(function (item, index) {
      return '<button class="vp-outline-item" type="button" data-video-chapter="' + index + '"><time>' + label(item.at) + '</time><span>' + item.title + '</span></button>';
    }).join("") : '<p class="vp-outline-empty">Разделы появятся вместе с видео.</p>') + '</div><p class="vp-outline-hint">Нажатие на раздел будет переводить видео к нужному моменту.</p></aside>';

    var toggle = root.querySelector(".vp-outline-toggle");
    var close = root.querySelector(".vp-outline-close");
    function setOpen(value) {
      root.dataset.outlineOpen = String(value);
      toggle.setAttribute("aria-expanded", String(value));
      if (value) close.focus();
    }

    toggle.addEventListener("click", function () { setOpen(root.dataset.outlineOpen !== "true"); });
    close.addEventListener("click", function () { setOpen(false); toggle.focus(); });
    root.querySelectorAll("[data-video-chapter]").forEach(function (button) {
      button.addEventListener("click", function () {
        var chapter = entries[Number(button.dataset.videoChapter)];
        root.querySelectorAll("[aria-current]").forEach(function (item) { item.removeAttribute("aria-current"); });
        button.setAttribute("aria-current", "true");
        root.dispatchEvent(new CustomEvent("edabalans:video-chapter-selected", { bubbles: true, detail: { at: chapter.at, title: chapter.title } }));
        setOpen(false);
        toggle.focus();
      });
    });
    mountVideo(root);
  }

  function boot() { document.querySelectorAll("[data-video-player]").forEach(mount); }
  window.EdabalansVideoPlayer = { mount: mount, boot: boot };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
}());
