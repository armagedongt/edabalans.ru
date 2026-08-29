# Handoff: первая часть Системы рецептов

Статус: `локально завершено`

Основной commit: `a6271ebe0640182f88ed95c59dbc03b2796f1c23`
(`content: draft recipe system and layered meal constructor`).

## Что изменено

### Исследование, архитектура и решения

- `work/recipe-catalog/code-research.md`
- `work/recipe-catalog/day-06-semantic-map.md`
- `work/recipe-catalog/decisions.md`
- `work/recipe-catalog/first-part-system.md`
- `work/recipe-catalog/user-spec.md`
- `work/recipe-catalog/logs/userspec/interview.yml`
- `work/recipe-catalog/fact-check-notes.md`

### Материалы первой части

- `work/recipe-catalog/drafts/01-anchor-points.md`
- `work/recipe-catalog/drafts/02-oatmeal-evolution.md`
- `work/recipe-catalog/drafts/03-how-to-make-food-tasty.md`
- `work/recipe-catalog/drafts/04-why-recipe-may-not-fit.md`
- `work/recipe-catalog/drafts/05-meal-constructor.md`
- `work/recipe-catalog/drafts/06-store-food-without-cooking.md`
- `work/recipe-catalog/drafts/07-demo-same-products-four-forms.md`
- `work/recipe-catalog/drafts/08-demo-one-meal-three-characters.md`
- `work/recipe-catalog/drafts/09-first-recipes-selection.md`
- `work/recipe-catalog/drafts/10-system-of-recipes-offer.md`

### Дизайн конструктора

- `work/recipe-catalog/visuals/design-contract.md`
- `work/recipe-catalog/visuals/prompts.md`
- `work/recipe-catalog/visuals/meal-constructor-variant-1-stacked.png`
- `work/recipe-catalog/visuals/meal-constructor-variant-2-route.png`
- `work/recipe-catalog/visuals/meal-constructor-variant-3-layers.png`
- `work/recipe-catalog/visuals/meal-constructor-variant-4a-full-stack.png`
- `work/recipe-catalog/visuals/meal-constructor-variant-4b-grouped-stack.png`
- `work/recipe-catalog/visuals/meal-constructor-variant-4c-grouped-with-spices.png`

## Зафиксированные дизайн-решения

- Основной формат иллюстрации — горизонтальный 16:9.
- Конструктор показывается полноширинными горизонтальными слоями, а не маршрутом,
  стрелками или сходящимися дорожками.
- Каждый слой перечисляет конкретные варианты выбора. Белки, гарниры,
  форм-факторы, специи, соусы и топпинги не заменяются общими иконками.
- Основная структура содержит одиннадцать слоёв и три группы: «Собираем основу»,
  «Делаем вкусно», «Проверяем».
- Объём остаётся отдельным слоем с тремя вариантами: овощи, фрукты/ягоды и жидкая
  часть блюда.
- Специи и ароматика находятся внутри конструктора отдельным слоем, но не становятся
  отдельным учебным модулем.
- Основной визуальный кандидат —
  `meal-constructor-variant-4c-grouped-with-spices.png`.
- PNG-файлы являются концептами. Для публикации выбранную схему нужно пересобрать
  в редактируемом макете и проверить на фактической ширине материала.

## Выполненные проверки

- Все десять читательских черновиков проверены через
  `tools/validate_author_draft.py`; итоговый статус каждого — `pass`.
- Для подборки рецептов явно разрешено сохранение исходных Telegra.ph-ссылок;
  после этого проверка защищённых ссылок прошла.
- Выполнен поиск незакрытых `TODO`, `TBD`, `PENDING` и `PLACEHOLDER` внутри
  `work/recipe-catalog`; совпадений нет.
- `git diff --cached --check -- work/recipe-catalog` выполнен без ошибок после
  исправления пробелов и лишних пустых строк.
- `git show --check a6271ebe0640182f88ed95c59dbc03b2796f1c23` выполнен без ошибок.
- Состав основного commit проверен через `git diff-tree`: в нём только 25 файлов
  `work/recipe-catalog` этой задачи.
- Push, merge, перенос в `main` и deploy не выполнялись.

## Незавершённые вопросы

- До публикации пересчитать актуальные КБЖУ, порции и DQS финальной овсянки.
- Отобрать реальные карточки и фотографии магазинных продуктов для материала 06.
- Утвердить окончательный список рецептов первой части и подготовить финальные
  граммовки/карточки.
- Выбрать production-компоновку между 4a, 4b и 4c. Рекомендация текущего потока —
  4c, потому что в ней отдельно видны специи и смысловые группы.
- Уточнить финальный список вариантов внутри слоёв: особенно белковые продукты,
  гарниры, соусы и топпинги. Сейчас это содержательно полный рабочий набор, но не
  закрытый справочник.
- Пересобрать выбранную инфографику в редактируемом формате и проверить
  типографику, контраст и читаемость на экране мастер-класса.
- Отдельным решением перенести утверждённые материалы из `work/` в канонический
  runtime мастер-класса и заменить старый placeholder «Топпинги» конструктором.

## Состояние рабочего дерева

В репозитории остались многочисленные посторонние изменения других потоков. Они не
вошли в основной commit и не принимались этой задачей. До создания handoff в индексе
уже находилась другая версия `work/integration-handoff.md`; её staged-содержимое
сохранено отдельно от результата этого потока.
