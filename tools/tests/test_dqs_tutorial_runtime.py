"""Execute the shipped tutorial functions with synthetic browser boundaries."""
import pathlib
import shutil
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]


class DqsTutorialRuntimeTests(unittest.TestCase):
    def test_tutorial_lifecycle(self):
        node = shutil.which("node")
        self.assertIsNotNone(node, "Node.js is required for DQS runtime checks")
        script = r"""
const fs = require('fs'), vm = require('vm'), assert = require('assert/strict');
const html = fs.readFileSync('backend/app/static/apps/dqs.html', 'utf8');
const source = html.slice(html.indexOf('function tutorialStorageKey()'), html.indexOf('function renderTutorial()'));
assert.ok(source.length > 100);
function browser(completed=false, brokenStorage=false) {
  const storage = new Map(), timers = [], events = [], alerts = [];
  const c = {currentUser:{email:'one@example.test', tutorialCompleted:completed},
    TUTORIAL_PREFIX:'dqs_tutorial_seen_', tutorialStep:0, shown:0, closed:0,
    localStorage:{getItem(k){if(brokenStorage) throw Error('blocked'); return storage.get(k);},
      setItem(k,v){if(brokenStorage) throw Error('blocked'); storage.set(k,v);}},
    setTimeout(fn){timers.push(fn);}, window:{dispatchEvent(e){events.push(e);}},
    CustomEvent:class {constructor(type,options){this.type=type;this.detail=options.detail;}},
    document:{body:{style:{}},getElementById(){return {remove(){c.closed++;}};}},
    renderTutorial(){c.shown++;}, alert(e){alerts.push(e);}, api:async()=>({ok:true})};
  vm.createContext(c); vm.runInContext(source,c);
  c.flush=()=>{while(timers.length) timers.shift()();};
  return {c, events, alerts};
}
(async()=>{
  const course = fs.readFileSync('backend/app/static/masterclass-first-days-preview.html','utf8');
  const openMaterial = course.split('\n').find(line=>line.includes('function openDqsMaterial('));
  assert.ok(openMaterial);
  const nodes = new Map(); let opened=0;
  const shell = {pages:{}, dqsTutorialRequested:false,
    document:{querySelector(id){if(!nodes.has(id))nodes.set(id,{});return nodes.get(id);}},
    esc:s=>s, splitArticleHtml:s=>({body:s}), renderContentEmbeds:s=>s,
    materialMetaHtml:()=>'', configureArticleToc(){}, previousVisibleStep:()=>-1,
    materialButtonText:()=>'', renderMenu(){}, window:{scrollTo(){}},
    openDqsApplication:async()=>{opened++;}, showActionError:e=>{throw e;}};
  vm.createContext(shell); vm.runInContext(openMaterial,shell);
  shell.openDqsMaterial({steps:[{}]},0);
  nodes.get('#dqs-open-app').onclick();
  assert.equal(opened,1); assert.equal(shell.dqsTutorialRequested,false);
  let {c,events}=browser();
  c.maybeShowTutorial(); c.flush(); assert.equal(c.shown,1);
  c.closeTutorial(true); c.maybeShowTutorial(); c.flush(); assert.equal(c.shown,1);
  assert.equal(c.currentUser.tutorialCompleted,false); assert.equal(events.length,0);
  c.currentUser={email:'one@example.test',tutorialCompleted:false};
  c.maybeShowTutorial(); c.flush(); assert.equal(c.shown,1);
  c.currentUser={email:'two@example.test'}; c.maybeShowTutorial(); c.flush(); assert.equal(c.shown,2);
  ({c,events}=browser()); await c.completeTutorial(); assert.equal(events.length,1);
  c.maybeShowTutorial(); c.flush(); assert.equal(c.shown,0);
  ({c}=browser(true)); c.maybeShowTutorial(); c.flush(); assert.equal(c.shown,0);
  c.window.EdabalansDqsOpenTutorial(); assert.equal(c.shown,1);
  ({c}=browser()); c.maybeShowTutorial(); c.closeTutorial(true); c.flush(); assert.equal(c.shown,0);
  ({c}=browser(false,true)); c.tutorialStep=4; await c.tutorialNext();
  assert.equal(c.closed,1); assert.equal(c.currentUser.tutorialCompleted,true);
  c.maybeShowTutorial(); c.flush(); assert.equal(c.shown,0);
  const failed=browser(); failed.c.api=async()=>({ok:false,error:'offline'});
  failed.c.tutorialStep=4; await failed.c.tutorialNext();
  assert.equal(failed.c.closed,0); assert.equal(failed.events.length,0);
  assert.equal(failed.c.currentUser.tutorialCompleted,false); assert.equal(failed.alerts.length,1);
})().catch(e=>{console.error(e);process.exit(1);});
"""
        result = subprocess.run([node, "-e", script], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
