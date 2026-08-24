(function () {
  "use strict";

  const main = document.querySelector("main.intensive-page");
  const day = location.pathname.match(/\/(day-[1-4])(?:\.html)?\/?$/)?.[1];
  const editMode = new URLSearchParams(location.search).get("edit") === "1";
  if (!main || !day || !editMode) return;

  const storageKey = `edabalans-intensive-${day}`;
  const saved = localStorage.getItem(storageKey);
  if (saved) main.innerHTML = saved;

  document.documentElement.classList.add("intensive-editor-preview");
  main.contentEditable = "true";
  main.spellcheck = true;
  main.querySelectorAll("h1, h2, h3, p, li, a, span, strong").forEach((element) => {
    element.contentEditable = "true";
    element.spellcheck = true;
  });
  main.addEventListener("click", (event) => {
    if (event.target.closest("a")) event.preventDefault();
  });

  const toolbar = document.createElement("div");
  toolbar.className = "intensive-local-toolbar";
  toolbar.contentEditable = "false";
  toolbar.innerHTML = `
    <strong>Редактирование дня</strong>
    <span id="intensive-save-status">Правьте текст прямо на странице</span>
    <button id="intensive-save" type="button">Сохранить черновик</button>
    <button id="intensive-reset" type="button">Сбросить</button>
    <a href="/intensive/${day}">Открыть без редактора</a>`;
  document.body.append(toolbar);

  const status = toolbar.querySelector("#intensive-save-status");
  toolbar.querySelector("#intensive-save").addEventListener("click", () => {
    localStorage.setItem(storageKey, main.innerHTML);
    status.textContent = "Сохранено в этом браузере";
  });
  toolbar.querySelector("#intensive-reset").addEventListener("click", () => {
    if (!confirm("Удалить локальный черновик этого дня?")) return;
    localStorage.removeItem(storageKey);
    location.reload();
  });
}());
