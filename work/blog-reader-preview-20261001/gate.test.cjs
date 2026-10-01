const {test} = require('node:test');
const assert = require('node:assert/strict');
const {eligible, due, parseLastShown, readingProgress} = require('./reader.js');
test('Only identified and confirmed unsubscribed visitors qualify', () => {
  assert.equal(eligible(true, 'not_subscribed'), true);
  for (const identity of [false, null, undefined]) assert.equal(eligible(identity, 'not_subscribed'), false);
  for (const status of ['subscribed', 'unknown', 'error', null, undefined]) assert.equal(eligible(true, status), false);
});
test('Persisted time cannot silently treat corrupt storage as no prior popup', () => {
  assert.equal(parseLastShown(null), null);
  assert.equal(parseLastShown('100'), 100);
  for (const value of ['', ' ', 'NaN', '-1', '1e3', 'Infinity', '9007199254740993']) {
    assert.equal(due(parseLastShown(value), 86400100), false);
  }
});
test('Popup interval is 24h; unreadable or corrupt timestamp fails closed', () => {
  assert.equal(due(null, 100), true);
  assert.equal(due(100, 86400099), false);
  assert.equal(due(100, 86400100), true);
  assert.equal(due(NaN, 86400100), false);
  assert.equal(due(200, 100), false);
});
test('Progress excludes inserted cards and plaques, not just footer', () => {
  const boxes = [{top:100,height:200},{top:900,height:100}];
  assert.equal(readingProgress(0,1300,700,boxes), .5);
  assert.equal(readingProgress(0,1300,200,boxes), .1);
  assert.equal(readingProgress(0,1300,2000,boxes), 1);
  assert.equal(readingProgress(0,1300,-50,boxes), 0);
  assert.equal(readingProgress(0,0,100,[]), 0);
});
