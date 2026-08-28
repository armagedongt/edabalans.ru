from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]
SLIDER = ROOT / "content/masterclass/components/dqs-image-slider/slider.js"


def test_slider_runtime_binds_navigation_counter_dots_and_swipe() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is not available")
    script = r"""
const fs = require('fs');
const vm = require('vm');
function classList() { return { active: false, toggle(_name, value) { this.active = value; } }; }
const dots = [0, 1].map((index) => ({ dataset: { slide: String(index) }, classList: classList(), scrollIntoView() {} }));
const track = { style: {} };
const slides = [{}, {}];
const counter = { textContent: '' };
const previous = {};
const next = {};
const handlers = {};
const windowElement = { addEventListener(name, handler) { handlers[name] = handler; } };
const root = {
  dataset: {},
  querySelector(selector) {
    return ({ '.gallery-track': track, '.gallery-counter': counter, '.gallery-prev': previous,
      '.gallery-next': next, '.gallery-window': windowElement })[selector] || null;
  },
  querySelectorAll(selector) {
    return selector === '.gallery-slide' ? slides : selector === '.gallery-dot' ? dots : [];
  }
};
const scope = { querySelectorAll(selector) { return selector === '[data-gallery]' ? [root] : []; } };
const context = { window: {}, document: scope, Number, Math };
vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), context);
context.window.bindGallery(scope);
if (track.style.transform !== 'translateX(-0%)' || counter.textContent !== '1 / 2') process.exit(1);
next.onclick();
if (track.style.transform !== 'translateX(-100%)' || counter.textContent !== '2 / 2' || !dots[1].classList.active) process.exit(2);
dots[0].onclick();
if (track.style.transform !== 'translateX(-0%)') process.exit(3);
handlers.pointerdown({ clientX: 100 });
handlers.pointerup({ clientX: 20 });
if (track.style.transform !== 'translateX(-100%)') process.exit(4);
context.window.bindGallery(scope);
if (root.dataset.galleryBound !== 'true') process.exit(5);
"""
    result = subprocess.run(
        [node, "-e", script, str(SLIDER)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
