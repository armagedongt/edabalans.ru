// Delegation survives article navigation: copy only the explicit code block.
document.addEventListener('click', async (event) => {
  const button = event.target.closest('.article-copy-button');
  if (!button || !button.closest('#article')) return;
  const code = button.closest('.article-copy-block').querySelector('pre code');
  button.setAttribute('aria-live', 'polite');
  try {
    await navigator.clipboard.writeText(code.textContent);
    button.textContent = 'Скопировано';
  } catch {
    button.textContent = 'Не скопировано — попробуйте ещё раз';
  }
});
