const supported = new Set(['account', 'strength', 'dqs', 'metabolism', 'recipes']);
const appPaths = {account:'/lk', strength: '/training', dqs: '/dqs', metabolism: '/metabolism', recipes: '/recipes'};

export function mount(root, app, context, host) {
  if (!supported.has(app) || !context.can_manage || root.dataset.clientPicker) return;
  root.dataset.clientPicker = 'true';
  if (!document.getElementById('app-client-picker-style')) {
    const style = document.createElement('style');
    style.id = 'app-client-picker-style';
    style.textContent = `
      .ed-client-button{display:inline-flex;align-items:center;gap:5px;max-width:100%;min-height:32px;padding:2px 6px;border:1px solid var(--ed-app-line,#e7e7ef);border-radius:8px;background:#fff;color:inherit;font:inherit;cursor:pointer;text-align:left}
      .ed-client-button span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0}.ed-client-button:after{content:'▾';flex:none;color:var(--ed-app-accent,#6f3de8)}
      .ed-client-button:focus-visible,.ed-client-popup :focus-visible{outline:2px solid #6f3de8;outline-offset:2px}
      .ed-client-recipe{padding:0 12px 8px;font-size:13px;color:#62677a}
      .ed-client-popup{box-sizing:border-box;position:fixed;margin:0;padding:12px;width:min(400px,calc(100vw - 24px));max-height:65dvh;border:1px solid #e7e7ef;border-radius:var(--ed-app-radius-large,16px);background:#fff;color:#17172b;box-shadow:0 10px 35px #17172b22;font:14px/1.4 var(--ed-font-body,Manrope,Arial,sans-serif)}
      .ed-client-popup[open]{display:flex;flex-direction:column;gap:8px}.ed-client-popup::backdrop{background:transparent}.ed-client-popup header{display:flex;justify-content:space-between;align-items:center;gap:10px}
      .ed-client-popup button,.ed-client-popup input{font:inherit}.ed-client-popup button{cursor:pointer}.ed-client-popup header button{border:0;background:transparent;font-size:22px;min-width:36px;min-height:36px}
      .ed-client-popup input{box-sizing:border-box;width:100%;min-height:40px;padding:8px;border:1px solid #d8d8e4;border-radius:8px}.ed-client-list{overflow:auto;min-height:40px;overscroll-behavior:contain}
      .ed-client-row{display:block;width:100%;padding:10px 8px;text-align:left;border:0;border-bottom:1px solid #efeff5;background:#fff;color:#17172b}.ed-client-row:hover,.ed-client-row[aria-current=true]{background:#f5f1ff}.ed-client-row strong,.ed-client-row small{display:block;overflow-wrap:anywhere}.ed-client-row small{color:#62677a}.ed-client-more,.ed-client-own{min-height:38px;border:1px solid #e7e7ef;background:#fff;color:#6f3de8;border-radius:8px}.ed-client-message{margin:0;color:#62677a;font-size:13px;overflow-wrap:anywhere}
      .ed-client-scopes{display:flex;flex-wrap:wrap;gap:4px}.ed-client-scopes button{flex:1;min-height:38px;padding:5px;border:1px solid var(--ed-app-line,#e7e7ef);border-radius:8px;background:#fff;color:inherit;font-size:12px}.ed-client-scopes button[aria-pressed=true]{background:var(--ed-app-accent-soft,#f5f1ff);border-color:var(--ed-app-accent,#6f3de8)}
      .ed-client-item{display:grid;grid-template-columns:minmax(0,1fr) 38px;align-items:stretch;border-bottom:1px solid #efeff5}.ed-client-item .ed-client-row{border-bottom:0;min-width:0}.ed-client-favorite{border:0;background:#fff;color:var(--ed-app-accent,#6f3de8);font-size:22px;min-height:40px;padding:0}.ed-client-group{margin:8px 0 3px;font-size:12px;font-weight:700;color:#62677a}.ed-client-row .ed-client-activity{margin-top:4px;font-size:11px;color:#62677a}
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
  let dialog, opener;
  function decorate() {
    if (!root.isConnected) { observer.disconnect(); dialog?.remove(); return; }
    if (app === 'account') {
      const button = root.querySelector('[data-account-profile]');
      if (button && !button.dataset.clientPickerBound) {
        button.dataset.clientPickerBound = 'true';
        button.setAttribute('aria-haspopup','dialog');
        button.removeAttribute('aria-expanded');
        button.onclick = () => open(button);
      }
      return;
    }
    let places = [...root.querySelectorAll(app === 'strength' ? '.st-top-email' : app === 'dqs' ? '.dqs-foot-account' : app === 'metabolism' ? '[data-account-name]' : '.ed-client-recipe')];
    if (app === 'recipes' && !places.length && root.querySelector('.recipe-shell')) {
      const place = document.createElement('div'); place.className = 'ed-client-recipe';
      root.querySelector('.recipe-shell').prepend(place); places = [place];
    }
    for (const place of places) {
      if (place.querySelector('.ed-client-button')) continue;
      const button = document.createElement('button'); button.type = 'button'; button.className = 'ed-client-button';
      button.setAttribute('aria-label', 'Выбрать клиента'); button.setAttribute('aria-haspopup', 'dialog');
      const label = document.createElement('span'); label.textContent = identity.email || identity.display_name || 'Выбрать клиента'; button.append(label);
      button.title = [identity.display_name, identity.email].filter(Boolean).join(' · ');
      if (app === 'dqs') {
        for (const node of [...place.childNodes]) if (node.nodeType === Node.TEXT_NODE && node.textContent.includes('@')) node.textContent = ' · ';
        place.prepend(button);
      } else place.replaceChildren(button);
      button.onclick = () => open(button);
    }
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
    const check = window.EdabalansAppContext?.canSwitchClient;
    return !check || check();
  }
  function navigate(userId) {
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
    dialog.innerHTML = '<header><strong>Выбрать клиента</strong><button type="button" aria-label="Закрыть">×</button></header><div class="ed-client-scopes" role="group" aria-label="Показать клиентов"><button type="button" data-scope="used" aria-pressed="true">Уже заходили</button><button type="button" data-scope="active" aria-pressed="false">Активные · 30 дней</button><button type="button" data-scope="all" aria-pressed="false">Все клиенты</button></div><input type="search" aria-label="Имя, фамилия или email" placeholder="Имя, фамилия или email" autocomplete="off"><button class="ed-client-own" type="button">Мои данные</button><p class="ed-client-message" role="status"></p><div class="ed-client-list"></div><button class="ed-client-more" type="button" hidden>Показать ещё</button>';
    document.body.append(dialog);
    if(app==='account'){
      dialog.querySelector('.ed-client-own').textContent='Мой кабинет';
      const logout=document.createElement('button');logout.type='button';logout.className='ed-client-own';logout.textContent='Выйти';logout.onclick=()=>root.querySelector('.account-logout').click();dialog.append(logout);
    }
    const currentDialog = dialog, list = dialog.querySelector('.ed-client-list'), input = dialog.querySelector('input'), message = dialog.querySelector('[role=status]'), more = dialog.querySelector('.ed-client-more');
    let generation = 0, timer, offset = 0, busy = false, scope = 'used', users = [];
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
      busy = true; message.textContent = 'Открываю…';
      try {
        if (app !== 'recipes' && app !== 'account') {
          const base = '/admin/api/apps/' + app + '/users/' + encodeURIComponent(user.user_id);
          const detail = await api(base);
          if (!detail.has_state) await api(base + '/open', {method: 'POST'});
        }
        // Inputs may have changed while the state request was running.
        if (!currentDialog.open) return;
        if (maySwitch()) navigate(user.user_id); else message.textContent = 'Сначала дождитесь сохранения текущих изменений.';
      } catch (error) { message.textContent = error.message; }
      finally { busy = false; }
    }
    function displayName(user) {
      const name = (user.display_name || '').trim();
      return /\p{L}/u.test(name) ? name : user.email;
    }
    function renderRows() {
      list.replaceChildren();
      users.sort((a,b) => Number(favorites.has(b.user_id))-Number(favorites.has(a.user_id)) || (Date.parse(b.last_opened_at)||0)-(Date.parse(a.last_opened_at)||0));
      let group;
      for (const user of users) {
        const favorite = favorites.has(user.user_id), nextGroup = favorite ? 'Избранное' : scope === 'all' ? 'Результаты поиска' : 'Пользовались приложением';
        if (group !== nextGroup) { const heading = document.createElement('h3'); heading.className = 'ed-client-group'; heading.textContent = nextGroup; list.append(heading); group = nextGroup; }
        const item = document.createElement('div'); item.className = 'ed-client-item'; item.dataset.userId = user.user_id;
        const row = document.createElement('button'); row.type = 'button'; row.className = 'ed-client-row'; row.setAttribute('aria-current', String(user.user_id === identity.user_id));
        const name = document.createElement('strong'), email = document.createElement('small'), activity = document.createElement('small');
        name.textContent = displayName(user); email.textContent = user.email; row.append(name);
        if (name.textContent !== user.email) row.append(email);
        activity.className = 'ed-client-activity';
        activity.textContent = user.has_opened_app ? 'Открывал' + (user.last_opened_at ? ' · ' + new Date(user.last_opened_at).toLocaleDateString('ru-RU') : '') : 'Ещё не открывал';
        row.append(activity); row.onclick = () => choose(user);
        const star = document.createElement('button'); star.type = 'button'; star.className = 'ed-client-favorite'; star.textContent = favorite ? '★' : '☆'; star.setAttribute('aria-pressed', String(favorite));
        star.title = (favorite ? 'Убрать из избранного: ' : 'Добавить в избранное: ') + displayName(user); star.setAttribute('aria-label', star.title);
        star.onclick = () => {
          const next = new Set(favorites);
          if (next.has(user.user_id)) next.delete(user.user_id); else if (next.size < 100) next.add(user.user_id); else { message.textContent = 'В избранном уже 100 клиентов.'; return; }
          try { localStorage.setItem(favoriteKey, JSON.stringify([...next])); } catch { message.textContent = 'Браузер не разрешил сохранить избранное.'; return; }
          favorites = next; renderRows(); draw(false, true);
        };
        item.append(row, star); list.append(item);
      }
    }
    async function draw(append = false, preserve = false) {
      const request = ++generation;
      if (!append) { offset = 0; if (!preserve) { users = []; list.replaceChildren(); } }
      if (scope === 'all' && !input.value.trim()) { users = []; list.replaceChildren(); more.hidden = true; message.textContent = 'Введите имя или email для поиска по всей базе.'; return; }
      more.hidden = true; message.textContent = 'Загружаю…';
      try {
        const params = new URLSearchParams({q:input.value.trim(), offset:String(offset), app_code:app, scope});
        for (const id of favorites) params.append('favorite_ids', id);
        const data = await api('/api/apps/manager/users?' + params);
        if (generation !== request || !currentDialog.open) return;
        users = [...new Map([...(append ? users : []), ...data.users].map(user => [user.user_id, user])).values()]; renderRows();
        offset += data.users.length; more.hidden = !data.more; message.textContent = users.length ? '' : scope === 'all' ? 'Ничего не найдено' : 'Пока нет пользователей. Найдите клиента во вкладке «Все клиенты».';
      } catch (error) { if (request === generation && currentDialog.open) message.textContent = error.message; }
    }
    for (const button of currentDialog.querySelectorAll('[data-scope]')) button.onclick = () => {
      generation++; clearTimeout(timer); scope = button.dataset.scope;
      currentDialog.querySelectorAll('[data-scope]').forEach(tab => tab.setAttribute('aria-pressed', String(tab === button)));
      draw();
    };
    input.oninput = () => { generation++; clearTimeout(timer); timer = setTimeout(() => draw(), 220); };
    more.onclick = () => draw(true);
    currentDialog.showModal();
    const rect = button.getBoundingClientRect();
    currentDialog.style.left = Math.max(12, Math.min(rect.left, innerWidth - currentDialog.offsetWidth - 12)) + 'px';
    if (rect.bottom < innerHeight / 2) currentDialog.style.top = Math.max(12, rect.bottom + 6) + 'px';
    else { currentDialog.style.bottom = Math.max(12, innerHeight - rect.top + 6) + 'px'; currentDialog.style.top = 'auto'; }
    input.focus(); await draw();
  }
  const observer = new MutationObserver(decorate); observer.observe(root, {childList: true, subtree: true}); decorate();
}
