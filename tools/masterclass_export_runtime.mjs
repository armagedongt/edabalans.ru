import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';

const root = path.resolve(import.meta.dirname, '..');
const sourcePath = path.join(
  root,
  'backend',
  'app',
  'static',
  'masterclass-first-days-preview.html',
);
const targetPath = path.join(
  root,
  'content',
  'masterclass',
  'course',
  'course.json',
);

const html = fs.readFileSync(sourcePath, 'utf8');
const scripts = [...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/gi)];
let source = scripts.map((match) => match[1]).find((text) => text.includes('function extendDays'));
if (!source) throw new Error('Course source script was not found');

const bootStart = source.indexOf("    document.querySelector('#back')");
const closureEnd = source.lastIndexOf('  }());');
if (bootStart < 0 || closureEnd < 0) throw new Error('Course bootstrap boundaries changed');
source = `${source.slice(0, bootStart)}
    build();
    extendDays();
    globalThis.__courseExport = {program: program, days: days};
${source.slice(closureEnd)}`;

const sandbox = {
  console,
  globalThis: null,
  location: {hostname: '127.0.0.1', origin: 'http://127.0.0.1'},
  localStorage: {getItem: () => null, setItem: () => {}},
  window: {},
};
sandbox.globalThis = sandbox;
vm.runInNewContext(source, sandbox, {filename: sourcePath});

const appByDay = {
  4: {
    code: 'dqs',
    label: 'Открыть мою таблицу DQS',
    summary: 'Сразу перейти к заполнению прошлых дней по фотографиям из дневника.',
    meta: 'Откроется отдельным приложением на весь экран',
    completion: 'first_server_save',
  },
};

const days = sandbox.__courseExport.days.map((sourceDay, dayIndex) => {
  const day = {...sourceDay};
  const topics = day.topics || [];
  const app = day.app || appByDay[day.number];
  const offer = day.offer;
  delete day.topics;
  delete day.app;
  delete day.offer;

  const steps = topics.map((topic, topicIndex) => ({
    id: `day-${String(day.number).padStart(2, '0')}-article-${String(topicIndex + 1).padStart(2, '0')}`,
    kind: 'article',
    title: topic.title,
    summary: topic.summary,
    status: topic.draft ? 'draft' : 'ready',
  }));
  if (day.number === 1) {
    steps.push({
      id: 'day-01-questionnaire',
      kind: 'questionnaire',
      app: 'onboarding-questionnaire',
      completion: 'submitted',
    });
    steps.push({
      id: 'day-01-messenger-link',
      kind: 'messenger',
      completion: 'link_requested',
    });
  }
  if (app) {
    steps.push({
      id: `day-${String(day.number).padStart(2, '0')}-${app.code}`,
      kind: app.code,
      ...app,
      completion: app.completion || (app.code === 'closing-review' ? 'submitted' : 'opened'),
    });
  }
  if (offer) {
    steps.push({
      id: `day-${String(day.number).padStart(2, '0')}-offer`,
      kind: 'offer',
      ...offer,
      completion: 'opened',
    });
  }

  return {
    ...day,
    slug: `day-${String(day.number).padStart(2, '0')}`,
    navTitle: sandbox.__courseExport.program[dayIndex][0],
    navSummary: sandbox.__courseExport.program[dayIndex][1],
    recipeDay: day.number === 16 || day.number === 18,
    publicationStatus: topics.some((topic) => topic.draft) ? 'draft_with_placeholders' : 'ready',
    steps,
  };
});

const manifest = {
  schemaVersion: 1,
  courseVersion: '2026-08-23.1',
  courseCode: 'masterclass-21',
  title: 'Мастер-класс',
  status: 'launch_draft',
  dayIntervalHours: 20,
  source: 'approved warm prototype',
  days,
};

fs.mkdirSync(path.dirname(targetPath), {recursive: true});
fs.writeFileSync(targetPath, `${JSON.stringify(manifest, null, 2)}\n`, 'utf8');
console.log(`Wrote ${targetPath}`);
