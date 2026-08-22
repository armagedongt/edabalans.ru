const state = { items: [], scenarios: [], selected: null };

const escapeHtml = value => String(value ?? '')
  .replaceAll('&', '&amp;')
  .replaceAll('<', '&lt;')
  .replaceAll('>', '&gt;')
  .replaceAll('"', '&quot;')
  .replaceAll("'", '&#039;');

function telegramMarkup(source) {
  let value = escapeHtml(source || '');
  value = value
    .replace(/&lt;br\s*\/?&gt;/gi, '\n')
    .replace(/&lt;blockquote&gt;([\s\S]*?)&lt;\/blockquote&gt;/gi, '<blockquote>$1</blockquote>')
    .replace(/&lt;(?:b|strong)&gt;([\s\S]*?)&lt;\/(?:b|strong)&gt;/gi, '<strong>$1</strong>')
    .replace(/&lt;(?:i|em)&gt;([\s\S]*?)&lt;\/(?:i|em)&gt;/gi, '<em>$1</em>')
    .replace(/&lt;u&gt;([\s\S]*?)&lt;\/u&gt;/gi, '<u>$1</u>')
    .replace(/&lt;(?:s|del)&gt;([\s\S]*?)&lt;\/(?:s|del)&gt;/gi, '<s>$1</s>')
    .replace(/&lt;a\s+href=&quot;(https?:\/\/[^&]+?)&quot;&gt;([\s\S]*?)&lt;\/a&gt;/gi, '<a href="$1" target="_blank" rel="noreferrer">$2</a>')
    .replace(/\[([^\]]+)]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noreferrer">$1</a>')
    .replace(/(^|[^\p{L}\p{N}_*])\*([^*\n]+)\*(?=$|[^\p{L}\p{N}_*])/gu, '$1<strong>$2</strong>')
    .replace(/(^|[^\p{L}\p{N}_])_([^_\n]+)_(?=$|[^\p{L}\p{N}_])/gu, '$1<em>$2</em>')
    .replace(/(^|[^\p{L}\p{N}_])~([^~\n]+)~(?=$|[^\p{L}\p{N}_])/gu, '$1<s>$2</s>');
  return value;
}

function mediaLabel(kind) {
  return ({ video: 'ВИДЕО', audio: 'АУДИО', photo: 'ФОТО', image: 'ФОТО', document: 'ФАЙЛ', voice: 'ГОЛОСОВОЕ' })[kind] || 'МЕДИАФАЙЛ';
}

async function getJson(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

async function loadSummary() {
  const summary = await getJson('/api/summary');
  document.querySelector('#stat-archive').textContent = summary.archive_items;
  document.querySelector('#stat-media').textContent = summary.media_assets;
  document.querySelector('#stat-copies').textContent = summary.working_copies;
}

async function loadArchive() {
  const q = document.querySelector('#search').value.trim();
  const media = document.querySelector('#media-filter').value;
  const scenario = document.querySelector('#scenario-filter').value;
  const params = new URLSearchParams({ q, media, scenario });
  state.items = await getJson(`/api/archive?${params}`);
  const selectedScenario = state.scenarios.find(item => String(item.id) === scenario);
  document.querySelector('#scenario-path').textContent = selectedScenario
    ? `${selectedScenario.name} · ${selectedScenario.post_count} постов в сценарии`
    : `Все сценарии · ${state.scenarios.length}`;
  renderCatalog();
}

async function loadScenarios() {
  state.scenarios = await getJson('/api/scenarios');
  const select = document.querySelector('#scenario-filter');
  select.innerHTML = '<option value="">Все сценарии</option>' + state.scenarios.map(scenario =>
    `<option value="${escapeHtml(scenario.id)}">${escapeHtml(scenario.name)} · ${scenario.post_count}</option>`
  ).join('');
}

function renderCatalog() {
  const catalog = document.querySelector('#catalog');
  document.querySelector('#result-count').textContent = state.items.length;
  if (!state.items.length) {
    catalog.innerHTML = '<div class="empty-list">Ничего не найдено. Попробуйте другую фразу.</div>';
    return;
  }
  catalog.innerHTML = state.items.map(item => `
    <button class="catalog-item ${state.selected?.id === item.id ? 'selected' : ''}" data-id="${item.id}" type="button">
      <div>
        <h3>${escapeHtml(item.title)}</h3>
        <p>${escapeHtml(item.plain_text || 'Без текстовой подписи')}</p>
        <div class="source-tags">
          <span class="scenario-tag">${escapeHtml(item.scenario_name || 'Сценарий без названия')}</span>
          <span class="block-tag">блок ${escapeHtml(item.source_block_id)}</span>
        </div>
      </div>
      <div>
        ${item.media_kind ? `<span class="media-tag">${mediaLabel(item.media_kind)}</span>` : ''}
        ${item.copy_count ? `<span class="copy-tag">копий: ${item.copy_count}</span>` : ''}
      </div>
    </button>
  `).join('');
  catalog.querySelectorAll('.catalog-item').forEach(button => button.addEventListener('click', () => selectItem(button.dataset.id)));
}

function selectItem(id) {
  state.selected = state.items.find(item => item.id === id);
  renderCatalog();
  const bubble = document.querySelector('#message-bubble');
  bubble.classList.remove('empty');
  bubble.innerHTML = `${state.selected.media_kind ? `<div class="media-placeholder">[ ${mediaLabel(state.selected.media_kind)} ]</div>` : ''}${telegramMarkup(state.selected.source_text) || '<span class="empty">Без подписи</span>'}`;
  document.querySelector('#preview-origin').textContent = `${state.selected.scenario_name || 'Сценарий без названия'} · блок ${state.selected.source_block_id}`;
  document.querySelector('#copy-button').disabled = false;
}

async function copySelected() {
  if (!state.selected) return;
  const button = document.querySelector('#copy-button');
  button.disabled = true;
  button.textContent = 'Копирую…';
  try {
    await getJson(`/api/archive/${state.selected.id}/copy`, { method: 'POST' });
    button.textContent = 'Рабочая копия создана';
    await Promise.all([loadSummary(), loadArchive()]);
  } catch (error) {
    button.textContent = 'Не удалось скопировать';
  } finally {
    setTimeout(() => {
      button.textContent = 'Создать рабочую копию';
      button.disabled = false;
    }, 1200);
  }
}

async function loadSequence() {
  const rows = await getJson('/api/sequence');
  const flow = document.querySelector('#sequence-flow');
  flow.innerHTML = rows.map(row => {
    if (row.kind === 'message') return `
      <article class="flow-step message">
        <header><h3><span class="step-icon">✉</span>${escapeHtml(row.label || row.content_title)}</h3><span class="step-kind">Пост ${row.position}</span></header>
        <p class="step-preview">${escapeHtml((row.body_source || '').replace(/<[^>]+>/g, '').replaceAll('*', '').slice(0, 210))}</p>
      </article>`;
    if (row.kind === 'delay') return `
      <article class="flow-step delay">
        <header><h3><span class="step-icon">◷</span>${escapeHtml(row.label)}</h3><span class="step-kind">задержка</span></header>
      </article>`;
    if (row.kind === 'condition') return `
      <article class="flow-step condition">
        <header><h3><span class="step-icon">?</span>${escapeHtml(row.label)}</h3><span class="step-kind">условие</span></header>
        <div class="branches"><span class="branch">Да → после покупки</span><span class="branch">Нет → продолжить прогрев</span></div>
      </article>`;
    return '';
  }).join('');
}

function activatePage(page) {
  document.querySelectorAll('.page').forEach(element => element.classList.toggle('active', element.id === `${page}-page`));
  document.querySelectorAll('.nav-item[data-page]').forEach(element => element.classList.toggle('active', element.dataset.page === page));
  document.querySelector('#page-title').textContent = page === 'library' ? 'Библиотека сообщений' : 'Редактор цепочки';
}

let searchTimer;
document.querySelector('#search').addEventListener('input', () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(loadArchive, 250);
});
document.querySelector('#media-filter').addEventListener('change', loadArchive);
document.querySelector('#scenario-filter').addEventListener('change', loadArchive);
document.querySelector('#copy-button').addEventListener('click', copySelected);
document.querySelectorAll('.nav-item[data-page]').forEach(button => button.addEventListener('click', () => activatePage(button.dataset.page)));

Promise.all([loadSummary(), loadScenarios().then(loadArchive), loadSequence()]).catch(error => {
  document.querySelector('#catalog').innerHTML = `<div class="empty-list">Не удалось открыть базу: ${escapeHtml(error.message)}</div>`;
});
