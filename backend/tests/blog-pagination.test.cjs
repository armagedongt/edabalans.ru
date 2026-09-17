const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../app/static/blog/assets/blog.js'), 'utf8');

function fixture(search = '') {
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
  Object.defineProperty(pagination, 'innerHTML', { set() { this.children = []; } });
  const empty = element();
  const anchor = element();
  const document = {
    documentElement: { dataset: {} },
    querySelector(selector) { return selector === '.pagination' ? pagination : selector === '.empty-state' ? empty : null; },
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
    pagination, empty, history,
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
