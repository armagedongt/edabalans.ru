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
  const pageParams = new URLSearchParams(location.search);
  const strengthMobileMode = location.pathname === "/admin/strength" && pageParams.get("mobile") === "1";
  if (strengthMobileMode) document.body.classList.add("strength-mobile-admin");
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
    const summary = await api("/admin/api/summary");
    root.innerHTML = `
      <div class="admin-home-head">
        <div><small>ЕДИНАЯ АДМИНКА</small><h1>Главное</h1></div>
        <div class="admin-home-actions"><form id="admin-home-search"><input name="q" placeholder="Найти человека по имени, email или Telegram"><button>Найти</button></form></div>
      </div>
      <div class="admin-grid">
        <article class="admin-stat"><small>ЛЮДЕЙ В CRM</small><b>${summary.users}</b><span>единый user_id</span></article>
        <article class="admin-stat"><small>ПОКУПАТЕЛЕЙ</small><b>${summary.buyers}</b><span>подтверждённые покупки</span></article>
        <article class="admin-stat"><small>ОПЛАТ В ИСТОРИИ</small><b>${summary.paid_payments}</b><span>${money(summary.revenue_rub)}</span></article>
        <article class="admin-stat"><small>ПРОВЕРИТЬ ДОСТУПЫ</small><b>${summary.access_reviews}</b><span>очередь CRM</span></article>
      </div>
      <div class="admin-home-note">Все рабочие разделы находятся в меню слева. На телефоне оно открывается кнопкой ☰.</div>`;
    document.getElementById("admin-home-search").addEventListener("submit", (event) => {
      event.preventDefault();
      const q = new FormData(event.currentTarget).get("q").trim();
      location.href = `/admin/users${q ? `?q=${encodeURIComponent(q)}` : ""}`;
    });
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

  function strengthMobileUrl(userId) {
    const params = new URLSearchParams({ mobile: "1" });
    if (userId) params.set("user", userId);
    return `/admin/strength?${params}`;
  }

  function strengthMobileRows(users, query = "") {
    const needle = query.trim().toLocaleLowerCase("ru-RU");
    const filtered = users.filter((user) => {
      if (!needle) return true;
      return `${user.display_name || ""} ${user.email || ""}`.toLocaleLowerCase("ru-RU").includes(needle);
    });
    return filtered.map((user) => `
      <button class="strength-mobile-person" type="button" data-user-id="${esc(user.user_id)}">
        <strong>${esc(user.display_name || user.email || "Без имени")}</strong>
        <span>${esc(user.email || "email не указан")}</span>
        <small>${summaryText("strength", user.summary || {})}</small>
      </button>`).join("") || '<div class="strength-mobile-empty">Клиенты не найдены</div>';
  }

  async function openStrengthMobilePicker({ required = false } = {}) {
    let overlay = document.getElementById("strength-mobile-picker");
    if (!overlay) {
      overlay = document.createElement("div");
      overlay.id = "strength-mobile-picker";
      overlay.className = "strength-mobile-picker";
      overlay.innerHTML = `
        <section class="strength-mobile-picker-card" role="dialog" aria-modal="true" aria-labelledby="strength-mobile-picker-title">
          <header><div><small>АДМИНКА ТРЕНИРОВОК</small><h2 id="strength-mobile-picker-title">Выберите клиента</h2></div>${required ? "" : '<button type="button" class="strength-mobile-picker-close" aria-label="Закрыть">×</button>'}</header>
          <label class="strength-mobile-search"><span>Поиск по имени или email</span><input type="search" autocomplete="off" placeholder="Например, anna@mail.ru"></label>
          <div class="strength-mobile-picker-list"><div class="strength-mobile-empty">Загружаю клиентов…</div></div>
        </section>`;
      document.body.appendChild(overlay);
    }
    document.body.classList.add("strength-mobile-picker-open");
    const close = () => {
      if (required) return;
      overlay.remove();
      document.body.classList.remove("strength-mobile-picker-open");
    };
    overlay.addEventListener("click", (event) => { if (event.target === overlay) close(); });
    const closeButton = overlay.querySelector(".strength-mobile-picker-close");
    if (closeButton) closeButton.addEventListener("click", close);
    const list = overlay.querySelector(".strength-mobile-picker-list");
    const input = overlay.querySelector("input");
    try {
      const result = await api("/admin/api/apps/users?app_code=strength&with_records=true");
      const users = result.users || [];
      const draw = () => {
        list.innerHTML = strengthMobileRows(users, input.value);
        list.querySelectorAll("[data-user-id]").forEach((button) => button.addEventListener("click", () => {
          location.href = strengthMobileUrl(button.dataset.userId);
        }));
      };
      input.addEventListener("input", draw);
      draw();
      input.focus({ preventScroll: true });
    } catch (error) {
      list.innerHTML = `<div class="strength-mobile-empty error">${esc(error.message)}</div>`;
    }
  }

  function renderStrengthMobilePerson(user, appDetail) {
    const email = user.email || "email не указан";
    root.innerHTML = `
      <div class="strength-mobile-current">
        <button type="button" id="strength-mobile-current-user" aria-haspopup="dialog">
          <small>АДМИНКА ТРЕНИРОВОК · СМЕНИТЬ ПОЛЬЗОВАТЕЛЯ</small>
          <strong>${esc(user.display_name || email || "Без имени")}</strong>
          <span>${esc(email)}</span>
        </button>
      </div>
      ${appDetail.has_state
        ? `<div class="strength-mobile-app" data-edabalans-app="strength" data-edabalans-admin-user="${esc(user.id)}" data-edabalans-account-url="${esc(strengthMobileUrl(user.id))}"><div class="admin-empty">Загружаю тренировки…</div></div>`
        : '<div class="strength-mobile-empty standalone">У этого клиента пока нет записей в тренировках.</div>'}`;
    document.getElementById("strength-mobile-current-user").addEventListener("click", () => openStrengthMobilePicker());
    const mount = document.querySelector("[data-edabalans-admin-user]");
    if (mount && window.EdabalansEmbed) window.EdabalansEmbed.load(mount);
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

  function applicationUserHref(code, userId) {
    const params = new URLSearchParams({ user: userId });
    if (code === "strength" && strengthMobileMode) params.set("mobile", "1");
    return `/admin/${code}?${params}`;
  }

  function applicationUserStatus(code, user) {
    if (user.has_state) return summaryText(code, user.summary || {});
    if (user.has_access) return "доступ есть, приложение ещё не открывалось";
    return "нет доступа и данных";
  }

  function applicationUserRows(code, users, compact = false) {
    return users.map((user) => `
      <button class="admin-app-person ${user.has_state ? "started" : ""}" type="button" data-user-id="${esc(user.user_id)}">
        <span class="admin-app-person-copy"><strong>${esc(user.display_name || user.email || "Без имени")}</strong><small>${esc(user.email || "email не указан")}</small></span>
        <span class="admin-app-person-state">${esc(applicationUserStatus(code, user))}</span>
        ${compact ? "" : `<span class="admin-app-person-open">Открыть →</span>`}
      </button>`).join("") || '<div class="admin-empty compact">Ничего не найдено</div>';
  }

  function bindApplicationUserRows(container, code) {
    container.querySelectorAll("[data-user-id]").forEach((button) => button.addEventListener("click", () => {
      location.href = applicationUserHref(code, button.dataset.userId);
    }));
  }

  async function openApplicationUserPicker(code) {
    document.getElementById("admin-app-picker")?.remove();
    const overlay = document.createElement("div");
    overlay.id = "admin-app-picker";
    overlay.className = "admin-app-picker";
    overlay.innerHTML = `
      <section class="admin-app-picker-card" role="dialog" aria-modal="true" aria-labelledby="admin-app-picker-title">
        <header><div><small>${esc(labels[code])}</small><h2 id="admin-app-picker-title">Сменить профиль</h2></div><button type="button" class="admin-app-picker-close" aria-label="Закрыть">×</button></header>
        <label class="admin-app-picker-search"><span>Имя или email</span><input type="search" autocomplete="off" placeholder="Начните вводить имя или email"></label>
        <p class="admin-app-picker-hint">Сначала показаны люди с данными, затем с доступом. Остальных можно найти поиском.</p>
        <div class="admin-app-picker-list"><div class="admin-empty compact">Загружаю…</div></div>
      </section>`;
    document.body.appendChild(overlay);
    document.body.classList.add("admin-app-picker-open");
    const input = overlay.querySelector("input");
    const list = overlay.querySelector(".admin-app-picker-list");
    let requestNumber = 0;
    let timer = null;
    const close = () => {
      overlay.remove();
      document.body.classList.remove("admin-app-picker-open");
    };
    const draw = async () => {
      const currentRequest = ++requestNumber;
      const q = input.value.trim();
      list.innerHTML = '<div class="admin-empty compact">Загружаю…</div>';
      try {
        const result = await api(`/admin/api/apps/users?app_code=${code}${q ? `&q=${encodeURIComponent(q)}` : ""}`);
        if (currentRequest !== requestNumber) return;
        list.innerHTML = applicationUserRows(code, result.users || [], true);
        bindApplicationUserRows(list, code);
      } catch (error) {
        if (currentRequest === requestNumber) list.innerHTML = `<div class="admin-error">${esc(error.message)}</div>`;
      }
    };
    overlay.addEventListener("click", (event) => { if (event.target === overlay) close(); });
    overlay.querySelector(".admin-app-picker-close").addEventListener("click", close);
    input.addEventListener("input", () => {
      clearTimeout(timer);
      timer = setTimeout(draw, 220);
    });
    await draw();
    input.focus({ preventScroll: true });
  }

  function managedApplicationToolbar(code, detail) {
    const user = detail.user;
    const email = user.email || "email не указан";
    return `
      <section class="admin-managed-toolbar" aria-label="Административный режим">
        <button class="admin-managed-person" id="admin-managed-person" type="button" aria-haspopup="dialog">
          <span><small>АДМИНИСТРАТИВНЫЙ РЕЖИМ · СМЕНИТЬ ПРОФИЛЬ</small><strong>${esc(user.display_name || email || "Без имени")}</strong></span>
          <em>${esc(email)}</em>
        </button>
        <label class="admin-managed-app-select"><span>Сменить приложение</span><select id="admin-managed-app">${["dqs", "strength", "metabolism"].map((item) => `<option value="${item}" ${item === code ? "selected" : ""}>${esc(labels[item])}</option>`).join("")}</select></label>
      </section>`;
  }

  async function managedApplicationPerson(id, code) {
    setHeading(labels[code], "АДМИНИСТРАТИВНЫЙ РЕЖИМ");
    loading();
    const detail = await api(`/admin/api/apps/${code}/users/${id}`);
    const stage = detail.has_state
      ? `<div class="admin-managed-app" data-edabalans-app="${code}" data-edabalans-admin-user="${esc(detail.user.id)}" data-edabalans-account-url="${esc(applicationUserHref(code, detail.user.id))}"><div class="admin-empty">Загружаю приложение…</div></div>`
      : `<section class="admin-managed-empty"><strong>${esc(labels[code])} ещё не открывался</strong><p>${detail.has_access ? "Доступ у человека есть. Начальное состояние появится только после явного открытия." : "У человека нет действующего доступа к этому приложению."}</p>${detail.has_access ? '<button class="admin-action" id="admin-open-app" type="button">Открыть приложение</button>' : ""}</section>`;
    root.innerHTML = `${managedApplicationToolbar(code, detail)}${stage}`;
    document.getElementById("admin-managed-person").addEventListener("click", () => openApplicationUserPicker(code));
    document.getElementById("admin-managed-app").addEventListener("change", (event) => {
      location.href = applicationUserHref(event.target.value, detail.user.id);
    });
    const openButton = document.getElementById("admin-open-app");
    if (openButton) openButton.addEventListener("click", async () => {
      openButton.disabled = true;
      openButton.textContent = "Открываю…";
      try {
        await api(`/admin/api/apps/${code}/users/${id}/open`, { method: "POST" });
        await managedApplicationPerson(id, code);
      } catch (error) {
        openButton.disabled = false;
        openButton.textContent = "Открыть приложение";
        failure(error);
      }
    });
    const mount = document.querySelector("[data-edabalans-admin-user]");
    if (mount && window.EdabalansEmbed) window.EdabalansEmbed.load(mount);
  }

  async function application(code) {
    const selected = new URLSearchParams(location.search).get("user");
    if (selected) return managedApplicationPerson(selected, code);
    setHeading(labels[code], "ПРИЛОЖЕНИЕ");
    loading();
    const result = await api(`/admin/api/apps/users?app_code=${code}`);
    root.innerHTML = `
      <div class="admin-app-directory-head"><h1>${esc(labels[code])}</h1><label><input id="admin-app-directory-search" type="search" aria-label="Поиск человека" placeholder="Имя или email"></label></div>
      <div class="admin-app-directory-list">${applicationUserRows(code, result.users || [])}</div>`;
    const list = root.querySelector(".admin-app-directory-list");
    const input = document.getElementById("admin-app-directory-search");
    let requestNumber = 0;
    let timer = null;
    bindApplicationUserRows(list, code);
    input.addEventListener("input", () => {
      clearTimeout(timer);
      timer = setTimeout(async () => {
        const currentRequest = ++requestNumber;
        const q = input.value.trim();
        try {
          const next = await api(`/admin/api/apps/users?app_code=${code}${q ? `&q=${encodeURIComponent(q)}` : ""}`);
          if (currentRequest !== requestNumber) return;
          list.innerHTML = applicationUserRows(code, next.users || []);
          bindApplicationUserRows(list, code);
        } catch (error) {
          if (currentRequest === requestNumber) list.innerHTML = `<div class="admin-error">${esc(error.message)}</div>`;
        }
      }, 220);
    });
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
    if (context === "strength" && strengthMobileMode) {
      renderStrengthMobilePerson({ ...user, email }, appDetail);
      return;
    }
    root.innerHTML = `
      <div class="admin-mode-banner"><div><strong>Административный режим</strong><span>Вы работаете с профилем ${esc(user.display_name || email || "без имени")}</span></div><button class="admin-action alt" id="admin-back" type="button">Сменить профиль</button></div>
      <div class="admin-profile-head"><div class="admin-profile-id"><div class="admin-avatar">${esc((user.display_name || email || "?").charAt(0).toUpperCase())}</div><div><h2>${esc(user.display_name || email || "Без имени")}</h2><p>${esc(email || "email не указан")} · ${esc(user.id)}</p></div></div><div class="admin-badges">${context ? `<span class="admin-badge">${appDetail.has_access ? "доступ есть" : "нет доступа"}</span><span class="admin-badge ${appDetail.has_state ? "" : "off"}">${appDetail.has_state ? "данные есть" : "данных нет"}</span>` : `<span class="admin-badge">${user.purchase_count} покупок</span><span class="admin-badge">${user.accesses.filter((item) => !item.revoked_at).length} доступов</span>`}</div></div>
      ${switcher(user, modules, context || "users")}
      <div class="admin-detail-grid ${context ? "app-context" : ""}">
        <article class="admin-card"><h3>${context ? labels[context] : "Сводка по приложениям"}</h3><div id="admin-app-panel">${context ? appDetails(context, appDetail) : moduleOverview(modules)}</div></article>
        <article class="admin-card"><h3>Быстрые переходы</h3><div class="admin-links"><a class="admin-action alt" href="/crm?user=${user.id}">Карточка CRM</a>${modules.telegram.exists ? `<a class="admin-action alt" href="/bot?view=contacts&user=${user.id}">Пользователь в боте</a>` : ""}${modules.dqs.exists || modules.dqs.has_access ? `<a class="admin-action alt" href="/admin/dqs?user=${user.id}">DQS</a>` : ""}${modules.strength.exists || modules.strength.has_access ? `<a class="admin-action alt" href="/admin/strength?user=${user.id}">Силовые</a>` : ""}${modules.metabolism.exists || modules.metabolism.has_access ? `<a class="admin-action alt" href="/admin/metabolism?user=${user.id}">Метаболизм</a>` : ""}</div><div class="admin-note" style="margin-top:14px">В DQS, силовых и метаболизме изменения выполняются тем же интерфейсом, который видит человек, и записываются в журнал.</div></article>
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
    if (["dqs", "strength", "metabolism"].includes(context) && appDetail.has_state) {
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
    if (["dqs", "strength", "metabolism"].includes(code)) return `<div data-edabalans-app="${code}" data-edabalans-admin-user="${esc(detail.user.id)}" data-edabalans-account-url="/admin/${code}"><div class="admin-empty">Загружаю приложение…</div></div>`;
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

  const contentNumber = (value) => value == null ? "—" : new Intl.NumberFormat("ru-RU").format(value);

  function contentEntity(entity) {
    const text = esc(entity.text || "");
    if (entity.type === "link" || entity.type === "text_link") {
      const href = entity.href || entity.text;
      return href ? `<a href="${esc(href)}" target="_blank" rel="noopener">${text}</a>` : text;
    }
    if (entity.type === "bold") return `<strong>${text}</strong>`;
    if (entity.type === "italic") return `<em>${text}</em>`;
    if (entity.type === "underline") return `<u>${text}</u>`;
    if (entity.type === "strikethrough") return `<s>${text}</s>`;
    if (entity.type === "blockquote") return `<span class="content-quote">${text}</span>`;
    return text;
  }

  function contentMedia(media, index) {
    const label = media.type === "video_file" || media.type === "video" ? "Видео" : media.type === "photo" || media.type === "image" ? "Изображение" : "Медиа";
    const href = media.source_url || media.preview_url;
    return `<div class="content-media-marker"><b>▧ ${label} ${index + 1}</b><span>${href ? `<a href="${esc(href)}" target="_blank" rel="noopener">Открыть вложение ↗</a>` : "Файл не копировался; позиция сохранена"}</span></div>`;
  }

  function contentBody(item) {
    if (!item.blocks || !item.blocks.length) return `<div class="content-post-text">${esc(item.text || "Текст ещё не импортирован")}</div>`;
    const mediaByMessage = new Map();
    item.media.forEach((media, index) => {
      const id = media.metadata && media.metadata.telegram_message_id;
      if (id != null) mediaByMessage.set(String(id), [...(mediaByMessage.get(String(id)) || []), [media, index]]);
    });
    const used = new Set();
    const blocks = item.blocks.map((block) => {
      const entities = block.entities || block.segments || [];
      const text = entities.length ? entities.map(contentEntity).join("") : esc(block.text || "");
      const positions = Array.isArray(block.media_positions) ? block.media_positions : [];
      const attached = positions.map((position) => [item.media[position], position]).filter(([media]) => media);
      (mediaByMessage.get(String(block.message_id)) || []).forEach((pair) => attached.push(pair));
      attached.forEach(([, index]) => used.add(index));
      const poll = block.poll ? `<div class="content-poll"><b>${esc(block.poll.question || "Опрос")}</b>${(block.poll.answers || []).map((answer) => `<span>${esc(answer)}</span>`).join("")}</div>` : "";
      return `<div class="content-block">${text ? `<div>${text}</div>` : ""}${poll}${attached.map(([media, index]) => contentMedia(media, index)).join("")}</div>`;
    }).join("");
    const remaining = item.media.map((media, index) => used.has(index) ? "" : contentMedia(media, index)).join("");
    return `<div class="content-post-text">${blocks}${remaining}</div>`;
  }

  function contentMetricCards(metrics) {
    const reactions = (metrics.emotions || []).reduce((sum, item) => sum + Number(item.count || 0), 0);
    const cards = [
      ["Просмотры", metrics.views], ["Рейтинг", metrics.rating], ["Плюсы", metrics.pluses],
      ["Минусы", metrics.minuses], ["Сохранения", metrics.saves],
      ["Комментарии", metrics.comments_reported], ["Реакции", reactions || null],
      ["Репосты", metrics.details && metrics.details.forwards]
    ];
    return `<div class="content-metrics">${cards.map(([label, value]) => `<div><small>${label}</small><b>${contentNumber(value)}</b></div>`).join("")}</div>`;
  }

  async function contentComments(item) {
    if (item.source !== "pikabu") return "";
    const comments = await api(`/admin/api/content/items/${encodeURIComponent(item.id)}/comments`);
    const reported = item.metrics.comments_reported;
    return `<article class="admin-card content-comments"><div class="content-comments-head"><div><h3>Комментарии</h3><p>Загружено ${comments.length}${reported == null ? "" : ` из ${reported}`}</p></div><a class="admin-action alt" href="${esc(item.canonical_url)}#comments" target="_blank" rel="noopener">Открыть на Pikabu ↗</a></div>${comments.length ? comments.map((comment) => `<div class="content-comment ${comment.is_owner_comment ? "owner" : ""}" style="--depth:${Math.min(comment.depth || 0, 6)}"><div><b>${esc(comment.author_name || "Без имени")}</b><span>${date(comment.published_at)} · рейтинг ${contentNumber(comment.rating)}</span></div><p>${esc(comment.text)}</p>${comment.permalink ? `<a href="${esc(comment.permalink)}" target="_blank" rel="noopener">Комментарий ↗</a>` : ""}</div>`).join("") : '<div class="admin-empty compact">Тексты комментариев ещё не собраны. Число комментариев и ссылка на обсуждение доступны выше.</div>'}</article>`;
  }

  async function contentCatalog() {
    const params = new URLSearchParams(location.search);
    const selected = params.get("item");
    setHeading("Каталог статей", "АВТОРСКИЕ МАТЕРИАЛЫ");
    loading();
    if (selected) {
      const item = await api(`/admin/api/content/items/${encodeURIComponent(selected)}`);
      const recommendations = { present: "Есть ссылки на другие материалы", mentioned_without_links: "Упомянуты без ссылок", absent: "Не упомянуты", review: "Нужно проверить" };
      const links = item.links.map((link) => `<div class="content-link"><b>${esc(link.text || link.type || "Ссылка")}</b><a href="${esc(link.url)}" target="_blank" rel="noopener">${esc(link.url)}</a></div>`).join("") || '<div class="admin-empty compact">Ссылок нет</div>';
      root.innerHTML = `
        <button class="admin-back" id="admin-back">← Назад к каталогу</button>
        <div class="admin-profile-head"><div class="admin-profile-id"><div><h2>${esc(item.title)}</h2><p>${item.source === "pikabu" ? "Pikabu" : "Telegram"} · ${date(item.published_at)} · ID ${esc(item.external_id)}</p></div></div><div class="admin-actions">${item.app_deep_link ? `<a class="admin-action" href="${esc(item.app_deep_link)}">Открыть в Telegram</a>` : ""}<a class="admin-action alt" href="${esc(item.canonical_url)}" target="_blank" rel="noopener">Оригинал ↗</a></div></div>
        <div class="admin-detail-grid content-detail-grid">
          <article class="admin-card"><h3>Текст</h3>${contentBody(item)}</article>
          <article class="admin-card"><h3>Разметка</h3><div class="content-primary-link"><small>ОРИГИНАЛ</small><a href="${esc(item.canonical_url)}" target="_blank" rel="noopener">${esc(item.canonical_url)} ↗</a></div>${contentMetricCards(item.metrics)}<div class="content-section"><h4>CTA</h4>${item.cta_url ? `<b>${esc(item.cta_text || "CTA")}</b><a class="content-visible-url" href="${esc(item.cta_url)}" target="_blank" rel="noopener">${esc(item.cta_url)}</a>` : '<span class="admin-help">Нет CTA</span>'}</div><div class="admin-rows"><div class="admin-row"><span>Рекомендации</span><b>${esc(recommendations[item.recommendations_status] || item.recommendations_status)}</b></div><div class="admin-row"><span>Медиа</span><b>${item.media.length} вложений</b></div><div class="admin-row"><span>Ссылки</span><b>${item.links.length}</b></div></div><div class="content-section"><h4>Ссылки из поста</h4>${links}</div></article>
        </div><div id="content-comments"></div>`;
      document.getElementById("admin-back").onclick = () => { location.href = `/admin/content?source=${encodeURIComponent(item.source)}`; };
      document.getElementById("content-comments").innerHTML = await contentComments(item);
      return;
    }
    const q = params.get("q") || "";
    const source = ["pikabu", "telegram"].includes(params.get("source")) ? params.get("source") : "pikabu";
    const sort = params.get("sort") || "date";
    const hasLinks = params.get("links") || "";
    const [summary, rows] = await Promise.all([
      api("/admin/api/content/summary"),
      api(`/admin/api/content/items?limit=1000&q=${encodeURIComponent(q)}&source=${source}&sort=${encodeURIComponent(sort)}&has_links=${encodeURIComponent(hasLinks)}`)
    ]);
    const navUrl = (nextSource) => `/admin/content?source=${nextSource}`;
    root.innerHTML = `
      <div class="content-source-tabs"><a class="${source === "pikabu" ? "active" : ""}" href="${navUrl("pikabu")}">Pikabu <b>${summary.by_source.pikabu || 0}</b></a><a class="${source === "telegram" ? "active" : ""}" href="${navUrl("telegram")}">Telegram <b>${summary.by_source.telegram || 0}</b></a></div>
      <div class="admin-toolbar content-toolbar"><input class="admin-filter" id="content-filter" value="${esc(q)}" placeholder="Заголовок или ID поста"><select id="content-sort"><option value="date">По дате</option><option value="views">По просмотрам</option><option value="likes">По лайкам / реакциям</option><option value="rating">По рейтингу</option><option value="comments">По комментариям</option><option value="links">По числу ссылок</option></select><select id="content-links"><option value="">Все ссылки</option><option value="yes">Есть ссылки</option><option value="no">Без ссылок</option></select><button class="admin-action" id="content-search">Применить</button></div>
      <div class="admin-list">${rows.map((item) => { const badges = [["просм.", item.views], ["рейтинг", item.rating], ["комм.", item.comments_reported], ["ссылок", item.link_count]].filter(([, value]) => value != null); return `<button class="admin-person content-person" data-content-id="${esc(item.id)}"><div><h3>${esc(item.title)}</h3><p>${date(item.published_at)} · ${esc(item.external_id)}</p></div><div class="content-preview-metrics">${badges.map(([label, value]) => `<span><b>${contentNumber(value)}</b> ${label}</span>`).join("")}<span class="admin-badge ${item.cta_url ? "" : "off"}">${item.cta_url ? "CTA" : "без CTA"}</span></div></button>`; }).join("") || '<div class="admin-empty">В этом источнике материалов пока нет</div>'}</div>`;
    document.getElementById("content-sort").value = sort;
    document.getElementById("content-links").value = hasLinks;
    root.querySelectorAll("[data-content-id]").forEach((button) => button.addEventListener("click", () => { location.href = `/admin/content?source=${source}&item=${encodeURIComponent(button.dataset.contentId)}`; }));
    const search = () => { const next = new URLSearchParams({ source, sort: document.getElementById("content-sort").value }); const value = document.getElementById("content-filter").value.trim(); const links = document.getElementById("content-links").value; if (value) next.set("q", value); if (links) next.set("links", links); location.href = `/admin/content?${next}`; };
    document.getElementById("content-search").onclick = search;
    document.getElementById("content-filter").addEventListener("keydown", (event) => { if (event.key === "Enter") search(); });
  }

  function pricingAmount(value) {
    return value === null || value === undefined ? "" : String(value);
  }

  async function pricingCatalog() {
    setHeading("Цены и тарифы", "ЕДИНЫЙ КАТАЛОГ");
    loading();
    const payload = await api("/admin/api/pricing");
    const versions = payload.versions || [];
    const selectedId = new URLSearchParams(location.search).get("version");
    const selected = versions.find((item) => item.id === selectedId)
      || versions.find((item) => item.status === "draft")
      || versions.find((item) => item.status === "active")
      || versions[0];
    const live = payload.live_consumption_enabled;
    if (!selected) {
      root.innerHTML = `<div class="pricing-banner"><div><h3>Каталог ещё не создан</h3><p>Создайте первый черновик. Он не повлияет на сайт.</p></div><button class="admin-action" id="pricing-create">Создать черновик</button></div>`;
      document.getElementById("pricing-create").onclick = async () => { await api("/admin/api/pricing/drafts", { method: "POST" }); await pricingCatalog(); };
      return;
    }
    const editable = selected.status === "draft";
    const sectionNames = { site_tariffs: "Три тарифа на главной странице", products: "Базовые цены продуктов", upsells: "Ступени допродаж после покупки" };
    const grouped = (selected.entries || []).reduce((result, entry) => { (result[entry.section] ||= []).push(entry); return result; }, {});
    const sections = Object.entries(grouped).map(([section, entries]) => `
      <section class="pricing-section"><h3>${esc(sectionNames[section] || section)}</h3><div class="pricing-table">
        ${entries.map((entry) => `<div class="pricing-row" data-price-code="${esc(entry.code)}">
          <div class="pricing-name"><b>${esc(entry.name)}</b><small>${esc(entry.code)}${entry.stage_code ? ` · этап ${esc(entry.stage_code)}` : ""}${entry.resource_codes.length ? ` · ${entry.resource_codes.map(esc).join(", ")}` : ""}</small></div>
          <div class="pricing-cell"><label>БАЗОВАЯ<input class="pricing-input" data-field="regular_amount" type="number" min="0" step="1" value="${esc(pricingAmount(entry.regular_amount))}"></label></div>
          <div class="pricing-cell"><label>ЗАЧЁРКНУТАЯ<input class="pricing-input" data-field="compare_at_amount" type="number" min="0" step="1" value="${esc(pricingAmount(entry.compare_at_amount))}"></label></div>
          <div class="pricing-cell"><label>ЦЕНА ПРОДАЖИ<input class="pricing-input" data-field="sale_amount" type="number" min="0" step="1" value="${esc(pricingAmount(entry.sale_amount))}"></label></div>
          <label class="pricing-check"><input data-field="enabled" type="checkbox" ${entry.enabled ? "checked" : ""}> Показывать</label>
        </div>`).join("")}
      </div></section>`).join("");
    root.innerHTML = `
      <div class="pricing-banner ${live ? "live" : ""}"><div><h3>${live ? "Серверный каталог включён" : "Подготовительный режим — на покупки не влияет"}</h3><p>${live ? "Новые страницы и checkout читают активную версию." : "Текущий сайт и существующая логика цен продолжают работать как раньше."}</p></div><span class="admin-badge ${live ? "" : "warn"}">${live ? "LIVE" : "ВЫКЛЮЧЕНО"}</span></div>
      <article class="admin-card ${editable ? "" : "pricing-readonly"}">
        <div class="pricing-version-head"><div><h2>Версия ${selected.version_number} · ${esc(selected.name)}</h2><p>${esc(selected.status)} · создана ${date(selected.created_at)}${selected.activated_at ? ` · опубликована ${date(selected.activated_at)}` : ""}</p></div><span class="admin-badge ${editable ? "warn" : ""}">${editable ? "ЧЕРНОВИК" : "НЕИЗМЕНЯЕМАЯ"}</span></div>
        <div class="pricing-meta"><label>НАЗВАНИЕ ВЕРСИИ<input class="pricing-input" id="pricing-name" value="${esc(selected.name)}"></label><label>КОММЕНТАРИЙ<textarea class="pricing-input" id="pricing-note">${esc(selected.note || "")}</textarea></label></div>
        ${sections}
        <div class="pricing-actions">${editable ? '<button class="admin-action" id="pricing-save">Сохранить черновик</button><button class="admin-action alt" id="pricing-publish">Опубликовать версию</button>' : '<button class="admin-action" id="pricing-create">Создать новый черновик из этой версии</button>'}</div>
      </article>
      <article class="admin-card pricing-history"><h3>История версий</h3>${versions.map((version) => `<button class="admin-row" data-pricing-version="${version.id}"><span>v${version.version_number} · ${esc(version.name)}</span><b>${esc(version.status)}</b></button>`).join("")}</article>`;
    root.querySelectorAll("[data-pricing-version]").forEach((button) => button.onclick = () => { location.href = `/admin/pricing?version=${button.dataset.pricingVersion}`; });
    if (!editable) {
      document.getElementById("pricing-create").onclick = async () => { const result = await api("/admin/api/pricing/drafts", { method: "POST" }); location.href = `/admin/pricing?version=${result.version.id}`; };
      return;
    }
    const collect = () => Array.from(root.querySelectorAll("[data-price-code]")).map((row) => ({
      code: row.dataset.priceCode,
      regular_amount: row.querySelector('[data-field="regular_amount"]').value === "" ? null : Number(row.querySelector('[data-field="regular_amount"]').value),
      compare_at_amount: row.querySelector('[data-field="compare_at_amount"]').value === "" ? null : Number(row.querySelector('[data-field="compare_at_amount"]').value),
      sale_amount: Number(row.querySelector('[data-field="sale_amount"]').value),
      enabled: row.querySelector('[data-field="enabled"]').checked
    }));
    document.getElementById("pricing-save").onclick = async () => {
      await api(`/admin/api/pricing/versions/${selected.id}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: document.getElementById("pricing-name").value, note: document.getElementById("pricing-note").value, entries: collect() }) });
      await pricingCatalog();
    };
    document.getElementById("pricing-publish").onclick = async () => {
      if (!confirm("Опубликовать эту неизменяемую версию? Пока переключатель выключен, текущие покупки не изменятся.")) return;
      await api(`/admin/api/pricing/versions/${selected.id}/publish`, { method: "POST" });
      await pricingCatalog();
    };
  }

  function moscowToday() {
    const parts = new Intl.DateTimeFormat("en-GB", { timeZone: "Europe/Moscow", year: "numeric", month: "2-digit", day: "2-digit" })
      .formatToParts(new Date())
      .reduce((result, part) => { result[part.type] = part.value; return result; }, {});
    return `${parts.year}-${parts.month}-${parts.day}`;
  }

  function marketingDate(value) {
    if (!value) return "—";
    return new Intl.DateTimeFormat("ru-RU", {
      timeZone: "Europe/Moscow", day: "2-digit", month: "2-digit", year: "2-digit", hour: "2-digit", minute: "2-digit"
    }).format(new Date(value));
  }

  function marketingShortDate(value) {
    if (!value) return "—";
    return new Intl.DateTimeFormat("ru-RU", {
      timeZone: "Europe/Moscow", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit"
    }).format(new Date(value)).replace(", ", " · ");
  }

  function marketingEvent(value, fallback = "—") {
    if (!value) return `<span class="marketing-empty">${esc(fallback)}</span>`;
    return `<b>${marketingDate(value.at)}</b>${value.detail ? `<small>${esc(value.detail)}</small>` : ""}${value.label ? `<small>${esc(value.label)}</small>` : ""}`;
  }

  function marketingEvents(values) {
    if (!values || !values.length) return '<span class="marketing-empty">—</span>';
    return values.map((value) => `<span class="marketing-event-list">${marketingEvent(value)}</span>`).join("");
  }

  function marketingOption(value, selected) {
    return `<option value="${esc(value)}" ${value === selected ? "selected" : ""}>${esc(value)}</option>`;
  }

  function marketingTimeline(item) {
    const entries = [];
    const add = (value, label) => {
      if (!value || !value.at) return;
      entries.push({ at: value.at, label: value.label || label, detail: value.detail || "" });
    };
    add(item.landing_entry, "Переход с посадки");
    add(item.start, "Старт бота");
    add(item.site_home, "Главная интенсива");
    (item.check_before_day_one || []).forEach((value) => add(value, "Проверка подписки"));
    add(item.day_one, "Открыл день 1");
    add(item.subscription, "Подписка подтверждена");
    (item.check_after_day_one || []).forEach((value) => add(value, "Проверка подписки"));
    add(item.later_days, "Открыл дни 2+");
    (item.other_actions || []).forEach((value) => add(value, value.label || "Другое действие"));
    return entries.sort((left, right) => left.at.localeCompare(right.at)).filter((entry, index, all) =>
      index === 0 || entry.at !== all[index - 1].at || entry.label !== all[index - 1].label
    );
  }

  function bindMarketingScrollbars() {
    root.querySelectorAll(".marketing-horizontal-scroll").forEach((rail) => {
      const target = root.querySelector(`#${rail.dataset.scrollTarget}`);
      const spacer = rail.firstElementChild;
      if (!target || !spacer) return;
      let syncing = false;
      let hasOverflow = false;
      const resize = () => {
        spacer.style.width = `${target.scrollWidth}px`;
        hasOverflow = target.scrollWidth > target.clientWidth + 1;
        rail.hidden = !hasOverflow;
      };
      target.addEventListener("scroll", () => {
        if (syncing) return;
        syncing = true;
        rail.scrollLeft = target.scrollLeft;
        syncing = false;
      }, { passive: true });
      rail.addEventListener("scroll", () => {
        if (syncing) return;
        syncing = true;
        target.scrollLeft = rail.scrollLeft;
        syncing = false;
      }, { passive: true });
      new ResizeObserver(resize).observe(target);
      resize();

      // The journeys table can be much taller than one screen. Its scrollbar
      // must remain reachable while reading it, not only after the last row.
      if (rail.dataset.scrollTarget === "marketing-journeys") {
        rail.classList.add("marketing-horizontal-scroll--fixed");
        const placeRail = () => {
          const box = target.getBoundingClientRect();
          const visible = hasOverflow && box.bottom > 76 && box.top < window.innerHeight;
          rail.toggleAttribute("hidden", !visible);
          if (!visible) return;
          const left = Math.max(8, box.left);
          rail.style.left = `${left}px`;
          rail.style.width = `${Math.max(0, Math.min(box.width, window.innerWidth - left - 8))}px`;
        };
        window.addEventListener("scroll", placeRail, { passive: true });
        window.addEventListener("resize", placeRail, { passive: true });
        placeRail();
      }
    });
  }

  function marketingPopoverData(title, entries) {
    return encodeURIComponent(JSON.stringify({ title, entries }));
  }

  function marketingPopoverButton(summary, title, entries) {
    return `<button type="button" class="marketing-popover-trigger" data-marketing-popover="${marketingPopoverData(title, entries)}">${esc(summary)}</button>`;
  }

  function bindMarketingTimelinePopover() {
    const popover = root.querySelector("#marketing-timeline-popover");
    if (!popover) return;
    const hide = () => { popover.hidden = true; };
    root.querySelectorAll("[data-marketing-popover]").forEach((cell) => {
      const show = () => {
        const data = JSON.parse(decodeURIComponent(cell.dataset.marketingPopover));
        popover.innerHTML = `<b>${esc(data.title)}</b><div>${data.entries.map((entry) => `<span>${entry.at ? `<time>${marketingDate(entry.at)}</time>` : ""}<strong>${esc(entry.label)}</strong>${entry.detail ? `<small>${esc(entry.detail)}</small>` : ""}</span>`).join("") || "Данных пока нет"}</div>`;
        popover.hidden = false;
        const box = cell.getBoundingClientRect();
        const width = Math.min(340, window.innerWidth - 24);
        const left = Math.max(12, Math.min(box.left, window.innerWidth - width - 12));
        popover.style.width = `${width}px`;
        popover.style.left = `${left}px`;
        popover.style.top = `${Math.max(12, Math.min(box.bottom + 8, window.innerHeight - popover.offsetHeight - 12))}px`;
      };
      cell.addEventListener("mouseenter", show);
      cell.addEventListener("mouseleave", hide);
      cell.addEventListener("focusin", show);
      cell.addEventListener("focusout", hide);
    });
  }

  async function marketingDashboard() {
    setHeading("Аналитика", "МАРКЕТИНГ И ВОРОНКА");
    loading();
    const params = new URLSearchParams(location.search);
    const from = params.get("from") || "2025-12-01";
    const to = params.get("to") || moscowToday();
    const source = params.get("source") || "";
    const campaign = params.get("campaign") || "";
    const creative = params.get("creative") || "";
    const user = params.get("user") || "";
    const request = new URLSearchParams({ from, to });
    if (source) request.set("source", source);
    if (campaign) request.set("campaign", campaign);
    if (creative) request.set("creative", creative);
    if (user) request.set("user", user);
    const data = await api(`/admin/api/marketing/overview?${request}`);
    const selected = data.filters.selected;
    const missingStage = (code) => data.collection[code] ? "—" : "не подключено";
    const rows = (data.rows || []).map((item) => {
      const userName = item.user_id
        ? `<a href="/admin/users?user=${encodeURIComponent(item.user_id)}">${esc(item.display_name)}</a>`
        : `<b>${esc(item.display_name)}</b>`;
      const allActions = marketingTimeline(item);
      const courseActions = allActions.filter((action) => /день|подписк|главная интенсива|видео/i.test(action.label));
      const maxDay = item.later_days?.max_day;
      const courseSummary = maxDay ? `день ${maxDay}` : item.day_one ? "день 1" : item.subscription ? "подписан" : "—";
      const status = item.status === "blocked" ? "Заблокировал" : item.status === "lost_before_start" ? "Не стартовал" : item.is_new_lead ? "Новый" : "Повторный";
      const sourceDetails = [
        { label: `Источник: ${item.source}` },
        { label: `Размещение: ${item.placement}` },
        { label: `Кампания: ${item.campaign}` },
        { label: `Объявление: ${item.creative}` },
        { label: `Ссылка: ${item.link_name}` },
      ];
      const entryDetails = item.landing_entry ? [{ at: item.landing_entry.at, label: item.landing_entry.label, detail: `${item.landing_entry.messenger || item.messenger} · ${item.landing_entry.method === "qr" ? "QR" : "кнопка"}` }] : [];
      const startDetails = item.start ? [{ at: item.start.at, label: item.start.label || "Старт бота" }] : [];
      const statusDetails = [{ label: status }, { label: `Мессенджер: ${item.messenger}` }];
      const lastAction = item.last_action || allActions.at(-1);
      const profileDetails = [
        { label: item.display_name },
        ...item.usernames.map((username) => ({ label: username })),
        ...allActions,
      ];
      return `<tr>
        <td class="marketing-person" data-marketing-popover="${marketingPopoverData("Путь пользователя", profileDetails)}">${userName}</td>
        <td>${marketingPopoverButton(item.source, "Источник и кампания", sourceDetails)}</td>
        <td>${marketingPopoverButton(item.landing_entry ? (item.landing_entry.method === "qr" ? "QR" : "Кнопка") : "—", "Вход с посадки", entryDetails)}</td>
        <td>${marketingPopoverButton(item.start ? marketingShortDate(item.start.at) : "—", "Старт бота", startDetails)}</td>
        <td>${marketingPopoverButton(status, "Статус", statusDetails)}</td>
        <td>${marketingPopoverButton(courseSummary, "Путь в интенсиве", courseActions)}</td>
        <td>${marketingPopoverButton(lastAction ? marketingShortDate(lastAction.at) : "—", "Все действия", allActions)}</td>
      </tr>`;
    }).join("");
    const analytics = (data.analytics || []).map((item) => `<tr>
      <td>${esc(item.label)}</td>
      <td>${item.collection === "not_connected" ? '<span class="marketing-empty">не подключено</span>' : item.count.toLocaleString("ru-RU")}</td>
      <td>${item.conversion_from_previous === null ? "—" : `${item.conversion_from_previous.toLocaleString("ru-RU")}%`}</td>
      <td>${item.lost_from_previous === null ? "—" : item.lost_from_previous.toLocaleString("ru-RU")}</td>
      <td>${item.conversion_from_start === null ? "—" : `${item.conversion_from_start.toLocaleString("ru-RU")}%`}</td>
    </tr>`).join("");
    const entryBreakdown = (data.entry_breakdown || []).map((item) => `<tr>
      <td>${esc(item.source)}</td><td>${esc(item.campaign)}</td><td>${esc(item.creative)}</td>
      <td>${esc(item.messenger)}</td><td>${item.entry === "qr" ? "QR-код" : "Кнопка"}</td>
      <td>${item.entries.toLocaleString("ru-RU")}</td><td>${item.starts.toLocaleString("ru-RU")}</td>
      <td>${item.lost.toLocaleString("ru-RU")}</td><td>${item.conversion === null ? "—" : `${item.conversion.toLocaleString("ru-RU")}%`}</td>
    </tr>`).join("");
    root.innerHTML = `
      <div class="marketing-sticky-head">
        <nav class="marketing-quick-nav" aria-label="Разделы аналитики"><a href="#marketing-journeys">Пути людей</a><a href="#marketing-conversions">Конверсии</a><a href="#marketing-entry-losses">Потери до старта</a></nav>
        <form class="marketing-filters" id="marketing-filters">
        <div class="marketing-date-range"><label>С<input name="from" type="date" min="2025-12-01" value="${esc(data.period.from)}"></label><label>По<input name="to" type="date" min="2025-12-01" value="${esc(data.period.to)}"></label></div>
        <label>Источник<select name="source"><option value="">Все источники</option>${data.filters.sources.map((value) => marketingOption(value, selected.source)).join("")}</select></label>
        <label>Кампания<select name="campaign"><option value="">Все кампании</option>${data.filters.campaigns.map((value) => marketingOption(value, selected.campaign)).join("")}</select></label>
        <label>Объявление<select name="creative"><option value="">Все объявления</option>${data.filters.creatives.map((value) => marketingOption(value, selected.creative)).join("")}</select></label>
        <label class="marketing-user-filter">Пользователь<input name="user" value="${esc(selected.user)}" placeholder="Имя, username или ID"></label>
        <div class="marketing-filter-actions"><button class="admin-action">Показать</button><a class="admin-action alt" href="/admin/marketing">Сбросить</a></div>
        </form>
      </div>
      <div class="marketing-result-line">Найдено пользователей: <b>${data.totals.matching_rows.toLocaleString("ru-RU")}</b>${data.totals.rows < data.totals.matching_rows ? ` · в таблице первые ${data.totals.rows.toLocaleString("ru-RU")}, аналитика по всем` : ""}</div>
      ${data.totals.events_truncated ? '<div class="marketing-note">Событий больше безопасного предела отчёта. Текущая таблица и аналитика неполные — сузьте период.</div>' : ""}
      <div class="marketing-table-wrap" id="marketing-journeys"><table class="marketing-table marketing-leads"><thead><tr>
        <th>Пользователь</th><th>Источник</th><th>Вход</th><th>Старт</th><th>Статус</th><th>Интенсив</th><th>Последнее</th>
      </tr></thead><tbody>${rows || '<tr><td colspan="7"><div class="admin-empty">По выбранным фильтрам пользователей нет</div></td></tr>'}</tbody></table></div>
      <div class="marketing-horizontal-scroll" data-scroll-target="marketing-journeys" aria-label="Горизонтальная прокрутка таблицы путей"><div></div></div>
      <h2 class="marketing-analytics-title" id="marketing-conversions">Конверсии текущего среза</h2>
      <div class="marketing-table-wrap marketing-analytics-wrap" id="marketing-conversions-table"><table class="marketing-table marketing-analytics"><thead><tr><th>Действие</th><th>Количество</th><th>От прошлого шага</th><th>Потеряно</th><th>От стартовавших</th></tr></thead><tbody>${analytics}</tbody></table></div>
      <div class="marketing-horizontal-scroll" data-scroll-target="marketing-conversions-table" aria-label="Горизонтальная прокрутка конверсий"><div></div></div>
      <h2 class="marketing-analytics-title" id="marketing-entry-losses">Потери до старта по объявлениям</h2>
      <div class="marketing-table-wrap" id="marketing-entry-losses-table"><table class="marketing-table"><thead><tr><th>Источник</th><th>Кампания</th><th>Объявление</th><th>Мессенджер</th><th>Способ</th><th>Переходы</th><th>Старты</th><th>Потеряно</th><th>Конверсия</th></tr></thead><tbody>${entryBreakdown || '<tr><td colspan="9"><div class="admin-empty">Новые точные данные появятся после публикации обновлённой посадки</div></td></tr>'}</tbody></table></div>
      <div class="marketing-horizontal-scroll" data-scroll-target="marketing-entry-losses-table" aria-label="Горизонтальная прокрутка потерь до старта"><div></div></div>
      ${data.totals.clicks_ignore_user_filter ? '<div class="marketing-note">Переходы считаются по источнику и кампании: технический клик пока нельзя надёжно привязать к поиску конкретного пользователя.</div>' : ""}<aside class="marketing-timeline-popover" id="marketing-timeline-popover" hidden></aside>`;
    document.getElementById("marketing-filters").addEventListener("submit", (event) => {
      event.preventDefault();
      const form = new FormData(event.currentTarget);
      const next = new URLSearchParams();
      for (const key of ["from", "to", "source", "campaign", "creative", "user"]) {
        const value = String(form.get(key) || "").trim();
        if (value) next.set(key, value);
      }
      location.href = `/admin/marketing?${next}`;
    });
    bindMarketingScrollbars();
    bindMarketingTimelinePopover();
  }

  async function run() {
    const active = section();
    selectNavigation(active);
    if (["dqs", "strength", "metabolism"].includes(active)) return application(active);
    if (active === "users") return users();
    if (active === "content") return contentCatalog();
    if (active === "pricing") return pricingCatalog();
    if (active === "marketing") return marketingDashboard();
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
