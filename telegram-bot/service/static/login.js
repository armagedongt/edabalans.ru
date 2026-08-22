const form = document.querySelector('#login-form');
const errorBox = document.querySelector('#login-error');
const password = form.elements.password;
const showPassword = document.querySelector('#show-password');

showPassword.onclick = () => {
  const visible = password.type === 'text';
  password.type = visible ? 'password' : 'text';
  showPassword.textContent = visible ? 'Показать' : 'Скрыть';
};

form.onsubmit = async event => {
  event.preventDefault();
  errorBox.textContent = '';
  const submit = form.querySelector('[type="submit"]');
  submit.disabled = true;
  submit.textContent = 'Входим…';
  try {
    const response = await fetch('/bot-api/login', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(Object.fromEntries(new FormData(form))),
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || 'Не удалось войти');
    }
    location.replace('/bot');
  } catch (error) {
    errorBox.textContent = error.message;
    submit.disabled = false;
    submit.textContent = 'Войти';
    password.focus();
    password.select();
  }
};
