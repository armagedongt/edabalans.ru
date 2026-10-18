const assert = require('node:assert/strict');
const {due,progress,cookieDomain,subscriptionAnchor} = require('../app/static/blog/assets/reader-subscription.js');
assert.equal(due(null,0),true);
assert.equal(due(1000,1000+86400000-1),false);
assert.equal(due(1000,1000+86400000),true);
assert.equal(due(NaN,100000000),false);
assert.equal(due(100000001,100000000),false);
assert.equal(progress(100,1100,600,[]),.5);
assert.equal(progress(100,1100,700,[{top:500,height:200}]),.5);
assert.equal(progress(100,1100,1100,[{top:900,height:200}]),1);
assert.equal(progress(100,100,100,[]),0);
assert.equal(cookieDomain('blog.edabalans.ru'),'edabalans.ru');
assert.equal(cookieDomain('go.xn-----jlceacr3bggd8ajed5a6kl.xn--p1ai'),'xn-----jlceacr3bggd8ajed5a6kl.xn--p1ai');
assert.equal(cookieDomain('edabalans.ru.evil.test'),undefined);
assert.equal(cookieDomain('notedabalans.ru'),undefined);
const first = {id:'first'}, next = {id:'first-next'}, selected = {id:'selected'};
const article = id => ({dataset:{subscriptionBeforeHeading:id},querySelectorAll(selector){
  assert.equal(selector,':scope > h2');
  return [first,next,selected];
}});
assert.equal(subscriptionAnchor(article('selected')),selected);
assert.equal(subscriptionAnchor(article('first')),first);
assert.equal(subscriptionAnchor(article('missing')),undefined);
assert.equal(subscriptionAnchor(article('fir')),undefined,'A prefix must not relocate the insertion');
assert.equal(subscriptionAnchor(article(undefined)),undefined);
console.log('reader subscription timing, domain, progress and curated anchor assertions passed');
const {test} = require('node:test');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../app/static/blog/assets/reader-subscription.js'), 'utf8');

async function entry(search, context, fail = false) {
  const result = { inline: null, opened: false, request: null };
  const popup = {
    showModal() { result.opened = true; }, close() {}, addEventListener() {},
    querySelector(selector) {
      if (selector === '.reader-channel') return {cloneNode: () => ({addEventListener() {}})};
      return {addEventListener() {}};
    }
  };
  const heading = {id: 'section', before(node) { result.inline = node; }};
  const article = {
    dataset: {subscriptionBeforeHeading: 'section'},
    querySelector: () => null,
    querySelectorAll: selector => selector === ':scope > h2' ? [heading] : [],
    getBoundingClientRect: () => ({top: 0, bottom: 1000})
  };
  const document = {
    cookie: '', visibilityState: 'visible', addEventListener() {}, querySelector: () => null,
    getElementById: id => id === 'reader-popup' ? popup : article
  };
  vm.runInNewContext(source, {
    URLSearchParams, document, location: {search, hostname:'edabalans.ru', protocol:'https:'},
    window: {addEventListener() {}}, scrollY: 0, innerHeight: 800,
    fetch: async url => {
      result.request = url;
      if (fail) throw new Error('offline');
      return {ok:true, json:async () => context};
    }
  });
  await new Promise(resolve => setImmediate(resolve));
  result.cookie = document.cookie;
  return result;
}

for (const channel of ['tg', 'max']) {
  test(`channel ${channel} reaches context and hides both invitations for unknown visitor`, async () => {
    const state = await entry('?utm_source=post&from='+channel, {show_subscription:false});
    assert.equal(state.request, '/blog/reader/context?from='+channel);
    assert.equal(state.inline, null);
    assert.equal(state.opened, false);
    assert.equal(state.cookie, '');
  });
  test(`confirmed non-member can see both invitations even from ${channel}`, async () => {
    const state = await entry('?from='+channel, {show_subscription:true});
    assert.equal(state.inline.id, 'reader-channel-inline');
    assert.equal(state.opened, true);
  });
}
test('context failure hides only marked entry, and does not persist suppression', async () => {
  for (const search of ['?from=tg','?from=max']) {
    const state = await entry(search, null, true);
    assert.equal(state.inline, null);
    assert.equal(state.opened, false);
    assert.equal(state.cookie, '');
  }
  for (const search of ['', '?from=other']) {
    const state = await entry(search, null, true);
    assert.equal(state.request, '/blog/reader/context');
    assert.equal(state.inline.id, 'reader-channel-inline');
    assert.equal(state.opened, true);
  }
});
