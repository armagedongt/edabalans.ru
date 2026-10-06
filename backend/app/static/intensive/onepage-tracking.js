(function () {
  "use strict";
  const article = document.querySelector("[data-intensive-onepage]");
  if (!article || article.dataset.trackingStarted) return;
  article.dataset.trackingStarted = "true";

  const COUNTER_ID = 97331502;
  const LOCAL = ["localhost", "127.0.0.1", "[::1]"].includes(location.hostname) || location.protocol === "file:";
  // Legacy personal links must not load the SDK: automatic requests read raw URLs too.
  const personalLink = value => { try {
    const query = new URL(value, location.href).searchParams;
    return query.has("i") || query.has("token");
  } catch (_) { return false; } };
  if (!LOCAL && (personalLink(location.href) || personalLink(document.referrer))) return;
  const ATTR_KEYS = ["utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term", "yclid", "alias"];
  const attribution = {};
  const params = new URLSearchParams(location.search);
  ATTR_KEYS.forEach(key => { if (params.get(key)) attribution[key] = params.get(key).slice(0, 256); });
  const common = {page_key: "intensive-onepage", article_revision: article.dataset.intensiveRevision || "draft", ...attribution};
  const once = new Set();
  const identified = article.dataset.intensiveIdentified === "true";
  const visitId = crypto.randomUUID();
  const headings = Array.from(article.querySelectorAll("h2,h3")).map(node => ({
    node, id: node.id || node.previousElementSibling?.getAttribute("data-intensive-section"),
    title: node.textContent.trim(), level: Number(node.tagName.slice(1))
  })).filter(heading => heading.id);
  let lastHeading = null, furthestHeading = null, nextSnapshot = 15000;
  const sections = Array.from(article.querySelectorAll("[data-intensive-section], [data-intensive-end]"));
  const end = article.querySelector("[data-intensive-end]");
  const header = document.querySelector(".reading-header");
  const contents = document.querySelector("#contents");
  const blockSelector = "p,li,h1,h2,h3,blockquote";
  // Leaf text blocks avoid counting nested lists/quotes twice. Images are not reading progress.
  const blocks = Array.from(article.querySelectorAll(blockSelector))
    .filter(node => !node.querySelector(blockSelector) && (node.compareDocumentPosition(end) & Node.DOCUMENT_POSITION_FOLLOWING))
    .map(node => ({node, length: node.textContent.trim().length, ranges: []}));
  const total = blocks.reduce((sum, block) => sum + block.length, 0);
  let activeMs = 0, coverage = 0, maxDepth = 0, frame = 0;
  let lastTick = performance.now(), lastActivity = lastTick;
  let foreground = !document.hidden && document.hasFocus();
  let checkpoint = "", suspended = false;
  const snapshots = [];
  if (LOCAL) window.__intensiveOnepagePreviewEvents = snapshots;

  function safeUrl(value) {
    if (!value) return "";
    try {
      const url = new URL(value, location.href);
      if (!/^https?:$/.test(url.protocol)) return "";
      const clean = new URL(url.origin + url.pathname);
      ATTR_KEYS.forEach(key => { if (url.searchParams.get(key)) clean.searchParams.set(key, url.searchParams.get(key).slice(0, 256)); });
      return clean.href;
    } catch (_) { return ""; }
  }

  function loadMetrika() {
    if (LOCAL) return;
    const queued = Array.from(window.ym && window.ym.a || []).some(call => call[0] === COUNTER_ID && call[1] === "init");
    const initialized = window["yaCounter" + COUNTER_ID] || queued;
    window.ym = window.ym || function () { (window.ym.a = window.ym.a || []).push(arguments); };
    window.ym.l = window.ym.l || Date.now();
    if (!document.querySelector('script[src*="mc.yandex.ru/metrika/tag.js"]')) {
      const script = document.createElement("script");
      script.async = true;
      script.src = "https://mc.yandex.ru/metrika/tag.js";
      document.head.appendChild(script);
    }
    if (!initialized) {
      // The explicit pageview carries only the attribution used by this article.
      window.ym(COUNTER_ID, "init", {defer: true, clickmap: true, trackLinks: false, accurateTrackBounce: true, webvisor: false});
      window.ym(COUNTER_ID, "hit", safeUrl(location.href), {referer: safeUrl(document.referrer), params: common});
    }
  }

  function summary() {
    return {...(furthestHeading ? {furthest_heading_id: furthestHeading.id, furthest_heading_title: furthestHeading.title} : {}), ...(lastHeading ? {heading_id: lastHeading.id, heading_title: lastHeading.title} : {}), active_seconds: Math.floor(activeMs / 1000), viewed_percent: Math.floor(coverage), max_depth_percent: Math.floor(maxDepth)};
  }
  function track(eventType, detail = {}, uniqueKey) {
    if (uniqueKey && once.has(uniqueKey)) return;
    if (uniqueKey) once.add(uniqueKey);
    const data = {...common, ...summary(), visit_id: visitId, ...detail};
    if (LOCAL) snapshots.push({event_type: eventType, ...data});
    else window.ym(COUNTER_ID, "reachGoal", eventType, data);
    // Only a server-rendered signed session writes personal facts for future reminders.
    if (!LOCAL && identified) {
      const channelClick = ["intensive_onepage_telegram_click", "intensive_onepage_max_click"].includes(eventType);
      if (channelClick || ["intensive_onepage_open", "intensive_onepage_section", "intensive_onepage_end",
        "intensive_onepage_reading_start", "intensive_onepage_heading", "intensive_onepage_session",
        "intensive_onepage_view_10", "intensive_onepage_view_25", "intensive_onepage_view_50",
        "intensive_onepage_view_75", "intensive_onepage_view_90"].includes(eventType)) {
        fetch("/api/intensive/events", {method: "POST", credentials: "same-origin", keepalive: true,
          headers: {"Content-Type": "application/json"}, body: JSON.stringify({
            event_type: channelClick ? "intensive_onepage_messenger_click" :
              (eventType === "intensive_onepage_session" || eventType.startsWith("intensive_onepage_view_")) ? "intensive_onepage_progress" : eventType,
            event_id: crypto.randomUUID(), visit_id: visitId, article_revision: common.article_revision,
            ...summary(), ...detail
          })}).catch(() => {});
      }
    }
  }
  function mergeRange(block, start, finish) {
    const ranges = [...block.ranges, [start, finish]].sort((a, b) => a[0] - b[0]);
    block.ranges = [];
    for (const range of ranges) {
      const previous = block.ranges[block.ranges.length - 1];
      if (previous && range[0] <= previous[1]) previous[1] = Math.max(previous[1], range[1]);
      else block.ranges.push(range);
    }
  }
  function accountTime() {
    const now = performance.now();
    if (foreground && !suspended && !contents?.open) activeMs += Math.max(0, Math.min(now, lastActivity + 60000) - lastTick);
    lastTick = now;
    if (activeMs >= 60000) track("intensive_onepage_active_60", {}, "active60");
  }
  function sample() {
    frame = 0;
    if (document.hidden || !document.hasFocus() || suspended || contents?.open) return;
    const top = Math.max(0, header ? header.getBoundingClientRect().bottom : 0);
    const bottom = window.innerHeight;
    for (const block of blocks) {
      const rect = block.node.getBoundingClientRect();
      if (rect.height <= 0 || rect.bottom <= top || rect.top >= bottom) continue;
      mergeRange(block, Math.max(0, (top - rect.top) / rect.height), Math.min(1, (bottom - rect.top) / rect.height));
    }
    const viewed = blocks.reduce((sum, block) => sum + block.length * block.ranges.reduce((n, range) => n + range[1] - range[0], 0), 0);
    coverage = total ? Math.min(100, viewed / total * 100) : 0;
    const distance = Math.max(1, end.getBoundingClientRect().top + window.scrollY - window.innerHeight);
    maxDepth = Math.max(maxDepth, Math.min(100, Math.max(0, window.scrollY / distance * 100)));
    for (const heading of headings) {
      const rect = heading.node.getBoundingClientRect();
      if (rect.top < top - 5 || rect.bottom > bottom) continue;
      lastHeading = heading;
      if (!furthestHeading || headings.indexOf(heading) > headings.indexOf(furthestHeading)) furthestHeading = heading;
      track("intensive_onepage_heading", {heading_id: heading.id, heading_title: heading.title,
        heading_level: heading.level}, "heading:" + heading.id);
    }
    if (activeMs >= 10000 && coverage >= 1) track("intensive_onepage_reading_start", {}, "reading-start");
    [10, 25, 50, 75, 90].forEach(percent => {
      if (coverage >= percent) track("intensive_onepage_view_" + percent, {percent}, "view" + percent);
    });
    for (const marker of sections) {
      const y = marker.getBoundingClientRect().top;
      // Only visible boundaries count. A hash/fast jump never credits skipped sections.
      if (y < top - 5 || y > bottom) continue;
      const section = marker.getAttribute("data-intensive-section");
      if (section) track("intensive_onepage_section", {section}, "section:" + section);
      else track("intensive_onepage_end", {}, "end");
    }
  }
  function schedule() { if (!frame) frame = requestAnimationFrame(sample); }
  function activity() { accountTime(); lastActivity = performance.now(); }
  function reportSession() {
    accountTime();
    const next = JSON.stringify(summary());
    if (checkpoint !== next) { checkpoint = next; track("intensive_onepage_session"); }
  }
  function navigation() {
    const nav = performance.getEntriesByType("navigation")[0];
    if (!nav) return {};
    return {ttfb_ms: Math.round(nav.responseStart), dom_ms: Math.round(nav.domContentLoadedEventEnd), load_ms: Math.round(nav.loadEventEnd)};
  }
  function loaded() {
    const images = Array.from(article.querySelectorAll("img"));
    track("intensive_onepage_loaded", {...navigation(), images_total: images.length,
      images_loaded: images.filter(img => img.complete && img.naturalWidth > 0).length}, "loaded");
    schedule();
  }

  loadMetrika();
  track("intensive_onepage_open", {}, "open");
  const ready = () => track("intensive_onepage_ready", navigation(), "ready");
  if (document.readyState === "complete") ready();
  else document.addEventListener("DOMContentLoaded", () => setTimeout(ready, 0), {once: true});
  if (document.readyState === "complete") setTimeout(loaded, 0);
  else window.addEventListener("load", () => setTimeout(loaded, 0), {once: true});
  article.querySelectorAll("img").forEach((img, index) => {
    const fail = () => track("intensive_onepage_media_error", {image_index: index}, "image:" + index);
    img.addEventListener("error", fail, {once: true});
    if (img.complete && !img.naturalWidth) fail();
  });
  article.querySelectorAll("a[data-intensive-channel]").forEach(link => {
    const click = () => {
      accountTime();
      track("intensive_onepage_" + link.dataset.intensiveChannel + "_click", {messenger: link.dataset.intensiveChannel});
    };
    link.addEventListener("click", click);
    link.addEventListener("auxclick", event => { if (event.button === 1) click(); });
  });
  document.addEventListener("click", event => {
    const link = event.target.closest('a[href^="#"]');
    if (link && link.closest(".reading-header, #contents")) track("intensive_onepage_navigation", {
      target: link.getAttribute("href").slice(1, 80), source: link.closest(".reading-header") ? "header" : "contents"
    });
    if (event.target.closest(".toc-trigger")) track("intensive_onepage_contents_open");
  });
  ["pointerdown", "keydown", "wheel", "touchstart"].forEach(type => document.addEventListener(type, activity, {passive: true}));
  window.addEventListener("scroll", () => { activity(); schedule(); }, {passive: true});
  window.addEventListener("resize", schedule);
  window.addEventListener("hashchange", schedule);
  window.addEventListener("blur", () => { accountTime(); foreground = false; });
  window.addEventListener("focus", () => { lastTick = performance.now(); lastActivity = lastTick; foreground = !document.hidden; schedule(); });
  document.addEventListener("visibilitychange", () => {
    accountTime();
    foreground = !document.hidden && document.hasFocus();
    if (document.hidden) reportSession();
    else { lastTick = performance.now(); lastActivity = lastTick; schedule(); }
  });
  window.addEventListener("pagehide", () => { reportSession(); suspended = true; });
  window.addEventListener("pageshow", () => { suspended = false; lastTick = performance.now(); lastActivity = lastTick; foreground = !document.hidden && document.hasFocus(); schedule(); });
  if (window.ResizeObserver) new ResizeObserver(schedule).observe(article);
  setInterval(() => {
    accountTime(); sample();
    if (activeMs >= nextSnapshot) { nextSnapshot = activeMs + 15000; reportSession(); }
  }, 1000);
  schedule();
}());

