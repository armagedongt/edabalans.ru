(function () {
  "use strict";

  const root = document.getElementById("admin-content");
  const title = document.getElementById("admin-title");
  const kicker = document.getElementById("admin-kicker");
  const labels = { dqs: "DQS", strength: "Силовые", metabolism: "Метаболизм" };
  const descriptions = {
    dqs: "30-дневный дневник качества рациона",
    strength: "Тренировочные сессии, упражнения и прогресс",
    metabolism: "Два сохранённых варианта расчёта пользователя"
  };
  const dqsCategories = [
    ["Фрукты", [2,2,2,1,0,0,0,-1]], ["Овощи", [2,2,2,1,0,0,0,-1]], ["Зелень", [2,2,2,1,0,0,0,-1]],
    ["Мясо", [2,2,1,0,0,-1,-2,-2]], ["Молочка", [2,2,1,0,-1,-2,-2,-2]], ["Сыры", [2,0,-1,-2,-2,-2,-2,-2]],
    ["Орехи", [2,0,-1,-2,-2,-2,-2,-2]], ["Масло", [1,0,0,-1,-2,-2,-2,-2]], ["ЦЗ", [2,2,1,0,-1,-1,-1,-2]],
    ["Бобовые", [2,2,1,0,-1,-1,-1,-2]], ["Картофель", [2,2,1,0,-1,-1,-1,-2]], ["Др. гарниры", [0,-1,-2,-2,-2,-2,-2,-2]],
    ["Сладости", [-2,-2,-2,-2,-2,-2,-2,-2]], ["Напитки", [-2,-2,-2,-2,-2,-2,-2,-2]], ["Алкоголь", [-2,-2,-2,-2,-2,-2,-2,-2]],
    ["Жареное", [-2,-2,-2,-2,-2,-2,-2,-2]], ["Типа мясо", [-2,-2,-2,-2,-2,-2,-2,-2]]
  ];

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

  async function api(path, options = {}) {
    const response = await fetch(path, { credentials: "same-origin", ...options });
    if (response.status === 401) {
      location.replace(`/admin?next=${encodeURIComponent(location.pathname + location.search)}`);
      throw new Error("Сессия завершена");
    }
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
    root.innerHTML = `<div class="admin-section-head"><div><h2>${labels[code]}</h2><p>${descriptions[code]} · ${result.users.length} пользователей с доступом или данными</p></div></div><div class="admin-list">${result.users.map((user) => `<button class="admin-person" data-href="/admin/${code}?user=${user.user_id}"><div><h3>${esc(user.display_name || user.email || "Без имени")}</h3><p>${esc(user.email || "email не указан")} · ${user.has_state ? summaryText(code, user.summary) : "приложение ещё не открывалось"}</p></div><div class="admin-actions"><span class="admin-badge ${user.has_access ? "" : "warn"}">${user.has_access ? "доступ есть" : "только исторические данные"}</span>${user.has_state ? `<span class="admin-badge">v${user.version}</span><span class="admin-badge off">${date(user.updated_at)}</span>` : '<span class="admin-badge off">нет состояния</span>'}</div></button>`).join("") || '<div class="admin-empty">В этом приложении пока нет пользователей</div>'}</div>`;
    bindPersonButtons();
  }

  function switcher(user, modules, context) {
    const items = [
      { code: "crm", label: "CRM", exists: true, href: `/crm?user=${user.id}` },
      ...["dqs", "strength", "metabolism"].map((code) => ({ code, label: labels[code], exists: modules[code].exists || modules[code].has_access, hasState: modules[code].exists, href: `/admin/${code}?user=${user.id}` })),
      { code: "telegram", label: "Telegram", exists: modules.telegram.exists, href: `/bot?view=contacts&user=${user.id}` }
    ];
    return `<div class="admin-switcher">${items.map((item) => `<a class="admin-switch ${item.exists ? "exists" : ""} ${context === item.code ? "active" : ""}" href="${item.exists ? esc(item.href) : "#"}"><b>${esc(item.label)}</b><small>${item.hasState === false ? "доступ есть, данных нет" : item.exists ? "Открыть данные" : "недоступно"}</small></a>`).join("")}</div>`;
  }

  async function person(id, context) {
    setHeading("Карточка человека", "ЕДИНЫЙ USER_ID");
    loading();
    let user;
    let moduleResult;
    let appDetail;
    if (context) {
      [moduleResult, appDetail] = await Promise.all([
        api(`/admin/api/users/${id}/modules`),
        api(`/admin/api/apps/${context}/users/${id}`)
      ]);
      user = { ...appDetail.user, emails: [{ email: appDetail.user.email }], purchase_count: 0, accesses: [] };
    } else {
      [user, moduleResult] = await Promise.all([
        api(`/admin/api/users/${id}`),
        api(`/admin/api/users/${id}/modules`)
      ]);
    }
    const modules = moduleResult.modules;
    const email = user.emails[0] && user.emails[0].email;
    root.innerHTML = `
      <button class="admin-back" id="admin-back">← Назад к списку</button>
      <div class="admin-profile-head"><div class="admin-profile-id"><div class="admin-avatar">${esc((user.display_name || email || "?").charAt(0).toUpperCase())}</div><div><h2>${esc(user.display_name || email || "Без имени")}</h2><p>${esc(email || "email не указан")} · ${esc(user.id)}</p></div></div><div class="admin-badges">${context ? `<span class="admin-badge">${appDetail.has_access ? "доступ есть" : "нет доступа"}</span><span class="admin-badge ${appDetail.has_state ? "" : "off"}">${appDetail.has_state ? "данные есть" : "данных нет"}</span>` : `<span class="admin-badge">${user.purchase_count} покупок</span><span class="admin-badge">${user.accesses.filter((item) => !item.revoked_at).length} доступов</span>`}</div></div>
      ${switcher(user, modules, context || "users")}
      <div class="admin-detail-grid">
        <article class="admin-card"><h3>${context ? labels[context] : "Сводка по приложениям"}</h3><div id="admin-app-panel">${context ? appDetails(context, appDetail) : moduleOverview(modules)}</div></article>
        <article class="admin-card"><h3>Быстрые переходы</h3><div class="admin-links"><a class="admin-action alt" href="/crm?user=${user.id}">Карточка CRM</a>${modules.telegram.exists ? `<a class="admin-action alt" href="/bot?view=contacts&user=${user.id}">Пользователь в боте</a>` : ""}${modules.dqs.exists || modules.dqs.has_access ? `<a class="admin-action alt" href="/admin/dqs?user=${user.id}">DQS</a>` : ""}${modules.strength.exists || modules.strength.has_access ? `<a class="admin-action alt" href="/admin/strength?user=${user.id}">Силовые</a>` : ""}${modules.metabolism.exists || modules.metabolism.has_access ? `<a class="admin-action alt" href="/admin/metabolism?user=${user.id}">Метаболизм</a>` : ""}</div><div class="admin-note" style="margin-top:14px">DQS доступен только для аналитики. В силовых и метаболизме административные изменения будут выполняться тем же интерфейсом приложения и записываться в журнал.</div></article>
      </div><div class="admin-footer">Все разделы связаны одним users.id; данные не копируются между приложениями.</div>`;
    document.getElementById("admin-back").onclick = () => { location.href = context ? `/admin/${context}` : "/admin/users"; };
    const openButton = document.getElementById("admin-open-app");
    if (openButton) openButton.onclick = async () => {
      openButton.disabled = true;
      openButton.textContent = "Открываю…";
      try {
        await api(`/admin/api/apps/${context}/users/${id}/open`, { method: "POST" });
        await person(id, context);
      } catch (error) {
        failure(error);
      }
    };
    if (context === "dqs" && appDetail.has_state) bindDqsPeriods(appDetail);
    if (["strength", "metabolism"].includes(context) && appDetail.has_state) {
      const mount = document.querySelector("[data-edabalans-admin-user]");
      if (mount && window.EdabalansEmbed) window.EdabalansEmbed.load(mount);
    }
  }

  function moduleOverview(modules) {
    return `<div class="admin-rows">${["dqs", "strength", "metabolism"].map((code) => `<div class="admin-row"><span>${labels[code]}</span><b>${modules[code].exists ? summaryText(code, modules[code].summary) : modules[code].has_access ? "доступ есть, данных нет" : "нет доступа"}</b></div>`).join("")}<div class="admin-row"><span>Telegram</span><b>${modules.telegram.exists ? `@${esc(modules.telegram.username || "без username")}` : "не связан"}</b></div></div>`;
  }

  function appDetails(code, detail) {
    if (!detail.has_state) {
      return `<div class="admin-empty compact">Данных пока нет.</div>${detail.has_access ? '<button class="admin-action" id="admin-open-app" type="button">Открыть приложение</button><p class="admin-help">Начальное состояние будет создано только после этого действия.</p>' : '<div class="admin-note">У человека нет действующего доступа к приложению.</div>'}`;
    }
    const state = detail.state;
    if (code === "dqs") return dqsAnalytics(state.data, 30);
    if (["strength", "metabolism"].includes(code)) return `<div class="admin-note">Административный режим · изменения сохраняются для выбранного человека и записываются в журнал.</div><div data-edabalans-app="${code}" data-edabalans-admin-user="${esc(detail.user.id)}"><div class="admin-empty">Загружаю приложение…</div></div>`;
    const summary = state.summary;
    let rows;
    if (code === "strength") rows = [["Тренировок", summary.sessions], ["Заполненных", summary.filled_sessions], ["Последняя дата", summary.last_date || "—"], ["Скрыто упражнений", summary.hidden_exercises]];
    else rows = [["Сохранено вариантов", summary.saved_variants], ["Активный вариант", summary.active_variant], ["Версия формулы", summary.formula_version]];
    return `<div class="admin-kpis">${rows.slice(0, 3).map(([key, value]) => `<div class="admin-kpi"><small>${esc(key)}</small><b>${esc(value)}</b></div>`).join("")}</div><div class="admin-rows" style="margin-top:10px">${rows.slice(3).map(([key, value]) => `<div class="admin-row"><span>${esc(key)}</span><b>${esc(value)}</b></div>`).join("")}<div class="admin-row"><span>Обновлено</span><b>${date(state.updated_at)}</b></div><div class="admin-row"><span>Версия состояния</span><b>${state.version}</b></div></div>`;
  }

  function dqsPortionScore(index, portions) {
    const scores = dqsCategories[index][1];
    const value = Math.max(0, Number(portions || 0));
    const whole = Math.floor(value);
    let total = 0;
    for (let position = 1; position <= whole; position += 1) total += scores[Math.min(position, scores.length) - 1];
    const fraction = value - whole;
    if (fraction) total += fraction * scores[Math.min(whole + 1, scores.length) - 1];
    return total;
  }

  function dqsCategoryScore(day, index) {
    const diversity = [0, 1, 2, 3, 4, 8].includes(index) && Array.isArray(day.d) && day.d[index] === true ? 1 : 0;
    return dqsPortionScore(index, Array.isArray(day.p) ? day.p[index] : 0) + diversity;
  }

  function dqsDayScore(day) {
    return dqsCategories.reduce((total, _, index) => total + dqsCategoryScore(day, index), 0);
  }

  function dqsEntryDate(startDate, dayNumber) {
    if (!startDate) return "";
    const value = new Date(`${startDate}T00:00:00`);
    value.setDate(value.getDate() + dayNumber - 1);
    return value.toISOString().slice(0, 10);
  }

  function dqsAnalytics(data, period, customRange = {}) {
    const days = data && data.days && typeof data.days === "object" ? data.days : {};
    const entries = Object.keys(days).map((key) => ({ number: Number(key), day: days[key], date: dqsEntryDate(data.start_date, Number(key)) })).filter((entry) => entry.number >= 1 && entry.number <= 30 && entry.day && Array.isArray(entry.day.p)).sort((a, b) => a.number - b.number);
    const selected = period === "custom"
      ? entries.filter((entry) => (!customRange.from || entry.date >= customRange.from) && (!customRange.to || entry.date <= customRange.to))
      : entries.slice(-Number(period));
    const scores = selected.map((entry) => dqsDayScore(entry.day));
    const average = scores.length ? scores.reduce((sum, value) => sum + value, 0) / scores.length : null;
    const lastSeven = scores.slice(-7);
    const lastAverage = lastSeven.length ? lastSeven.reduce((sum, value) => sum + value, 0) / lastSeven.length : null;
    const categoryRows = dqsCategories.map((category, index) => {
      const portions = selected.length ? selected.reduce((sum, entry) => sum + Number(entry.day.p[index] || 0), 0) / selected.length : 0;
      const points = selected.length ? selected.reduce((sum, entry) => sum + dqsCategoryScore(entry.day, index), 0) / selected.length : 0;
      return `<div class="dqs-admin-category"><span>${esc(category[0])}</span><b>${portions.toFixed(1)} порц.</b><em>${points >= 0 ? "+" : ""}${points.toFixed(1)}</em></div>`;
    }).join("");
    const min = scores.length ? Math.min(...scores, 0) : 0;
    const max = scores.length ? Math.max(...scores, 1) : 1;
    const chart = selected.map((entry) => {
      const score = dqsDayScore(entry.day);
      const height = Math.max(8, ((score - min) / Math.max(1, max - min)) * 92);
      return `<div class="dqs-admin-bar" title="День ${entry.number}: ${score.toFixed(1)}"><i style="height:${height}px"></i><small>${entry.number}</small></div>`;
    }).join("");
    const feed = selected.slice().reverse().map((entry) => {
      const portions = dqsCategories.map((category, index) => Number(entry.day.p[index] || 0) ? `${category[0]} ${Number(entry.day.p[index])}` : "").filter(Boolean).join(" · ");
      return `<div class="dqs-admin-feed"><div><b>День ${entry.number}</b><small>${esc(entry.date || "дата не задана")}</small><p>${esc(portions || "порции не указаны")}</p></div><strong>${dqsDayScore(entry.day).toFixed(1)}</strong></div>`;
    }).join("");
    const matrixHead = dqsCategories.map((category) => `<th>${esc(category[0])}</th>`).join("");
    const matrixRows = selected.map((entry) => `<tr><th>День ${entry.number}</th>${dqsCategories.map((_, index) => `<td>${dqsCategoryScore(entry.day, index).toFixed(1)}</td>`).join("")}</tr>`).join("");
    const bounds = entries.length ? { from: entries[0].date, to: entries[entries.length - 1].date } : { from: "", to: "" };
    return `<div class="dqs-admin-periods">${[7,14,30].map((value) => `<button class="${period === value ? "active" : ""}" data-dqs-period="${value}">${value} дней</button>`).join("")}<button class="${period === "custom" ? "active" : ""}" data-dqs-period="custom">Период</button><input data-dqs-from type="date" value="${esc(customRange.from || bounds.from)}"><input data-dqs-to type="date" value="${esc(customRange.to || bounds.to)}"></div><div class="admin-kpis"><div class="admin-kpi"><small>СТАРТ</small><b>${esc(data.start_date || "—")}</b></div><div class="admin-kpi"><small>ЗАПОЛНЕНО</small><b>${entries.length} / 30</b></div><div class="admin-kpi"><small>СРЕДНИЙ DQS</small><b>${average === null ? "—" : average.toFixed(1)}</b></div></div><div class="admin-row"><span>Последние 7 заполненных дней</span><b>${lastAverage === null ? "—" : lastAverage.toFixed(1)}</b></div><h4 class="dqs-admin-title">Динамика по дням</h4><div class="dqs-admin-chart">${chart || '<div class="admin-empty">Нет заполненных дней</div>'}</div><h4 class="dqs-admin-title">Средние по категориям</h4><div class="dqs-admin-categories">${categoryRows}</div><details class="dqs-admin-matrix"><summary>Матрица баллов по дням</summary><div><table><thead><tr><th>День</th>${matrixHead}</tr></thead><tbody>${matrixRows}</tbody></table></div></details><h4 class="dqs-admin-title">Лента заполнений</h4><div>${feed || '<div class="admin-empty">Нет данных</div>'}</div>`;
  }

  function bindDqsPeriods(detail) {
    document.querySelectorAll("[data-dqs-period]").forEach((button) => button.addEventListener("click", () => {
      const value = button.dataset.dqsPeriod;
      const range = { from: document.querySelector("[data-dqs-from]").value, to: document.querySelector("[data-dqs-to]").value };
      document.getElementById("admin-app-panel").innerHTML = dqsAnalytics(detail.state.data, value === "custom" ? "custom" : Number(value), range);
      bindDqsPeriods(detail);
    }));
    document.querySelectorAll("[data-dqs-from],[data-dqs-to]").forEach((input) => input.addEventListener("change", () => {
      const range = { from: document.querySelector("[data-dqs-from]").value, to: document.querySelector("[data-dqs-to]").value };
      document.getElementById("admin-app-panel").innerHTML = dqsAnalytics(detail.state.data, "custom", range);
      bindDqsPeriods(detail);
    }));
  }

  async function contentCatalog() {
    const params = new URLSearchParams(location.search);
    const selected = params.get("item");
    setHeading("Каталог статей", "АВТОРСКИЕ МАТЕРИАЛЫ");
    loading();
    if (selected) {
      const item = await api(`/admin/api/content/items/${encodeURIComponent(selected)}`);
      root.innerHTML = `
        <button class="admin-back" id="admin-back">← Назад к каталогу</button>
        <div class="admin-profile-head"><div class="admin-profile-id"><div><h2>${esc(item.title)}</h2><p>${esc(item.source)} · ${date(item.published_at)} · ID ${esc(item.external_id)}</p></div></div><div class="admin-actions"><a class="admin-action alt" href="${esc(item.canonical_url)}" target="_blank" rel="noopener">Оригинал ↗</a></div></div>
        <div class="admin-detail-grid">
          <article class="admin-card"><h3>Текст</h3><div style="white-space:pre-wrap;line-height:1.55">${esc(item.text || "Текст ещё не импортирован")}</div></article>
          <article class="admin-card"><h3>Разметка</h3><div class="admin-rows"><div class="admin-row"><span>CTA</span><b>${item.cta_url ? `<a href="${esc(item.cta_url)}" target="_blank" rel="noopener">${esc(item.cta_text || item.cta_url)} ↗</a>` : "нет"}</b></div><div class="admin-row"><span>Рекомендации</span><b>${esc(item.recommendations_status)}</b></div><div class="admin-row"><span>Медиа</span><b>${item.media.length} URL</b></div><div class="admin-row"><span>Ссылки</span><b>${item.links.length}</b></div></div><h3 style="margin-top:18px">Концовка</h3><div style="white-space:pre-wrap;line-height:1.5">${esc(item.ending_text || "не выделена")}</div></article>
        </div>`;
      document.getElementById("admin-back").onclick = () => { location.href = "/admin/content"; };
      return;
    }
    const q = params.get("q") || "";
    const [summary, rows] = await Promise.all([
      api("/admin/api/content/summary"),
      api(`/admin/api/content/items?source=pikabu&limit=250&q=${encodeURIComponent(q)}`)
    ]);
    root.innerHTML = `
      <div class="admin-grid"><article class="admin-stat"><small>МАТЕРИАЛОВ</small><b>${summary.items}</b><span>в общей базе</span></article><article class="admin-stat"><small>ИСТОЧНИКОВ</small><b>${summary.sources}</b><span>Pikabu, затем Telegram</span></article></div>
      <div class="admin-toolbar"><input class="admin-filter" id="content-filter" value="${esc(q)}" placeholder="Заголовок или ID поста"><button class="admin-action" id="content-search">Найти</button></div>
      <div class="admin-list">${rows.map((item) => `<button class="admin-person" data-content-id="${esc(item.id)}"><div><h3>${esc(item.title)}</h3><p>${date(item.published_at)} · ${esc(item.source)} · ${esc(item.external_id)}</p></div><div class="admin-actions"><span class="admin-badge">${item.views == null ? "нет просмотров" : new Intl.NumberFormat("ru-RU").format(item.views)}</span><span class="admin-badge ${item.cta_url ? "" : "off"}">${item.cta_url ? "есть CTA" : "без CTA"}</span></div></button>`).join("") || '<div class="admin-empty">Материалы ещё не импортированы</div>'}</div>`;
    root.querySelectorAll("[data-content-id]").forEach((button) => button.addEventListener("click", () => { location.href = `/admin/content?item=${encodeURIComponent(button.dataset.contentId)}`; }));
    const search = () => { const value = document.getElementById("content-filter").value.trim(); location.href = `/admin/content${value ? `?q=${encodeURIComponent(value)}` : ""}`; };
    document.getElementById("content-search").onclick = search;
    document.getElementById("content-filter").addEventListener("keydown", (event) => { if (event.key === "Enter") search(); });
  }

  async function run() {
    const active = section();
    selectNavigation(active);
    if (["dqs", "strength", "metabolism"].includes(active)) return application(active);
    if (active === "users") return users();
    if (active === "content") return contentCatalog();
    return dashboard();
  }

  document.getElementById("admin-global-search").addEventListener("submit", (event) => {
    event.preventDefault();
    const q = new FormData(event.currentTarget).get("q").trim();
    location.href = `/admin/users${q ? `?q=${encodeURIComponent(q)}` : ""}`;
  });
  document.getElementById("admin-logout").addEventListener("click", async () => {
    await fetch("/admin/api/logout", { method: "POST", credentials: "same-origin" });
    location.replace("/admin");
  });
  window.addEventListener("popstate", () => run().catch(failure));
  run().catch(failure);
}());
