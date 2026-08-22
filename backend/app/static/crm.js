(function () {
  "use strict";

  const root = document.getElementById("crm-app");
  const state = { view: "users", query: "", summary: null, users: [], payments: [], tags: [], offset: 0 };
  const pageSize = 250;
  const tagCategories = {
    manual: "Ручные",
    subscription: "Подписка",
    content_action: "Контент и действия",
    mailing_funnel: "Рассылки и воронки",
    source: "Источники",
    purchase_signal: "Сигналы о покупке",
    lottery: "Лотерея",
    other: "Прочее",
    technical: "Служебные"
    ,content: "Материалы", funnel: "Старые воронки", intensive: "Старый интенсив",
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
          <div><div class="crm-title">CRM клиентов</div><div class="crm-subtitle">Единая база Edabalans</div></div>
          <div class="crm-live">● РАБОТАЕТ</div>
        </div>
        <div class="crm-tabs">
          <button class="crm-tab ${active === "users" ? "active" : ""}" data-view="users">Все люди</button>
          <button class="crm-tab ${active === "buyers" ? "active" : ""}" data-view="buyers">Покупатели</button>
          <button class="crm-tab ${active === "payments" ? "active" : ""}" data-view="payments">Оплаты</button>
          <button class="crm-tab ${active === "access" ? "active" : ""}" data-view="access">Доступы</button>
          <button class="crm-tab ${active === "tags" ? "active" : ""}" data-view="tags">Теги</button>
          <button class="crm-tab ${active === "structure" ? "active" : ""}" data-view="structure">Как устроено</button>
        </div>
      </div>`;
  }

  function bindTop() {
    root.querySelectorAll("[data-view]").forEach((button) => {
      button.addEventListener("click", () => showView(button.dataset.view));
    });
  }

  function stats() {
    const data = state.summary || {};
    return `
      <div class="crm-stats">
        <div class="crm-stat"><div class="crm-k">ЛЮДЕЙ В CRM</div><div class="crm-v">${data.users || 0}</div><div class="crm-s">единый user_id</div></div>
        <div class="crm-stat"><div class="crm-k">ПОКУПАТЕЛЕЙ</div><div class="crm-v">${data.buyers || 0}</div><div class="crm-s">есть подтверждённая оплата</div></div>
        <div class="crm-stat"><div class="crm-k">ПОКУПОК В ИСТОРИИ</div><div class="crm-v">${data.paid_payments || 0}</div><div class="crm-s">включая старые без известной суммы</div></div>
        <div class="crm-stat"><div class="crm-k">ВЫРУЧКА</div><div class="crm-v">${money(data.revenue_rub)}</div><div class="crm-s">подтверждённые RUB</div></div>
        <div class="crm-stat"><div class="crm-k">АККАУНТОВ TILDA</div><div class="crm-v">${data.tilda_members || 0}</div><div class="crm-s">последняя каноничная сверка</div></div>
        <div class="crm-stat"><div class="crm-k">ПРОВЕРИТЬ ДОСТУПЫ</div><div class="crm-v">${data.access_reviews || 0}</div><div class="crm-s">только реальные спорные случаи</div></div>
      </div>`;
  }

  function accessTags(accesses) {
    if (!accesses || !accesses.length) return '<span class="crm-tag empty">доступов нет</span>';
    return accesses.map((code) => `<span class="crm-tag">${esc(code.replace("ACCESS_", ""))}</span>`).join("");
  }

  function userCard(user) {
    const buyer = user.purchase_count > 0;
    const origin = user.data_origin === "native" ? "Новая система" : "История";
    return `
      <article class="crm-client">
        <button class="crm-client-button" data-user-id="${esc(user.id)}">
          <div class="crm-client-top">
            <div><div class="crm-name">${esc(user.display_name || user.email || user.telegram || "Без имени")}</div>
            <div class="crm-email">${esc(user.email || "email не указан")}${user.telegram ? ` · @${esc(user.telegram)}` : ""}</div></div>
            <div class="crm-badges"><span class="crm-origin ${user.data_origin === "native" ? "origin-native" : "origin-legacy"}">${origin}</span><span class="crm-status ${buyer ? "st-buyer" : "st-lead"}">${buyer ? "Покупатель" : "Лид"}</span></div>
          </div>
          <div class="crm-client-grid">
            <div class="crm-mini"><div class="crm-k">ОПЛАЧЕНО</div><div class="crm-v">${money(user.ltv_rub)}</div></div>
            <div class="crm-mini"><div class="crm-k">ПОКУПОК</div><div class="crm-v">${user.purchase_count}</div></div>
            <div class="crm-mini"><div class="crm-k">ПОСЛЕДНЯЯ</div><div class="crm-v">${date(user.last_purchase_at, false)}</div></div>
          </div>
          <div class="crm-tags">${accessTags(user.accesses)}</div>
        </button>
      </article>`;
  }

  function bindUserCards() {
    root.querySelectorAll("[data-user-id]").forEach((item) => {
      item.addEventListener("click", () => openUser(item.dataset.userId));
    });
  }

  async function renderUsers(buyersOnly) {
    root.innerHTML = top(buyersOnly ? "buyers" : "users") + '<div class="crm-loading">Загружаю клиентов…</div>';
    bindTop();
    const params = new URLSearchParams({ q: state.query, buyers_only: String(buyersOnly), limit: String(pageSize), offset: String(state.offset) });
    state.users = await api(`/admin/api/users?${params}`);
    root.innerHTML = top(buyersOnly ? "buyers" : "users") + `
      <div class="crm-toolbar">
        <input class="crm-search" id="crm-search" placeholder="Поиск по имени, email или Telegram" value="${esc(state.query)}">
        <button class="crm-btn alt" id="crm-refresh">Обновить</button>
      </div>
      ${stats()}
      <div class="crm-list">${state.users.map(userCard).join("") || '<div class="crm-card crm-empty">Ничего не найдено</div>'}</div>
      <div class="crm-pager">
        <button class="crm-btn alt small" id="crm-prev" ${state.offset === 0 ? "disabled" : ""}>← Предыдущие</button>
        <span>${state.users.length ? `${state.offset + 1}–${state.offset + state.users.length}` : "0"}</span>
        <button class="crm-btn alt small" id="crm-next" ${state.users.length < pageSize ? "disabled" : ""}>Следующие →</button>
      </div>
      <div class="crm-foot">PostgreSQL — источник истины · Google Sheets не используется этой админкой</div>`;
    bindTop();
    bindUserCards();
    const search = document.getElementById("crm-search");
    let timer;
    search.addEventListener("input", () => {
      clearTimeout(timer);
      state.query = search.value;
      state.offset = 0;
      timer = setTimeout(() => renderUsers(buyersOnly).catch(showError), 300);
    });
    document.getElementById("crm-refresh").addEventListener("click", () => loadHome(buyersOnly ? "buyers" : "users"));
    document.getElementById("crm-prev").addEventListener("click", () => {
      state.offset = Math.max(0, state.offset - pageSize);
      renderUsers(buyersOnly).catch(showError);
    });
    document.getElementById("crm-next").addEventListener("click", () => {
      state.offset += pageSize;
      renderUsers(buyersOnly).catch(showError);
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
        await renderTags();
      });
      const merge = card.querySelector(".tag-merge");
      if (merge) merge.addEventListener("click", async () => {
        const targetName = window.prompt("Введите точное название основного тега, в который объединяем:");
        if (!targetName) return;
        await api(`/admin/api/tags/${id}/merge`, { method: "POST", body: JSON.stringify({ target_name: targetName }) });
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
    state.payments = await api("/admin/api/payments?limit=500");
    const rows = state.payments.map((payment) => `
      <tr ${payment.user_id ? `data-user-id="${esc(payment.user_id)}"` : ""}>
        <td>${date(payment.paid_at || payment.source_event_at, true)}</td>
        <td><strong>${esc(payment.display_name || "Без имени")}</strong><div class="crm-email">${esc(payment.email || "")}</div></td>
        <td>${esc(payment.product_name || "Продукт не определён")}</td>
        <td><span class="crm-status ${["paid","confirmed"].includes(payment.status) ? "st-paid" : "st-processing"}">${esc(payment.status)}</span>${payment.review_status === "pending" ? '<div class="crm-row-meta">нужна проверка</div>' : ""}</td>
        <td class="crm-money">${money(payment.amount)}</td>
      </tr>`).join("");
    root.innerHTML = top("payments") + `${stats()}
      <div class="crm-table-wrap"><table class="crm-table">
        <thead><tr><th>Дата</th><th>Человек</th><th>Продукт</th><th>Статус</th><th>Сумма</th></tr></thead>
        <tbody>${rows || '<tr><td colspan="5" class="crm-empty">Оплат пока нет</td></tr>'}</tbody>
      </table></div><div class="crm-foot">Лента оплат неизменяема · повторный webhook не создаёт дубль</div>`;
    bindTop();
    bindUserCards();
  }

  function renderStructure() {
    root.innerHTML = top("structure") + `
      <section class="crm-card">
        <div class="crm-card-title">Главный принцип</div>
        <p>Один человек хранится один раз в таблице <strong>users</strong>. Email, Telegram, оплаты, доступы, теги и данные приложений присоединяются к нему по единому <strong>user_id</strong>.</p>
        <p class="crm-row-meta">Поэтому база не превращается в одну таблицу с сотнями колонок, а карточка клиента собирает связанные сведения в одном понятном экране.</p>
        <p class="crm-row-meta"><strong>История</strong> — данные, перенесённые из старых Google-таблиц и потому потенциально неполные. <strong>Новая система</strong> — клиенты, созданные российским API после переключения интеграций.</p>
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

  function paymentRow(item) {
    return `<div class="crm-row"><div class="crm-row-main"><span>${esc(item.product_name || "Продукт не определён")}</span><strong>${money(item.amount)}</strong></div>
      <div class="crm-row-meta">${date(item.paid_at || item.source_event_at, true)} · ${esc(item.status)}${item.product_code ? ` · ${esc(item.product_code)}` : ""}</div></div>`;
  }

  async function openUser(id) {
    root.innerHTML = top("") + '<div class="crm-loading">Открываю карточку…</div>';
    const user = await api(`/admin/api/users/${id}`);
    const resources = await api("/admin/api/resources");
    let botState = null;
    try { botState = await api(`/bot-api/users/${id}`); } catch (_) { /* Telegram may not be connected yet. */ }
    const primaryEmail = user.emails[0] && user.emails[0].email;
    const telegram = user.messengers.find((item) => item.platform === "telegram");
    const firstSource = user.attribution.find((item) => item.source || item.utm_source || item.utm_campaign);
    const origin = user.data_origin === "native" ? "Новая система" : "История";
    const tilda = user.tilda_membership;
    root.innerHTML = `
      <div class="crm-profile-head">
        <div class="crm-profile-id">
          <button class="crm-back" id="crm-back">← Назад</button>
          <div class="crm-avatar">${esc((user.display_name || primaryEmail || "?").charAt(0).toUpperCase())}</div>
          <div><div class="crm-name">${esc(user.display_name || primaryEmail || "Без имени")}</div>
          <div class="crm-email">${esc(primaryEmail || "email не указан")}${telegram && telegram.username ? ` · @${esc(telegram.username)}` : ""}</div></div>
        </div>
        <div class="crm-badges"><span class="crm-origin ${user.data_origin === "native" ? "origin-native" : "origin-legacy"}">${origin}</span><span class="crm-status ${user.purchase_count ? "st-buyer" : "st-lead"}">${user.purchase_count ? "Покупатель" : "Лид"}</span></div>
      </div>
      <div class="crm-kpis">
        <div class="crm-stat"><div class="crm-k">ОПЛАЧЕНО</div><div class="crm-v">${money(user.ltv_rub)}</div></div>
        <div class="crm-stat"><div class="crm-k">ПОКУПОК</div><div class="crm-v">${user.purchase_count}</div></div>
        <div class="crm-stat"><div class="crm-k">ДОСТУПОВ</div><div class="crm-v">${user.accesses.filter((item) => !item.revoked_at).length}</div></div>
        <div class="crm-stat"><div class="crm-k">ПЕРВОЕ ПОЯВЛЕНИЕ</div><div class="crm-v" style="font-size:15px">${date(user.first_seen_at, false)}</div></div>
      </div>
      <div class="crm-grid">
        <div>
          <section class="crm-card"><div class="crm-card-title">Контакты <span class="crm-card-sub">единый user_id</span></div>
            <form class="crm-form" id="name-form"><label><div class="crm-k">ИМЯ</div><input class="crm-input" id="display-name" value="${esc(user.display_name || "")}"></label>
              <button class="crm-btn small" type="submit">Сохранить имя</button></form>
            ${user.emails.map((item) => `<div class="crm-row"><div class="crm-row-main"><span>${esc(item.email)}</span><span>${item.primary ? "основной" : ""}</span></div></div>`).join("") || `<form class="crm-two" id="email-form"><input class="crm-input" id="link-email" type="email" placeholder="Email после регистрации в ЛК"><button class="crm-btn small">Связать</button></form>`}
            ${user.phones.map((item) => `<div class="crm-row"><div class="crm-row-main"><span>${esc(item.phone)}</span><span>телефон</span></div></div>`).join("")}
            ${user.messengers.map((item) => `<div class="crm-row"><div class="crm-row-main"><span>${esc(item.platform)}</span><strong>${esc(item.username ? `@${item.username}` : item.platform_user_id || "без ID")}</strong></div></div>`).join("")}
          </section>
          <section class="crm-card"><div class="crm-card-title">История покупок</div>${user.payments.map(paymentRow).join("") || '<div class="crm-empty">Покупок пока нет</div>'}</section>
          <section class="crm-card"><div class="crm-card-title">Ручная проверка доступов <span class="crm-card-sub">${esc(user.access_review_status)}</span></div>
            <div class="crm-tags">${user.accesses.filter((item)=>!item.revoked_at).map((item)=>`<button class="crm-tag revoke-access" data-code="${esc(item.code)}">${esc(item.name)} ×</button>`).join("") || '<span class="crm-tag empty">доступов нет</span>'}</div>
            <form class="crm-two" id="grant-form" style="margin-top:10px"><select class="crm-input" id="resource-code">${resources.map((r)=>`<option value="${esc(r.code)}">${esc(r.name)}</option>`).join("")}</select><button class="crm-btn small">Выдать</button></form>
            <form class="crm-form" id="review-form" style="margin-top:10px"><select class="crm-input" id="review-status"><option value="waiting_registration">Ждём регистрацию</option><option value="pending">Проверить</option><option value="completed">Проверено</option><option value="conflict">Конфликт</option><option value="not_required">Не требуется</option></select><select class="crm-input" id="tilda-status"><option value="not_checked">Tilda не проверена</option><option value="pending">Tilda проверить</option><option value="granted">Tilda доступ открыт</option><option value="not_required">Tilda не требуется</option></select><textarea class="crm-textarea" id="review-note" placeholder="Что проверить">${esc(user.access_review_note || "")}</textarea><button class="crm-btn small">Сохранить проверку</button></form>
          </section>
          <section class="crm-card"><div class="crm-card-title">Tilda Members Area <span class="crm-card-sub">${tilda ? esc(tilda.account_status || "импортировано") : "нет в выгрузке"}</span></div>
            ${tilda ? `<div class="crm-tags">${tilda.groups.map((group)=>`<span class="crm-tag">${esc(group)}</span>`).join("") || '<span class="crm-tag empty">групп нет</span>'}</div><div class="crm-row-meta" style="margin-top:10px">Регистрация: ${date(tilda.member_created_at, true)} · последняя активность: ${date(tilda.last_active_at, true)}</div>` : '<div class="crm-row-meta">Этот email не найден в последней каноничной выгрузке Tilda.</div>'}
          </section>
        </div>
        <div>
          <section class="crm-card"><div class="crm-card-title">Telegram-рассылка <span class="crm-card-sub">${botState ? esc(botState.run_status || "без цепочки") : "не подключён"}</span></div>
            ${botState ? `<div class="crm-row-meta">Шаг: ${esc(botState.current_step || "—")} · отправлено ${botState.sent} из ${botState.total}</div>
              <div style="height:8px;background:#edf1ea;border-radius:8px;overflow:hidden;margin:10px 0"><div style="height:100%;width:${botState.total ? Math.min(100, botState.sent / botState.total * 100) : 0}%;background:#2f6b47"></div></div>
              ${botState.error ? `<div class="crm-row-meta" style="color:#a24b38">${esc(botState.error)}</div>` : ""}
              <form class="crm-form" id="telegram-message-form"><textarea class="crm-textarea" id="telegram-message" placeholder="Написать этому клиенту в Telegram"></textarea><button class="crm-btn small" type="submit">Отправить сообщение</button></form>` : '<div class="crm-row-meta">У клиента пока нет связанного аккаунта тестового Telegram-бота.</div>'}
          </section>
          <section class="crm-card"><div class="crm-card-title">Источник</div>
            <div class="crm-source"><div class="crm-k">ПЕРВЫЙ ИЗВЕСТНЫЙ</div><strong>${esc((firstSource && (firstSource.source || firstSource.utm_source)) || "Не указан")}</strong>
            <div class="crm-row-meta">${esc((firstSource && firstSource.utm_campaign) || "")}</div></div>
          </section>
          <section class="crm-card"><div class="crm-card-title">Теги</div><div class="crm-tags">${user.tags.map((item) => `<span class="crm-tag">${esc(item.name)}</span>`).join("") || '<span class="crm-tag empty">тегов нет</span>'}</div>
            <form class="crm-two" id="tag-form" style="margin-top:10px"><input class="crm-input" id="tag-name" placeholder="Например: рассылка 100"><button class="crm-btn small" type="submit">Добавить</button></form>
          </section>
          <section class="crm-card"><div class="crm-card-title">Заметки</div>
            <form class="crm-form" id="note-form"><textarea class="crm-textarea" id="note-body" placeholder="Добавить комментарий о клиенте"></textarea><button class="crm-btn small" type="submit">Сохранить заметку</button></form>
            <div style="margin-top:10px">${user.notes.map((item) => `<div class="crm-row"><div>${esc(item.body)}</div><div class="crm-row-meta">${date(item.created_at, true)} · ${esc(item.author)}</div></div>`).join("") || '<div class="crm-empty">Заметок нет</div>'}</div>
          </section>
        </div>
      </div><div class="crm-foot">Карточка объединяет связанные таблицы PostgreSQL, а не копирует клиента в одну гигантскую строку</div>`;

    document.getElementById("crm-back").addEventListener("click", () => showView(state.view));
    document.getElementById("name-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      await api(`/admin/api/users/${id}`, { method: "PATCH", body: JSON.stringify({ display_name: document.getElementById("display-name").value }) });
      await openUser(id);
    });
    const emailForm = document.getElementById("email-form");
    if (emailForm) emailForm.addEventListener("submit", async (event) => { event.preventDefault(); await api(`/admin/api/users/${id}/email`, {method:"POST", body:JSON.stringify({email:document.getElementById("link-email").value})}); await openUser(id); });
    document.getElementById("review-status").value = user.access_review_status;
    document.getElementById("tilda-status").value = user.tilda_access_status;
    document.getElementById("review-form").addEventListener("submit", async (event) => { event.preventDefault(); await api(`/admin/api/users/${id}/access-review`, {method:"PATCH", body:JSON.stringify({status:document.getElementById("review-status").value,tilda_status:document.getElementById("tilda-status").value,note:document.getElementById("review-note").value})}); await openUser(id); });
    document.getElementById("grant-form").addEventListener("submit", async (event) => { event.preventDefault(); await api(`/admin/api/users/${id}/accesses`, {method:"POST", body:JSON.stringify({resource_code:document.getElementById("resource-code").value})}); await openUser(id); });
    root.querySelectorAll(".revoke-access").forEach((button)=>button.addEventListener("click", async()=>{ if (!window.confirm("Закрыть этот доступ?")) return; await api(`/admin/api/users/${id}/accesses/${button.dataset.code}`, {method:"DELETE"}); await openUser(id); }));
    document.getElementById("tag-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      const name = document.getElementById("tag-name").value.trim();
      if (!name) return;
      await api(`/admin/api/users/${id}/tags`, { method: "POST", body: JSON.stringify({ name }) });
      await openUser(id);
    });
    document.getElementById("note-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      const body = document.getElementById("note-body").value.trim();
      if (!body) return;
      await api(`/admin/api/users/${id}/notes`, { method: "POST", body: JSON.stringify({ body }) });
      await openUser(id);
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

  async function loadHome(view) {
    state.summary = await api("/admin/api/summary");
    return showView(view || state.view);
  }

  async function showView(view) {
    if (view !== state.view && (view === "users" || view === "buyers")) state.offset = 0;
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

  loadHome("users").catch(showError);
})();
