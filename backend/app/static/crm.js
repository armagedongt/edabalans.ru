(function () {
  "use strict";

  const root = document.getElementById("crm-app");
  const state = { view: "users", query: "", summary: null, users: [], payments: [] };

  function esc(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function money(value) {
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
        <div class="crm-stat"><div class="crm-k">ОПЛАЧЕННЫХ ОПЕРАЦИЙ</div><div class="crm-v">${data.paid_payments || 0}</div><div class="crm-s">история не перезаписывается</div></div>
        <div class="crm-stat"><div class="crm-k">ВЫРУЧКА</div><div class="crm-v">${money(data.revenue_rub)}</div><div class="crm-s">подтверждённые RUB</div></div>
      </div>`;
  }

  function accessTags(accesses) {
    if (!accesses || !accesses.length) return '<span class="crm-tag empty">доступов нет</span>';
    return accesses.map((code) => `<span class="crm-tag">${esc(code.replace("ACCESS_", ""))}</span>`).join("");
  }

  function userCard(user) {
    const buyer = user.purchase_count > 0;
    return `
      <article class="crm-client">
        <button class="crm-client-button" data-user-id="${esc(user.id)}">
          <div class="crm-client-top">
            <div><div class="crm-name">${esc(user.display_name || user.email || user.telegram || "Без имени")}</div>
            <div class="crm-email">${esc(user.email || "email не указан")}${user.telegram ? ` · @${esc(user.telegram)}` : ""}</div></div>
            <span class="crm-status ${buyer ? "st-buyer" : "st-lead"}">${buyer ? "Покупатель" : "Лид"}</span>
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
    const params = new URLSearchParams({ q: state.query, buyers_only: String(buyersOnly), limit: "250" });
    state.users = await api(`/admin/api/users?${params}`);
    root.innerHTML = top(buyersOnly ? "buyers" : "users") + `
      <div class="crm-toolbar">
        <input class="crm-search" id="crm-search" placeholder="Поиск по имени, email или Telegram" value="${esc(state.query)}">
        <button class="crm-btn alt" id="crm-refresh">Обновить</button>
      </div>
      ${stats()}
      <div class="crm-list">${state.users.map(userCard).join("") || '<div class="crm-card crm-empty">Ничего не найдено</div>'}</div>
      <div class="crm-foot">PostgreSQL — источник истины · Google Sheets не используется этой админкой</div>`;
    bindTop();
    bindUserCards();
    const search = document.getElementById("crm-search");
    let timer;
    search.addEventListener("input", () => {
      clearTimeout(timer);
      state.query = search.value;
      timer = setTimeout(() => renderUsers(buyersOnly).catch(showError), 300);
    });
    document.getElementById("crm-refresh").addEventListener("click", () => loadHome(buyersOnly ? "buyers" : "users"));
  }

  async function renderPayments() {
    root.innerHTML = top("payments") + '<div class="crm-loading">Загружаю оплаты…</div>';
    bindTop();
    state.payments = await api("/admin/api/payments?limit=500");
    const rows = state.payments.map((payment) => `
      <tr ${payment.user_id ? `data-user-id="${esc(payment.user_id)}"` : ""}>
        <td>${date(payment.paid_at || payment.source_event_at, true)}</td>
        <td><strong>${esc(payment.display_name || "Без имени")}</strong><div class="crm-email">${esc(payment.email || "")}</div></td>
        <td>${esc(payment.product_name_raw)}</td>
        <td><span class="crm-status ${payment.status === "paid" ? "st-paid" : "st-processing"}">${esc(payment.status)}</span></td>
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

  function paymentRow(item) {
    return `<div class="crm-row"><div class="crm-row-main"><span>${esc(item.product_name_raw)}</span><strong>${money(item.amount)}</strong></div>
      <div class="crm-row-meta">${date(item.paid_at || item.source_event_at, true)} · ${esc(item.status)}${item.product_code ? ` · ${esc(item.product_code)}` : ""}</div></div>`;
  }

  async function openUser(id) {
    root.innerHTML = top("") + '<div class="crm-loading">Открываю карточку…</div>';
    const user = await api(`/admin/api/users/${id}`);
    const primaryEmail = user.emails[0] && user.emails[0].email;
    const telegram = user.messengers.find((item) => item.platform === "telegram");
    const firstSource = user.attribution.find((item) => item.source || item.utm_source || item.utm_campaign);
    root.innerHTML = `
      <div class="crm-profile-head">
        <div class="crm-profile-id">
          <button class="crm-back" id="crm-back">← Назад</button>
          <div class="crm-avatar">${esc((user.display_name || primaryEmail || "?").charAt(0).toUpperCase())}</div>
          <div><div class="crm-name">${esc(user.display_name || primaryEmail || "Без имени")}</div>
          <div class="crm-email">${esc(primaryEmail || "email не указан")}${telegram && telegram.username ? ` · @${esc(telegram.username)}` : ""}</div></div>
        </div>
        <span class="crm-status ${user.purchase_count ? "st-buyer" : "st-lead"}">${user.purchase_count ? "Покупатель" : "Лид"}</span>
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
            ${user.emails.map((item) => `<div class="crm-row"><div class="crm-row-main"><span>${esc(item.email)}</span><span>${item.primary ? "основной" : ""}</span></div></div>`).join("")}
            ${user.messengers.map((item) => `<div class="crm-row"><div class="crm-row-main"><span>${esc(item.platform)}</span><strong>${esc(item.username ? `@${item.username}` : item.platform_user_id || "без ID")}</strong></div></div>`).join("")}
          </section>
          <section class="crm-card"><div class="crm-card-title">История покупок</div>${user.payments.map(paymentRow).join("") || '<div class="crm-empty">Покупок пока нет</div>'}</section>
          <section class="crm-card"><div class="crm-card-title">Доступы</div><div class="crm-tags">${accessTags(user.accesses.filter((item) => !item.revoked_at).map((item) => item.code))}</div></section>
        </div>
        <div>
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
  }

  async function loadHome(view) {
    state.summary = await api("/admin/api/summary");
    return showView(view || state.view);
  }

  async function showView(view) {
    state.view = view;
    if (view === "payments") return renderPayments();
    return renderUsers(view === "buyers");
  }

  function showError(error) {
    root.innerHTML = `<div class="crm-error"><strong>CRM не загрузилась</strong><div style="margin-top:8px">${esc(error.message)}</div><button class="crm-btn" style="margin-top:14px" id="retry">Повторить</button></div>`;
    const retry = document.getElementById("retry");
    if (retry) retry.addEventListener("click", () => loadHome().catch(showError));
  }

  loadHome("users").catch(showError);
})();
