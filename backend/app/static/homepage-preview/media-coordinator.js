(() => {
  const frameSelector = 'iframe[data-media-player]';
  let activeFrame = null;

  const frames = () => [...document.querySelectorAll(frameSelector)];
  const localMedia = () => [...document.querySelectorAll('audio,video')];
  const pauseFrame = (frame) => {
    frame.contentWindow?.postMessage({ type: 'edabalans:pause-player' }, location.origin);
  };
  const pauseLocalMedia = (except = null) => {
    localMedia().forEach((media) => {
      if (media !== except && !media.paused) media.pause();
    });
  };
  const pauseOtherFrames = (except = null) => {
    frames().forEach((frame) => {
      if (frame !== except) pauseFrame(frame);
    });
  };

  document.addEventListener('play', (event) => {
    const media = event.target;
    if (!(media instanceof HTMLMediaElement)) return;
    activeFrame = null;
    pauseLocalMedia(media);
    pauseOtherFrames();
  }, true);

  window.addEventListener('message', (event) => {
    if (event.origin !== location.origin) return;
    const frame = frames().find((candidate) => event.source === candidate.contentWindow) || null;
    if (!frame) return;
    if (event.data?.type === 'edabalans:player-idle') {
      if (activeFrame === frame) activeFrame = null;
      return;
    }
    if (event.data?.type !== 'edabalans:player-active') return;
    activeFrame = frame;
    pauseLocalMedia();
    pauseOtherFrames(frame);
  });

  document.addEventListener('load', (event) => {
    const frame = event.target;
    if (!(frame instanceof HTMLIFrameElement) || !frame.matches(frameSelector)) return;
    const audibleLocalMedia = localMedia().some((media) => !media.paused && !media.muted);
    if (audibleLocalMedia || (activeFrame && activeFrame !== frame)) {
      pauseFrame(frame);
      return;
    }
    if (frame.dataset.mediaContext === 'anya-review') pauseOtherFrames(frame);
  }, true);

  window.EdaMediaCoordinator = Object.freeze({
    pauseAll() {
      activeFrame = null;
      pauseLocalMedia();
      pauseOtherFrames();
    }
  });
})();
