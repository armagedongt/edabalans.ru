(function () {
  'use strict';

  function enhance(root, slug) {
    if (!root) return;
    root.classList.add('edb-program-card');
    root.dataset.programCard = slug || '';
  }

  window.EdabalansProgramCard = { enhance: enhance };
})();
