# Вставки приложений мастер-класса в Tilda

Статус: `implementation_ready_not_deployed`; единая вставка курса подготовлена,
production-страница Tilda ещё не переключена.

## Общий принцип

На физической странице Tilda «Мастер-класс» размещается один контейнер и один
стабильный загрузчик. Весь интерфейс и логика остаются на сервере. Email определяется общим
загрузчиком; цена, доступ и срок не передаются из Tilda. При первом входе клиент
подтверждает email шестизначным кодом из письма. После этого вход сохраняется в
этом браузере на 30 дней. Код действует 10 минут, разрешает не более пяти попыток
и после успешного входа повторно не используется.

Подписанные маркеры предложений и рецептов больше не копируются в отдельные лекции
Tilda. Единое приложение получает нужный маркер от backend только тогда, когда
участник дошёл до соответствующего пункта программы.

```html
<div
  data-edabalans-app="masterclass-course"
  data-edabalans-account-url="ВСТАВИТЬ_АДРЕС_ГЛАВНОЙ_MEMBERS_AREA"
></div>
<script src="https://app.edabalans.ru/embed.js"></script>
```

На этой же физической странице должен находиться один стандартный блок корзины
Tilda `ST100`. Он может быть визуально скрыт, но не удалён: серверная кнопка
покупки передаёт заказ именно в эту корзину.

Для закрытой проверки перед запуском остаются только внешние настройки: настоящий
адрес главной Members Area, SMTP-параметры на сервере и штатный `ST100` на копии
страницы. Саму вставку расширять дополнительным кодом не нужно.

## Старые отдельные вставки

Блоки ниже оставлены только для совместимости старого стенда. В новую страницу
21-дневного курса их не вставлять: анкета, DQS, рецепты, саморевью и персональные
предложения открываются внутри единого приложения.

## Конкретные места старого стенда

### Задание №1 — начальная анкета

```html
<div data-edabalans-app="onboarding-questionnaire"></div>
<script src="https://app.edabalans.ru/embed.js"></script>
```

### Предложение второго дня

На этой же странице добавить стандартный блок Tilda `ST100`.

```html
<div data-edabalans-app="masterclass-offers" data-edabalans-placement="day-2-offer" data-edabalans-placement-token="ВСТАВИТЬ_МАРКЕР_DAY_2"></div>
<script src="https://app.edabalans.ru/embed.js"></script>
```

### Первая часть рецептов

На странице нужен `ST100`.

```html
<div data-edabalans-app="recipes-part-1" data-edabalans-placement="recipes-part-1-gate" data-edabalans-placement-token="ВСТАВИТЬ_МАРКЕР_RECIPES_1"></div>
<script src="https://app.edabalans.ru/embed.js"></script>
```

### Постоянный блок допматериалов после первой части

```html
<div data-edabalans-app="masterclass-offers" data-edabalans-placement="offers-hub" data-edabalans-placement-token="ВСТАВИТЬ_МАРКЕР_OFFERS_HUB"></div>
<script src="https://app.edabalans.ru/embed.js"></script>
```

### Вторая часть рецептов

На странице нужен `ST100`.

```html
<div data-edabalans-app="recipes-part-2" data-edabalans-placement="recipes-part-2-gate" data-edabalans-placement-token="ВСТАВИТЬ_МАРКЕР_RECIPES_2"></div>
<script src="https://app.edabalans.ru/embed.js"></script>
```

### Итоговое саморевью

```html
<div data-edabalans-app="closing-review" data-edabalans-placement="closing-review" data-edabalans-placement-token="ВСТАВИТЬ_МАРКЕР_CLOSING_REVIEW"></div>
<script src="https://app.edabalans.ru/embed.js"></script>
```

Если на странице после анкеты показывается предложение, ниже добавить второй
контейнер `masterclass-offers` с тем же placement и тем же подписанным маркером,
а также один общий `ST100`. Повторно подключать `embed.js` на одной странице не
требуется.

## Почтовый вход

Перед включением клиентских лекций в production в серверном `.env` настраиваются
отдельный случайный `APP_AUTH_SECRET` (не пароль админки), `SMTP_HOST`, `SMTP_PORT`,
`SMTP_USERNAME`, `SMTP_PASSWORD` и `SMTP_FROM_EMAIL`.
Для Яндекс Почты используется пароль приложения, а не основной пароль аккаунта.
Секрет не вставляется в Tilda, исходный код или GitHub.

## Корзина

Кнопка приложения не содержит самостоятельно заданной цены. Она запрашивает
актуальный вариант у backend и только затем передаёт корзине команду
`#order:Название=Цена`. Tilda webhook остаётся источником подтверждения оплаты;
нажатие кнопки само по себе не создаёт покупку и не выдаёт доступ.

Tilda может сначала прислать заказ со статусом `processing`, а затем повторить тот
же `orderid`/`paymentid` со статусом `paid`. Backend в таком случае обновляет одну
существующую оплату и выдаёт каждый положенный доступ ровно один раз; повторный
`paid` остаётся безопасным дублем.
