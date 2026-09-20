(function () {
  "use strict";

  const root = document.getElementById("crm-app");
  const state = {
    view: "users", query: "", summary: null, users: [], payments: [], tags: [], offset: 0,
    paymentOffset: 0, paymentSnapshotAt: null, userProducts: null, userTags: null, userRequest: null, userDetails: new Map(),
    paymentFilters: { q: "", product_code: "", date_from: "", date_to: "", amount_kind: "all" }, userFilters: { buyer_kind: "all", product_code: "", first_seen_from: "", first_seen_to: "", masterclass_access: "", accompaniment_status: "all", tag_id: "" }
  };
  const pageSize = 100;
  const paymentPageSize = 100;
  const tagCategories = {
    manual: "Ручные",
    subscription: "Подписка",
    content_action: "Контент и действия",
    mailing_funnel: "Рассылки и воронки",
    source: "Источники",
    purchase_signal: "Сигналы о покупке",
    other: "Прочее",
    technical: "Служебные"
    ,content: "Материалы", funnel: "Старые воронки", intensive: "Старый интенсив",
    refund: "Возвраты", lottery: "Лотерея",
    obsolete: "Устаревшее", purchase: "Покупки", routing: "Маршрутизация",
    tariff: "Тарифы", access_hint: "Проверка доступов", review: "На разбор",
    content_review: "Контент на разбор"
  };

  function esc(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function money(value) {
    if (value === null || value === undefined) return "сумма неизвестна";
    return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(value || 0) + " ₽";
  }

  function date(value, withTime) {
    if (!value) return "—";
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return esc(value);
    return parsed.toLocaleString("ru-RU", withTime ? {
      day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit"
    } : { day: "2-digit", month: "2-digit", year: "numeric" });
  }

  async function api(path, options) {
    const response = await fetch(path, {
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", ...(options && options.headers) },
      ...options
    });
    if (response.status === 401) {
      location.replace(`/admin?next=${encodeURIComponent(location.pathname + location.search)}`);
      throw new Error("Сессия завершена");
    }
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || `Ошибка сервера ${response.status}`);
    }
    return response.status === 204 ? null : response.json();
  }

  function top(active) {
    return `
      <div class="crm-top">
        <div class="crm-head">
          <div class="crm-title">CRM</div>
          <div class="crm-tabs" aria-label="Раздел CRM">
            <button class="crm-tab ${active === "users" || active === "buyers" ? "active" : ""}" data-view="users">Люди</button>
            <button class="crm-tab ${active === "payments" ? "active" : ""}" data-view="payments">Оплаты</button>
            <button class="crm-tab ${active === "tags" ? "active" : ""}" data-view="tags">Теги</button>
          </div>
        </div>
      </div>`;
  }

  function bindTop() {
    root.querySelectorAll("[data-view]").forEach((button) => {
      button.addEventListener("click", () => showView(button.dataset.view).catch(showError));
    });
  }

  function stats() {
    const data = state.summary || {};
    return `
      <div class="crm-stats">
        <div class="crm-stat"><div class="crm-k">ЛЮДЕЙ В CRM</div><div class="crm-v">${data.users || 0}</div><div class="crm-s">единый user_id</div></div>
        <div class="crm-stat"><div class="crm-k">ПОКУПАТЕЛЕЙ</div><div class="crm-v">${data.buyers || 0}</div><div class="crm-s">есть подтверждённая оплата</div></div>
        <div class="crm-stat"><div class="crm-k">ПОКУПОК В ИСТОРИИ</div><div class="crm-v">${data.paid_payments || 0}</div><div class="crm-s">включая старые без известной суммы</div></div>
        <div class="crm-stat"><div class="crm-k">ВЫРУЧКА ПО ФАКТУ</div><div class="crm-v">${money(data.revenue_rub)}</div><div class="crm-s">без расчётных сумм${data.estimated_revenue_rub ? ` · ещё ≈ ${money(data.estimated_revenue_rub)}` : ""}</div></div>
        <div class="crm-stat"><div class="crm-k">АККАУНТОВ TILDA</div><div class="crm-v">${data.tilda_members || 0}</div><div class="crm-s">последняя каноничная сверка</div></div>
        <div class="crm-stat"><div class="crm-k">ПРОВЕРИТЬ ДОСТУПЫ</div><div class="crm-v">${data.access_reviews || 0}</div><div class="crm-s">только реальные спорные случаи</div></div>
      </div>`;
  }

  function loadUserDetail(id) {
    if (!state.userDetails.has(id)) {
      const request = api(`/admin/api/users/${id}`).catch((error) => {
        state.userDetails.delete(id);
        throw error;
      });
      state.userDetails.set(id, request);
    }
    return state.userDetails.get(id);
  }

  function botAge(value) {
    if (!value) return "не запускал";
    const started = new Date(value);
    if (Number.isNaN(started.getTime())) return "—";
    const days = Math.max(0, Math.floor((Date.now() - started.getTime()) / 86400000));
    return days === 0 ? "сегодня" : `${days} дн.`;
  }

  function telegramPlaneIcon() {
    return `<svg viewBox="190 270 580 510" aria-hidden="true"><path fill="currentColor" d="M226.328 494.722c145.761-63.505 242.957-105.372 291.589-125.6 138.855-57.755 167.708-67.787 186.514-68.119 4.137-.072 13.385.953 19.375 5.814 5.059 4.105 6.451 9.65 7.117 13.541.666 3.892 1.495 12.757.836 19.683-7.525 79.062-40.084 270.924-56.648 359.475-7.009 37.469-20.81 50.032-34.17 51.261-29.036 2.672-51.085-19.189-79.208-37.624-44.006-28.847-68.867-46.804-111.583-74.953-49.366-32.531-17.364-50.411 10.769-79.631 7.363-7.647 135.296-124.012 137.772-134.568.31-1.32.597-6.241-2.326-8.84-2.924-2.599-7.239-1.71-10.353-1.003-4.413 1.002-74.714 47.468-210.902 139.399-19.954 13.703-38.029 20.379-54.223 20.029-17.853-.386-52.194-10.094-77.723-18.393-31.313-10.178-56.2-15.56-54.032-32.846 1.128-9.004 13.527-18.212 37.196-27.624Z"/></svg>`;
  }

  function messengerIcon(platform) {
    const body = platform === "telegram"
      ? telegramPlaneIcon()
      : platform === "max"
        ? '<img src="/assets/max-logo.png" alt="">'
        : "MSG";
    return `<span class="crm-messenger-icon is-${esc(platform || "other")}" aria-label="${esc(platform || "messenger")}">${body}</span>`;
  }

  function botStart(user) {
    const starts = (user.messengers || [])
      .map((item) => item.main_scenario_seen_at || item.first_seen_at || (item.platform === "telegram" ? user.first_seen_at : null))
      .filter(Boolean)
      .sort();
    return starts[0] || null;
  }

  function channelState(user) {
    const statuses = (user.messengers || []).map((item) => item.subscription_status).filter(Boolean);
    if (statuses.some((value) => ["active", "subscribed"].includes(value))) return { label: "Подписан", tone: "is-positive" };
    if (statuses.some((value) => ["inactive", "unsubscribed", "left", "blocked"].includes(value))) return { label: "Не подписан", tone: "is-negative" };
    return { label: "Не проверено", tone: "is-unknown" };
  }

  function accessCodes(user) {
    return (user.accesses || []).map((item) => typeof item === "string" ? item : item.code);
  }

  function clientStage(user) {
    const accesses = accessCodes(user);
    if (accesses.includes("ACCESS_COACHING")) return { code:"support", label:"Сопровождение" };
    if (accesses.includes("ACCESS_CONSULTATION")) return { code:"consultation", label:"Консультация" };
    if ((user.purchase_count || 0) > 0) return { code:"buyer", label:"Покупатель" };
    return { code:"lead", label:"Лид" };
  }

  function messengerContact(user, platform) {
    const account = (user.messengers || []).find((item) => item.platform === platform);
    const username = account && account.username || (platform === "telegram" ? user.telegram : null);
    const handle = username && !/^https?:\/\//i.test(username) ? username.replace(/^@/, "") : username;
    const value = platform === "max"
      ? account && account.platform_user_id ? account.platform_user_id : handle ? `@${handle}` : "—"
      : handle ? `@${handle}` : account && account.platform_user_id ? account.platform_user_id : "—";
    if (platform === "telegram" && handle) return `<a class="crm-contact-link" href="https://t.me/${encodeURIComponent(handle)}" target="_blank" rel="noopener">${esc(value)}</a>`;
    if (platform === "max" && username && /^https:\/\/max\.ru\/u\//i.test(username)) return `<a class="crm-contact-link" href="${esc(username)}" target="_blank" rel="noopener">MAX</a>`;
    return `<span class="crm-contact-plain">${esc(value)}</span>`;
  }

  function profileMessengerButton(user, platform) {
    const account = (user.messengers || []).find((item) => item.platform === platform);
    if (!account) return "";
    const username = account.username || "";
    const telegramHandle = username && !/^https?:\/\//i.test(username) ? username.replace(/^@/, "") : "";
    const isPublicMax = /^https:\/\/max\.ru\/u\//i.test(username);
    const tag = platform === "telegram" && telegramHandle ? "a" : platform === "max" && isPublicMax ? "a" : "span";
    const href = platform === "telegram" && telegramHandle
      ? ` href="https://t.me/${encodeURIComponent(telegramHandle)}" target="_blank" rel="noopener"`
      : platform === "max" && isPublicMax ? ` href="${esc(username)}" target="_blank" rel="noopener"` : "";
    const title = platform === "max" && account.platform_user_id ? ` title="MAX: ${esc(account.platform_user_id)}"` : "";
    const body = platform === "telegram" ? `${telegramPlaneIcon()}<span>Telegram</span>` : `<img src="/assets/max-logo.png" alt=""><span>MAX</span>`;
    return `<${tag} class="crm-contact-button crm-contact-button--${platform}"${href}${title}>${body}</${tag}>`;
  }

  function courseProgressPreview(user) {
    const progress = user.product_progress || [];
    if (!progress.length) return "";
    return `<div class="crm-popover-section-title">Прогресс курсов</div>${progress.map((item) => `<div class="crm-progress-item"><div><strong>${esc(item.name)}</strong><span>${item.legacy_assumed_complete ? "пройдено полностью" : `${item.completed} из ${item.total}`}</span></div><div class="crm-progress-track"><i style="width:${Math.max(0, Math.min(100, item.percent || 0))}%"></i></div></div>`).join("")}`;
  }

  function paymentDelayFromBot(user, payment) {
    const startedAt = botStart(user);
    if (!startedAt || !payment || !(payment.paid_at || payment.source_event_at)) return "срок не определён";
    const started = new Date(startedAt).getTime();
    const paid = new Date(payment.paid_at || payment.source_event_at).getTime();
    if (Number.isNaN(started) || Number.isNaN(paid) || paid < started) return "срок не определён";
    const days = Math.floor((paid - started) / 86400000);
    return days === 0 ? "в день старта бота" : `через ${days} дн. после старта бота`;
  }

  function previewTrigger(kind, user, label) {
    const descriptions = { tariff: "тариф и доступы", payments: "оплаты", accesses: "доступы", messengers: "мессенджеры", notes: "заметки", progress: "статус и прогресс" };
    return `<div class="crm-preview" data-preview-kind="${kind}" data-preview-user="${esc(user.id)}">
      <button class="crm-preview-trigger ${kind}" type="button" aria-expanded="false" aria-label="Показать ${descriptions[kind]}: ${esc(user.display_name || user.email || "человек")}">${label}</button>
      <div class="crm-popover" role="tooltip"><div class="crm-popover-loading">Загружаю…</div></div>
    </div>`;
  }

  function previewContent(kind, user) {
    if (kind === "messengers") {
      const messengers = user.messengers || [];
      if (!messengers.length) return '<div class="crm-popover-empty">Мессенджер не привязан</div>';
      return `<div class="crm-popover-title">Мессенджеры</div>${messengers.map((item) => `<div class="crm-popover-item"><strong>${messengerIcon(item.platform)} ${esc(item.platform === "telegram" ? "Telegram" : item.platform === "max" ? "MAX" : item.platform)}</strong><span>${item.username ? `@${esc(item.username)} · ` : ""}в боте ${botAge(item.main_scenario_seen_at || item.first_seen_at)} · ${channelState({ messengers: [item] }).label.toLowerCase()}</span></div>`).join("")}`;
    }
    if (kind === "notes") {
      const notes = user.notes || [];
      if (!notes.length) return '<div class="crm-popover-empty">Заметок пока нет</div>';
      return `<div class="crm-popover-title">Последние заметки</div>${notes.slice(0, 4).map((item) => `<div class="crm-popover-item"><strong>${esc(item.body)}</strong><span>${date(item.created_at, false)} · ${esc(item.author)}</span></div>`).join("")}${notes.length > 4 ? `<div class="crm-popover-note">Ещё ${notes.length - 4} — в карточке</div>` : ""}`;
    }
    if (kind === "tariff") {
      const products = [...(user.purchased_products || [])].sort((left, right) => String(left.purchased_at || "").localeCompare(String(right.purchased_at || "")));
      const initial = products[0];
      const accesses = (user.accesses || []).filter((item) => typeof item !== "string" && !item.revoked_at);
      const purchase = initial
        ? `<div class="crm-popover-line"><strong>${esc(initial.product_name || "Продукт")}</strong><span>${esc(initial.tariff || "Основной")}${initial.purchased_at ? ` · ${date(initial.purchased_at, false)}` : ""}</span></div>`
        : '<div class="crm-popover-empty">Подтверждённый тариф не найден</div>';
      const accessList = accesses.length
        ? `<div class="crm-popover-line crm-popover-accesses"><strong>Доступно</strong><span>${accesses.map((item) => `${esc(item.name || item.code)}${item.paused_at ? " (приостановлен)" : ""}`).join(" · ")}</span></div>`
        : '<div class="crm-popover-note">Активных доступов нет</div>';
      return `${purchase}${accessList}${courseProgressPreview(user)}`;
    }
    if (kind === "payments") {
      const payments = (user.payments || []).filter((item) => ["paid", "confirmed"].includes(item.status));
      if (!payments.length) return '<div class="crm-popover-empty">Подтверждённых покупок нет</div>';
      return `<div class="crm-popover-title">Оплаты</div>${payments.slice(0, 8).map((item) => `<div class="crm-popover-payment"><strong>${item.amount_is_estimated ? "≈ " : ""}${money(item.amount)}</strong><span>${esc(item.product_name || item.product_name_raw || "Продукт")}${item.tariff ? ` · ${esc(item.tariff)}` : ""} · ${date(item.paid_at || item.source_event_at, false)}</span></div>`).join("")}${payments.length > 8 ? `<div class="crm-popover-note">Ещё ${payments.length - 8} — в карточке</div>` : ""}${courseProgressPreview(user)}`;
    }
    if (kind === "progress") {
      const stage = clientStage(user);
      if (stage.code === "lead") {
        const source = (user.attribution || []).find((item) => item.source || item.utm_source);
        const events = (user.attribution || []).slice(-4).reverse();
        return `<div class="crm-popover-title">Путь лида</div><div class="crm-popover-item"><strong>${esc((source && (source.source || source.utm_source)) || "Источник не определён")}</strong><span>первое появление ${date(user.first_seen_at, false)}</span></div>${(user.messengers || []).map((item) => `<div class="crm-popover-item"><strong>${messengerIcon(item.platform)} ${esc(item.platform)}</strong><span>старт ${date(item.main_scenario_seen_at || item.first_seen_at, false)} · ${channelState({messengers:[item]}).label.toLowerCase()}</span></div>`).join("")}${events.map((item) => `<div class="crm-popover-item"><strong>${esc(item.event_type || "Событие")}</strong><span>${date(item.occurred_at, false)}</span></div>`).join("")}`;
      }
      const progress = user.product_progress || [];
      return `<div class="crm-popover-title">${esc(stage.label)} · прогресс</div>${progress.map((item) => `<div class="crm-progress-item"><div><strong>${esc(item.name)}</strong><span>${item.legacy_assumed_complete ? "пройдено полностью" : `${item.completed} из ${item.total}`}</span></div><div class="crm-progress-track"><i style="width:${Math.max(0, Math.min(100, item.percent || 0))}%"></i></div></div>`).join("") || '<div class="crm-popover-empty">Прогресс по продуктам пока не зафиксирован</div>'}`;
    }
    const accesses = (user.accesses || []).filter((item) => !item.revoked_at);
    if (!accesses.length) return '<div class="crm-popover-empty">Действующих доступов нет</div>';
    return `<div class="crm-popover-title">Доступы</div>${accesses.map((item) => `<div class="crm-popover-item"><strong>${esc(item.name || item.code)}</strong><span>${item.paused_at ? "На паузе" : "Действует"}${item.expires_at ? ` · до ${date(item.expires_at, false)}` : " · без срока"}</span></div>`).join("")}`;
  }

  function bindUserPreviews() {
    root.querySelectorAll(".crm-preview").forEach((preview) => {
      let loaded = false;
      const trigger = preview.querySelector(".crm-preview-trigger");
      const popover = preview.querySelector(".crm-popover");
      const place = () => {
        const triggerRect = trigger.getBoundingClientRect();
        const popoverRect = popover.getBoundingClientRect();
        const left = Math.max(10, Math.min(triggerRect.left, window.innerWidth - popoverRect.width - 10));
        const below = triggerRect.bottom + 7;
        const top = below + popoverRect.height <= window.innerHeight - 10
          ? below
          : Math.max(10, triggerRect.top - popoverRect.height - 7);
        popover.style.left = `${left}px`;
        popover.style.top = `${top}px`;
      };
      const load = async () => {
        trigger.setAttribute("aria-expanded", "true");
        requestAnimationFrame(place);
        if (loaded) return;
        try {
          const user = await loadUserDetail(preview.dataset.previewUser);
          popover.innerHTML = previewContent(preview.dataset.previewKind, user);
          loaded = true;
          requestAnimationFrame(place);
        } catch (error) {
          popover.innerHTML = `<div class="crm-popover-empty">${esc(error.message)}</div>`;
        }
      };
      preview.addEventListener("pointerenter", load);
      preview.addEventListener("focusin", load);
      preview.addEventListener("pointerleave", () => trigger.setAttribute("aria-expanded", "false"));
      preview.addEventListener("focusout", (event) => { if (!preview.contains(event.relatedTarget)) trigger.setAttribute("aria-expanded", "false"); });
      trigger.addEventListener("click", (event) => { event.stopPropagation(); load(); });
    });
  }

  function peopleMode() {
    if (["active", "former"].includes(state.userFilters.accompaniment_status)) return "support";
    if (state.userFilters.buyer_kind === "non_buyers") return "leads";
    if (state.userFilters.buyer_kind === "buyers") return "buyers";
    return "all";
  }

  function messengerCell(user) {
    const messengers = user.messengers || [];
    const label = messengers.length
      ? `<span class="crm-messenger-icons">${messengers.map((item) => messengerIcon(item.platform)).join("")}</span>`
      : '<span class="crm-no-messenger">—</span>';
    return previewTrigger("messengers", user, label);
  }

  function userRow(user, mode) {
    const stage = clientStage(user);
    const source = esc(user.first_source || "—");
    const commonStart = `
      <tr data-user-id="${esc(user.id)}" tabindex="0" role="link" aria-label="Открыть карточку: ${esc(user.display_name || user.email || user.telegram || "Без имени")}">
        <td class="crm-person-name"><strong>${esc(user.display_name || user.email || user.telegram || "Без имени")}</strong></td>
        <td class="crm-person-email">${esc(user.email || "—")}</td>
        <td class="crm-contact-cell">${messengerCell(user)}</td>
        <td class="crm-source-cell">${source}</td>`;
    const startedAt = botStart(user);
    const bot = `<td class="crm-bot-age"><strong>${startedAt ? `с ${date(startedAt, false)} · ${botAge(startedAt)}` : "не запускал"}</strong><span>${user.first_purchase_at ? `первая покупка ${date(user.first_purchase_at, false)}` : "покупки ещё нет"}</span></td>`;
    const subscription = `<td><span class="crm-channel-state ${channelState(user).tone}">${channelState(user).label}</span></td>`;
    const progress = `<td>${previewTrigger("progress", user, `<span class="crm-stage is-${stage.code}">${esc(stage.label)}</span>`)}</td>`;
    const paid = `<td class="crm-money">${previewTrigger("payments", user, `<strong>${money(user.ltv_rub)}</strong>${user.estimated_ltv_rub ? `<span class="crm-estimated">+ ≈ ${money(user.estimated_ltv_rub)}</span>` : ""}`)}</td>`;
    if (mode === "leads") {
      return `${commonStart}${bot}${subscription}${progress}<td>${previewTrigger("notes", user, `<strong>${user.note_count || 0}</strong>`)}</td></tr>`;
    }
    if (mode === "support") {
      return `${commonStart}${paid}${subscription}${progress}<td>${previewTrigger("notes", user, `<strong>${user.note_count || 0}</strong>`)}</td></tr>`;
    }
    return `${commonStart}<td>${previewTrigger("tariff", user, esc(user.initial_tariff || "—"))}</td>${paid}${progress}${bot}${subscription}</tr>`;
  }

  function bindUserCards() {
    root.querySelectorAll("[data-user-id]").forEach((item) => {
      item.addEventListener("click", (event) => { if (!event.target.closest(".crm-preview, a")) openUser(item.dataset.userId); });
      item.addEventListener("keydown", (event) => {
        if (event.key !== "Enter" && event.key !== " ") return;
        if (event.target.closest(".crm-preview, a")) return;
        event.preventDefault();
        openUser(item.dataset.userId);
      });
    });
  }

  async function loadUserRows() {
    if (state.userRequest) state.userRequest.abort();
    state.userRequest = new AbortController();
    const result = document.getElementById("crm-user-results");
    if (result) result.classList.add("is-loading");
    const filters = state.userFilters;
    const params = new URLSearchParams({ q: state.query, buyers_only: "false", limit: String(pageSize), offset: String(state.offset) });
    Object.entries(filters).forEach(([key, value]) => { if (value !== "") params.set(key, value); });
    try {
      state.users = await api(`/admin/api/users?${params}`, { signal: state.userRequest.signal });
    } catch (error) {
      if (error.name === "AbortError") return;
      const current = document.getElementById("crm-user-results");
      if (current) {
        current.classList.remove("is-loading");
        current.innerHTML = `<div class="crm-error inline"><strong>Люди не загрузились</strong><div>${esc(error.message)}</div><button class="crm-btn small" id="crm-results-retry">Повторить</button></div>`;
        document.getElementById("crm-results-retry").addEventListener("click", () => loadUserRows());
      }
      return;
    }
    const current = document.getElementById("crm-user-results");
    if (!current) return;
    current.classList.remove("is-loading");
    const mode = peopleMode();
    const headings = mode === "leads"
      ? ["Имя", "Email", "Мессенджеры", "Источник", "В боте", "Подписка", "Статус", "Заметки"]
      : mode === "support"
        ? ["Имя", "Email", "Мессенджеры", "Источник", "Итого", "Подписка", "Статус", "Заметки"]
        : ["Имя", "Email", "Мессенджеры", "Источник", "Тариф", "Итого", "Статус", "В боте", "Подписка"];
    const columnClass = (heading) => `crm-col-${({"Имя":"name","Email":"email","Мессенджеры":"messengers","Источник":"source","Тариф":"tariff","Итого":"total","Статус":"status","В боте":"bot","Подписка":"channel","Заметки":"notes"})[heading] || "default"}`;
    current.innerHTML = `<div class="crm-table-wrap"><table class="crm-table crm-people-table crm-people-${mode}"><colgroup>${headings.map((heading) => `<col class="${columnClass(heading)}">`).join("")}</colgroup><thead><tr>${headings.map((heading) => `<th>${heading}</th>`).join("")}</tr></thead><tbody>${state.users.map((user) => userRow(user, mode)).join("") || `<tr><td colspan="${headings.length}" class="crm-empty">Ничего не найдено</td></tr>`}</tbody></table></div>
      <div class="crm-pager"><button class="crm-btn alt small" id="crm-prev" ${state.offset === 0 ? "disabled" : ""}>← Предыдущие</button><span>${state.users.length ? `${state.offset + 1}–${state.offset + state.users.length}` : "0"}</span><button class="crm-btn alt small" id="crm-next" ${state.users.length < pageSize ? "disabled" : ""}>Следующие →</button></div>`;
    bindUserCards();
    bindUserPreviews();
    document.getElementById("crm-prev").addEventListener("click", () => { state.offset = Math.max(0, state.offset - pageSize); loadUserRows().catch(showError); });
    document.getElementById("crm-next").addEventListener("click", () => { state.offset += pageSize; loadUserRows().catch(showError); });
  }

  async function renderUsers(buyersOnly) {
    root.innerHTML = top("users") + '<div class="crm-loading">Загружаю клиентов…</div>';
    bindTop();
    if (buyersOnly) state.userFilters.buyer_kind = "buyers";
    const referenceRequest = state.userProducts && state.userTags ? null : Promise.all([api("/admin/api/payment-products"), api("/admin/api/tags?status=active")]).catch(() => null);
    const products = state.userProducts || [];
    const tags = state.userTags || [];
    const filters = state.userFilters;
    root.innerHTML = top("users") + `
      <div class="crm-toolbar">
        <input class="crm-search" id="crm-search" placeholder="Поиск по имени, email или Telegram" value="${esc(state.query)}">
        <button class="crm-btn alt" id="crm-refresh">Обновить</button>
      </div>
      <div class="crm-quick-filters" aria-label="Быстрые фильтры"><button class="crm-chip ${filters.buyer_kind === "all" && filters.masterclass_access === "" && filters.accompaniment_status === "all" ? "active" : ""}" data-people-all>Все</button><button class="crm-chip ${filters.buyer_kind === "buyers" ? "active" : ""}" data-buyer-kind="buyers">Покупатели</button><button class="crm-chip ${filters.buyer_kind === "non_buyers" ? "active" : ""}" data-buyer-kind="non_buyers">Лиды</button><button class="crm-chip ${filters.accompaniment_status === "active" ? "active" : ""}" data-accompaniment="active">Сопровождение</button><button class="crm-chip ${filters.accompaniment_status === "former" ? "active" : ""}" data-accompaniment="former">Бывшее сопровождение</button><button class="crm-chip ${filters.masterclass_access === "true" ? "active" : ""}" data-masterclass-access="true">Есть МК</button><button class="crm-chip ${filters.masterclass_access === "false" ? "active" : ""}" data-masterclass-access="false">Нет МК</button><button class="crm-chip" data-view="access">Проблемы доступа</button></div>
      <details class="crm-card crm-filters"><summary>Другие фильтры</summary><form class="crm-payment-toolbar" id="crm-user-filters"><label><span>Первое появление с</span><input class="crm-input" name="first_seen_from" type="date" value="${esc(filters.first_seen_from)}"></label><label><span>по</span><input class="crm-input" name="first_seen_to" type="date" value="${esc(filters.first_seen_to)}"></label><select class="crm-input" id="crm-product-filter" name="product_code"><option value="">Любой продукт</option>${products.map((item) => `<option value="${esc(item.code)}" ${filters.product_code === item.code ? "selected" : ""}>${esc(item.name)}</option>`).join("")}</select><select class="crm-input" name="masterclass_access"><option value="">Доступ к МК: любой</option><option value="true" ${filters.masterclass_access === "true" ? "selected" : ""}>Доступ к МК есть</option><option value="false" ${filters.masterclass_access === "false" ? "selected" : ""}>Нет доступа к МК</option></select><select class="crm-input" id="crm-tag-filter" name="tag_id"><option value="">Любой тег</option>${tags.map((item) => `<option value="${esc(item.id)}" ${filters.tag_id === item.id ? "selected" : ""}>${esc(item.name)}</option>`).join("")}</select><button class="crm-btn small">Применить</button><button class="crm-btn alt small" type="button" id="crm-reset-filters">Сбросить</button></form><div class="crm-filter-help"><p><b>Первое появление</b> — самая ранняя известная запись человека в CRM, а не обязательно вход из Telegram или сайта.</p><p><b>Тег</b> — метка для отбора; он сам по себе не подтверждает оплату и не выдаёт доступ.</p><p><b>Проблемы доступа</b> — очередь спорных исторических случаев. Действующие права меняются в карточке человека.</p></div></details>
      <div id="crm-user-results" class="crm-results"><div class="crm-loading inline">Загружаю людей…</div></div>`;
    bindTop();
    const search = document.getElementById("crm-search");
    let timer;
    search.addEventListener("input", () => {
      clearTimeout(timer);
      state.query = search.value;
      state.offset = 0;
      timer = setTimeout(() => loadUserRows().catch(showError), 300);
    });
    document.getElementById("crm-user-filters").addEventListener("submit", (event) => { event.preventDefault(); state.userFilters = { ...state.userFilters, ...Object.fromEntries(new FormData(event.currentTarget).entries()) }; state.offset = 0; loadUserRows().catch(showError); });
    document.getElementById("crm-reset-filters").addEventListener("click", () => { state.userFilters = { buyer_kind: "all", product_code: "", first_seen_from: "", first_seen_to: "", masterclass_access: "", accompaniment_status: "all", tag_id: "" }; state.offset = 0; renderUsers(false).catch(showError); });
    document.getElementById("crm-refresh").addEventListener("click", () => loadUserRows().catch(showError));
    root.querySelector("[data-people-all]").addEventListener("click", () => { state.userFilters.buyer_kind = "all"; state.userFilters.masterclass_access = ""; state.userFilters.accompaniment_status = "all"; state.offset = 0; renderUsers(false).catch(showError); });
    root.querySelectorAll("[data-buyer-kind]").forEach((button) => button.addEventListener("click", () => { state.userFilters.buyer_kind = button.dataset.buyerKind; state.userFilters.accompaniment_status = "all"; state.offset = 0; renderUsers(false).catch(showError); }));
    root.querySelectorAll("[data-masterclass-access]").forEach((button) => button.addEventListener("click", () => { state.userFilters.masterclass_access = button.dataset.masterclassAccess; state.offset = 0; renderUsers(false).catch(showError); }));
    root.querySelectorAll("[data-accompaniment]").forEach((button) => button.addEventListener("click", () => { state.userFilters.accompaniment_status = button.dataset.accompaniment; state.userFilters.buyer_kind = "all"; state.offset = 0; renderUsers(false).catch(showError); }));
    await loadUserRows();
    if (referenceRequest) referenceRequest.then((loadedReferences) => {
      if (!loadedReferences) return;
      const [loadedProducts, loadedTags] = loadedReferences;
      state.userProducts = loadedProducts; state.userTags = loadedTags;
      const productSelect = document.getElementById("crm-product-filter");
      const tagSelect = document.getElementById("crm-tag-filter");
      if (productSelect) productSelect.innerHTML = `<option value="">Любой продукт</option>${loadedProducts.map((item) => `<option value="${esc(item.code)}">${esc(item.name)}</option>`).join("")}`;
      if (tagSelect) tagSelect.innerHTML = `<option value="">Любой тег</option>${loadedTags.map((item) => `<option value="${esc(item.id)}">${esc(item.name)}</option>`).join("")}`;
      if (productSelect) productSelect.value = filters.product_code;
      if (tagSelect) tagSelect.value = filters.tag_id;
    });
  }

  async function renderTags() {
    root.innerHTML = top("tags") + '<div class="crm-loading">Загружаю теги…</div>';
    bindTop();
    const q = state.tagQuery || "";
    const category = state.tagCategory || "";
    const status = state.tagStatus === undefined ? "active" : state.tagStatus;
    const params = new URLSearchParams({ q, category, status });
    state.tags = await api(`/admin/api/tags?${params}`);
    const categoryOptions = Object.entries(tagCategories).map(([value, label]) => `<option value="${value}">${label}</option>`).join("");
    const cards = state.tags.map((tag) => `
      <article class="crm-card crm-tag-card" data-tag-id="${esc(tag.id)}">
        <div class="crm-tag-head"><div><strong>${esc(tag.name)}</strong><div class="crm-row-meta">${tag.user_count} человек · ${esc(tag.sources || "источник не указан")}</div></div>
          <span class="crm-status ${tag.status === "active" ? "st-paid" : "st-processing"}">${tag.status === "merged" ? `объединён → ${esc(tag.merged_into_name)}` : esc(tag.status)}</span></div>
        ${tag.status === "merged" ? "" : `<div class="crm-tag-edit">
          <input class="crm-input tag-name" value="${esc(tag.name)}">
          <select class="crm-input tag-category">${categoryOptions.replace(`value="${esc(tag.category)}"`, `value="${esc(tag.category)}" selected`)}</select>
          <select class="crm-input tag-status"><option value="active" ${tag.status === "active" ? "selected" : ""}>Активен</option><option value="review" ${tag.status === "review" ? "selected" : ""}>На разбор</option><option value="archived" ${tag.status === "archived" ? "selected" : ""}>Архив</option></select>
          <button class="crm-btn small tag-save">Сохранить</button>
          <button class="crm-btn alt small tag-merge">Объединить</button>
        </div>`}
      </article>`).join("");
    root.innerHTML = top("tags") + `
      <div class="crm-toolbar crm-tag-toolbar">
        <input class="crm-search" id="tag-search" placeholder="Поиск тега" value="${esc(q)}">
        <select class="crm-input" id="tag-category-filter"><option value="">Все группы</option>${categoryOptions}</select>
        <select class="crm-input" id="tag-status-filter"><option value="active">Активные</option><option value="review">На разбор</option><option value="archived">Архив</option><option value="merged">Объединённые</option><option value="">Все</option></select>
      </div>
      <section class="crm-card"><div class="crm-card-title">Порядок в тегах <span class="crm-card-sub">${state.tags.length} вариантов</span></div>
        <div class="crm-row-meta">Переименование сразу меняет название у всех людей. «Объединить» сохраняет исходные назначения и показывает основной тег — действие обратимо.</div></section>
      <div class="crm-tag-list">${cards || '<div class="crm-card crm-empty">Теги не найдены</div>'}</div>
      <div class="crm-foot">Исходные назначения LeadTeh сохраняются · покупки остаются отдельными фактами</div>`;
    bindTop();
    document.getElementById("tag-category-filter").value = category;
    document.getElementById("tag-status-filter").value = status;
    let timer;
    document.getElementById("tag-search").addEventListener("input", (event) => {
      clearTimeout(timer);
      state.tagQuery = event.target.value;
      timer = setTimeout(() => renderTags().catch(showError), 300);
    });
    document.getElementById("tag-category-filter").addEventListener("change", (event) => {
      state.tagCategory = event.target.value;
      renderTags().catch(showError);
    });
    document.getElementById("tag-status-filter").addEventListener("change", (event) => {
      state.tagStatus = event.target.value;
      renderTags().catch(showError);
    });
    root.querySelectorAll(".crm-tag-card").forEach((card) => {
      const id = card.dataset.tagId;
      const save = card.querySelector(".tag-save");
      if (save) save.addEventListener("click", async () => {
        await api(`/admin/api/tags/${id}`, { method: "PATCH", body: JSON.stringify({
          name: card.querySelector(".tag-name").value,
          category: card.querySelector(".tag-category").value,
          status: card.querySelector(".tag-status").value
        }) });
        state.userTags = null;
        await renderTags();
      });
      const merge = card.querySelector(".tag-merge");
      if (merge) merge.addEventListener("click", async () => {
        const targetName = window.prompt("Введите точное название основного тега, в который объединяем:");
        if (!targetName) return;
        await api(`/admin/api/tags/${id}/merge`, { method: "POST", body: JSON.stringify({ target_name: targetName }) });
        state.userTags = null;
        await renderTags();
      });
    });
  }

  async function renderTagAudit() {
    root.innerHTML = top("tags") + '<div class="crm-loading">Собираю каталог тегов…</div>';
    bindTop();
    const [tags, variables] = await Promise.all([
      api("/admin/api/tags?status="), api("/admin/api/audit/variables")
    ]);
    const labels = {content:"Материалы",source:"Источники",tariff:"Тарифы и подсказки",
      purchase:"Подтверждения покупок",subscription:"Подписки",routing:"Маршрутизация",
      access_hint:"Проверка доступов",review:"На разбор",content_review:"Контент на разбор",
      refund:"Возвраты",lottery:"Лотерея",
      funnel:"Архив — старые воронки",intensive:"Архив — старый интенсив",
      obsolete:"Архив — устаревшее",technical:"Архив — служебное"};
    const grouped = {};
    tags.forEach((tag) => (grouped[tag.category] ||= []).push(tag));
    const columns = Object.entries(labels).map(([key,label]) => {
      const items = grouped[key] || [];
      return `<section class="crm-tag-column"><h3>${label} · ${items.length}</h3>${items.map((tag) =>
        `<button class="crm-tag-chip" data-tag-id="${esc(tag.id)}"><strong>${esc(tag.name)}</strong><small>${tag.user_count} человек · ${esc(tag.status)}${tag.audit_reason ? ` · ${esc(tag.audit_reason)}` : ""}</small></button>`
      ).join("") || '<div class="crm-row-meta">Пусто</div>'}</section>`;
    }).join("");
    const variableActions = variables.reduce((acc,item) => { acc[item.action]=(acc[item.action]||0)+1; return acc; },{});
    root.innerHTML = top("tags") + `
      <div class="crm-review-banner">Старые теги не удалены: архив скрыт из карточек, объединения обратимы, сомнительные записи находятся в «На разбор».</div>
      <div class="crm-tag-board">${columns}</div>
      <section class="crm-card" style="margin-top:10px"><div class="crm-card-title">Переменные LeadTeh <span class="crm-card-sub">${variables.length} разобрано</span></div>
        <div class="crm-row-meta">Не превращаем 227 технических переменных в колонки CRM. Итог аудита: ${Object.entries(variableActions).map(([k,v])=>`${esc(k)} — ${v}`).join(" · ")}</div></section>
      <div class="crm-foot">Нажмите тег, чтобы открыть точное редактирование</div>`;
    bindTop();
    root.querySelectorAll("[data-tag-id]").forEach((button) => button.addEventListener("click", () => {
      state.tagQuery = button.querySelector("strong").textContent; state.tagStatus = ""; renderTags().catch(showError);
    }));
  }

  async function renderAccessReviews() {
    root.innerHTML = top("access") + '<div class="crm-loading">Загружаю очередь…</div>';
    bindTop();
    const rows = await api("/admin/api/access-reviews");
    root.innerHTML = top("access") + `<section class="crm-card"><div class="crm-card-title">Ручная проверка доступов <span class="crm-card-sub">${rows.length} человек</span></div>
      <div class="crm-row-meta">Сначала человек регистрируется в личном кабинете, затем связывает Telegram по email. Никакой исторический тег не выдаёт доступ автоматически.</div></section>
      <div class="crm-list">${rows.map((user) => `<article class="crm-client"><button class="crm-client-button" data-user-id="${esc(user.id)}"><div class="crm-client-top"><div><div class="crm-name">${esc(user.display_name || user.email || user.telegram || "Без имени")}</div><div class="crm-email">${esc(user.email || "ждём регистрацию/email")} ${user.telegram ? `· @${esc(user.telegram)}` : ""}</div></div><span class="crm-status st-processing">${esc(user.access_review_status)}</span></div><div class="crm-row-meta">Покупок: ${user.purchase_count} · Tilda: ${esc(user.tilda_access_status)}</div></button></article>`).join("") || '<div class="crm-card crm-empty">Очередь пуста</div>'}</div>`;
    bindTop(); bindUserCards();
  }

  async function renderPayments() {
    root.innerHTML = top("payments") + '<div class="crm-loading">Загружаю оплаты…</div>';
    bindTop();
    const filters = state.paymentFilters;
    const params = new URLSearchParams({ limit: String(paymentPageSize), offset: String(state.paymentOffset) });
    Object.entries(filters).forEach(([key, value]) => { if (value !== "") params.set(key, value); });
    if (state.paymentSnapshotAt) params.set("snapshot_at", state.paymentSnapshotAt);
    const productRequest = state.userProducts ? Promise.resolve(state.userProducts) : api("/admin/api/payment-products").catch(() => null);
    const payments = await api(`/admin/api/payments?${params}`);
    const products = state.userProducts || [];
    state.payments = payments;
    if (!state.paymentSnapshotAt && payments[0] && payments[0].snapshot_at) state.paymentSnapshotAt = payments[0].snapshot_at;
    const rows = state.payments.map((payment) => `
      <tr ${payment.user_id ? `data-user-id="${esc(payment.user_id)}"` : ""}>
        <td>${date(payment.paid_at || payment.source_event_at, true)}</td>
        <td><strong>${esc(payment.display_name || payment.payer_name || "Без имени")}</strong><div class="crm-email">${esc(payment.email || (payment.user_id ? "" : "ещё не привязан к карточке"))}</div></td>
        <td>${esc(payment.product_name || "Продукт не определён")}${payment.external_order_id ? `<div class="crm-row-meta">№ ${esc(payment.external_order_id)}</div>` : ""}${payment.review_status === "pending" || !["paid","confirmed"].includes(payment.status) ? `<div class="crm-payment-warning">${payment.review_status === "pending" ? "нужна проверка" : esc(payment.status)}</div>` : ""}</td>
        <td class="crm-money crm-payment-amount">${payment.amount_is_estimated ? "≈ " : ""}${money(payment.amount)}</td>
      </tr>`).join("");
    root.innerHTML = top("payments") + `<form class="crm-payment-toolbar" id="payment-filters">
        <input class="crm-input" id="payment-q" placeholder="Человек, email или продукт" value="${esc(filters.q)}">
        <select class="crm-input" id="payment-product"><option value="">Все продукты</option>${products.map((item) => `<option value="${esc(item.code)}" ${filters.product_code === item.code ? "selected" : ""}>${esc(item.name)}</option>`).join("")}</select>
        <label><span>С</span><input class="crm-input" id="payment-from" type="date" value="${esc(filters.date_from)}"></label>
        <label><span>По</span><input class="crm-input" id="payment-to" type="date" value="${esc(filters.date_to)}"></label>
        <select class="crm-input" id="payment-kind"><option value="all">Факт и оценки</option><option value="actual" ${filters.amount_kind === "actual" ? "selected" : ""}>Только факт</option><option value="estimated" ${filters.amount_kind === "estimated" ? "selected" : ""}>Только оценки</option></select>
        <button class="crm-btn" type="submit">Показать</button>
      </form>
      <div class="crm-table-wrap"><table class="crm-table">
        <thead><tr><th>Дата</th><th>Человек</th><th>Что куплено</th><th>Сумма</th></tr></thead>
        <tbody>${rows || '<tr><td colspan="4" class="crm-empty">Оплат пока нет</td></tr>'}</tbody>
      </table></div>
      <div class="crm-pager"><button class="crm-btn alt small" id="payment-prev" ${state.paymentOffset === 0 ? "disabled" : ""}>← Предыдущие</button><span>${state.payments.length ? `${state.paymentOffset + 1}–${state.paymentOffset + state.payments.length}` : "0"}</span><button class="crm-btn alt small" id="payment-next" ${state.payments.length < paymentPageSize ? "disabled" : ""}>Следующие →</button></div>`;
    bindTop();
    bindUserCards();
    document.getElementById("payment-filters").addEventListener("submit", (event) => {
      event.preventDefault();
      state.paymentFilters = {
        q: document.getElementById("payment-q").value,
        product_code: document.getElementById("payment-product").value,
        date_from: document.getElementById("payment-from").value,
        date_to: document.getElementById("payment-to").value,
        amount_kind: document.getElementById("payment-kind").value
      };
      state.paymentOffset = 0;
      state.paymentSnapshotAt = null;
      renderPayments().catch(showError);
    });
    document.getElementById("payment-prev").addEventListener("click", () => { state.paymentOffset = Math.max(0, state.paymentOffset - paymentPageSize); renderPayments().catch(showError); });
    document.getElementById("payment-next").addEventListener("click", () => { state.paymentOffset += paymentPageSize; renderPayments().catch(showError); });
    productRequest.then((loadedProducts) => {
      if (!loadedProducts) return;
      state.userProducts = loadedProducts;
      const select = document.getElementById("payment-product");
      if (!select) return;
      select.innerHTML = `<option value="">Все продукты</option>${loadedProducts.map((item) => `<option value="${esc(item.code)}">${esc(item.name)}</option>`).join("")}`;
      select.value = filters.product_code;
    });
  }

  function renderStructure() {
    root.innerHTML = top("structure") + `
      <section class="crm-card">
        <div class="crm-card-title">Главный принцип</div>
        <p>Один человек хранится один раз в таблице <strong>users</strong>. Email, Telegram, оплаты, доступы, теги и данные приложений присоединяются к нему по единому <strong>user_id</strong>.</p>
        <p class="crm-row-meta">Поэтому база не превращается в одну таблицу с сотнями колонок, а карточка клиента собирает связанные сведения в одном понятном экране.</p>
        <p class="crm-row-meta"><strong>История</strong> — перенесённые данные, которые могут быть неполными. <strong>Новая система</strong> — клиенты, созданные текущим API после переключения интеграций.</p>
      </section>
      <div class="crm-flow">
        <div class="crm-flow-step"><strong>1. Человек</strong>users → основная карточка и постоянный user_id</div>
        <div class="crm-flow-step"><strong>2. Контакты</strong>user_emails + messenger_accounts → почты, Telegram и будущие каналы</div>
        <div class="crm-flow-step"><strong>3. Продажи</strong>payments → каждая попытка оплаты и купленный продукт</div>
        <div class="crm-flow-step"><strong>4. Доступ</strong>products + product_access_rules → user_accesses → что именно разрешено человеку</div>
        <div class="crm-flow-step"><strong>5. Работа с клиентом</strong>tags + user_tags + client_notes + attribution_events → сегменты, заметки и источники</div>
        <div class="crm-flow-step"><strong>6. Приложения</strong>отдельные таблицы DQS, тренировок и других продуктов будут ссылаться на тот же users.id</div>
      </div>
      <div class="crm-structure-grid">
        <section class="crm-card"><div class="crm-card-title">CRM-ядро</div><div class="crm-row-meta">users, user_emails, messenger_accounts, payments, attribution_events, tags, user_tags, client_notes</div></section>
        <section class="crm-card"><div class="crm-card-title">Продукты и права</div><div class="crm-row-meta">products, product_aliases, resources, product_access_rules, user_accesses</div></section>
        <section class="crm-card"><div class="crm-card-title">Контроль переноса</div><div class="crm-row-meta">import_batches, legacy_import_records, user_merge_events — технический журнал импорта и объединения дублей</div></section>
      </div>
      <section class="crm-card" style="margin-top:10px">
        <div class="crm-card-title">Полный паспорт базы</div>
        <p class="crm-row-meta">В документе перечислены все таблицы, их поля, связи, правила изменения и схема добавления будущих приложений.</p>
        <a class="crm-doc-link" href="https://github.com/armagedongt/edabalans.ru/blob/main/docs/CRM_DATA_MODEL.md" target="_blank" rel="noopener">Открыть документ</a>
      </section>
      <div class="crm-foot">Эта вкладка и документ обновляются вместе с каждой миграцией структуры базы</div>`;
    bindTop();
  }

  function purchaseCard(item, user) {
    const code = String(item.product_code || "").toUpperCase();
    const tone = /CONSULT|COACHING/.test(code) ? "is-service" : /DQS|ADDON|RECIPE/.test(code) || item.tariff === "Дополнение" ? "is-addon" : "is-core";
    const details = [
      date(item.paid_at || item.purchased_at || item.source_event_at, false),
      item.external_order_id ? `№ ${item.external_order_id}` : "",
    ].filter(Boolean).join(" · ");
    const amount = item.amount === undefined || item.amount === null
      ? ""
      : `<strong class="crm-purchase-amount">${item.amount_is_estimated ? "≈ " : ""}${money(item.amount)}</strong>`;
    return `<div class="crm-preview crm-purchase-preview" data-preview-kind="progress" data-preview-user="${esc(user.id)}"><button class="crm-preview-trigger crm-purchase-item ${tone}" type="button" aria-expanded="false" aria-label="Показать прогресс: ${esc(item.product_name || "продукт")}"><span class="crm-purchase-main"><span><strong>${esc(item.product_name || "Продукт не определён")}</strong>${item.tariff ? `<span class="crm-purchase-tariff">${esc(item.tariff)}</span>` : ""}</span>${amount}</span>${details && details !== "—" ? `<span class="crm-row-meta">${esc(details)}</span>` : ""}</button><div class="crm-popover" role="tooltip"><div class="crm-popover-loading">Загружаю…</div></div></div>`;
  }

  async function openUser(id) {
    root.innerHTML = top("") + '<div class="crm-loading">Открываю карточку…</div>';
    const user = await loadUserDetail(id);
    const resources = await api("/admin/api/resources");
    const [moduleResult, personalLinkResult] = await Promise.all([
      api(`/admin/api/users/${id}/modules`),
      api(`/admin/api/users/${id}/personal-access-links`)
    ]);
    const modules = moduleResult.modules;
    const personalLinks = personalLinkResult.links || [];
    let botState = null;
    try { botState = await api(`/bot-api/users/${id}`); } catch (_) { /* Telegram may not be connected yet. */ }
    const primaryEmail = user.emails[0] && user.emails[0].email;
    const stage = clientStage(user);
    const otherTags = user.tags.filter((item) => item.category !== "purchase");
    const purchasedByCode = new Map((user.purchased_products || []).map((item) => [item.product_code, item]));
    const confirmedPayments = (user.payments || []).filter((item) => ["paid", "confirmed"].includes(item.status));
    const purchaseHistory = confirmedPayments.length
      ? confirmedPayments.map((item) => ({ ...purchasedByCode.get(item.product_code), ...item, tariff: item.tariff || (purchasedByCode.get(item.product_code) || {}).tariff }))
      : (user.purchased_products || []);
    const firstPayment = [...confirmedPayments].sort((left, right) => String(left.paid_at || left.source_event_at || "").localeCompare(String(right.paid_at || right.source_event_at || "")))[0];
    const accessByCode = Array.from(user.accesses.filter((item) => !item.revoked_at).reduce((groups, item) => {
      const current = groups.get(item.code);
      if (!current || (current.paused_at && !item.paused_at)) groups.set(item.code, item);
      return groups;
    }, new Map()).values());
    root.innerHTML = `
      <div class="crm-profile-head">
        <div class="crm-profile-id">
          <button class="crm-back" id="crm-back">← Назад</button>
          <div class="crm-profile-identity"><div class="crm-name">${esc(user.display_name || primaryEmail || "Без имени")}</div>
          <span class="crm-profile-email">${esc(primaryEmail || "email не указан")}</span><span class="crm-profile-messengers">${profileMessengerButton(user, "telegram")}${profileMessengerButton(user, "max")}</span></div>
        </div>
      </div>
      <section class="crm-card crm-apps-card"><div class="crm-card-title">Человек в системе</div>
        <div class="crm-app-links">
          <a class="crm-app-link ${modules.dqs.exists || modules.dqs.has_access ? "available" : "disabled"}" href="${modules.dqs.exists || modules.dqs.has_access ? `/admin/dqs?user=${user.id}` : "#"}"><strong>DQS</strong><span>${modules.dqs.exists ? "открыть аналитику" : modules.dqs.has_access ? "доступ есть, данных нет" : "нет доступа"}</span></a>
          <a class="crm-app-link ${modules.strength.exists || modules.strength.has_access ? "available" : "disabled"}" href="${modules.strength.exists || modules.strength.has_access ? `/admin/strength?user=${user.id}` : "#"}"><strong>Силовые</strong><span>${modules.strength.exists ? "открыть тренировки" : modules.strength.has_access ? "открыть приложение" : "нет доступа"}</span></a>
          <a class="crm-app-link ${modules.metabolism.exists || modules.metabolism.has_access ? "available" : "disabled"}" href="${modules.metabolism.exists || modules.metabolism.has_access ? `/admin/metabolism?user=${user.id}` : "#"}"><strong>Метаболизм</strong><span>${modules.metabolism.exists ? "открыть расчёт" : modules.metabolism.has_access ? "открыть приложение" : "нет доступа"}</span></a>
        </div>
      </section>
      <div class="crm-profile-summary">
        <div><span>Первое появление</span><strong>${date(user.first_seen_at, false)}</strong></div>
        <div><span>Первая оплата</span><strong>${firstPayment ? date(firstPayment.paid_at || firstPayment.source_event_at, false) : "—"}</strong><em>${paymentDelayFromBot(user, firstPayment)}</em></div>
        <div><span>Оплачено</span>${previewTrigger("payments", user, `<strong>${money(user.ltv_rub)}</strong>`)}</div>
        <div><span>Статус и прогресс</span>${previewTrigger("progress", user, `<span class="crm-stage is-${stage.code}">${esc(stage.label)}</span>`)}</div>
        <div><span>Подписка</span><span class="crm-channel-state ${channelState(user).tone}">${channelState(user).label}</span></div>
      </div>
      <section class="crm-card crm-note-card"><div class="crm-card-title">Заметки</div>
        <div class="crm-note-layout"><form class="crm-form" id="note-form"><textarea class="crm-textarea" id="note-body" placeholder="Добавить комментарий о клиенте"></textarea><button class="crm-btn small" type="submit">Сохранить заметку</button></form>
        <div class="crm-note-history">${user.notes.slice(0, 3).map((item) => `<div class="crm-row"><div>${esc(item.body)}</div><div class="crm-row-meta">${date(item.created_at, true)} · ${esc(item.author)}</div></div>`).join("") || '<div class="crm-empty">Заметок пока нет</div>'}${user.notes.length > 3 ? `<div class="crm-row-meta">Ещё ${user.notes.length - 3} заметок</div>` : ""}</div></div>
      </section>
      <div class="crm-profile-main-grid">
        <section class="crm-card crm-purchases-card"><div class="crm-card-title">Покупки и тарифы</div>
          <div class="crm-purchase-grid">${purchaseHistory.map((item) => purchaseCard(item, user)).join("") || '<div class="crm-empty">Подтверждённых покупок пока нет</div>'}</div>
          <details class="crm-inline-access" open><summary><strong>Управление доступами</strong><span>${accessByCode.filter((item)=>!item.paused_at).length} активных</span></summary>
            <div class="crm-access-heading">Текущие доступы</div>
            <div class="crm-access-list">${accessByCode.map((item)=>`<div class="crm-access-row"><div><strong>${esc(item.name)}</strong><span>${item.paused_at ? "Приостановлен" : "Действует"}</span></div><div><button class="crm-btn alt small ${item.paused_at ? "resume-access" : "pause-access"}" data-code="${esc(item.code)}" type="button">${item.paused_at ? "Возобновить" : "Приостановить"}</button><button class="crm-btn alt small revoke-access" data-code="${esc(item.code)}" type="button">Отозвать</button></div></div>`).join("") || '<div class="crm-empty">Доступов нет</div>'}</div>
            <div class="crm-access-heading">Выдать доступ</div>
            <form class="crm-two" id="grant-form"><select class="crm-input" id="resource-code"><option value="" selected disabled>Выберите доступ</option>${resources.map((r)=>`<option value="${esc(r.code)}">${esc(r.name)}</option>`).join("")}</select><button class="crm-btn small">Выдать</button></form>
            <div class="crm-access-explainer">Приостановить — временно закрыть, сохранив запись. Возобновить — вернуть её. Отозвать — окончательно закрыть текущую выдачу.</div>
          </details>
          <details class="crm-inline-personal"><summary><strong>Персональная ссылка на доступ</strong></summary>
            <form class="crm-form" id="personal-link-form">
              <div class="crm-resource-grid">${resources.map((r)=>`<label><input type="checkbox" name="personal-resource" value="${esc(r.code)}"> <span>${esc(r.name)}</span></label>`).join("")}</div>
              <div class="crm-two-fields"><label><div class="crm-k">ОБЫЧНАЯ СТОИМОСТЬ</div><input class="crm-input" id="personal-standard" type="number" min="0" step="1" placeholder="например 10800"></label><label><div class="crm-k">ИТОГО</div><input class="crm-input" id="personal-final" type="number" min="0" step="1" value="0"></label></div>
              <div class="crm-two-fields"><label><div class="crm-k">ССЫЛКА ДЕЙСТВУЕТ, ДНЕЙ</div><input class="crm-input" id="personal-days" type="number" min="1" max="365" value="14"></label><label class="crm-check"><input id="personal-unlock" type="checkbox"><span>Открыть все дни выбранных курсов сразу</span></label></div>
              <button class="crm-btn small">Сформировать ссылку и сообщение</button>
            </form>
            <div id="personal-link-result"></div>
            ${personalLinks.length ? `<div class="crm-card-sub" style="margin-top:14px">Последние ссылки</div>${personalLinks.slice(0,5).map((item)=>`<div class="crm-row"><div class="crm-row-main"><span>${item.mode==='free'?'Бесплатно':money(item.final_amount)}</span><strong>${esc(item.status)}</strong></div><div class="crm-row-meta">${esc(item.resources.join(', '))} · до ${date(item.expires_at,true)}</div></div>`).join("")}` : ""}
          </details>
        </section>
        <div>
          <section class="crm-card"><div class="crm-card-title">Контакты</div>
            <form class="crm-form" id="name-form"><label><div class="crm-k">ИМЯ</div><input class="crm-input" id="display-name" value="${esc(user.display_name || "")}"></label>
              <button class="crm-btn small" type="submit">Сохранить имя</button></form>
            ${user.emails.map((item) => `<div class="crm-row"><div class="crm-row-main"><span>${esc(item.email)}</span><span>${item.primary ? "основной" : ""}</span></div></div>`).join("") || `<form class="crm-two" id="email-form"><input class="crm-input" id="link-email" type="email" placeholder="Email после регистрации в ЛК"><button class="crm-btn small">Связать</button></form>`}
            ${user.phones.map((item) => `<div class="crm-row"><div class="crm-row-main"><span>${esc(item.phone)}</span><span>телефон</span></div></div>`).join("")}
            <div class="crm-row"><div class="crm-k">ВХОД В ЛИЧНЫЙ КАБИНЕТ</div><div class="crm-row-main"><span>${user.credential.exists ? "Пароль создан" : "Пароль ещё не создан"}</span><code id="account-password-value">••••••••</code></div><div class="crm-two" style="margin-top:10px"><button class="crm-btn small" id="reveal-account-password" type="button" ${user.credential.password_available ? "" : "disabled"}>Показать пароль</button><button class="crm-btn small" id="reset-account-password" type="button">${user.credential.exists ? "Задать новый" : "Создать пароль"}</button></div></div>
          </section>
        </div>
      </div>
      <div class="crm-grid">
        <section class="crm-card"><div class="crm-card-title">Этапы рассылки <span class="crm-card-sub">${botState ? esc(botState.run_status || "без цепочки") : "не подключена"}</span></div>
            ${botState ? `<div class="crm-row-meta">Шаг: ${esc(botState.current_step || "—")} · отправлено ${botState.sent} из ${botState.total}</div>
              <div style="height:8px;background:#edf1ea;border-radius:8px;overflow:hidden;margin:10px 0"><div style="height:100%;width:${botState.total ? Math.min(100, botState.sent / botState.total * 100) : 0}%;background:#2f6b47"></div></div>
              ${botState.error ? `<div class="crm-row-meta" style="color:#a24b38">${esc(botState.error)}</div>` : ""}
              <form class="crm-form" id="telegram-message-form"><textarea class="crm-textarea" id="telegram-message" placeholder="Написать этому клиенту в Telegram"></textarea><button class="crm-btn small" type="submit">Отправить сообщение</button></form>` : '<div class="crm-row-meta">У клиента пока нет связанного аккаунта тестового Telegram-бота.</div>'}
        </section>
        <section class="crm-card"><div class="crm-card-title">Теги</div><div class="crm-tags">${otherTags.map((item) => `<span class="crm-tag">${esc(item.name)}</span>`).join("") || '<span class="crm-tag empty">тегов нет</span>'}</div>
            <form class="crm-two" id="tag-form" style="margin-top:10px"><input class="crm-input" id="tag-name" placeholder="Например: рассылка 100"><button class="crm-btn small" type="submit">Добавить</button></form>
        </section>
      </div>`;

    bindTop();
    bindUserPreviews();
    document.getElementById("crm-back").addEventListener("click", () => showView(state.view));
    document.getElementById("name-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      await api(`/admin/api/users/${id}`, { method: "PATCH", body: JSON.stringify({ display_name: document.getElementById("display-name").value }) });
      await refreshUser(id);
    });
    const emailForm = document.getElementById("email-form");
    if (emailForm) emailForm.addEventListener("submit", async (event) => { event.preventDefault(); await api(`/admin/api/users/${id}/email`, {method:"POST", body:JSON.stringify({email:document.getElementById("link-email").value})}); await refreshUser(id); });
    document.getElementById("reveal-account-password").addEventListener("click", async () => {
      const result = await api(`/admin/api/users/${id}/credential/reveal`, {method:"POST"});
      document.getElementById("account-password-value").textContent = result.password;
    });
    document.getElementById("reset-account-password").addEventListener("click", async () => {
      if (user.credential.exists && !window.confirm("Текущий пароль перестанет работать, а все активные входы клиента завершатся. Продолжить?")) return;
      const result = await api(`/admin/api/users/${id}/credential/reset`, {method:"POST"});
      document.getElementById("account-password-value").textContent = result.password;
    });
    document.getElementById("grant-form").addEventListener("submit", async (event) => { event.preventDefault(); await api(`/admin/api/users/${id}/accesses`, {method:"POST", body:JSON.stringify({resource_code:document.getElementById("resource-code").value})}); await refreshUser(id); });
    document.getElementById("personal-link-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      const resourceCodes = Array.from(root.querySelectorAll('input[name="personal-resource"]:checked')).map((input) => input.value);
      if (!resourceCodes.length) { document.getElementById("personal-link-result").innerHTML = '<div class="crm-review-banner">Выберите хотя бы один продукт.</div>'; return; }
      const standardValue = document.getElementById("personal-standard").value;
      const result = await api(`/admin/api/users/${id}/personal-access-links`, {method:"POST",body:JSON.stringify({resource_codes:resourceCodes,standard_amount:standardValue===""?null:Number(standardValue),final_amount:Number(document.getElementById("personal-final").value||0),expires_days:Number(document.getElementById("personal-days").value||14),fully_unlocked:document.getElementById("personal-unlock").checked})});
      document.getElementById("personal-link-result").innerHTML = `<textarea class="crm-textarea" id="personal-ready-text" readonly>${esc(result.telegram_text)}</textarea><button class="crm-btn small" id="copy-personal-text" type="button">Скопировать сообщение</button>`;
      document.getElementById("copy-personal-text").onclick = async () => { await navigator.clipboard.writeText(result.telegram_text); document.getElementById("copy-personal-text").textContent = "Скопировано"; };
    });
    root.querySelectorAll(".revoke-access").forEach((button)=>button.addEventListener("click", async()=>{ if (!window.confirm("Закрыть этот доступ?")) return; await api(`/admin/api/users/${id}/accesses/${button.dataset.code}`, {method:"DELETE"}); await refreshUser(id); }));
    root.querySelectorAll(".pause-access").forEach((button)=>button.addEventListener("click", async()=>{ await api(`/admin/api/users/${id}/accesses/${button.dataset.code}/pause`, {method:"POST"}); await refreshUser(id); }));
    root.querySelectorAll(".resume-access").forEach((button)=>button.addEventListener("click", async()=>{ await api(`/admin/api/users/${id}/accesses/${button.dataset.code}/resume`, {method:"POST"}); await refreshUser(id); }));
    document.getElementById("tag-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      const name = document.getElementById("tag-name").value.trim();
      if (!name) return;
      await api(`/admin/api/users/${id}/tags`, { method: "POST", body: JSON.stringify({ name }) });
      await refreshUser(id);
    });
    document.getElementById("note-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      const body = document.getElementById("note-body").value.trim();
      if (!body) return;
      await api(`/admin/api/users/${id}/notes`, { method: "POST", body: JSON.stringify({ body }) });
      await refreshUser(id);
    });
    const telegramForm = document.getElementById("telegram-message-form");
    if (telegramForm) telegramForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const text = document.getElementById("telegram-message").value.trim();
      if (!text) return;
      await api(`/bot-api/users/${id}/messages`, { method: "POST", body: JSON.stringify({ text }) });
      document.getElementById("telegram-message").value = "";
      event.submitter.textContent = "Отправлено";
    });
  }

  async function refreshUser(id) {
    state.userDetails.delete(id);
    await openUser(id);
  }

  async function loadHome(view) {
    state.summary = await api("/admin/api/summary");
    return showView(view || state.view);
  }

  async function showView(view) {
    if (view !== state.view && (view === "users" || view === "buyers")) state.offset = 0;
    if (view !== state.view && view === "payments") { state.paymentOffset = 0; state.paymentSnapshotAt = null; }
    state.view = view;
    if (view === "payments") return renderPayments();
    if (view === "access") return renderAccessReviews();
    if (view === "tags") return renderTagAudit();
    if (view === "structure") return renderStructure();
    return renderUsers(view === "buyers");
  }

  function showError(error) {
    root.innerHTML = `<div class="crm-error"><strong>CRM не загрузилась</strong><div style="margin-top:8px">${esc(error.message)}</div><button class="crm-btn" style="margin-top:14px" id="retry">Повторить</button></div>`;
    const retry = document.getElementById("retry");
    if (retry) retry.addEventListener("click", () => loadHome().catch(showError));
  }

  async function initialise() {
    state.summary = await api("/admin/api/summary");
    const params = new URLSearchParams(location.search); state.query = params.get("q") || "";
    const initialUser = params.get("user");
    if (initialUser) return openUser(initialUser);
    return showView("users");
  }

  initialise().catch(showError);
})();
