(function () {
  'use strict';

  function groupSections(root, headingSelector, bodyTags) {
    var headings = Array.prototype.slice.call(root.children).filter(function (node) {
      return node.matches(headingSelector);
    });
    if (!headings.length) return;

    var sections = document.createElement('div');
    sections.className = 'edb-program-card__sections';
    headings[0].parentNode.insertBefore(sections, headings[0]);

    headings.forEach(function (heading, index) {
      var section = document.createElement('section');
      section.className = 'edb-program-card__section';
      var boundary = headings[index + 1] || null;
      var node = heading.nextElementSibling;
      section.appendChild(heading);

      while (node && node !== boundary && bodyTags.indexOf(node.tagName) !== -1) {
        var next = node.nextElementSibling;
        section.appendChild(node);
        node = next;
      }
      sections.appendChild(section);
    });
  }

  function enhance(root, slug) {
    if (!root) return;
    root.classList.add('edb-program-card');
    root.dataset.programCard = slug || '';

    if (slug === 'program' || slug === 'consultation') groupSections(root, 'h2', ['P']);
    if (slug === 'recipes') groupSections(root, 'h3', ['UL']);
  }

  window.EdabalansProgramCard = { enhance: enhance };
})();
