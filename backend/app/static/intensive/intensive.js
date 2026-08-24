(function () {
  "use strict";

  const article = document.getElementById("intensive-content");
  const editButton = document.getElementById("intensive-edit");
  const day = article?.dataset.day;
  const editing = new URLSearchParams(location.search).get("edit") === "1";
  let version = 0;
  let savedRange = null;

  if (!article || !editButton || !/^day-[1-4]$/.test(day || "")) return;
  editButton.disabled = true;

  function loginUrl() {
    return `/admin?next=${encodeURIComponent(location.pathname + "?edit=1")}`;
  }

  async function getContent(admin) {
    const prefix = admin ? "/admin/api" : "/api";
    const response = await fetch(`${prefix}/intensive/${day}`, { credentials: "same-origin" });
    if (admin && response.status === 401) {
      location.replace(loginUrl());
      return null;
    }
    if (!response.ok) throw new Error("Не удалось загрузить страницу");
    return response.json();
  }

  async function start() {
    try {
      const content = await getContent(editing);
      if (!content) return;
      version = content.version;
      if (content.html) article.innerHTML = content.html;
      if (editing) {
        article.contentEditable = "true";
        article.spellcheck = true;
        editButton.textContent = "Сохранить и опубликовать";
        createToolbar();
        article.focus();
      }
      editButton.disabled = false;
    } catch (error) {
      editButton.disabled = false;
      if (editing) alert(error.message);
    }
  }

  function rememberSelection() {
    const selection = window.getSelection();
    if (!selection || !selection.rangeCount || !article.contains(selection.anchorNode)) return;
    savedRange = selection.getRangeAt(0).cloneRange();
  }

  function restoreSelection() {
    if (!savedRange) return;
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(savedRange);
  }

  function runCommand(command, value) {
    restoreSelection();
    document.execCommand(command, false, value || null);
    article.focus();
    rememberSelection();
  }

  function addLink() {
    const href = prompt("Вставьте ссылку");
    if (!href) return;
    runCommand("createLink", href.trim());
  }

  function addImage() {
    const src = prompt("Вставьте прямую HTTPS-ссылку на картинку");
    if (!src) return;
    let url;
    try {
      url = new URL(src.trim());
    } catch (_error) {
      alert("Нужна полная HTTPS-ссылка на картинку");
      return;
    }
    if (url.protocol !== "https:") {
      alert("Картинка должна открываться по HTTPS");
      return;
    }
    runCommand("insertImage", url.href);
  }

  function createToolbar() {
    const toolbar = document.createElement("div");
    toolbar.className = "editor-toolbar";
    toolbar.setAttribute("role", "toolbar");
    toolbar.setAttribute("aria-label", "Форматирование статьи");
    const tools = [
      ["Текст", "formatBlock", "p"],
      ["Заголовок", "formatBlock", "h2"],
      ["Важное", "formatBlock", "blockquote"],
      ["Акцент", "formatBlock", "aside"],
      ["Жирный", "bold"],
      ["Курсив", "italic"],
      ["• Список", "insertUnorderedList"],
      ["1. Список", "insertOrderedList"],
      ["Ссылка", "link"],
      ["Картинка", "image"],
    ];
    tools.forEach(([label, command, value]) => {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = label;
      button.addEventListener("mousedown", (event) => event.preventDefault());
      button.addEventListener("click", () => {
        if (command === "link") addLink();
        else if (command === "image") addImage();
        else runCommand(command, value);
      });
      toolbar.appendChild(button);
    });
    toolbar.appendChild(editButton);
    document.body.prepend(toolbar);
    document.addEventListener("selectionchange", rememberSelection);
  }

  editButton.addEventListener("click", async () => {
    if (!editing) {
      location.assign(`${location.pathname}?edit=1`);
      return;
    }
    editButton.disabled = true;
    editButton.textContent = "Публикую…";
    try {
      const response = await fetch(`/admin/api/intensive/${day}`, {
        method: "PUT",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ html: article.innerHTML, version })
      });
      if (response.status === 401) {
        location.replace(loginUrl());
        return;
      }
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.detail || "Не удалось сохранить страницу");
      location.replace(location.pathname);
    } catch (error) {
      alert(error.message);
      editButton.disabled = false;
      editButton.textContent = "Сохранить и опубликовать";
    }
  });

  start();
}());
