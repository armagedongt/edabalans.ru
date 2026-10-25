const names = {telegram: 'Telegram', max: 'MAX'};
const escape = value => String(value || '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

// The course and workout journal use the same account-link controls.
export function render(host, summary, links, onPreferred, onConnect) {
  host.innerHTML = '<div class="messenger-popup-actions">' + Object.keys(names).map(platform => {
    const state = summary.linked[platform];
    if (state.linked) return '<span>✓ ' + names[platform] + (state.preferred ? ' — основной' : ' подключён') + '</span>';
    return links[platform] ? '<a data-platform="'+platform+'" href="' + escape(links[platform]) + '" target="_blank" rel="noopener">Подключить ' + names[platform] + '</a>' : '<span>' + names[platform] + ': ссылка недоступна</span>';
  }).join('') + '</div>' + (summary.require_preferred ? '<p>Выберите основной мессенджер: ' + Object.keys(names).map(platform => '<button type="button" data-preferred="'+platform+'">'+names[platform]+'</button>').join(' ') + '</p>' : '');
  host.querySelectorAll('[data-preferred]').forEach(button => {
    button.onclick = () => onPreferred(button.dataset.preferred);
  });
  if (onConnect) host.querySelectorAll('[data-platform]').forEach(link => {
    link.onclick = event => { event.preventDefault(); onConnect(link.dataset.platform); };
  });
}

export async function mount(host, api) {
  let busy = false;
  const links = {}, expires = {};
  const controller = new AbortController();
  async function refresh() {
    if (!host.isConnected) { controller.abort(); return; }
    if (busy) return;
    busy = true;
    host.textContent = 'Проверяю подключённый мессенджер…';
    try {
      const summary = await api.state();
      if (!host.isConnected) return;
      api.onState(summary);
      if (summary.destination) {
        const platform = summary.destination;
        host.innerHTML = '<p>К этому аккаунту подключён <a href="'+escape(summary.bot_links[platform])+'" target="_blank" rel="noopener">'+names[platform]+'</a>. Отправить туда план?</p>';
      } else {
        const failures = [];
        await Promise.all(Object.keys(names).filter(platform => !summary.linked[platform].linked && (!links[platform] || Date.now() >= expires[platform])).map(async platform => {
          try {
            const link = await api.link(platform);
            links[platform] = link.deep_link;
            expires[platform] = Date.parse(link.expires_at);
          }
          catch (error) { failures.push(error.message); }
        }));
        if (!host.isConnected) return;
        host.innerHTML = '<p>'+(summary.require_link?'К этому аккаунту ещё не подключён мессенджер. Подключите Telegram или MAX.':'Выберите основной мессенджер для отправки.')+'</p><div data-connect></div><p data-link-error></p>';
        render(host.querySelector('[data-connect]'), summary, links, async platform => {
          try { await api.prefer(platform); await refresh(); }
          catch (error) { host.querySelector('[data-link-error]').textContent = error.message; }
        });
        host.querySelector('[data-link-error]').textContent = failures.join(' ');
      }
    } catch (error) {
      if (!host.isConnected) return;
      host.textContent = error.message;
      api.onState({destination:null});
    } finally {
      busy = false;
      if (host.isConnected) {
        const button = document.createElement('button');
        button.type = 'button'; button.className = 'st-modal-btn'; button.textContent = 'Проверить подключение'; button.onclick = refresh;
        host.appendChild(button);
      }
    }
  }
  window.addEventListener('focus', refresh, {signal:controller.signal});
  await refresh();
  return () => controller.abort();
}
