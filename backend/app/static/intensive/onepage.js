'use strict';
const header = document.querySelector('.reading-header');
const progress = document.querySelector('.reading-track');
const fill = document.querySelector('.reading-fill');
const end = document.getElementById('reading-end');
const dialog = document.getElementById('contents');
const trigger = document.querySelector('.toc-trigger');
const closeButton = document.querySelector('.toc-close');

// Gentle early acceleration: 5% actual reading gives about 12% visual progress.
function displayProgress(actual) {
  return actual + 1.6 * actual * Math.pow(1 - actual, 3);
}
function updateReading() {
  const endY = end.getBoundingClientRect().top + window.scrollY;
  const distance = Math.max(1, endY - window.innerHeight);
  const actual = Math.max(0, Math.min(1, window.scrollY / distance));
  fill.style.clipPath = `inset(0 ${(1 - displayProgress(actual)) * 100}% 0 0 round 10px)`;
  progress.setAttribute('aria-valuenow', String(Math.round(actual * 100)));

}
let frame = 0;
function scheduleUpdate() {
  if (!frame) frame = requestAnimationFrame(() => { frame = 0; updateReading(); });
}
window.addEventListener('scroll', scheduleUpdate, {passive: true});
window.addEventListener('resize', scheduleUpdate);
window.addEventListener('load', scheduleUpdate);
new ResizeObserver(scheduleUpdate).observe(document.getElementById('article'));
trigger.addEventListener('click', () => {
  dialog.showModal();
  dialog.scrollTop = 0;
});
closeButton.addEventListener('click', () => dialog.close());
dialog.addEventListener('click', event => {
  if (event.target.closest('a[href^="#"]')) dialog.close();
  if (event.target === dialog) {
    const rect = dialog.getBoundingClientRect();
    if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) dialog.close();
  }
});
updateReading();
