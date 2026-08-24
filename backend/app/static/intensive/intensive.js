(function () {
  "use strict";

  const article = document.getElementById("intensive-content");
  const editButton = document.getElementById("intensive-edit");
  const day = article?.dataset.day;
  const editing = new URLSearchParams(location.search).get("edit") === "1";
  let version = 0;

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
        editButton.textContent = "Save";
        article.focus();
      }
      editButton.disabled = false;
    } catch (error) {
      editButton.disabled = false;
      if (editing) alert(error.message);
    }
  }

  editButton.addEventListener("click", async () => {
    if (!editing) {
      location.assign(`${location.pathname}?edit=1`);
      return;
    }
    editButton.disabled = true;
    editButton.textContent = "Saving…";
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
      editButton.textContent = "Save";
    }
  });

  start();
}());
