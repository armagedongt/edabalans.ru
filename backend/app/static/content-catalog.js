(() => {
  "use strict";
  const PAGE_SIZE = 10;
  const state = { mode: "catalog", offset: 0, page: null, selectedKey: null, group: null, itemId: null, dirty: false, saving: false, candidateSelection: new Set(), candidateSelectionKey: null };
  const el = (id) => document.getElementById(id);
  const list = el("group-list"), editor = el("editor"), empty = el("empty");

  async function api(url, options = {}) {
    const response = await fetch(url, { credentials: "same-origin", ...options });
    if (response.status === 401) { location.href = `/admin?next=${encodeURIComponent(location.pathname)}`; throw new Error("Нужен вход"); }
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || `Ошибка ${response.status}`);
    return payload;
  }
  function text(value) { return value == null ? "" : String(value); }
  function setStatus(message, error = false) { el("save-state").textContent = message; el("save-state").classList.toggle("error", error); }
  function markDirty() { state.dirty = true; el("save").disabled = false; setStatus("Есть несохранённые изменения"); }
  function canLeave() { return !state.dirty || confirm("Изменения не сохранены. Перейти без сохранения?"); }
  function queryString() {
    const params = new URLSearchParams({ offset: state.offset, limit: PAGE_SIZE });
    const values = { q: el("search").value.trim(), source: el("source").value, shape: el("shape").value, purpose: el("purpose").value, editorial_status: el("editorial-status").value };
    Object.entries(values).forEach(([key, value]) => { if (value) params.set(key, value); });
    return params;
  }
  function itemLabel(item, index) { return `${item.source_label} · ${item.variant_label || `версия ${index + 1}`}`; }
  function groupCard(group) {
    const button = document.createElement("button"); button.type = "button"; button.className = "group-card";
    button.classList.toggle("active", group.key === state.selectedKey);
    const title = document.createElement("h2"); title.textContent = group.title;
    const snippet = document.createElement("p"); snippet.textContent = group.snippet || "";
    const meta = document.createElement("div"); meta.className = "group-meta";
    [...(group.sources || []), group.is_family ? `${group.manifestations} версии` : "единичный"].forEach((value) => { const span = document.createElement("span"); span.textContent = value; meta.append(span); });
    button.append(title, snippet, meta); button.onclick = () => selectGroup(group.key); return button;
  }
  function candidateCard(group) {
    const first = group.items[0] || {};
    return groupCard({ key: group.id, title: first.title || "Возможная семья", snippet: first.text || "", sources: [...new Set(group.items.map((item) => item.source_label))], is_family: true, manifestations: group.items.length });
  }
  async function loadSummary() {
    const value = await api("/admin/api/content/authoring/summary");
    el("summary").textContent = `${value.manifestations} материалов · ${value.families} семей · ${value.candidate_groups} кандидатов`;
  }
  async function loadPage() {
    list.innerHTML = '<div class="empty">Загрузка…</div>';
    const url = state.mode === "candidates" ? `/admin/api/content/authoring/candidates?offset=${state.offset}&limit=${PAGE_SIZE}` : `/admin/api/content/authoring/groups?${queryString()}`;
    state.page = await api(url);
    if (state.offset >= state.page.total && state.offset > 0) { state.offset = Math.max(0, state.offset - PAGE_SIZE); return loadPage(); }
    const pageGroups = state.page.groups || [];
    list.replaceChildren(...pageGroups.map(state.mode === "candidates" ? candidateCard : groupCard));
    const from = state.page.total ? state.offset + 1 : 0, to = Math.min(state.offset + PAGE_SIZE, state.page.total);
    el("page-label").textContent = `${from}–${to} из ${state.page.total}`;
    el("prev").disabled = state.offset === 0; el("next").disabled = to >= state.page.total;
    if (!pageGroups.length) { state.selectedKey = null; state.group = null; editor.hidden = true; empty.hidden = false; empty.textContent = "Ничего не найдено"; return; }
    const keys = pageGroups.map((row) => state.mode === "candidates" ? row.id : row.key);
    if (!keys.includes(state.selectedKey)) state.selectedKey = keys[0];
    await selectGroup(state.selectedKey, false);
    renderListSelection();
  }
  function renderListSelection() { list.querySelectorAll(".group-card").forEach((button, index) => { const row = state.page.groups[index]; const active = (state.mode === "candidates" ? row.id : row.key) === state.selectedKey; button.classList.toggle("active", active); if (active) button.setAttribute("aria-current", "true"); else button.removeAttribute("aria-current"); }); }
  async function selectGroup(key, check = true) {
    if (check && !canLeave()) return;
    state.dirty = false; state.selectedKey = key; renderListSelection();
    if (state.mode === "candidates") {
      state.group = state.page.groups.find((row) => row.id === key);
      if (state.candidateSelectionKey !== key) {
        state.candidateSelectionKey = key;
        state.candidateSelection = new Set(state.group.items.map((item) => item.id));
      }
    }
    else state.group = await api(`/admin/api/content/authoring/groups/${encodeURIComponent(key)}`);
    const preferredStatus = state.mode === "catalog" ? el("editorial-status").value : "active";
    state.itemId = state.group.items.find((item) => preferredStatus !== "all" && item.editorial_status === preferredStatus)?.id || state.group.items.find((item) => item.editorial_status === "active")?.id || state.group.items[0]?.id;
    renderEditor();
  }
  function topLink(label, href) { const a = document.createElement("a"); a.href = href; a.target = "_blank"; a.rel = "noopener"; a.textContent = label; return a; }
  function renderEditor() {
    const items = state.group?.items || [], item = items.find((row) => row.id === state.itemId) || items[0];
    if (!item) { editor.hidden = true; empty.hidden = false; return; }
    state.itemId = item.id; editor.hidden = false; empty.hidden = true; state.dirty = false;
    const top = el("top-links"); top.replaceChildren();
    if (/^https?:\/\//.test(item.canonical_url || "")) top.append(topLink("Открыть оригинал ↗", item.canonical_url));
    (item.media || []).forEach((media, index) => {
      const href = media.source_url || media.preview_url;
      if (href) top.append(topLink(`Медиа ${index + 1} ↗`, href));
      else { const span = document.createElement("span"); const locator = media.metadata?.source_locator; span.textContent = locator ? `Медиа ${index + 1}: ${locator}` : `Медиа ${index + 1}: привязка сохранена`; top.append(span); }
    });
    if (!top.childNodes.length) { const span = document.createElement("span"); span.textContent = "Ссылка на источник или медиа не зафиксирована"; top.append(span); }
    const tabs = el("version-tabs"); tabs.replaceChildren();
    items.forEach((row, index) => { const button = document.createElement("button"); button.type = "button"; button.setAttribute("aria-pressed", row.id === item.id ? "true" : "false"); button.textContent = itemLabel(row, index); button.classList.toggle("active", row.id === item.id); button.classList.toggle("removed", row.editorial_status === "removed"); button.onclick = () => { if (row.id !== state.itemId && canLeave()) { state.itemId = row.id; renderEditor(); } }; tabs.append(button); });
    el("title").value = item.title; el("variant").value = item.variant_label || ""; el("text").value = item.text || "";
    el("removed-note").hidden = item.editorial_status !== "removed"; el("toggle-remove").textContent = item.editorial_status === "removed" ? "Вернуть эту версию" : "Убрать эту версию";
    el("save").disabled = true; setStatus("Изменений нет");
    const metadata = el("metadata"); metadata.innerHTML = "";
    const grid = document.createElement("div"); grid.className = "metadata-grid";
    const rows = [["Источник", item.source_label], ["ID", item.external_id], ["Редакция", item.revision], ["Назначение", item.purpose], ["Продажа", item.sales_level], ["Темы", (item.topics || []).join(", ") || "—"], ["Смыслы", (item.meanings || []).join(", ") || "—"], ["Функция", item.primary_function || "—"], ["Ключ каталога", item.catalog_key]];
    rows.forEach(([label, value]) => { const span = document.createElement("span"); span.textContent = label; const bold = document.createElement("b"); bold.textContent = text(value); grid.append(span, bold); }); metadata.append(grid);
    renderCandidatePanel();
  }
  function renderCandidatePanel() {
    const panel = el("candidate-panel"); panel.hidden = state.mode !== "candidates"; if (panel.hidden) return;
    const checks = el("candidate-checks"); checks.replaceChildren();
    state.group.items.forEach((item) => { const label = document.createElement("label"); label.className = "candidate-check"; const input = document.createElement("input"); input.type = "checkbox"; input.value = item.id; input.checked = state.candidateSelection.has(item.id); input.onchange = () => { if (input.checked) state.candidateSelection.add(item.id); else state.candidateSelection.delete(item.id); }; const span = document.createElement("span"); span.textContent = `${item.source_label} · ${item.title}`; label.append(input, span); checks.append(label); });
  }
  function currentItem() { return state.group.items.find((row) => row.id === state.itemId); }
  async function save() {
    if (state.saving || !state.dirty) return; state.saving = true; el("save").disabled = true; setStatus("Сохраняю…");
    const item = currentItem();
    try {
      const updated = await api(`/admin/api/content/authoring/items/${encodeURIComponent(item.id)}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ expected_revision: item.revision, title: el("title").value, text: el("text").value, variant_label: el("variant").value, editorial_status: item.editorial_status }) });
      const index = state.group.items.findIndex((row) => row.id === updated.id); state.group.items[index] = updated; state.dirty = false; setStatus(`Сохранено · редакция ${updated.revision}`);
      const statusFilter = el("editorial-status").value;
      if (state.mode === "catalog" && statusFilter !== "all" && updated.editorial_status !== statusFilter) {
        state.selectedKey = null;
        await loadPage();
      } else {
        renderEditor(); setStatus(`Сохранено · редакция ${updated.revision}`);
      }
      await loadSummary();
    } catch (error) { setStatus(`Не сохранено: ${error.message}`, true); el("save").disabled = false; }
    finally { state.saving = false; }
  }
  async function candidateDecision(action) {
    if (state.dirty) { setStatus("Сначала сохраните изменения в тексте", true); return; }
    const selected = [...state.candidateSelection];
    if (action === "merge" && selected.length < 2) { setStatus("Для семьи нужно выбрать хотя бы два материала", true); return; }
    try {
      setStatus("Сохраняю решение…"); await api("/admin/api/content/authoring/candidates/decision", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ candidate_id: state.group.id, pair_keys: state.group.pair_keys, action, selected_ids: selected }) }); state.selectedKey = null; state.candidateSelectionKey = null; state.candidateSelection.clear(); await Promise.all([loadPage(), loadSummary()]);
    } catch (error) { setStatus(`Решение не сохранено: ${error.message}`, true); }
  }
  ["title", "variant", "text"].forEach((id) => el(id).addEventListener("input", markDirty));
  el("toggle-remove").onclick = () => { const item = currentItem(); item.editorial_status = item.editorial_status === "removed" ? "active" : "removed"; el("removed-note").hidden = item.editorial_status !== "removed"; el("toggle-remove").textContent = item.editorial_status === "removed" ? "Вернуть эту версию" : "Убрать эту версию"; markDirty(); };
  el("save").onclick = save; el("merge-candidate").onclick = () => candidateDecision("merge"); el("reject-candidate").onclick = () => candidateDecision("reject");
  el("filters").onsubmit = (event) => { event.preventDefault(); if (!canLeave()) return; state.offset = 0; state.selectedKey = null; loadPage().catch(fail); };
  el("candidate-toggle").onclick = () => { if (!canLeave()) return; state.mode = state.mode === "catalog" ? "candidates" : "catalog"; state.offset = 0; state.selectedKey = null; el("candidate-toggle").classList.toggle("active", state.mode === "candidates"); el("candidate-toggle").setAttribute("aria-pressed", state.mode === "candidates" ? "true" : "false"); el("candidate-toggle").textContent = state.mode === "candidates" ? "← Вернуться ко всему каталогу" : "Возможные семьи"; el("filters").hidden = state.mode === "candidates"; loadPage().catch(fail); };
  el("prev").onclick = () => { if (canLeave()) { state.offset = Math.max(0, state.offset - PAGE_SIZE); state.selectedKey = null; loadPage().catch(fail); } };
  el("next").onclick = () => { if (canLeave()) { state.offset += PAGE_SIZE; state.selectedKey = null; loadPage().catch(fail); } };
  document.addEventListener("keydown", (event) => { if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") { event.preventDefault(); save(); } });
  window.addEventListener("beforeunload", (event) => { if (state.dirty) { event.preventDefault(); event.returnValue = ""; } });
  function fail(error) { empty.hidden = false; editor.hidden = true; empty.textContent = `Ошибка: ${error.message}`; }
  Promise.all([loadSummary(), loadPage()]).catch(fail);
})();
