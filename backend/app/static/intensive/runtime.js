(function () {
  "use strict";

  const COUNTER_ID = 97331502;
  const VERSION = "2026-09-08-depth";
  const LOCAL_KEY = "edabalans:intensive:client:v2";
  const ATTR_KEYS = ["utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term", "yclid", "alias"];
  const MASTERCLASS_URL = "https://xn-----jlceacr3bggd8ajed5a6kl.xn--p1ai/mk1#masterclass";
  const SERVER_EVENT_CODES = new Set([
    "intensive_main_open", "intensive_day_open", "intensive_home_open", "intensive_menu_open", "intensive_telegram_click",
    "intensive_max_click", "intensive_next_day_unlocked", "intensive_next_day_click",
    "intensive_masterclass_click", "page_progress", "video_engaged", "video_progress",
    "video_complete", "video_exit"
  ]);
  const params = new URLSearchParams(location.search);
  const requestedMessenger = ({tg: "telegram", max: "max"})[params.get("from")] || null;
  const entrySource = (["bot", "channel"].includes(params.get("entry")) ? params.get("entry") : "direct");
  const pathMatch = location.pathname.match(/\/intensive\/day-([1-4])/);
  const day = pathMatch ? Number(pathMatch[1]) : 0;
  const isLocalPreview = ["127.0.0.1", "localhost"].includes(location.hostname);
  const isStaticFilePreview = location.protocol === "file:";
  const localMenuPreview = isStaticFilePreview ? params.get("preview") : null;
  let trustedPlatform = null;
  let menuTimerInterval = null;
  let menuTimerRefresh = null;

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
    if (isStaticFilePreview) {
      if (localMenuPreview === "next-open") {
        return {identified: true, platform: "telegram", opened_days: [1], assignment_days: [1], unlocked_days: [1, 2], unlock_at: {}, offer: null};
      }
      if (localMenuPreview === "timer") {
        return {identified: true, platform: "telegram", opened_days: [1, 2], assignment_days: [1, 2], unlocked_days: [1, 2], unlock_at: {3: new Date(Date.now() + 23 * 60 * 60 * 1000).toISOString()}, offer: null};
      }
      if (localMenuPreview === "assignment") {
        return {identified: true, platform: "telegram", opened_days: [1], assignment_days: [], unlocked_days: [1], unlock_at: {}, offer: null};
      }
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
    const localDay = isStaticFilePreview && /^\/intensive\/day-[1-4]$/.test(url)
      ? `./${url.slice("/intensive/".length)}.html`
      : url;
    const target = new URL(localDay, isStaticFilePreview ? location.href : location.origin);
    Object.entries(clientState.attribution).forEach(([key, value]) => {
      if (value && !target.searchParams.has(key)) target.searchParams.set(key, value);
    });
    ["from", "entry"].forEach((key) => {
      const value = params.get(key);
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
    if (trustedPlatform && SERVER_EVENT_CODES.has(code)) {
      fetch("/api/intensive/events", {
        method: "POST",
        credentials: "same-origin",
        keepalive: true,
        headers: {"Content-Type": "application/json", Accept: "application/json"},
        body: JSON.stringify(Object.assign({event_type: code}, payload))
      }).catch(() => {});
    }
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
    return (isStaticFilePreview && !localMenuPreview) || (serverState.unlocked_days || []).includes(number);
  }

  function cardStatus(card) {
    let status = card.querySelector("[data-day-status]");
    if (status) return status;
    status = document.createElement("span");
    status.className = "day-card__status";
    status.dataset.dayStatus = "true";
    card.querySelector(".day-card__text")?.appendChild(status);
    return status;
  }

  function setCardStatus(card, text, tone, timerEndsAt) {
    const status = cardStatus(card);
    status.className = `day-card__status day-card__status--${tone}`;
    status.replaceChildren(document.createTextNode(text));
    if (timerEndsAt) {
      const timer = document.createElement("strong");
      timer.dataset.menuUnlockTimer = String(timerEndsAt);
      status.append(" ", timer);
    }
  }

  function renderMenuTimers() {
    if (menuTimerInterval !== null) window.clearInterval(menuTimerInterval);
    if (menuTimerRefresh !== null) window.clearTimeout(menuTimerRefresh);
    menuTimerInterval = null;
    menuTimerRefresh = null;

    const timers = Array.from(document.querySelectorAll("[data-menu-unlock-timer]"));
    const refreshAt = timers.reduce((earliest, timer) => {
      const unlockAt = Number(timer.dataset.menuUnlockTimer);
      return Number.isFinite(unlockAt) && (earliest === null || unlockAt < earliest)
        ? unlockAt
        : earliest;
    }, null);
    if (refreshAt === null) return;

    const update = () => {
      timers.forEach((timer) => {
        const remaining = Number(timer.dataset.menuUnlockTimer) - Date.now();
        timer.textContent = remaining > 0 ? formatRemaining(remaining) : "сейчас";
      });
    };
    update();
    menuTimerInterval = window.setInterval(update, 1000);
    menuTimerRefresh = window.setTimeout(async () => {
      window.clearInterval(menuTimerInterval);
      menuTimerInterval = null;
      menuTimerRefresh = null;
      const refreshedState = await loadServerState();
      setupMenu(refreshedState);
    }, Math.max(500, refreshAt - Date.now() + 500));
  }

  function setupMenu(serverState) {
    const openedDays = new Set(serverState.opened_days || []);
    const unlockedDays = new Set(serverState.unlocked_days || []);
    const assignmentDays = new Set(serverState.assignment_days || []);
    const nextReadableDay = serverState.identified
      ? [1, 2, 3, 4].find((number) => unlockedDays.has(number) && !openedDays.has(number))
      : null;
    const nextLockedDay = serverState.identified
      ? [1, 2, 3, 4].find((number) => !unlockedDays.has(number))
      : null;

    document.querySelectorAll(".day-card[data-day]").forEach((card) => {
      const number = Number(card.dataset.day);
      card.href = addAttribution(`/intensive/day-${number}`);
      card.classList.remove("is-locked", "is-read", "is-next-open", "is-next-locked");
      card.removeAttribute("aria-disabled");
      card.onclick = null;
      card.querySelector("[data-day-status]")?.remove();
      if (!isUnlocked(serverState, number)) {
        card.classList.add("is-locked");
        card.setAttribute("aria-disabled", "true");
        card.onclick = (event) => event.preventDefault();
        if (number === nextLockedDay) {
          card.classList.add("is-next-locked");
          const previousDay = number - 1;
          const unlockAt = Date.parse((serverState.unlock_at || {})[String(number)] || "");
          if (openedDays.has(previousDay) && assignmentDays.has(previousDay) && Number.isFinite(unlockAt) && unlockAt > Date.now()) {
            setCardStatus(card, "Следующая часть откроется через", "timer", unlockAt);
          } else {
            setCardStatus(card, "Сначала прочитайте предыдущую часть", "blocked");
          }
        }
      } else if (number === nextReadableDay) {
        card.classList.add("is-next-open");
      } else if (serverState.identified && openedDays.has(number)) {
        card.classList.add("is-read");
        setCardStatus(card, "Прочитано", "read");
      }
    });
    renderMenuTimers();
    document.querySelectorAll(".home-action").forEach((link) => {
      link.href = addAttribution(MASTERCLASS_URL);
      link.onclick = (event) => {
        event.preventDefault();
        navigateAfterGoal(link.href, "intensive_masterclass_click", {target_url: link.href});
      };
    });
  }

  function setupChannels(serverState) {
    document.querySelectorAll("[data-channel-block]").forEach((block) => {
      block.hidden = false;
      const actions = block.querySelector(".channel-actions");
      block.querySelectorAll("[data-channel]").forEach((link) => {
        const messenger = link.dataset.channel;
        if (requestedMessenger && messenger !== requestedMessenger) link.hidden = true;
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
      if (requestedMessenger) actions?.classList.add("is-single");
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
    if (day !== 4 || !serverState.identified) return;
    const links = Array.from(document.querySelectorAll(".masterclass-cta"));
    if (!links.length) return;
    let activationPromise = null;
    let offerTarget = null;
    async function activate() {
      if (offerTarget) return offerTarget;
      if (activationPromise) return activationPromise;
      activationPromise = (async () => {
        const response = await fetch("/api/intensive/offer-token", {credentials: "same-origin", headers: {Accept: "application/json"}});
        if (!response.ok) throw new Error(`offer ${response.status}`);
        const offer = await response.json();
        const target = new URL(MASTERCLASS_URL);
        target.searchParams.set("intensive_offer", offer.token);
        offerTarget = addAttribution(target.href);
        links.forEach((link) => {
          link.removeAttribute("aria-disabled");
          link.href = offerTarget;
        });
        return offerTarget;
      })();
      try {
        return await activationPromise;
      } finally {
        activationPromise = null;
      }
    }
    links.forEach((link) => {
      link.href = addAttribution(MASTERCLASS_URL);
      link.addEventListener("click", async (event) => {
        event.preventDefault();
        link.setAttribute("aria-disabled", "true");
        try {
          const target = await activate();
          navigateAfterGoal(target, "intensive_masterclass_click", {offer_id: "intensive-day4-1000", target_url: MASTERCLASS_URL});
        } catch (_error) {
          link.removeAttribute("aria-disabled");
        }
      });
    });
    if (!("IntersectionObserver" in window)) {
      activate().catch(() => {});
      return;
    }
    const observer = new IntersectionObserver((entries) => {
      if (!entries.some((entry) => entry.isIntersecting)) return;
      activate().then(() => observer.disconnect()).catch(() => {});
    }, {rootMargin: "0px", threshold: 0.01});
    links.forEach((link) => observer.observe(link));
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

  function setupPageProgress() {
    if (day !== 1) return;
    const article = document.querySelector('[data-view="day1"] .intensive-article, .intensive-article, .article');
    if (!article) return;
    const milestones = new Set();
    let scheduled = false;
    const measure = () => {
      scheduled = false;
      const rect = article.getBoundingClientRect();
      const articleTop = window.scrollY + rect.top;
      const articleHeight = Math.max(article.scrollHeight, rect.height, 1);
      const visibleThrough = Math.max(0, window.scrollY + window.innerHeight - articleTop);
      const progress = Math.min(100, visibleThrough * 100 / articleHeight);
      [25, 50, 75, 100].forEach((milestone) => {
        if (progress >= milestone && !milestones.has(milestone)) {
          milestones.add(milestone);
          goal("page_progress", {day: 1, progress_percent: milestone});
        }
      });
    };
    const scheduleMeasure = () => {
      if (scheduled) return;
      scheduled = true;
      window.requestAnimationFrame(measure);
    };
    window.addEventListener("scroll", scheduleMeasure, {passive: true});
    window.addEventListener("resize", scheduleMeasure, {passive: true});
    scheduleMeasure();
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
    setupPageProgress();
    await setupDayOffer(serverState);
    if (day) {
      goal("intensive_day_open", {day, entry: entrySource});
      clientState.lastPage = `day-${day}`;
    } else {
      goal("intensive_main_open", {entry: entrySource});
      clientState.lastPage = "menu";
    }
    saveClientState(clientState);
  }

  init();
}());
