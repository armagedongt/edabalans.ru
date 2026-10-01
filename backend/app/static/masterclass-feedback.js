(function(){
  'use strict';
  var root=document.createElement('div');
  root.className='mc-feedback';root.hidden=true;
  root.innerHTML='<section class="mc-feedback-card" role="dialog" aria-modal="true" aria-labelledby="mc-feedback-title" tabindex="-1"><form novalidate><h2 id="mc-feedback-title"></h2><p class="mc-feedback-intro"></p><div class="mc-feedback-questions"></div><div class="mc-feedback-question"><label for="mc-feedback-comment"></label><textarea id="mc-feedback-comment" maxlength="4000"></textarea></div><p class="mc-feedback-error" role="alert" hidden></p><button class="mc-feedback-submit" type="submit">Отправить и продолжить</button></form></section>';
  document.body.appendChild(root);
  var active=null,submit=null,answers={},oldOverflow='';
  var card=root.querySelector('.mc-feedback-card'),questions=root.querySelector('.mc-feedback-questions'),error=root.querySelector('.mc-feedback-error');
  function clearError(){error.hidden=true;questions.querySelectorAll('.is-missing').forEach(function(item){item.classList.remove('is-missing')})}
  function questionNode(question){
    var section=document.createElement('section');section.className='mc-feedback-question';section.dataset.code=question.code;
    if(question.type==='choice'){
      var fieldset=document.createElement('fieldset'),legend=document.createElement('legend'),choices=document.createElement('div');legend.textContent=question.title;choices.className='mc-feedback-options';choices.setAttribute('role','radiogroup');choices.setAttribute('aria-label',question.title);
      question.options.forEach(function(option){var button=document.createElement('button');button.type='button';button.className='mc-feedback-option';button.textContent=option;button.setAttribute('role','radio');button.setAttribute('aria-checked','false');button.onclick=function(){answers[question.code]=option;choices.querySelectorAll('button').forEach(function(item){item.setAttribute('aria-checked',String(item===button))});clearError()};choices.appendChild(button)});
      fieldset.appendChild(legend);fieldset.appendChild(choices);section.appendChild(fieldset);
    }else{
      var label=document.createElement('label'),hint=document.createElement('small'),row=document.createElement('div'),input=document.createElement('input'),output=document.createElement('output'),ends=document.createElement('div');
      input.id='mc-feedback-'+question.code;label.htmlFor=input.id;label.textContent=question.title;section.appendChild(label);
      if(question.hint){hint.className='mc-feedback-hint';hint.textContent=question.hint;section.appendChild(hint)}
      row.className='mc-feedback-range-row';input.type='range';input.className='mc-feedback-range is-unanswered';input.min='1';input.max='10';input.value='5';input.setAttribute('aria-valuetext','Ответ не выбран');output.className='mc-feedback-value';output.textContent='Выберите';
      input.oninput=function(){answers[question.code]=Number(input.value);input.classList.remove('is-unanswered');input.setAttribute('aria-valuetext',input.value+' из 10');output.classList.add('is-answered');output.textContent=input.value+' / 10';clearError()};
      row.appendChild(input);row.appendChild(output);section.appendChild(row);ends.className='mc-feedback-ends';var low=document.createElement('span'),high=document.createElement('span');low.textContent='1 — '+question.low;high.textContent='10 — '+question.high;ends.appendChild(low);ends.appendChild(high);section.appendChild(ends);
    }
    return section;
  }
  function show(pulse){
    active=pulse;answers={};clearError();questions.replaceChildren();root.querySelector('form').reset();
    root.querySelector('#mc-feedback-title').textContent=pulse.title;root.querySelector('.mc-feedback-intro').textContent=pulse.intro;
    pulse.questions.forEach(function(question){questions.appendChild(questionNode(question))});root.querySelector('label[for="mc-feedback-comment"]').textContent=pulse.comment;
    oldOverflow=document.body.style.overflow;document.body.style.overflow='hidden';root.hidden=false;card.scrollTop=0;card.focus();
  }
  function hide(){root.hidden=true;active=null;document.body.style.overflow=oldOverflow}
  root.querySelector('form').onsubmit=function(event){
    event.preventDefault();if(!active||!submit)return;
    var first=active.questions.find(function(question){return answers[question.code]===undefined});
    if(first){var section=questions.querySelector('[data-code="'+first.code+'"]');section.classList.add('is-missing');error.textContent='Ответьте на этот вопрос.';error.hidden=false;section.scrollIntoView({block:'center',behavior:'smooth'});section.querySelector('button,input').focus({preventScroll:true});return}
    answers.comment=root.querySelector('#mc-feedback-comment').value;
    var button=root.querySelector('.mc-feedback-submit');button.disabled=true;clearError();
    Promise.resolve(submit(active.day,answers)).then(function(){hide()}).catch(function(problem){error.textContent='Не удалось сохранить ответ. Попробуйте ещё раз.';error.hidden=false;console.warn('Feedback save failed',problem)}).finally(function(){button.disabled=false});
  };
  window.MasterclassFeedback={configure:function(callback){submit=callback},sync:function(payload){if(payload&&payload.feedback_pulse){if(!active||active.day!==payload.feedback_pulse.day)show(payload.feedback_pulse)}else if(active)hide()},isOpen:function(){return !root.hidden}};
}());
