const $ = id => document.getElementById(id);
const esc = value => String(value).replace(/[&<>"']/g, c => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
}[c]));
const formatted = value => esc(value).replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
const paragraphs = value => value.trim().split(/\n\s*\n/).filter(Boolean);
let screens = [], illustrations = {}, current = 0;
const scenes = {
  intro: ['top'], card: ['card'], copy: ['copy', 'paste'],
  controls: ['toolbar', 'new-date'], templates: ['templates', 'composition'],
  history: ['history-training', 'history-exercise'],
  'send-saving': ['send-control', 'send', 'saved', 'error']
};

function lessonParts(screen) {
  const body = screen.paragraphs.join('\n\n');
  const starts = [...body.matchAll(/^\d+\.\s+/gm)];
  return {
    lead: paragraphs(body.slice(0, starts[0]?.index ?? body.length)),
    items: starts.map((match, index) => paragraphs(body.slice(
      match.index + match[0].length, starts[index + 1]?.index ?? body.length
    )))
  };
}

function figure(key) {
  const shot = illustrations[key], a = shot.annotation;
  let targets = '', labels = '';
  for (const mark of a.marks) {
    const [x, y, width, height, radius] = mark.target;
    const rect = `<rect x="${x}" y="${y}" width="${width}" height="${height}" rx="${radius}"`;
    targets += rect + ' class="annotation-target-halo"/>' + rect + ' class="annotation-target"/>';
    labels += `<polyline class="annotation-leader" points="${mark.leader.map(p => p.join(',')).join(' ')}"/>` +
      `<circle class="annotation-badge" cx="${mark.badge[0]}" cy="${mark.badge[1]}" r="11"/>` +
      `<text class="annotation-badge-label" x="${mark.badge[0]}" y="${mark.badge[1]}">${mark.n}</text>`;
  }
  return `<figure class="shot" data-shot="${key}" style="width:${a.width}px;aspect-ratio:${a.width}/${a.height}">` +
    `<img src="${esc(shot.src)}" alt="${esc(shot.alt)}" width="${shot.width}" height="${shot.height}" ` +
    `style="position:absolute;left:0;top:${a.offset / a.height * 100}%;width:${a.imageWidth / a.width * 100}%">` +
    (labels ? `<svg aria-hidden="true" viewBox="0 0 ${a.width} ${a.height}">${targets}${labels}</svg>` : '') + '</figure>';
}

function show(index) {
  current = Math.max(0, Math.min(screens.length - 1, index));
  const screen = screens[current], parts = lessonParts(screen);
  $('tutorial').dataset.scene = screen.scene;
  $('counter').textContent = `${current + 1} / ${screens.length}`;
  $('lesson-title').textContent = screen.title;
  $('lesson-lead').innerHTML = parts.lead.map(p => `<p>${formatted(p)}</p>`).join('');
  $('lesson-lead').hidden = !parts.lead.length;
  $('screenshots').innerHTML = scenes[screen.scene].map(figure).join('');
  $('lesson-text').innerHTML = parts.items.map(item =>
    '<li>' + item.map(p => `<p>${formatted(p)}</p>`).join('') + '</li>'
  ).join('');
  for (const id of ['previous', 'previous-top']) $(id).disabled = current === 0;
  for (const id of ['next', 'next-top']) $(id).disabled = current === screens.length - 1;
  window.scrollTo(0, 0);
}

for (const id of ['previous', 'previous-top']) $(id).onclick = () => show(current - 1);
for (const id of ['next', 'next-top']) $(id).onclick = () => show(current + 1);

let close;
try {
  if (window.parent !== window && typeof window.parent.ST?.closeModal === 'function') {
    close = () => window.parent.ST.closeModal();
  }
} catch { /* A public guide may also be embedded on another origin. */ }
if (close) {
  $('close-tutorial').hidden = false;
  $('close-tutorial').onclick = close;
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') { event.preventDefault(); close(); }
    if (event.key === 'Tab') {
      const buttons = [...document.querySelectorAll('button:not(:disabled):not([hidden])')];
      const first = buttons[0], last = buttons.at(-1);
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault(); last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault(); first.focus();
      }
    }
  });
}

fetch('content.json?v=20261023').then(response => {
  if (!response.ok) throw new Error('tutorial unavailable');
  return response.json();
}).then(data => {
  screens = data.screens;
  illustrations = data.illustrations;
  $('tutorial-error').hidden = true;
  show(0);
}).catch(() => {
  $('tutorial-error').textContent = 'Не удалось загрузить справку. Обновите страницу.';
});
