(function () {
  "use strict";
  const form = document.getElementById("login-form");
  const errorBox = document.getElementById("login-error");
  const password = form.elements.password;
  const showPassword = document.getElementById("show-password");

  showPassword.addEventListener("click", () => {
    const visible = password.type === "text";
    password.type = visible ? "password" : "text";
    showPassword.textContent = visible ? "Показать" : "Скрыть";
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    errorBox.textContent = "";
    const submit = form.querySelector('[type="submit"]');
    submit.disabled = true;
    submit.textContent = "Входим…";
    try {
      const response = await fetch("/admin/api/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(Object.fromEntries(new FormData(form)))
      });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.detail || "Не удалось войти");
      }
      const params = new URLSearchParams(location.search);
      const requested = params.get("next");
      const destination = requested && requested.startsWith("/") && !requested.startsWith("//")
        ? requested
        : location.pathname + location.search;
      location.replace(destination);
    } catch (error) {
      errorBox.textContent = error.message;
      submit.disabled = false;
      submit.textContent = "Войти";
      password.focus();
      password.select();
    }
  });
}());
