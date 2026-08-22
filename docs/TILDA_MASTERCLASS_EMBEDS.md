# Вставки приложений мастер-класса в Tilda

Статус: migration `20260822_0015` и серверные блоки уже выпущены в production;
вставки ещё не добавлены в реальные лекции Tilda и поэтому не видны клиентам.

## Общий принцип

В каждый T123 вставляется только контейнер нужного приложения и один стабильный
загрузчик. Весь интерфейс и логика остаются на сервере. Email определяется общим
загрузчиком; цена, доступ и срок не передаются из Tilda.

```html
<div data-edabalans-app="APP_CODE" data-edabalans-placement="PLACEMENT"></div>
<script src="https://app.edabalans.ru/embed.js"></script>
```

## Конкретные места

### Задание №1 — начальная анкета

```html
<div data-edabalans-app="onboarding-questionnaire"></div>
<script src="https://app.edabalans.ru/embed.js"></script>
```

### Предложение второго дня

На этой же странице добавить стандартный блок Tilda `ST100`.

```html
<div data-edabalans-app="masterclass-offers" data-edabalans-placement="day-2-offer"></div>
<script src="https://app.edabalans.ru/embed.js"></script>
```

### Первая часть рецептов

На странице нужен `ST100`.

```html
<div data-edabalans-app="recipes-part-1" data-edabalans-placement="recipes-part-1-gate"></div>
<script src="https://app.edabalans.ru/embed.js"></script>
```

### Постоянный блок допматериалов после первой части

```html
<div data-edabalans-app="masterclass-offers" data-edabalans-placement="offers-hub"></div>
<script src="https://app.edabalans.ru/embed.js"></script>
```

### Вторая часть рецептов

На странице нужен `ST100`.

```html
<div data-edabalans-app="recipes-part-2" data-edabalans-placement="recipes-part-2-gate"></div>
<script src="https://app.edabalans.ru/embed.js"></script>
```

### Итоговое саморевью

```html
<div data-edabalans-app="closing-review" data-edabalans-placement="closing-review"></div>
<script src="https://app.edabalans.ru/embed.js"></script>
```

Если на странице после анкеты показывается предложение, ниже добавить второй
контейнер `masterclass-offers` с тем же placement и один общий `ST100`. Повторно
подключать `embed.js` на одной странице не требуется.

## Корзина

Кнопка приложения не содержит самостоятельно заданной цены. Она запрашивает
актуальный вариант у backend и только затем передаёт корзине команду
`#order:Название=Цена`. Tilda webhook остаётся источником подтверждения оплаты;
нажатие кнопки само по себе не создаёт покупку и не выдаёт доступ.

Tilda может сначала прислать заказ со статусом `processing`, а затем повторить тот
же `orderid`/`paymentid` со статусом `paid`. Backend в таком случае обновляет одну
существующую оплату и выдаёт каждый положенный доступ ровно один раз; повторный
`paid` остаётся безопасным дублем.
