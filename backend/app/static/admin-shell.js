(function () {
  "use strict";

  if (location.pathname === "/admin/strength" && new URLSearchParams(location.search).get("mobile") === "1") return;

  const body = document.body;
  body.classList.add("ed-admin-shell");
  const categoryOrder = ["clients", "applications", "marketing", "courses", "commerce", "service", "knowledge"];
  const categoryNames = {
    clients: "Клиенты",
    applications: "Приложения",
    marketing: "Маркетинг",
    courses: "Курсы",
    commerce: "Коммерция",
    service: "Служебное",
    knowledge: "База знаний"
  };
  const stateKey = "edabalans-admin-shell-state";
  const scrollKey = "edabalans-admin-shell-scroll";

  function esc(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (char) {
      return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char];
    });
  }

  function selected(item) {
    const target = new URL(item.url, location.origin);
    if (target.pathname !== location.pathname) return false;
    const targetView = target.searchParams.get("view");
    return !targetView || targetView === new URLSearchParams(location.search).get("view");
  }

  function compactIcon(label) {
    const words = String(label || "").trim().split(/\s+/).filter(Boolean);
    if (!words.length) return "•";
    if (words.length > 1) return (words[0][0] + words[1][0]).toLocaleUpperCase("ru-RU");
    return words[0].slice(0, 2).toLocaleUpperCase("ru-RU");
  }

  function itemMarkup(item, moduleId, icon) {
    const disabled = moduleId === "messaging.telegram.engine";
    const iconClass = moduleId === "platform.crm" ? " admin-nav-icon-crm" : "";
    const copy = `<span class="admin-nav-icon${iconClass}">${esc(icon)}</span><span class="admin-nav-copy"><b>${esc(item.label)}</b>${disabled ? '<small>редактируется через Codex</small>' : ""}</span>`;
    const category = esc(item.category || "service");
    if (disabled) return `<span class="admin-nav-disabled" data-admin-category="${category}" title="${esc(item.description)}" aria-label="${esc(item.label)}" aria-disabled="true">${copy}</span>`;
    const external = /^https:\/\//.test(item.url) && new URL(item.url).origin !== location.origin;
    return `<a href="${esc(item.url)}" data-admin-category="${category}" title="${esc(item.label)}" aria-label="${esc(item.label)}"${selected(item) ? ' class="active" aria-current="page"' : ""}${external ? ' target="_blank" rel="noopener"' : ""}>${copy}</a>`;
  }

  function render(modules) {
    const usedIcons = new Set();
    function uniqueIcon(item) {
      const base = item.icon || compactIcon(item.label);
      if (!usedIcons.has(base)) {
        usedIcons.add(base);
        return base;
      }
      let suffix = 2;
      let candidate = `${base[0] || "•"}${suffix}`;
      while (usedIcons.has(candidate)) {
        suffix += 1;
        candidate = `${base[0] || "•"}${suffix}`;
      }
      usedIcons.add(candidate);
      return candidate;
    }
    const items = (modules || []).flatMap(function (module) {
      return (module.admin_catalog || []).map(function (item) { return Object.assign({module_id: module.id}, item); });
    });
    const groups = categoryOrder.map(function (category) {
      return {category: category, items: items.filter(function (item) { return item.category === category; }).sort(function (a,b) { return a.order - b.order; })};
    }).filter(function (group) { return group.items.length; });
    const nav = document.querySelector(".admin-shell-nav");
    nav.innerHTML = groups.map(function (group) {
      return `<span data-admin-category="${group.category}">${categoryNames[group.category]}</span>` + group.items.map(function (item) {
        return itemMarkup(Object.assign({category: group.category}, item), item.module_id, uniqueIcon(item));
      }).join("");
    }).join("");
    const rememberedScroll = Number(sessionStorage.getItem(scrollKey) || 0);
    requestAnimationFrame(function () { nav.scrollTop = rememberedScroll; });
  }

  let sidebar = document.querySelector(".admin-sidebar");
  if (!sidebar) {
    sidebar = document.createElement("aside");
    sidebar.className = "admin-sidebar";
    body.prepend(sidebar);
  }
  sidebar.innerHTML = `
    <div class="admin-shell-brand-row">
      <a class="admin-brand" href="/admin"><img src="/favicon.png" alt=""><span>Похудение — это есть.рф<small>админка</small></span></a>
      <div class="admin-shell-controls">
        <button class="admin-shell-control" data-action="collapse" type="button" title="Свернуть меню" aria-label="Свернуть меню">‹</button>
        <button class="admin-shell-control" data-action="hide" type="button" title="Скрыть меню" aria-label="Скрыть меню">×</button>
      </div>
    </div>
    <nav class="admin-nav admin-shell-nav" aria-label="Разделы админки"><a href="/crm"><span class="admin-nav-icon">👥</span><span class="admin-nav-copy"><b>CRM</b></span></a></nav>
    <div class="admin-shell-footer"><a class="admin-shell-account" href="/lk"><span class="admin-nav-icon">⌂</span><span>Личный кабинет</span></a><button class="admin-shell-logout" type="button"><span class="admin-nav-icon">↪</span><span>Выйти</span></button></div>`;

  const backdrop = document.createElement("div");
  backdrop.className = "admin-shell-backdrop";
  const open = document.createElement("button");
  open.className = "admin-shell-open";
  open.type = "button";
  open.setAttribute("aria-label", "Показать меню");
  open.textContent = "☰";
  const mobileOpen = document.createElement("button");
  mobileOpen.className = "admin-shell-mobile-open";
  mobileOpen.type = "button";
  mobileOpen.setAttribute("aria-label", "Открыть меню");
  mobileOpen.setAttribute("aria-expanded", "false");
  mobileOpen.textContent = "☰";
  body.append(backdrop, open, mobileOpen);
  const collapseButton = sidebar.querySelector('[data-action="collapse"]');
  const shellNav = sidebar.querySelector(".admin-shell-nav");
  shellNav.addEventListener("scroll", function () {
    sessionStorage.setItem(scrollKey, String(Math.round(shellNav.scrollTop)));
  }, {passive: true});

  function setState(next) {
    body.classList.toggle("admin-shell-collapsed", next === "collapsed");
    body.classList.toggle("admin-shell-hidden", next === "hidden");
    const collapsed = next === "collapsed";
    collapseButton.textContent = collapsed ? "›" : "‹";
    collapseButton.title = collapsed ? "Раскрыть меню" : "Свернуть меню";
    collapseButton.setAttribute("aria-label", collapseButton.title);
    localStorage.setItem(stateKey, next);
  }
  setState(localStorage.getItem(stateKey) || "expanded");
  collapseButton.addEventListener("click", function () {
    setState(body.classList.contains("admin-shell-collapsed") ? "expanded" : "collapsed");
  });
  sidebar.querySelector('[data-action="hide"]').addEventListener("click", function () { setState("hidden"); });
  open.addEventListener("click", function () { setState("expanded"); });
  function closeMobile() { body.classList.remove("admin-shell-mobile-opened"); mobileOpen.setAttribute("aria-expanded", "false"); mobileOpen.textContent = "☰"; }
  mobileOpen.addEventListener("click", function () {
    const opened = body.classList.toggle("admin-shell-mobile-opened");
    mobileOpen.setAttribute("aria-expanded", String(opened));
    mobileOpen.textContent = opened ? "×" : "☰";
  });
  backdrop.addEventListener("click", closeMobile);
  sidebar.addEventListener("click", function (event) { if (event.target.closest("a") && matchMedia("(max-width:760px)").matches) closeMobile(); });
  sidebar.querySelector(".admin-shell-logout").addEventListener("click", async function () {
    await fetch("/admin/api/logout", {method:"POST", credentials:"same-origin"});
    location.replace("/admin");
  });

  fetch("/admin/api/project-map", {credentials:"same-origin"}).then(function (response) {
    if (!response.ok) throw new Error("catalog unavailable");
    return response.json();
  }).then(function (data) { render(data.modules); }).catch(function () {
    render([{id:"platform.crm",admin_catalog:[{category:"clients",order:10,url:"/crm",label:"CRM",description:"Клиенты",icon:"👥"}]}]);
  });
}());
