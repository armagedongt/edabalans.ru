(() => {
  const retentionMs = 72 * 60 * 60 * 1000;
  const blockSelector = 'p,li,h2,h3,h4,blockquote,figcaption,pre';

  function fingerprint(text) {
    let hash = 2166136261;
    for (const character of text.trim().replace(/\s+/g, ' ')) {
      hash = Math.imul(hash ^ character.codePointAt(0), 16777619);
    }
    return (hash >>> 0).toString(36);
  }

  function attach({article, target, account, headers, anchor, resume, controls, topOffset, end, remember = true, onRestore}) {
    const key = 'edabalans:reading:v1:' + JSON.stringify([account || 'anonymous', target]);
    const requestHeaders = {...headers, ...(account ? {'X-Reading-Account': encodeURIComponent(account)} : {})};
    const endpoint = '/api/account/reading-position?target=' + encodeURIComponent(target);
    const blocks = [...article.querySelectorAll(blockSelector)]
      .filter(node => !node.querySelector(blockSelector) && node.textContent.trim());
    const hashes = blocks.map(node => fingerprint(node.textContent));
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'reading-start';
    button.setAttribute('aria-label', 'В начало');
    button.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12 7-7 7 7M12 19V5"/></svg><span>В начало</span>';
    button.hidden = true;
    controls.append(button);

    let active = true;
    let ready = false;
    let dirty = false;
    let timer;
    let baseline = window.scrollY;
    let version = null;
    let writes = Promise.resolve();
    const stored = (() => {
      try { return JSON.parse(localStorage.getItem(key)); } catch { return null; }
    })();
    function readRemote() {
      return fetch(endpoint, {
        headers: requestHeaders, cache: 'no-store',
        signal: typeof AbortSignal.timeout === 'function' ? AbortSignal.timeout(2500) : undefined,
      }).then(response => response.ok ? response.json() : null).then(result => {
        if (result) version = result.version;
        return result;
      }).catch(() => null);
    }
    const remote = account ? readRemote() : Promise.resolve(null);

    function writeRemote(position) {
      return fetch(endpoint, {
        method: 'PUT', keepalive: true,
        headers: {...requestHeaders, 'Content-Type': 'application/json'},
        body: JSON.stringify({version, position}),
      });
    }

    function record(position, explicitReset = false) {
      if (!remember) return;
      const value = {position, saved_at: Date.now(), version: version ?? stored?.version ?? null};
      const serialized = JSON.stringify(value);
      try { localStorage.setItem(key, serialized); } catch {}
      if (!account) return;
      writes = writes.then(async () => {
        await remote;
        if (version == null && !(await readRemote())) return;
        let response = await writeRemote(position);
        if (response.status === 409) {
          const current = await readRemote();
          if (explicitReset && current) response = await writeRemote(null);
        }
        if (response.ok) {
          const saved = await response.json();
          version = saved.version;
          try {
            if (localStorage.getItem(key) === serialized) localStorage.setItem(key, JSON.stringify(saved));
          } catch {}
        }
        if (response.status === 409) {
          try {
            if (localStorage.getItem(key) === serialized) localStorage.removeItem(key);
          } catch {}
        }
      }).catch(() => {});
    }

    function capture() {
      if (!dirty || !ready || !article.isConnected) return;
      dirty = false;
      const edge = topOffset() + 2;
      let index = -1;
      for (const [i, node] of blocks.entries()) {
        if (!node.getClientRects().length) continue;
        if (node.getBoundingClientRect().top > edge) break;
        index = i;
      }
      record(index < 0 ? null : {index, fingerprint: hashes[index]});
    }

    function refreshButton() {
      button.hidden = window.scrollY < Math.max(180, topOffset() * 2);
    }

    function scroll() {
      if (!article.isConnected) { dispose(); return; }
      refreshButton();
      if (!ready || window.scrollY === baseline) return;
      baseline = window.scrollY;
      dirty = true;
      clearTimeout(timer);
      timer = setTimeout(capture, 350);
    }

    function finish() {
      if (!active) return;
      if (end?.getBoundingClientRect().top <= window.innerHeight + 4) {
        dirty = false;
        ready = false;
        record(null);
      }
    }

    function start() {
      dirty = false;
      clearTimeout(timer);
      record(null, true);
      if (location.hash) {
        const url = new URL(location.href);
        url.hash = '';
        history.replaceState(history.state, '', url);
      }
      window.scrollTo({top: 0, behavior: 'instant'});
      baseline = window.scrollY;
      refreshButton();
    }

    async function restore() {
      const initialY = window.scrollY;
      const synced = resume && !anchor ? await remote : null;
      if (!active || !article.isConnected) return;
      if (window.scrollY === initialY) {
        let block;
        if (anchor) {
          try { block = document.getElementById(decodeURIComponent(anchor.slice(1))); } catch {}
          if (!article.contains(block)) block = null;
        } else if (resume) {
          const useLocal = stored && (!synced || synced.version === 0 ||
            (stored.version === synced.version && stored.saved_at > synced.saved_at));
          const value = useLocal ? stored : synced;
          const saved = value && Date.now() - value.saved_at < retentionMs && value.position;
          if (saved) {
            if (hashes[saved.index] === saved.fingerprint) block = blocks[saved.index];
            else if (hashes.filter(hash => hash === saved.fingerprint).length === 1) {
              block = blocks[hashes.indexOf(saved.fingerprint)];
            }
          }
        }
        if (block?.getClientRects().length) {
          const top = () => window.scrollY + block.getBoundingClientRect().top - topOffset();
          onRestore?.();
          window.scrollTo({top: top(), behavior: 'instant'});
          const restoredY = window.scrollY;
          requestAnimationFrame(() => {
            if (!active || !article.isConnected || window.scrollY !== restoredY) return;
            window.scrollTo({top: top(), behavior: 'instant'});
            baseline = window.scrollY;
          });
        }
      }
      baseline = window.scrollY;
      ready = true;
      refreshButton();
    }

    button.addEventListener('click', start);
    window.addEventListener('scroll', scroll, {passive: true});
    window.addEventListener('pagehide', capture);
    window.addEventListener('popstate', capture, true);
    document.addEventListener('visibilitychange', saveWhenHidden);
    function saveWhenHidden(){ if (document.hidden) capture(); }
    requestAnimationFrame(restore);
    function dispose() {
      if (!active) return;
      if (article.isConnected) capture();
      active = false;
      clearTimeout(timer);
      window.removeEventListener('scroll', scroll);
      window.removeEventListener('pagehide', capture);
      window.removeEventListener('popstate', capture, true);
      document.removeEventListener('visibilitychange', saveWhenHidden);
      button.remove();
    }
    return {finish, dispose};
  }

  window.EdabalansReadingPosition = {attach};
})();
