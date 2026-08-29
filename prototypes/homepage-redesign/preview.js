(function () {
  document.querySelectorAll('img[data-original]').forEach((image) => {
    image.src = image.dataset.original;
  });
  document.querySelectorAll('.t-bgimg[data-original], [data-bg-lazy]').forEach((element) => {
    const source = element.dataset.original || element.dataset.bgLazy;
    if (source) element.style.backgroundImage = `url("${source}")`;
  });

  [].forEach((recordId) => {
    const text = document.querySelector(`#${recordId} .t119__preface`);
    if (!text || text.classList.contains('eb-chunk-grid')) return;
    const chunks = text.innerHTML
      .split(/(?:<br\s*\/?>(?:\s|&nbsp;)*){2,}/i)
      .map((chunk) => chunk.trim())
      .filter(Boolean);
    if (chunks.length < 2) return;
    text.classList.add('eb-chunk-grid');
    text.replaceChildren(...chunks.map((chunk) => {
      const card = document.createElement('div');
      card.className = 'eb-text-chunk';
      card.innerHTML = chunk;
      const textLength = card.textContent.trim().length;
      if (textLength < 220) card.classList.add('eb-text-chunk--short');
      if (textLength > 700) card.classList.add('eb-text-chunk--long');
      return card;
    }));
  });

  const wrapRecords = (startId, endId, className, eyebrow, title) => {
    const start = document.getElementById(startId);
    const end = document.getElementById(endId);
    if (!start || !end || start.closest(`.${className}`)) return;
    const section = document.createElement('section');
    section.className = `eb-stage ${className}`;
    if (eyebrow || title) {
      const header = document.createElement('div');
      header.className = 'eb-stage__header';
      header.innerHTML = `${eyebrow ? `<div class="eb-stage__eyebrow">${eyebrow}</div>` : ''}${title ? `<h2>${title}</h2>` : ''}`;
      section.append(header);
    }
    start.before(section);
    let node = start;
    while (node) {
      const next = node.nextSibling;
      section.append(node);
      if (node === end) break;
      node = next;
    }
  };

  wrapRecords('rec2042806011', 'rec2155107531', 'eb-stage--pricing', 'Форматы участия', 'Выберите свой тариф');
  wrapRecords('rec1099489631', 'rec1099531396', 'eb-stage--author', 'Автор программы', 'Опыт, который стоит за методикой');
  wrapRecords('rec1812491181', 'rec1812483351', 'eb-stage--compare', 'Посчитаем честно', 'Сравните стоимость решений');

  const insertBefore = (recordId, markup) => {
    const record = document.getElementById(recordId);
    if (!record) return null;
    const template = document.createElement('template');
    template.innerHTML = markup.trim();
    const elements = Array.from(template.content.children);
    record.before(...elements);
    return elements[0] || null;
  };

  insertBefore('rec1505281361', `
    <section class="sv-intro">
      <div class="sv-intro__glow"></div>
      <div class="sv-intro__container">
        <div class="sv-intro__eyebrow">Мастер-класс по питанию</div>
        <h1 class="sv-intro__title">Сделайте похудение <span>проще</span> всего за 3 недели</h1>
        <p class="sv-intro__text">Без жёстких диет, запретов и ежедневной борьбы с собой. Разберитесь с питанием так, чтобы им стало проще управлять в обычной жизни.</p>
        <div class="sv-intro__bottom">
          <div class="sv-intro__metric"><b>3</b><span><strong>недели</strong><small>пошаговой работы</small></span></div>
          <div class="sv-intro__metric"><b>21</b><span><strong>день</strong><small>практики</small></span></div>
          <a class="sv-intro__button" href="#sv-program">Посмотреть программу <span>↓</span></a>
        </div>
      </div>
    </section>`);

  insertBefore('rec1391211071', `
    <section class="sv-problem">
      <div class="sv-shell">
        <h2>«Меньше ешьте» не работает, <em>если питание уже вымотало</em></h2>
        <div class="sv-problem__panel">
          <h3>Худеть можно не только за счёт силы воли</h3>
          <div class="sv-problem__tags"><span>насыщение</span><span>пищевые привычки</span><span>структура рациона</span><span>удобные рецепты</span><span>план на сложные ситуации</span></div>
          <p>Именно этим мы будем заниматься все три недели: не запрещать еду, а постепенно менять условия, в которых становится проще есть меньше.</p>
          <div class="sv-problem__questions"><b>Что есть, чтобы насыщаться?</b><b>Как справляться с тягой?</b><b>Как встроить изменения в жизнь?</b></div>
        </div>
      </div>
    </section>`);

  insertBefore('rec2154729891', `
    <section class="sv-chat-story" aria-label="Переписка о похудении">
      <div class="sv-shell sv-chat-story__layout">
        <div class="sv-chat-story__copy"><span>Знакомая ситуация?</span><h2>Вроде всё знаете.<br>А вечером снова «что-нибудь вкусненькое»</h2><p>Мастер-класс не запрещает еду. Он помогает увидеть, почему привычный сценарий повторяется, и спокойно его изменить.</p></div>
        <div class="sv-chat" aria-live="polite">
          <div class="sv-chat__bar"><i>С</i><span><b>Семейный чат</b><small>3 участника</small></span></div>
          <div class="sv-chat__messages">
            <p class="sv-chat__bubble sv-chat__bubble--me">Я сегодня точно не ем сладкое после ужина</p>
            <p class="sv-chat__bubble">Ты это вчера говорила 😄</p>
            <p class="sv-chat__bubble sv-chat__bubble--me">Ну всё, заказываем пирог?</p>
            <p class="sv-chat__bubble sv-chat__bubble--accent">А может, сначала разберёмся, почему вечером так хочется есть?</p>
          </div>
        </div>
      </div>
    </section>
    <section class="sv-program" id="sv-program">
      <div class="sv-shell">
        <div class="sv-program__eyebrow">Программа мастер-класса</div>
        <h2>Что изменится за 3 недели</h2>
        <div class="sv-program__rows">
          <article><div class="sv-program__num">01</div><div><span>Неделя 1</span><h3>Основа питания и насыщения</h3><p>Разбираемся, почему одной силы воли недостаточно, и собираем базу, на которой держится комфортное похудение.</p><ul><li>продуктовые категории и самые сытные варианты;</li><li>баланс белков, жиров и углеводов без сложных схем;</li><li>дневник питания и понятная оценка рациона.</li></ul></div><div class="sv-program__mini"><b>ТАРЕЛКА</b><i></i><i></i><i></i></div></article>
          <article><div class="sv-program__num">02</div><div><span>Неделя 2</span><h3>Вкусная еда без запретов</h3><p>Учимся оставлять в рационе любимую еду и при этом получать больше насыщения.</p><ul><li>простые рецепты для обычной домашней жизни;</li><li>как адаптировать любимые блюда под свои цели;</li><li>система приёмов пищи без скуки и однообразия.</li></ul></div><div class="sv-program__mini sv-program__mini--orange"><b>РЕЦЕПТ</b><i></i><i></i><i></i></div></article>
          <article><div class="sv-program__num">03</div><div><span>Неделя 3</span><h3>Привычки и сложные ситуации</h3><p>Закрепляем изменения там, где обычно ломается даже хорошо составленный план.</p><ul><li>тяга к сладкому, вечерний голод и перекусы;</li><li>переедания, стресс и питание вне дома;</li><li>система, которую можно продолжать после программы.</li></ul></div><div class="sv-program__mini"><b>ПРИВЫЧКА</b><i></i><i></i><i></i></div></article>
        </div>
        <p class="sv-program__result">В результате — не набор советов, а система питания, которую можно продолжать после мастер-класса.</p>
      </div>
    </section>`);

  insertBefore('rec1793034171', `
    <section class="sv-extras">
      <div class="sv-shell sv-extras__layout"><div><span>Дополнительно</span><h2>Если захотите пойти дальше</h2><p>Это не обязательная часть мастер-класса, а отдельные инструменты для тех, кому захочется больше практики или точности.</p></div><div class="sv-extras__items"><article><b>01</b><h3>Каталог рецептов</h3><p>Практическая база блюд с понятным составом.</p></article><article><b>02</b><h3>Курс по подсчёту</h3><p>Отдельный продукт для тех, кому нужен точный учёт.</p></article></div></div>
    </section>`);

  insertBefore('rec2155105311', `
    <section class="sv-consultation">
      <div class="sv-shell"><div class="sv-consultation__head"><span>Личная работа</span><h2>Как проходит консультация</h2></div>
        <div class="sv-consultation__rows">
          <article><b>01</b><div><h3>Вы присылаете дневник питания</h3><p>Без попыток сделать его идеальным — важна ваша обычная жизнь.</p></div><div class="sv-consultation__window"><span>ЗАВТРАК</span><i></i><i></i><i></i></div></article>
          <article><b>02</b><div><h3>Я разбираю закономерности</h3><p>Показываю, где теряется насыщение и что можно улучшить без запретов.</p></div><div class="sv-consultation__window sv-consultation__window--chat"><span>Сергей</span><p>Вот здесь добавим нормальный обед 👌</p></div></article>
          <article><b>03</b><div><h3>Вы получаете понятный план</h3><p>Конкретные изменения, которые реально внедрить в ваш режим.</p></div><div class="sv-consultation__window"><span>ПЛАН</span><i></i><i></i><i></i></div></article>
        </div>
      </div>
    </section>`);

  document.querySelectorAll('#rec2154729891 .t089__text, #rec1793034171 .t089__text, #rec2154799541 .t089__text').forEach((heading, index) => {
    heading.innerHTML = heading.innerHTML.replace(/[1-3]\uFE0F?\u20E3/g, '').trim();
    heading.dataset.step = String(index + 1).padStart(2, '0');
  });

  document.querySelectorAll('.eb-stage--overview .eb-text-chunk').forEach((card, index) => {
    card.dataset.step = String(index + 1).padStart(2, '0');
    card.classList.add('eb-feature-card');
  });
  document.querySelectorAll('.eb-stage--consultation .eb-text-chunk').forEach((card, index) => {
    card.dataset.step = String(index + 1).padStart(2, '0');
    card.classList.add('eb-step-card');
  });

  const consultationCopy = document.querySelector('#rec2155111231 .t119__preface');
  if (consultationCopy) {
    consultationCopy.innerHTML = consultationCopy.innerHTML
      .replace(/Мастер-класса\s+и\s+Калорийного курса/gi, 'программы')
      .replace(/Калорийного курса/gi, 'программы');
  }

  ['rec1792587011', 'rec2154729211', 'rec2155111231'].forEach((recordId) => {
    const editorial = document.querySelector(`#${recordId} .t119__preface`);
    if (editorial) editorial.innerHTML = editorial.innerHTML.replace(/✅\s*/g, '');
  });

  const pricing = document.getElementById('rec2042806011');
  if (pricing && !pricing.querySelector('.eb-pricing-grid')) {
    const orderLinks = Array.from(pricing.querySelectorAll('a[href*="#order:"]'));
    const linkFor = (index) => orderLinks[index]?.getAttribute('href') || '#';
    const cards = [
      { name: 'Минимальный', meta: 'Программа на 21 день · Старт сразу после оплаты', price: '6 800 ₽', features: ['Мастер-класс'], href: linkFor(0) },
      { name: 'Стандартный', badge: '−30%', meta: 'Программа на 6–8 недель · Выгодная цена', price: '9 800 ₽', old: '13 700 ₽', features: ['Мастер-класс', 'Два дополнительных продукта'], href: linkFor(1), featured: true },
      { name: 'С консультацией', badge: '−30%', meta: 'Индивидуальный подход · Консультация в удобное время', price: '16 800 ₽', old: '23 000 ₽', features: ['Мастер-класс', 'Два дополнительных продукта', 'Индивидуальный разбор питания', 'Ответы на вопросы после программы', 'Тёплые слова поддержки в подарок'], href: linkFor(2) }
    ];
    const grid = document.createElement('div');
    grid.className = 'eb-pricing-grid';
    grid.innerHTML = cards.map((card, index) => `
      <article class="eb-price-card${card.featured ? ' eb-price-card--featured' : ''}">
        <div class="eb-price-card__top"><span class="eb-price-card__number">0${index + 1}</span>${card.badge ? `<span class="eb-price-card__badge">${card.badge}</span>` : ''}</div>
        <h3>${card.name}</h3><p class="eb-price-card__meta">${card.meta}</p>
        <div class="eb-price-card__price">${card.price}${card.old ? `<del>${card.old}</del>` : ''}</div>
        <ul>${card.features.map((feature) => `<li>${feature}</li>`).join('')}</ul>
        <a class="eb-price-card__button" href="${card.href}">Начать</a>
      </article>`).join('');
    pricing.append(grid);
    pricing.classList.add('eb-pricing-rebuilt');
  }

  const variant = document.body.classList.contains('eb-version-b') ? 'B' : 'A';
  const bar = document.createElement('header');
  bar.className = 'eb-sitebar';
  bar.innerHTML = `
    <a class="eb-sitebar__brand" href="#allrecords" aria-label="Похудение — это есть, наверх">Похудение — это есть!</a>
    <nav class="eb-sitebar__nav" aria-label="Главная навигация">
      <a href="#sv-program">Программа</a>
      <a href="#rec1099489631">Об авторе</a>
      <a href="#rec1098904406">Вопросы</a>
    </nav>
    <button class="eb-sitebar__search" type="button" aria-label="Поиск"></button>
    <a class="eb-sitebar__cta" href="#rec2042806011">Выбрать тариф</a>
    <button class="eb-sitebar__menu" type="button" aria-label="Открыть меню"><span></span><span></span></button>`;
  document.body.prepend(bar);

  document.querySelectorAll('a[href^="#"]').forEach((link) => {
    link.addEventListener('click', (event) => {
      const target = document.querySelector(link.getAttribute('href'));
      if (!target) return;
      event.preventDefault();
      target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  });
})();
