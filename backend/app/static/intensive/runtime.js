(function () {
  "use strict";

  const COUNTER_ID = 97331502;
  const VERSION = "2026-09-04";
  const LOCAL_KEY = "edabalans:intensive:client:v2";
  const ATTR_KEYS = ["utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term", "yclid", "alias"];
  const MASTERCLASS_URL = "https://xn-----jlceacr3bggd8ajed5a6kl.xn--p1ai/#masterclass";
  const params = new URLSearchParams(location.search);
  const pathMatch = location.pathname.match(/\/intensive\/day-([1-4])/);
  const day = pathMatch ? Number(pathMatch[1]) : 0;
  const isLocalPreview = ["127.0.0.1", "localhost"].includes(location.hostname);
  let trustedPlatform = null;

  function uuid() {
    return crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }

  function readClientState() {
    let state = {};
    try { state = JSON.parse(localStorage.getItem(LOCAL_KEY) || "{}"); } catch (_error) {}
    if (!state.sessionId) state.sessionId = uuid();
    if (!state.attribution) state.attribution = {};
    if (!state.unlockAnnouncements) state.unlockAnnouncements = [];
    ATTR_KEYS.forEach((key) => {
      const value = params.get(key);
      if (value) state.attribution[key] = value;
    });
    saveClientState(state);
    return state;
  }

  function saveClientState(state) {
    try { localStorage.setItem(LOCAL_KEY, JSON.stringify(state)); } catch (_error) {}
  }

  async function loadServerState() {
    if (isLocalPreview && location.protocol === "file:") {
      return {identified: false, platform: null, opened_days: [], assignment_days: [], unlocked_days: [1, 2, 3, 4], unlock_at: {}, offer: null};
    }
    try {
      const response = await fetch("/api/intensive/state", {credentials: "same-origin", headers: {Accept: "application/json"}});
      if (response.ok) return await response.json();
    } catch (_error) {}
    return {identified: false, platform: null, opened_days: [], assignment_days: [], unlocked_days: [1, 2, 3, 4], unlock_at: {}, offer: null};
  }

  const clientState = readClientState();

  function addAttribution(url) {
    const target = new URL(url, location.origin);
    Object.entries(clientState.attribution).forEach(([key, value]) => {
      if (value && !target.searchParams.has(key)) target.searchParams.set(key, value);
    });
    return target.href;
  }

  function loadMetrika() {
    if (isLocalPreview) return;
    window.ym = window.ym || function () {
      (window.ym.a = window.ym.a || []).push(arguments);
    };
    window.ym.l = window.ym.l || Date.now();
    if (document.querySelector("script[data-edabalans-metrika]")) return;
    const script = document.createElement("script");
    script.async = true;
    script.dataset.edabalansMetrika = "true";
    script.src = "https://mc.yandex.ru/metrika/tag.js";
    document.head.appendChild(script);
    window.ym(COUNTER_ID, "init", {clickmap: true, trackLinks: true, accurateTrackBounce: true, webvisor: true});
  }

  function goal(code, extra, callback) {
    if (isLocalPreview) {
      if (callback) callback();
      return;
    }
    const payload = Object.assign({
      event_id: uuid(),
      occurred_at: new Date().toISOString(),
      page_id: day ? `intensive_day_${day}` : "intensive_menu",
      day: day || undefined,
      content_version: VERSION,
      session_id: clientState.sessionId,
      platform: trustedPlatform || undefined
    }, clientState.attribution, extra || {});
    if (window.ym) window.ym(COUNTER_ID, "reachGoal", code, payload, callback);
    else if (callback) callback();
  }

  function navigateAfterGoal(url, code, payload) {
    let navigated = false;
    const navigate = () => {
      if (navigated) return;
      navigated = true;
      location.href = url;
    };
    goal(code, payload, navigate);
    setTimeout(navigate, 800);
  }

  function formatRemaining(milliseconds) {
    const total = Math.max(0, Math.ceil(milliseconds / 1000));
    const hours = String(Math.floor(total / 3600)).padStart(2, "0");
    const minutes = String(Math.floor(total % 3600 / 60)).padStart(2, "0");
    const seconds = String(total % 60).padStart(2, "0");
    return `${hours}:${minutes}:${seconds}`;
  }

  function setupView() {
    const root = document.querySelector(".intensive-page");
    if (!root) return;
    root.dataset.activeView = day === 1 ? "day1" : "menu";
    root.dataset.day1Style = "creative";
    root.dataset.cardVariant = "numbers";
    document.querySelectorAll("[data-view]").forEach((section) => {
      section.hidden = section.dataset.view !== (day === 1 ? "day1" : "menu");
    });
    const player = document.querySelector("iframe[data-media-player]");
    if (player) player.src = day === 1 ? player.dataset.productionSrc : "about:blank";
    if (day === 1) {
      document.querySelectorAll(".intensive-skill-label[hidden]").forEach((label) => { label.hidden = false; });
      document.querySelectorAll(".skill-heading[data-creative-title]").forEach((heading) => { heading.textContent = heading.dataset.creativeTitle; });
    }
  }

  function isUnlocked(serverState, number) {
    return isLocalPreview || (serverState.unlocked_days || []).includes(number);
  }

  function setupMenu(serverState) {
    document.querySelectorAll(".day-card[data-day]").forEach((card) => {
      const number = Number(card.dataset.day);
      card.href = addAttribution(`/intensive/day-${number}`);
      if (!isUnlocked(serverState, number)) {
        card.classList.add("is-locked");
        card.setAttribute("aria-disabled", "true");
        card.addEventListener("click", (event) => event.preventDefault());
      }
    });
    document.querySelectorAll(".home-action").forEach((link) => {
      link.href = addAttribution(MASTERCLASS_URL);
      link.addEventListener("click", (event) => {
        event.preventDefault();
        navigateAfterGoal(link.href, "intensive_masterclass_click", {target_url: link.href});
      });
    });
  }

  function setupChannels(serverState) {
    document.querySelectorAll("[data-channel-block]").forEach((block) => {
      if (!serverState.identified) {
        block.hidden = true;
        return;
      }
      block.hidden = false;
      const actions = block.querySelector(".channel-actions");
      block.querySelectorAll("[data-channel]").forEach((link) => {
        const messenger = link.dataset.channel;
        if (serverState.identified && serverState.platform && messenger !== serverState.platform) link.hidden = true;
        link.removeAttribute("aria-disabled");
        link.href = "#";
        let clickLocked = false;
        link.addEventListener("click", async (event) => {
          event.preventDefault();
          if (clickLocked) return;
          clickLocked = true;
          goal(messenger === "telegram" ? "intensive_telegram_click" : "intensive_max_click", {
            messenger,
            target_url: link.href,
            alias: clientState.attribution.alias
          });
          try {
            const response = await fetch(`/api/intensive/day-${day}/post/${messenger}`, {
              method: "POST",
              credentials: "same-origin",
              headers: {Accept: "application/json"}
            });
            if (!response.ok) throw new Error(`assignment ${response.status}`);
            const payload = await response.json();
            if (!(serverState.assignment_days || []).includes(day)) {
              serverState.assignment_days = [...(serverState.assignment_days || []), day];
            }
            const targetUrl = addAttribution(payload.target_url);
            navigateAfterGoal(targetUrl, "intensive_required_post_open", {
              messenger,
              post_alias: `intensive-day-${day}-${messenger}`,
              target_url: targetUrl
            });
          } catch (_error) {
            clickLocked = false;
          }
        });
      });
      if (serverState.identified && serverState.platform) actions?.classList.add("is-single");
    });
  }

  function setupNextDay(serverState) {
    if (!day || day >= 4) return;
    const timer = document.querySelector("[data-next-timer]");
    const unlock = document.querySelector("[data-next-unlock]");
    const open = document.querySelector("[data-next-open]");
    const warning = document.querySelector("[data-next-warning]");
    if (!timer || !unlock || !open) return;
    const nextDay = day + 1;
    const unlockAt = Date.parse((serverState.unlock_at || {})[String(nextDay)] || "");
    let announced = false;
    function render() {
      const timeReady = !Number.isFinite(unlockAt) || unlockAt <= Date.now();
      if (!timeReady) {
        timer.hidden = false;
        unlock.hidden = true;
        const value = timer.querySelector("strong");
        if (value) value.textContent = formatRemaining(unlockAt - Date.now());
        return;
      }
      timer.hidden = true;
      unlock.hidden = false;
      if (!announced && !clientState.unlockAnnouncements.includes(nextDay)) {
        announced = true;
        clientState.unlockAnnouncements.push(nextDay);
        saveClientState(clientState);
        goal("intensive_next_day_unlocked", {next_day: nextDay});
      }
    }
    open.addEventListener("click", (event) => {
      event.preventDefault();
      if (serverState.identified && !(serverState.assignment_days || []).includes(day)) {
        if (warning) warning.hidden = false;
        return;
      }
      navigateAfterGoal(addAttribution(`/intensive/day-${nextDay}`), "intensive_next_day_click", {next_day: nextDay});
    });
    render();
    setInterval(render, 1000);
  }

  async function setupDayOffer(serverState) {
    if (day !== 4 || !serverState.offer?.active) return;
    try {
      const response = await fetch("/api/intensive/offer-token", {credentials: "same-origin", headers: {Accept: "application/json"}});
      if (!response.ok) return;
      const offer = await response.json();
      document.querySelectorAll(".masterclass-cta").forEach((link) => {
        const target = new URL(MASTERCLASS_URL);
        target.searchParams.set("intensive_offer", offer.token);
        link.removeAttribute("aria-disabled");
        link.href = addAttribution(target.href);
        link.addEventListener("click", (event) => {
          event.preventDefault();
          navigateAfterGoal(link.href, "intensive_masterclass_click", {offer_id: offer.offer_id, target_url: MASTERCLASS_URL});
        });
      });
    } catch (_error) {}
  }

  function setupVideoAnalytics() {
    const player = document.querySelector("iframe[data-media-player]");
    if (!player) return;
    const milestones = new Set();
    window.addEventListener("message", (event) => {
      if (event.origin !== location.origin || event.source !== player.contentWindow) return;
      if (event.data?.type !== "edabalans:video-analytics") return;
      const payload = event.data.payload || {};
      const common = {
        video_id: payload.video_id,
        position_seconds: payload.max_position_sec,
        duration_seconds: payload.duration_seconds,
        progress_percent: payload.progress_percent
      };
      if (payload.event === "video_progress") {
        [25, 50, 75].forEach((milestone) => {
          if (payload.progress_percent >= milestone && !milestones.has(milestone)) {
            milestones.add(milestone);
            goal("video_progress", Object.assign({}, common, {progress_percent: milestone}));
          }
        });
        return;
      }
      if (["video_engaged", "video_complete", "video_exit"].includes(payload.event)) goal(payload.event, common);
    });
  }

  async function init() {
    loadMetrika();
    const serverState = await loadServerState();
    trustedPlatform = serverState.identified ? serverState.platform : null;
    setupView();
    setupMenu(serverState);
    setupChannels(serverState);
    setupNextDay(serverState);
    setupVideoAnalytics();
    await setupDayOffer(serverState);
    if (day) {
      goal(`intensive_day_${day}_open`);
      clientState.lastPage = `day-${day}`;
    } else {
      goal("intensive_home_open");
      if (clientState.lastPage !== "menu") goal("intensive_menu_open");
      clientState.lastPage = "menu";
    }
    saveClientState(clientState);
  }

  init();
}());
