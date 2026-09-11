(function () {
  'use strict';

  function enhance(root, slug) {
    if (!root) return;
    root.classList.add('edb-program-card');
    root.dataset.programCard = slug || '';
    if (root.dataset.programCardEnhanced === 'true') return;

    var headings = Array.prototype.slice.call(root.querySelectorAll(':scope > h3'));
    if (headings.length) {
      var days = document.createElement('div');
      days.className = 'edb-program-card__days';
      headings[0].parentNode.insertBefore(days, headings[0]);
      headings.forEach(function (heading) {
        var day = document.createElement('section');
        day.className = 'edb-program-card__day';
        days.appendChild(day);
        day.appendChild(heading);
        var list = days.nextElementSibling;
        if (list && list.tagName === 'UL') day.appendChild(list);
      });
    }

    root.dataset.programCardEnhanced = 'true';
  }

  window.EdabalansProgramCard = { enhance: enhance };
})();
