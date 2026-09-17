(function () {
  'use strict';
  window.EdabalansQuestionnairePerson = {
    render: function (container, data) {
      if (!data.personFields || !data.personFields.length) return;
      var section = document.createElement('section');
      section.className = 'ed-person-fields';
      data.personFields.forEach(function (field) {
        var label = document.createElement('label');
        var caption = document.createElement('span');
        caption.textContent = field.title;
        var input = document.createElement(field.options ? 'select' : 'input');
        if (field.options) {
          [''].concat(field.options).forEach(function (value) {
            var option = document.createElement('option');
            option.value = value; option.textContent = value || 'Выберите';
            input.appendChild(option);
          });
        } else {
          input.type = 'number'; input.min = field.min; input.max = field.max; input.step = field.step;
          input.inputMode = field.step === 1 ? 'numeric' : 'decimal';
        }
        input.dataset.personField = field.key;
        input.dataset.code = field.code;
        input.value = data.personParameters[field.key] === undefined ? '' : data.personParameters[field.key];
        label.append(caption, input); section.appendChild(label);
      });
      container.prepend(section);
    }
  };
})();
