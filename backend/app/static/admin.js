(function () {
  "use strict";

  const root = document.getElementById("admin-content");
  const title = document.getElementById("admin-title");
  const kicker = document.getElementById("admin-kicker");
  const labels = { dqs: "Diet Quality Score", strength: "Силовые тренировки", metabolism: "Калькулятор метаболизма" };
  const descriptions = {
    dqs: "30-дневный дневник качества рациона",
    strength: "Тренировочные сессии, упражнения и прогресс",
    metabolism: "Два сохранённых варианта расчёта пользователя"
  };

  function esc(value) {
    return String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
  }

  function date(value) {
    if (!value) return "—";
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? esc(value) : parsed.toLocaleString("ru-RU", { dateStyle: "short", timeStyle: "short" });
  }

  function money(value) {
    return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(value || 0) + " ₽";
  }

  async function api(path) {
    const response = await fetch(path, { credentials: "same-origin" });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || `Ошибка сервера ${response.status}`);
    }
    return response.json();
  }

  function section() {
    return location.pathname.split("/").filter(Boolean)[1] || "home";
  }

  function selectNavigation(active) {
    document.querySelectorAll("[data-section]").forEach((link) => link.classList.toggle("active", link.dataset.section === active));
  }

  function setHeading(name, sub) {
    title.textContent = name;
    kicker.textContent = sub || "EDABALANS";
  }

  function loading() { root.innerHTML = '<div class="admin-empty">Загружаю…</div>'; }
  function failure(error) { root.innerHTML = `<div class="admin-error"><strong>Раздел не загрузился</strong><div>${esc(error.message)}</div></div>`; }

  function summaryText(code, summary) {
    if (code === "dqs") return `${summary.filled_days || 0} из 30 дней${summary.start_date ? ` · старт ${esc(summary.start_date)}` : ""}`;
    if (code === "strength") return `${summary.sessions || 0} тренировок · заполнено ${summary.filled_sessions || 0}`;
    return `${summary.saved_variants || 0} сохранённых варианта · активный №${summary.active_variant || 1}`;
  }

  async function dashboard() {
    setHeading("Главное", "ЕДИНАЯ АДМИНКА");
    loading();
    const [summary, dqs, strength, metabolism] = await Promise.all([
      api("/admin/api/summary"),
      api("/admin/api/apps/users?app_code=dqs"),
      api("/admin/api/apps/users?app_code=strength"),
      api("/admin/api/apps/users?app_code=metabolism")
    ]);
    root.innerHTML = `
      <div class="admin-grid">
        <article class="admin-stat"><small>ЛЮДЕЙ В CRM</small><b>${summary.users}</b><span>единый user_id</span></article>
        <article class="admin-stat"><small>ПОКУПАТЕЛЕЙ</small><b>${summary.buyers}</b><span>подтверждённые покупки</span></article>
        <article class="admin-stat"><small>ОПЛАТ В ИСТОРИИ</small><b>${summary.paid_payments}</b><span>${money(summary.revenue_rub)}</span></article>
        <article class="admin-stat"><small>ПРОВЕРИТЬ ДОСТУПЫ</small><b>${summary.access_reviews}</b><span>очередь CRM</span></article>
      </div>
      <div class="admin-section-head"><div><h2>Приложения</h2><p>Каждый модуль использует ту же карточку человека.</p></div></div>
      <div class="admin-module-grid">
        ${appCard("dqs", dqs.users.length)}${appCard("strength", strength.users.length)}${appCard("metabolism", metabolism.users.length)}
      </div>
      <div class="admin-section-head"><div><h2>Рабочие разделы</h2><p>Один вход и переходы между связанными данными.</p></div></div>
      <div class="admin-module-grid">
        <article class="admin-module"><h3>CRM</h3><p>Люди, покупки, доступы, теги и заметки.</p><footer><span class="admin-badge">работает</span><a class="admin-action alt" href="/crm">Открыть</a></footer></article>
        <article class="admin-module"><h3>Telegram-бот</h3><p>Цепочки, сообщения, контакты, рассылки и ссылки.</p><footer><span class="admin-badge">работает</span><a class="admin-action alt" href="/bot">Открыть</a></footer></article>
        <article class="admin-module"><h3>База данных</h3><p>Технический просмотр PostgreSQL через NocoDB.</p><footer><span class="admin-badge warn">технический раздел</span><a class="admin-action alt" href="https://data.edabalans.ru" target="_blank" rel="noopener">Открыть ↗</a></footer></article>
      </div>`;
  }

  function appCard(code, count) {
    return `<article class="admin-module"><h3>${labels[code]}</h3><p>${descriptions[code]}</p><footer><span class="admin-badge">${count} пользователей</span><a class="admin-action alt" href="/admin/${code}">Открыть</a></footer></article>`;
  }

  function personButton(user, href) {
    return `<button class="admin-person" data-href="${esc(href)}"><div><h3>${esc(user.display_name || user.email || user.telegram || "Без имени")}</h3><p>${esc(user.email || "email не указан")}${user.telegram ? ` · @${esc(user.telegram)}` : ""}</p></div><div class="admin-actions"><span class="admin-badge ${user.purchase_count ? "" : "off"}">${user.purchase_count || 0} покупок</span><span class="admin-badge">Открыть →</span></div></button>`;
  }

  function bindPersonButtons() {
    root.querySelectorAll("[data-href]").forEach((button) => button.addEventListener("click", () => { location.href = button.dataset.href; }));
  }

  async function users() {
    const params = new URLSearchParams(location.search);
    const selected = params.get("user");
    if (selected) return person(selected, null);
    setHeading("Люди", "ЕДИНАЯ КАРТОЧКА");
    loading();
    const q = params.get("q") || "";
    const rows = await api(`/admin/api/users?limit=250&q=${encodeURIComponent(q)}`);
    root.innerHTML = `<div class="admin-toolbar"><input class="admin-filter" id="people-filter" value="${esc(q)}" placeholder="Имя, email или Telegram"><button class="admin-action" id="people-search">Найти</button></div><div class="admin-list">${rows.map((user) => personButton(user, `/admin/users?user=${user.id}`)).join("") || '<div class="admin-empty">Люди не найдены</div>'}</div>`;
    bindPersonButtons();
    const search = () => { const value = document.getElementById("people-filter").value.trim(); location.href = `/admin/users${value ? `?q=${encodeURIComponent(value)}` : ""}`; };
    document.getElementById("people-search").onclick = search;
    document.getElementById("people-filter").addEventListener("keydown", (event) => { if (event.key === "Enter") search(); });
  }

  async function application(code) {
    const selected = new URLSearchParams(location.search).get("user");
    if (selected) return person(selected, code);
    setHeading(labels[code], "ПРИЛОЖЕНИЕ");
    loading();
    const result = await api(`/admin/api/apps/users?app_code=${code}`);
    root.innerHTML = `<div class="admin-section-head"><div><h2>${labels[code]}</h2><p>${descriptions[code]} · ${result.users.length} пользователей</p></div></div><div class="admin-list">${result.users.map((user) => `<button class="admin-person" data-href="/admin/${code}?user=${user.user_id}"><div><h3>${esc(user.display_name || user.email || "Без имени")}</h3><p>${esc(user.email || "email не указан")} · ${summaryText(code, user.summary)}</p></div><div class="admin-actions"><span class="admin-badge">v${user.version}</span><span class="admin-badge off">${date(user.updated_at)}</span></div></button>`).join("") || '<div class="admin-empty">В этом приложении пока нет пользователей</div>'}</div>`;
    bindPersonButtons();
  }

  function switcher(user, modules, context) {
    const items = [
      { code: "crm", label: "CRM", exists: true, href: `/crm?user=${user.id}` },
      ...["dqs", "strength", "metabolism"].map((code) => ({ code, label: labels[code], exists: modules[code].exists, href: `/admin/${code}?user=${user.id}` })),
      { code: "telegram", label: "Telegram", exists: modules.telegram.exists, href: `/bot?view=contacts&user=${user.id}` }
    ];
    return `<div class="admin-switcher">${items.map((item) => `<a class="admin-switch ${item.exists ? "exists" : ""} ${context === item.code ? "active" : ""}" href="${item.exists ? esc(item.href) : "#"}"><b>${esc(item.label)}</b><small>${item.exists ? "Открыть данные" : "данных нет"}</small></a>`).join("")}</div>`;
  }

  async function person(id, context) {
    setHeading("Карточка человека", "ЕДИНЫЙ USER_ID");
    loading();
    const requests = [api(`/admin/api/users/${id}`), api(`/admin/api/users/${id}/modules`)];
    if (context) requests.push(api(`/admin/api/apps/${context}/users/${id}`));
    const [user, moduleResult, appDetail] = await Promise.all(requests);
    const modules = moduleResult.modules;
    const email = user.emails[0] && user.emails[0].email;
    root.innerHTML = `
      <button class="admin-back" id="admin-back">← Назад к списку</button>
      <div class="admin-profile-head"><div class="admin-profile-id"><div class="admin-avatar">${esc((user.display_name || email || "?").charAt(0).toUpperCase())}</div><div><h2>${esc(user.display_name || email || "Без имени")}</h2><p>${esc(email || "email не указан")} · ${esc(user.id)}</p></div></div><div class="admin-badges"><span class="admin-badge">${user.purchase_count} покупок</span><span class="admin-badge">${user.accesses.filter((item) => !item.revoked_at).length} доступов</span></div></div>
      ${switcher(user, modules, context || "users")}
      <div class="admin-detail-grid">
        <article class="admin-card"><h3>${context ? labels[context] : "Сводка по приложениям"}</h3>${context ? appDetails(context, appDetail.state) : moduleOverview(modules)}</article>
        <article class="admin-card"><h3>Быстрые переходы</h3><div class="admin-links"><a class="admin-action alt" href="/crm?user=${user.id}">Карточка CRM</a>${modules.telegram.exists ? `<a class="admin-action alt" href="/bot?view=contacts&user=${user.id}">Пользователь в боте</a>` : ""}${modules.dqs.exists ? `<a class="admin-action alt" href="/admin/dqs?user=${user.id}">DQS</a>` : ""}${modules.strength.exists ? `<a class="admin-action alt" href="/admin/strength?user=${user.id}">Силовые</a>` : ""}${modules.metabolism.exists ? `<a class="admin-action alt" href="/admin/metabolism?user=${user.id}">Метаболизм</a>` : ""}</div><div class="admin-note" style="margin-top:14px">Сейчас административный просмотр показывает состояние и связи. Редактирование пользовательских данных будет добавляться отдельными действиями с записью в журнал аудита.</div></article>
      </div><div class="admin-footer">Все разделы связаны одним users.id; данные не копируются между приложениями.</div>`;
    document.getElementById("admin-back").onclick = () => { location.href = context ? `/admin/${context}` : "/admin/users"; };
  }

  function moduleOverview(modules) {
    return `<div class="admin-rows">${["dqs", "strength", "metabolism"].map((code) => `<div class="admin-row"><span>${labels[code]}</span><b>${modules[code].exists ? summaryText(code, modules[code].summary) : "данных нет"}</b></div>`).join("")}<div class="admin-row"><span>Telegram</span><b>${modules.telegram.exists ? `@${esc(modules.telegram.username || "без username")}` : "не связан"}</b></div></div>`;
  }

  function appDetails(code, state) {
    const summary = state.summary;
    let rows;
    if (code === "dqs") rows = [["Дата старта", summary.start_date || "—"], ["Заполнено дней", `${summary.filled_days} из 30`]];
    else if (code === "strength") rows = [["Тренировок", summary.sessions], ["Заполненных", summary.filled_sessions], ["Последняя дата", summary.last_date || "—"], ["Скрыто упражнений", summary.hidden_exercises]];
    else rows = [["Сохранено вариантов", summary.saved_variants], ["Активный вариант", summary.active_variant], ["Версия формулы", summary.formula_version]];
    return `<div class="admin-kpis">${rows.slice(0, 3).map(([key, value]) => `<div class="admin-kpi"><small>${esc(key)}</small><b>${esc(value)}</b></div>`).join("")}</div><div class="admin-rows" style="margin-top:10px">${rows.slice(3).map(([key, value]) => `<div class="admin-row"><span>${esc(key)}</span><b>${esc(value)}</b></div>`).join("")}<div class="admin-row"><span>Обновлено</span><b>${date(state.updated_at)}</b></div><div class="admin-row"><span>Версия состояния</span><b>${state.version}</b></div></div>`;
  }

  async function run() {
    const active = section();
    selectNavigation(active);
    if (["dqs", "strength", "metabolism"].includes(active)) return application(active);
    if (active === "users") return users();
    return dashboard();
  }

  document.getElementById("admin-global-search").addEventListener("submit", (event) => {
    event.preventDefault();
    const q = new FormData(event.currentTarget).get("q").trim();
    location.href = `/admin/users${q ? `?q=${encodeURIComponent(q)}` : ""}`;
  });
  window.addEventListener("popstate", () => run().catch(failure));
  run().catch(failure);
}());
