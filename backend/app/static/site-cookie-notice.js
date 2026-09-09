(function () {
  "use strict";

  const COOKIE_NAME = "edabalans_cookie_notice";
  const COOKIE_VALUE = "accepted-v1";
  const STORAGE_KEY = "edabalans:cookie-notice:accepted-v1";
  const ACCEPTED_EVENT = "edabalans:cookie-accepted";
  const MAX_AGE_SECONDS = 365 * 24 * 60 * 60;
  const SHARED_COOKIE_ROOTS = [
    "edabalans.ru",
    "xn-----jlceacr3bggd8ajed5a6kl.xn--p1ai"
  ];

  function cookieRoot() {
    const hostname = window.location.hostname.toLowerCase();
    return SHARED_COOKIE_ROOTS.find((root) => (
      hostname === root || hostname.endsWith(`.${root}`)
    )) || null;
  }

  function cookieAccepted() {
    if (window.location.protocol === "file:") {
      try { return window.localStorage.getItem(STORAGE_KEY) === COOKIE_VALUE; } catch (_error) { return false; }
    }
    return document.cookie.split(";").some((part) => (
      part.trim() === `${COOKIE_NAME}=${COOKIE_VALUE}`
    ));
  }

  function rememberAcceptance() {
    if (window.location.protocol === "file:") {
      try { window.localStorage.setItem(STORAGE_KEY, COOKIE_VALUE); } catch (_error) {}
      return;
    }
    const attributes = [
      `${COOKIE_NAME}=${COOKIE_VALUE}`,
      `Max-Age=${MAX_AGE_SECONDS}`,
      "Path=/",
      "SameSite=Lax"
    ];
    const root = cookieRoot();
    if (root) attributes.push(`Domain=.${root}`);
    if (window.location.protocol === "https:") attributes.push("Secure");
    document.cookie = attributes.join("; ");
  }

  function ensureStyles() {
    if (document.getElementById("edabalans-cookie-notice-styles")) return;
    const style = document.createElement("style");
    style.id = "edabalans-cookie-notice-styles";
    style.textContent = `
      .cookie-notice {
        position: fixed;
        z-index: 40;
        right: auto;
        bottom: calc(18px + env(safe-area-inset-bottom, 0px));
        left: 50%;
        display: grid;
        width: min(calc(100% - 20px), 560px);
        grid-template-columns: minmax(0, 1fr) auto;
        align-items: center;
        gap: 10px;
        padding: 10px 10px 10px 14px;
        border: 1px solid rgba(255,255,255,.92);
        border-radius: 15px;
        background: rgba(255,255,255,.83);
        box-shadow: 0 6px 12px -6px rgba(22,104,157,.42), 0 2px 5px rgba(22,104,157,.1);
        color: #1d2b38;
        font-family: Manrope, Inter, Arial, sans-serif;
        transform: translateX(-50%);
        backdrop-filter: blur(8px);
      }
      .cookie-notice:not([data-cookie-ready="true"]),
      .cookie-notice[hidden] { display: none; }
      .cookie-notice__copy { margin: 0; font-size: 12px; font-weight: 500; line-height: 1.36; }
      .cookie-notice__copy a { color: inherit; font-weight: inherit; text-decoration: underline; text-underline-offset: 2px; }
      .cookie-notice__accept {
        min-height: 40px;
        padding: 0 13px;
        border: 0;
        border-radius: 12px;
        background: #239fe9;
        box-shadow: 0 4px 8px -4px rgba(17,142,216,.55);
        color: #fff;
        font: 700 12px/1 Manrope, Inter, Arial, sans-serif;
        white-space: nowrap;
        cursor: pointer;
        transition: background-color .16s ease, box-shadow .16s ease;
      }
      .cookie-notice__accept:hover,
      .cookie-notice__accept:focus-visible {
        background: #118ed8;
        box-shadow: 0 5px 9px -4px rgba(17,142,216,.62);
      }
      @media (max-width: 350px) {
        .cookie-notice { gap: 8px; padding-left: 12px; }
        .cookie-notice__copy { font-size: 11.5px; }
        .cookie-notice__accept { padding-inline: 10px; }
      }
      @media (prefers-reduced-motion: reduce) {
        .cookie-notice__accept { transition: none; }
      }
    `;
    document.head.appendChild(style);
  }

  function ensureNotice(root) {
    const existing = root.querySelector("[data-cookie-notice]");
    if (existing) return existing;
    const notice = document.createElement("aside");
    notice.className = "cookie-notice";
    notice.dataset.cookieNotice = "";
    notice.setAttribute("aria-label", "Уведомление об использовании cookie");
    notice.innerHTML = [
      '<p class="cookie-notice__copy">Сайт использует cookie. Продолжая, вы принимаете ',
      '<a href="https://edabalans.ru/legal/privacy" target="_blank" rel="noopener">',
      'политику обработки персональных данных</a>.</p>',
      '<button class="cookie-notice__accept" type="button" data-cookie-dismiss>Приемлемо</button>'
    ].join("");
    document.body.appendChild(notice);
    return notice;
  }

  function boot(root) {
    const scope = root && typeof root.querySelector === "function" ? root : document;
    const existing = scope.querySelector("[data-cookie-notice]");
    if (cookieAccepted()) {
      if (existing) {
        existing.hidden = true;
        existing.dataset.cookieReady = "true";
      }
      return null;
    }
    ensureStyles();
    const notice = existing || ensureNotice(scope);
    if (notice.dataset.cookieBound !== "true") {
      const dismiss = notice.querySelector("[data-cookie-dismiss]");
      dismiss?.addEventListener("click", () => {
        rememberAcceptance();
        notice.hidden = true;
        document.dispatchEvent(new CustomEvent(ACCEPTED_EVENT));
      });
      notice.dataset.cookieBound = "true";
    }
    notice.hidden = false;
    notice.dataset.cookieReady = "true";
    return notice;
  }

  window.EdabalansCookieNotice = Object.freeze({
    accepted: cookieAccepted,
    accept: function () {
      rememberAcceptance();
      document.querySelectorAll("[data-cookie-notice]").forEach((notice) => { notice.hidden = true; });
      document.dispatchEvent(new CustomEvent(ACCEPTED_EVENT));
    },
    boot: boot,
    eventName: ACCEPTED_EVENT,
    version: COOKIE_VALUE
  });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => boot(document), {once: true});
  } else {
    boot(document);
  }
}());
