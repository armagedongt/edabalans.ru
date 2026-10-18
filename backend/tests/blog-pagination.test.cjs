const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../app/static/blog/assets/blog.js'), 'utf8');

function fixture(search = '', server = false) {
  function element(dataset = {}) {
    return {
      dataset, hidden: false, children: [], attributes: {}, handlers: {},
      classList: { toggle() {} },
      setAttribute(name, value) { this.attributes[name] = value; },
      addEventListener(name, action) { this.handlers[name] = action; },
      appendChild(child) { this.children.push(child); },
      scrollIntoView() {},
    };
  }
  const cards = Array.from({ length: 22 }, (_, i) => element({ category: i < 18 ? 'A' : 'B' }));
  const buttons = ['all', 'A', 'B', 'empty'].map(categoryFilter => element({ categoryFilter }));
  const pagination = element();
  if (server) pagination.children.push({ textContent: 'server link' });
  Object.defineProperty(pagination, 'innerHTML', { set() { this.children = []; } });
  const empty = element();
  const anchor = element();
  const document = {
    documentElement: { dataset: {} },
    querySelector(selector) { return selector === '[data-blog-server-catalog]' && server ? {} : selector === '.pagination' ? pagination : selector === '.empty-state' ? empty : null; },
    querySelectorAll(selector) { return selector.includes('.articles-section') ? cards : selector === '[data-category-filter]' ? buttons : []; },
    createElement() { return element(); },
    getElementById() { return anchor; },
    addEventListener() {},
  };
  const history = [];
  vm.runInNewContext(source, { document, window: {}, localStorage: { getItem() { return null; } }, location: { search, pathname: '/blog' }, history: { pushState(_, __, url) { history.push(url); } }, URLSearchParams });
  return {
    visible: () => cards.flatMap((card, index) => card.hidden ? [] : [index]),
    page: () => pagination.children.find(button => button.attributes['aria-current'] === 'page')?.textContent,
    next() { pagination.handlers.click({ target: { closest() { return pagination.children.find(button => button.dataset.pageNext); } } }); },
    category(name) { buttons.find(button => button.dataset.categoryFilter === name).handlers.click(); },
    pagination, empty, history, buttons,
  };
}

test('first fifteen cards and remaining seven are accessible', () => {
  const ui = fixture();
  assert.deepEqual(ui.visible(), Array.from({ length: 15 }, (_, i) => i));
  assert.equal(ui.page(), '1');
  ui.next();
  assert.deepEqual(ui.visible(), [15, 16, 17, 18, 19, 20, 21]);
  assert.equal(ui.page(), '2');
  assert.equal(ui.history.at(-1), '?page=2#articles');
});

test('filter resets page even when the filtered category spans two pages', () => {
  const ui = fixture();
  ui.next();
  ui.category('A');
  assert.equal(ui.page(), '1');
  assert.deepEqual(ui.visible(), Array.from({ length: 15 }, (_, i) => i));
  ui.next();
  assert.deepEqual(ui.visible(), [15, 16, 17]);
  ui.category('B');
  assert.deepEqual(ui.visible(), [18, 19, 20, 21]);
  assert.equal(ui.pagination.children.length, 0);
  ui.category('empty');
  assert.deepEqual(ui.visible(), []);
  assert.equal(ui.empty.hidden, false);
  ui.category('all');
  assert.equal(ui.visible().length, 15);
  assert.equal(ui.empty.hidden, true);
});

test('direct links select filtered page two and clamp beyond last page', () => {
  assert.deepEqual(fixture('?category=A&page=2').visible(), [15, 16, 17]);
  assert.deepEqual(fixture('?category=A&page=999').visible(), [15, 16, 17]);
  assert.equal(fixture('?page=not-a-number').visible().length, 15);
});

test('server-rendered catalogue links are not overwritten or intercepted', () => {
  const ui = fixture('?page=2', true);
  assert.equal(ui.pagination.children[0].textContent, 'server link');
  assert.equal(ui.pagination.handlers.click, undefined);
  assert.ok(ui.buttons.every(button => button.handlers.click === undefined));
  assert.equal(ui.visible().length, 22);
  assert.deepEqual(ui.history, []);
});

const unifiedSource = fs.readFileSync(path.join(__dirname, '../app/static/blog/assets/blog-unified.js'), 'utf8');
function readingFixture({page = 'article', stored = '[]', unavailable = false} = {}) {
  const handlers = {};
  let top = 0;
  let value = stored;
  let writes = 0;
  let mark = null;
  let markCount = 0;
  const link = {
    href: 'https://example.test/blog/example',
    querySelector(selector) {
      return selector === '.read-mark' ? mark : {appendChild(item) {mark = item; markCount++;}};
    },
  };
  const body = {getBoundingClientRect() {return {top, height: 1000};}};
  const context = {
    URL,
    document: {
      body: {dataset: {page}},
      querySelector(selector) {return selector === 'link[rel=canonical]' ? {href: link.href} : null;},
      querySelectorAll() {return [link];},
      getElementById() {return body;},
      createElement() {return {};},
    },
    window: {
      innerHeight: 500,
      addEventListener(name, callback) {handlers[name] = callback;},
      removeEventListener(name) {delete handlers[name];},
    },
    localStorage: {
      getItem() {if (unavailable) throw new Error('storage blocked'); return value;},
      setItem(_, next) {if (unavailable) throw new Error('storage blocked'); writes++; value = next;},
    },
  };
  vm.runInNewContext(unifiedSource, context);
  return {
    scroll(nextTop) {top = nextTop; handlers.scroll?.();},
    saved: () => JSON.parse(value),
    writes: () => writes,
    marked: () => mark?.textContent,
    markCount: () => markCount,
    handlers,
  };
}

test('read mark starts at 75 percent of article body and persists only once', () => {
  const ui = readingFixture();
  ui.scroll(-249);
  assert.equal(ui.writes(), 0);
  ui.scroll(-250);
  assert.deepEqual(ui.saved(), ['example']);
  assert.equal(ui.writes(), 1);
  ui.scroll(-900);
  assert.equal(ui.writes(), 1);
  assert.equal(readingFixture({page: 'home', stored: JSON.stringify(ui.saved())}).marked(), '✓ Прочитано');
});

test('catalogue never marks articles from its own scroll and duplicate marks are avoided', () => {
  const ui = readingFixture({page: 'home', stored: '["example"]'});
  assert.equal(ui.handlers.scroll, undefined);
  ui.handlers.pageshow();
  assert.equal(ui.marked(), '✓ Прочитано');
  assert.equal(ui.markCount(), 1);
  ui.handlers.storage({key: 'edabalans-blog-read-v1'});
  assert.equal(ui.markCount(), 1);
  assert.equal(ui.writes(), 0);
});

test('blocked or malformed browser storage does not break reading', () => {
  const blocked = readingFixture({unavailable: true});
  assert.doesNotThrow(() => blocked.scroll(-250));
  const malformed = readingFixture({stored: '{invalid'});
  malformed.scroll(-250);
  assert.deepEqual(malformed.saved(), ['example']);
  const wrongShape = readingFixture({stored: '{}'});
  wrongShape.scroll(-250);
  assert.deepEqual(wrongShape.saved(), ['example']);
});
