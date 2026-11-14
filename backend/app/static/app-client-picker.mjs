const supported = new Set(['account', 'strength', 'dqs', 'metabolism', 'recipes']);
const appPaths = {account:'/lk', strength: '/training', dqs: '/dqs', metabolism: '/metabolism', recipes: '/recipes'};
const appLabels = {account:'Личный кабинет', strength:'Силовые', dqs:'DQS', metabolism:'Калькулятор метаболизма', recipes:'Рецепты'};

export function mount(root, app, context, host, admin) {
  if (!root.isConnected || (!supported.has(app) && !(admin && app === 'dashboard')) || !context.can_manage || root.dataset.clientPicker) return;
  root.dataset.clientPicker = 'true';
  if (!document.getElementById('app-client-picker-style')) {
    const style = document.createElement('style');
    style.id = 'app-client-picker-style';
    style.textContent = `
      .ed-client-button{display:inline-flex;align-items:center;gap:5px;max-width:100%;min-height:32px;padding:2px 6px;border:1px solid var(--ed-app-line,#e7e7ef);border-radius:8px;background:#fff;color:inherit;font:inherit;cursor:pointer;text-align:left}
      .ed-client-button span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0}.ed-client-button:after{content:'▾';flex:none;color:var(--ed-app-accent,#6f3de8)}
      .ed-client-button:focus-visible,.ed-client-popup :focus-visible{outline:2px solid #6f3de8;outline-offset:2px}
      .ed-app-switch-bar{display:flex;align-items:center;justify-content:space-between;gap:8px;margin:0 0 8px;padding:8px;border:1px solid #dce9f1;border-radius:12px;background:#fff}
      .ed-app-switch-bar .ed-client-button{min-width:0;max-width:60%}
      #account-app .ed-app-switch-bar{width:100%;box-sizing:border-box;margin:0}
      #account-app .ed-app-switch-bar .account-session{min-width:0}
      .ed-app-switch-button{flex:none;min-height:32px;margin-left:auto;padding:3px 8px;border:1px solid #addcf4;border-radius:8px;background:#fff;color:#087aad;font:inherit;cursor:pointer}
      #strength-app .ed-app-switch-button{font-size:12px}
      @media(max-width:700px){#strength-app .ed-app-switch-button{font-size:10px;padding:3px 4px}}
      .ed-app-switch-drawer{position:fixed;inset:0 0 0 auto;margin:0;width:min(350px,100vw);height:100dvh;max-height:100dvh;padding:16px;border:0;border-radius:14px 0 0 14px;background:#fff;color:#273b50;box-sizing:border-box;box-shadow:0 0 36px #22375025;font:14px/1.4 var(--ed-font-body,Manrope,Arial,sans-serif)}
      .ed-app-switch-drawer::backdrop{background:#17314930}.ed-app-switch-drawer header{display:flex;align-items:center;justify-content:space-between}.ed-app-switch-drawer header button{border:0;background:transparent;font-size:24px;min-width:36px;cursor:pointer}
      .ed-app-switch-drawer nav{display:grid;gap:5px;margin-top:12px}.ed-app-switch-drawer nav a{display:block;padding:10px;border:1px solid #dce9f1;border-radius:8px;color:#087aad;text-decoration:none}
      .ed-app-switch-drawer nav a[aria-current],.ed-app-switch-drawer nav a:hover{background:#e9f5fc;border-color:#addcf4}
      .ed-client-popup{box-sizing:border-box;position:fixed;margin:0;padding:12px;width:min(400px,calc(100vw - 24px));max-height:65dvh;border:1px solid #e7e7ef;border-radius:var(--ed-app-radius-large,16px);background:#fff;color:#17172b;box-shadow:0 10px 35px #17172b22;font:14px/1.4 var(--ed-font-body,Manrope,Arial,sans-serif)}
      .ed-client-popup[open]{display:flex;flex-direction:column;gap:8px}.ed-client-popup::backdrop{background:transparent}.ed-client-popup header{display:flex;justify-content:space-between;align-items:center;gap:10px}
      .ed-client-popup button,.ed-client-popup input{font:inherit}.ed-client-popup button{cursor:pointer}.ed-client-popup header button{border:0;background:transparent;font-size:22px;min-width:36px;min-height:36px}
      .ed-client-popup input{box-sizing:border-box;width:100%;min-height:40px;padding:8px;border:1px solid #d8d8e4;border-radius:8px}.ed-client-list{overflow:auto;min-height:40px;overscroll-behavior:contain}
      .ed-client-row{display:block;width:100%;min-height:56px;padding:8px;text-align:left;border:0;border-bottom:1px solid #efeff5;background:#fff;color:#17172b}.ed-client-row:hover,.ed-client-row[aria-current=true]{background:#f5f1ff}.ed-client-row small{color:#62677a}.ed-client-identity{display:flex;align-items:baseline;gap:6px;min-width:0;white-space:nowrap}.ed-client-identity strong{flex:0 1 auto;max-width:48%;min-width:0;overflow:hidden;text-overflow:ellipsis}.ed-client-identity small{flex:1 1 0;min-width:0;overflow:hidden;text-overflow:ellipsis;font-size:11px}.ed-client-more,.ed-client-own,.ed-client-favorites-toggle{min-height:40px;border:1px solid #e7e7ef;background:#fff;color:#6f3de8;border-radius:8px}.ed-client-actions{display:grid;grid-template-columns:1fr 1fr;gap:8px}.ed-client-favorites-toggle[aria-expanded=true]{background:var(--ed-app-accent-soft,#f5f1ff);border-color:var(--ed-app-accent,#6f3de8)}.ed-client-message{margin:0;color:#62677a;font-size:13px;overflow-wrap:anywhere}
      .ed-client-scopes{display:flex;flex-wrap:wrap;gap:4px}.ed-client-scopes button{flex:1;min-height:38px;padding:5px;border:1px solid var(--ed-app-line,#e7e7ef);border-radius:8px;background:#fff;color:inherit;font-size:12px}.ed-client-scopes button[aria-pressed=true]{background:var(--ed-app-accent-soft,#f5f1ff);border-color:var(--ed-app-accent,#6f3de8)}
      .ed-client-item{display:grid;grid-template-columns:minmax(0,1fr) 48px;align-items:stretch;border-bottom:1px solid #efeff5}.ed-client-item .ed-client-row{border-bottom:0;min-width:0}.ed-client-popup .ed-client-favorite{border:0;background:#fff;color:var(--ed-app-accent,#6f3de8);font-size:30px;line-height:1;min-width:48px;min-height:48px;padding:0;touch-action:manipulation}.ed-client-group{margin:8px 0 3px;font-size:12px;font-weight:700;color:#62677a}.ed-client-row .ed-client-activity{display:block;margin-top:3px;font-size:10px;line-height:1.2;color:#62677a}
    `;
    document.head.append(style);
  }
  const identity = context.selected || context.actor || {};
  const favoriteKey = 'edabalans-client-favorites:' + (context.actor?.user_id || 'admin') + ':' + app;
  let favorites = new Set();
  try {
    const saved = JSON.parse(localStorage.getItem(favoriteKey) || '[]');
    if (Array.isArray(saved)) favorites = new Set(saved.slice(0,100).filter(id => typeof id === 'string' && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id)));
  } catch {}
  let dialog, opener, drawer;
  function destination(code, userId) {
    const url = new URL(appPaths[code], host);
    if (userId) url.searchParams.set(code === 'account' ? 'account_user' : 'app_user', userId);
    return url;
  }
  function appSwitchButton() {
    const button = document.createElement('button');
    button.type = 'button'; button.className = 'ed-app-switch-button';
    button.setAttribute('aria-label', 'Выбрать приложение');
    button.setAttribute('aria-haspopup', 'dialog');
    button.textContent = 'Приложения ▾';
    button.onclick = () => {
      if (!drawer) {
        drawer = document.createElement('dialog');
        drawer.className = 'ed-app-switch-drawer';
        drawer.setAttribute('aria-label', 'Приложения');
        drawer.innerHTML = '<header><strong>Приложения</strong><button type="button" aria-label="Закрыть" autofocus>×</button></header><nav></nav><p role="status"></p>';
        const nav = drawer.querySelector('nav'), status = drawer.querySelector('[role=status]');
        const add = (label, url, current = false) => {
          const link = document.createElement('a');
          link.href = url.href; link.textContent = label;
          if (current) link.setAttribute('aria-current', 'page');
          nav.append(link); return link;
        };
        const userId = context.selected?.user_id;
        if (context.dashboard_url) {
          const dashboard = new URL(context.dashboard_url, host);
          dashboard.searchParams.set('view', 'apps');
          if (identity.user_id) dashboard.searchParams.set('user', identity.user_id);
          add('Дашборд клиента', dashboard);
        }
        for (const [code, label] of Object.entries(appLabels)) {
          const url = destination(code, userId);
          const link = add(label, url, code === app);
          if (userId && code !== app && ['strength', 'dqs', 'metabolism'].includes(code)) link.dataset.appCode = code;
        }
        drawer.querySelector('header button').onclick = () => drawer.close();
        let opening = false;
        drawer.addEventListener('click', async event => {
          if (event.target === drawer && event.clientX < drawer.getBoundingClientRect().left) drawer.close();
          const link = event.target.closest('a');
          if (link?.hasAttribute('aria-current') || link && !maySwitch()) {
            event.preventDefault();
            if (link.hasAttribute('aria-current')) drawer.close();
            else status.textContent = 'Сначала сохраните текущие изменения или дождитесь сохранения.';
            return;
          }
          if (!link) return;
          if (opening) { event.preventDefault(); return; }
          if (link.dataset.appCode && !event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey) {
            event.preventDefault();
            opening = true;
            status.textContent = 'Открываю…';
            try {
              await ensureState(link.dataset.appCode, userId);
              if (drawer.open && maySwitch()) location.assign(link.href);
              else status.textContent = 'Сначала сохраните текущие изменения.';
            } catch (error) { status.textContent = error.message; }
            finally { opening = false; }
          }
        });
        document.body.append(drawer);
      }
      drawer.querySelector('[role=status]').textContent = '';
      drawer.showModal();
    };
    return button;
  }
  function clientButton() {
    const button = document.createElement('button');
    button.type = 'button'; button.className = 'ed-client-button';
    button.setAttribute('aria-label', 'Выбрать клиента'); button.setAttribute('aria-haspopup', 'dialog');
    const label = document.createElement('span'); label.textContent = identity.email || identity.display_name || 'Выбрать клиента'; button.append(label);
    button.title = [identity.display_name, identity.email].filter(Boolean).join(' · ');
    button.onclick = () => open(button);
    return button;
  }
  function decorate() {
    if (!root.isConnected) { observer.disconnect(); dialog?.remove(); drawer?.remove(); return; }
    if (admin) {
      admin.button.onclick = () => open(admin.button);
      return;
    }
    if (app === 'account') {
      const button = root.querySelector('[data-account-profile]');
      if (button && !button.dataset.clientPickerBound) {
        button.dataset.clientPickerBound = 'true';
        button.setAttribute('aria-haspopup','dialog');
        button.setAttribute('aria-label','Выбрать клиента');
        button.removeAttribute('aria-expanded');
        button.onclick = () => open(button);
        const session = button.closest('.account-session');
        if (session) {
          const bar = document.createElement('div');
          bar.className = 'ed-app-switch-bar';
          session.before(bar); bar.append(session, appSwitchButton());
        }
      }
      return;
    }
    const strengthHeaders = app === 'strength' ? root.querySelectorAll('.st-top-email') : [];
    if (strengthHeaders.length) {
      root.querySelector(':scope > .ed-app-switch-bar')?.remove();
      for (const place of strengthHeaders) {
        if (!place.querySelector('.ed-client-button')) place.replaceChildren(clientButton());
        const header = place.closest('.st-top');
        if (header && !header.querySelector('.ed-app-switch-button')) header.append(appSwitchButton());
      }
      return;
    }
    const selector = {dqs: '.dqs-sticky', metabolism: '.mw-window', recipes: '.recipe-shell'}[app];
    const surface = selector && root.querySelector(selector) || root;
    if (surface !== root) root.querySelector(':scope > .ed-app-switch-bar')?.remove();
    if (surface.querySelector(':scope > .ed-app-switch-bar')) return;
    const bar = document.createElement('div');
    bar.className = 'ed-app-switch-bar'; bar.append(clientButton(), appSwitchButton()); surface.prepend(bar);
  }
  async function api(path, options = {}) {
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch(host + path, {credentials: 'include', cache: 'no-store', ...options, signal: controller.signal});
      const data = await response.json();
      if (!response.ok || data.ok === false) throw new Error(data.detail === 'user has no active access' ? 'У клиента нет действующего доступа к этому приложению.' : typeof data.detail === 'string' ? data.detail : data.error || 'Не удалось открыть клиента');
      return data;
    } catch (error) {
      if (error.name === 'AbortError') throw new Error('Сервер не ответил. Повторите выбор клиента.');
      throw error;
    } finally { clearTimeout(timer); }
  }
  function maySwitch() {
    if (admin) return admin.maySwitch();
    const check = window.EdabalansAppContext?.canSwitchClient;
    return !check || check();
  }
  async function ensureState(code, userId) {
    const base = '/admin/api/apps/' + code + '/users/' + encodeURIComponent(userId);
    const detail = await api(base);
    if (!detail.has_state) await api(base + '/open', {method: 'POST'});
  }
  function navigate(userId) {
    if (admin) { admin.navigate(userId); return; }
    // /lk does not restore its active embedded application on reload.
    const url = new URL(appPaths[app], location.origin);
    if (app === 'account') {
      for (const key of ['layout','theme']) { const value = new URL(location.href).searchParams.get(key); if(value)url.searchParams.set(key,value); }
      if(userId && userId !== context.actor?.user_id)url.searchParams.set('account_user',userId);
    } else if (userId) url.searchParams.set('app_user', userId); else url.searchParams.delete('app_user');
    url.hash = '';
    location.assign(url.href);
  }
  async function open(button) {
    dialog?.remove(); opener = button;
    dialog = document.createElement('dialog'); dialog.className = 'ed-client-popup'; dialog.setAttribute('aria-label', 'Выбрать клиента');
    dialog.dataset.app = app;
    dialog.innerHTML = '<header><strong>Выбрать клиента</strong><button type="button" aria-label="Закрыть">×</button></header><div class="ed-client-scopes" role="group" aria-label="Показать клиентов"><button type="button" data-scope="used" aria-pressed="true">Уже заходили</button><button type="button" data-scope="active" aria-pressed="false">Активные · 30 дней</button><button type="button" data-scope="all" aria-pressed="false">Все клиенты</button></div><input type="search" aria-label="Имя, фамилия или email" placeholder="Имя, фамилия или email" autocomplete="off"><div class="ed-client-actions"><button class="ed-client-own" type="button">Мои данные</button><button class="ed-client-favorites-toggle" type="button" aria-controls="ed-client-favorites">Избранное</button></div><p class="ed-client-message" role="status"></p><div class="ed-client-list"></div><button class="ed-client-more" type="button" hidden>Показать ещё</button>';
    document.body.append(dialog);
    if (admin) dialog.querySelector('.ed-client-own').hidden = true;
    if(app==='account'){
      dialog.querySelector('.ed-client-own').textContent='Мой кабинет';
      const logout=document.createElement('button');logout.type='button';logout.className='ed-client-own';logout.textContent='Выйти';logout.onclick=()=>root.querySelector('.account-logout').click();dialog.append(logout);
    }
    const currentDialog = dialog, list = dialog.querySelector('.ed-client-list'), input = dialog.querySelector('input'), message = dialog.querySelector('[role=status]'), more = dialog.querySelector('.ed-client-more');
    const favoritesToggle = dialog.querySelector('.ed-client-favorites-toggle');
    let favoritesExpanded = favorites.size > 0;
    favoritesToggle.setAttribute('aria-expanded', String(favoritesExpanded));
    favoritesToggle.onclick = () => { favoritesExpanded = !favoritesExpanded; renderRows(); };
    let generation = 0, timer, offset = 0, busy = false, scope = admin ? 'active' : 'used', users = [];
    function close() { clearTimeout(timer); generation++; currentDialog.close(); currentDialog.remove(); opener?.focus({preventScroll: true}); }
    currentDialog.querySelector('header button').onclick = close;
    currentDialog.addEventListener('cancel', event => { event.preventDefault(); close(); });
    currentDialog.addEventListener('keydown', event => { if (event.key === 'Escape') { event.preventDefault(); close(); } });
    currentDialog.addEventListener('click', event => { if (event.target === currentDialog) { const r = currentDialog.getBoundingClientRect(); if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) close(); } });
    currentDialog.querySelector('.ed-client-own').onclick = () => { if (maySwitch()) navigate(''); else message.textContent = 'Сначала сохраните текущие изменения или дождитесь сохранения.'; };
    async function choose(user) {
      if (busy) return;
      if(app==='account'&&!user.email){message.textContent='У клиента не указан email для входа в кабинет.';return;}
      if (!maySwitch()) { message.textContent = 'Сначала сохраните текущие изменения или дождитесь сохранения.'; return; }
      if (admin) { navigate(user.user_id); return; }
      busy = true; message.textContent = 'Открываю…';
      try {
        if (app !== 'recipes' && app !== 'account') await ensureState(app, user.user_id);
        // Inputs may have changed while the state request was running.
        if (!currentDialog.open) return;
        if (maySwitch()) navigate(user.user_id); else message.textContent = 'Сначала дождитесь сохранения текущих изменений.';
      } catch (error) { message.textContent = error.message; }
      finally { busy = false; }
    }
    function displayName(user) {
      const name = (user.display_name || '').trim();
      return /\p{L}/u.test(name) ? name : user.email || name || 'Без имени';
    }
    function renderRows() {
      list.replaceChildren();
      users.sort((a,b) => Number(favorites.has(b.user_id))-Number(favorites.has(a.user_id)) || (Date.parse(b.last_opened_at)||0)-(Date.parse(a.last_opened_at)||0));
      favoritesToggle.setAttribute('aria-expanded', String(favoritesExpanded));
      const favoriteList = document.createElement('div'); favoriteList.id = 'ed-client-favorites'; favoriteList.hidden = !favoritesExpanded;
      list.append(favoriteList);
      let regularHeading = false;
      for (const user of users) {
        const favorite = favorites.has(user.user_id);
        if (!favorite && !regularHeading) { const heading = document.createElement('h3'); heading.className = 'ed-client-group'; heading.textContent = scope === 'all' ? 'Результаты поиска' : 'Пользовались приложением'; list.append(heading); regularHeading = true; }
        const item = document.createElement('div'); item.className = 'ed-client-item'; item.dataset.userId = user.user_id;
        const row = document.createElement('button'); row.type = 'button'; row.className = 'ed-client-row'; row.setAttribute('aria-current', String(user.user_id === identity.user_id));
        const name = document.createElement('strong'), email = document.createElement('small'), activity = document.createElement('small');
        const line = document.createElement('span'); line.className = 'ed-client-identity';
        name.textContent = displayName(user); email.textContent = user.email; line.append(name);
        if (user.email && name.textContent !== user.email) line.append(email); else name.style.maxWidth = '100%';
        row.append(line); row.title = [...new Set([name.textContent,user.email].filter(Boolean))].join(' · ');
        activity.className = 'ed-client-activity';
        activity.textContent = user.has_opened_app ? (admin ? 'Активность' : 'Открывал') + (user.last_opened_at ? ' · ' + new Date(user.last_opened_at).toLocaleDateString('ru-RU') : '') : admin ? 'Нет активности' : 'Ещё не открывал';
        row.append(activity); row.onclick = () => choose(user);
        const star = document.createElement('button'); star.type = 'button'; star.className = 'ed-client-favorite'; star.textContent = favorite ? '★' : '☆'; star.setAttribute('aria-pressed', String(favorite));
        star.title = (favorite ? 'Убрать из избранного: ' : 'Добавить в избранное: ') + displayName(user); star.setAttribute('aria-label', star.title);
        star.onclick = () => {
          const next = new Set(favorites);
          if (next.has(user.user_id)) next.delete(user.user_id); else if (next.size < 100) next.add(user.user_id); else { message.textContent = 'В избранном уже 100 клиентов.'; return; }
          try { localStorage.setItem(favoriteKey, JSON.stringify([...next])); } catch { message.textContent = 'Браузер не разрешил сохранить избранное.'; return; }
          if (next.has(user.user_id)) favoritesExpanded = true;
          favorites = next; renderRows(); draw(false, true);
        };
        item.append(row, star); (favorite ? favoriteList : list).append(item);
      }
      if (!favoriteList.childElementCount) { const empty = document.createElement('p'); empty.className = 'ed-client-message'; empty.textContent = 'Пока нет избранных в этом списке.'; favoriteList.append(empty); }
    }
    async function draw(append = false, preserve = false) {
      const request = ++generation;
      if (!append) { offset = 0; if (!preserve) { users = []; list.replaceChildren(); } }
      if (scope === 'all' && !input.value.trim()) { users = []; list.replaceChildren(); more.hidden = true; message.textContent = 'Введите имя или email для поиска по всей базе.'; return; }
      more.hidden = true; message.textContent = 'Загружаю…';
      try {
        const params = new URLSearchParams({q:input.value.trim(), offset:String(offset), app_code:app, scope});
        for (const id of favorites) params.append('favorite_ids', id);
        const endpoint = admin ? '/admin/api/apps/client-directory' : '/api/apps/manager/users';
        const data = await api(endpoint + '?' + params);
        if (generation !== request || !currentDialog.open) return;
        users = [...new Map([...(append ? users : []), ...data.users].map(user => [user.user_id, user])).values()]; renderRows();
        offset += data.users.length; more.hidden = !data.more; message.textContent = users.length ? '' : scope === 'all' ? 'Ничего не найдено' : 'Пока нет пользователей. Найдите клиента во вкладке «Все клиенты».';
      } catch (error) { if (request === generation && currentDialog.open) message.textContent = error.message; }
    }
    for (const button of currentDialog.querySelectorAll('[data-scope]')) {
      button.setAttribute('aria-pressed', String(button.dataset.scope === scope));
      if (admin && button.dataset.scope === 'used') button.textContent = 'Была активность';
      button.onclick = () => {
        generation++; clearTimeout(timer); scope = button.dataset.scope;
        currentDialog.querySelectorAll('[data-scope]').forEach(tab => tab.setAttribute('aria-pressed', String(tab === button)));
        draw();
      };
    }
    input.oninput = () => { generation++; clearTimeout(timer); timer = setTimeout(() => draw(), 220); };
    more.onclick = () => draw(true);
    currentDialog.showModal();
    const rect = button.getBoundingClientRect();
    currentDialog.style.left = Math.max(12, Math.min(rect.left, innerWidth - currentDialog.offsetWidth - 12)) + 'px';
    if (rect.bottom < innerHeight / 2) currentDialog.style.top = Math.max(12, rect.bottom + 6) + 'px';
    else { currentDialog.style.bottom = Math.max(12, innerHeight - rect.top + 6) + 'px'; currentDialog.style.top = 'auto'; }
    input.focus(); await draw();
  }
  const observer = new MutationObserver(decorate);
  if (!admin) observer.observe(root, {childList: true, subtree: true});
  decorate();
}
