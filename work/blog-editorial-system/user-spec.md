---
# Creation date (YYYY-MM-DD)
created: 2026-08-31

# Status: draft | approved
status: approved

# Work type: feature | bug | refactoring
type: feature
---

# User-spec: blog-editorial-system

> **Executor instruction.** If the project has Project Knowledge, first read its main `SKILL.md`,
> then only the materials it routes to for this task. Read `decisions.md` if it exists. Work from
> the root of the project this spec belongs to. Implement the entire user-spec. Use the execution
> skills appropriate to the work.

## What We Are Building
Превращаем уже опубликованную статическую главную блога в небольшую редакционную систему: обновляем header и hero, добавляем авторскую фотографию и рубрики, создаём единый шаблон публичной Markdown-статьи и выпускаем первые шесть материалов. Главная, SEO страницы, related-блок и CTA используют один валидируемый manifest; короткие вставки в Markdown вызывают только заранее разрешённые адаптивные компоненты.

Первый выпуск не распознаёт посетителей и не персонализирует предложения по cookies/CRM. Общая cross-site identity-система исследуется отдельно и получит отдельный user-spec перед любым сбором данных или migration.

## Why
Сейчас блог умеет показывать только вручную зашитую главную с карточками-заглушками. Без общего публикационного контура каждая статья потребовала бы отдельной вёрстки, а карточки, SEO, CTA и рекомендации быстро разошлись бы. Новая система позволяет Сергею передавать исходник, получать проверенный самостоятельный Markdown и выпускать его по повторяемому разовому или пакетному процессу.

## Expected Behavior
1. Читатель открывает главную и на desktop/mobile видит «Похудение — это есть», подпись «Авторский блог Сергея Воронцова», фотографию и тезис «Пишу о питании, похудении и пищевых привычках, чтобы сделать ваше похудение проще».
2. В desktop header слева находится увеличенное «Похудение — это есть.рф» и строка «Блог Сергея Воронцова», по центру — «Главная», «Мастер-класс», «Блог», «Контакты», справа — понятная иконка темы с мягкой границей и жёлтым hover. На телефоне название и автор сохраняются в hero.
3. Читатель выбирает одну из рубрик: «Похудение», «Пищевые привычки», «Калории», «Тренировки», «Качество питания», «Личное», «ЗОЖ». Отдельного заголовка «Статьи» над каталогом нет; радиус внешней карточки уменьшается с текущих `12px` до `10px` во всех breakpoint.
4. Карточка ведёт на стабильный публичный URL статьи. Article shell содержит заголовок, excerpt/введение, hero/media, тело, компактное содержание, theme toggle, закрытые CTA-вставки, три related-материала и общий footer.
5. На desktop содержание доступно из закреплённой кнопки/popover, на mobile — в потоке страницы. Содержание показывается при трёх и более `h2` и скрывается при нуле, одном или двух. Якоря стабильны и доступны по клавиатуре.
6. В Markdown допустимы только канонические текстовые элементы и короткие allowlisted component calls. Raw HTML/JS, iframe, inline styles и неизвестные компоненты не исполняются.
7. Для разовой статьи интегратор сам предлагает категорию, CTA и related, согласует содержательный выбор и публикует. Для пакета интегратор ставит писарю полный source-led task, получает прошедшие writer gates MD, сам расставляет компоненты и выпускает пакет после общих проверок.
   Related validation запрещает ссылку на текущую статью, неизвестный source ID и материал, чей publish status не допускает публичную выдачу.
8. Первый пакет публикуется сразу индексируемым и содержит exact Pikabu sources: `13277231`, `11401696`, `11927800`, `11269472`, `12237133`, `11875492`. Из текстов удалены платформенные хвосты, обращения к Pikabu и приманки на несуществующие комментарии.

### Initial article manifest contract

| Source ID | Публичный заголовок | Slug | Рубрика | Основной CTA | Related source IDs |
|---|---|---|---|---|---|
| `13277231` | Сколько времени нужно на похудение? | `skolko-vremeni-nuzhno-na-pohudenie` | Похудение | Бесплатный интенсив | `11401696`, `11927800`, `11875492` |
| `11401696` | Похудение начинается не с похудения | `pohudenie-nachinaetsya-ne-s-pohudeniya` | Похудение | Бесплатный интенсив | `13277231`, `11927800`, `12237133` |
| `11927800` | Почему японцы худые, а ты нет? | `pochemu-yapontsy-hudye-a-ty-net` | Качество питания | Мастер-класс | `11401696`, `11875492`, `12237133` |
| `11269472` | Температура воды для приёма внутрь | `temperatura-vody-dlya-priema-vnutr` | ЗОЖ | Telegram | `12237133`, `11875492`, `11927800` |
| `12237133` | Самый здоровый человек на планете | `samyy-zdorovyy-chelovek-na-planete` | ЗОЖ | Telegram | `11269472`, `11927800`, `11401696` |
| `11875492` | Неприятная правда про мёд | `nepriyatnaya-pravda-pro-med` | Качество питания | Мастер-класс | `11927800`, `11269472`, `13277231` |

Для каждой записи `excerpt` — самостоятельное описание в 1–2 предложениях длиной до 180 символов, без Pikabu, комментариев и неподтверждённых обещаний; оно проходит writer review и schema length check. `hero` выбирается из первого смыслового медиа исходника, подтверждённого в handoff, сохраняется локально с provenance и обязательным осмысленным `alt`. Если первое медиа является служебным/декоративным, handoff явно назначает следующее; отсутствие принятого hero блокирует первый пакет.

## Acceptance Criteria
- [ ] Header и hero содержат точные утверждённые строки, найденную owner-фотографию, семь перечисленных рубрик и радиус карточки `10px`; композиция остаётся читаемой на `360/430/768/1440px` в обеих темах.
- [ ] Заголовок «Статьи» отсутствует; общий footer и существующее сохранение темы продолжают работать.
- [ ] Все шесть exact source ID доступны по slug из таблицы, индексируются и представлены настоящими карточками, построенными из одного manifest.
- [ ] Для каждой статьи title/category/CTA/related совпадают с таблицей; excerpt удовлетворяет правилу 1–2 предложений/180 символов; hero имеет локальный файл, provenance и непустой alt; canonical и OpenGraph указывают на текущую статью.
- [ ] TOC появляется ровно при `h2 >= 3`, использует детерминированные anchors и работает мышью и клавиатурой.
- [ ] Markdown не может исполнить raw HTML/JS; неизвестные directives, небезопасные URL/аргументы и дублированные slugs останавливают validation до публикации.
- [ ] Required media хранится в owned asset path и не зависит от Pikabu hotlink; отсутствие optional media не создаёт broken image.
- [ ] Каталог компонентов имеет один документированный синтаксис и owner; публичные CTA destinations берутся из нового типизированного code registry, принадлежащего соответствующим продуктовым/Telegram-модулям, а не копируются в тексты статей.
- [ ] Related validation отклоняет self-link, неизвестную и неопубликованную статью; публичный related-блок содержит ровно три разных доступных материала.
- [ ] Writer artifacts для каждого source ID доказывают full-source retrieval, удаление платформенных хвостов, source/fact review и итоговый `pass`.
- [ ] Первый production release считается готовым только после прохождения checks всеми шестью статьями.
- [ ] Документирован разовый и пакетный workflow с правилами выбора CTA/related, owner review и публикации.

## Constraints
- Сохраняются Inter, утверждённая палитра, light/dark-поведение и существующий общий footer.
- `platform.blog` владеет публичными routes/shell/template; `platform.content` — Markdown-диалектом, авторским голосом и writer gates; продуктовые модули — CTA-фактами и ссылками; `operations.proxy` — публичной границей host.
- Начальный канон — Git-backed Markdown и один schema-validated manifest для slug/title/excerpt/category/hero/related/CTA/status/source. Миграция БД не добавляется.
- Related разрешается только на другую manifest-запись с публичным publish status; self/unknown/unpublished reference останавливает validation.
- «Маленький скрипт» в терминологии владельца реализуется как закрытый declarative component call, который рендерит доверенный серверный код, а не как JavaScript из статьи.
- Переиспользуются sanitizer `article_markup` и существующий allowlist-pattern компонентов. Slug разрешается только через manifest lookup, а не соединением filesystem path.
- В выпуск не входят visitor identity, персональный offer, tracking cookie, fingerprinting и раскрытие CRM-state.
- Публичный CTA-каталог — небольшой versioned code contract, не database lookup: каждый product/Telegram owner поставляет стабильные label, destination и tracking key; цены и личные условия запрещены. Manifest validation требует разрешить каждый directive до deploy. Публичная статья не зависит от PostgreSQL. Смена destination требует проверенного code release; неизвестная запись ломает CI, а не убирает CTA у читателя.
- Полные Pikabu snapshots, browser profiles и рабочие корпуса писаря остаются вне Git; коммитятся только publishable owner content, разрешённые media и provenance metadata.
- Платный материал Мастер-класса не раскрывается целиком через teaser component.

## Risks
- **Небезопасный Markdown или аргументы компонента:** возможны XSS или неожиданные внешние ссылки. **Снижение риска:** закрытая грамматика, allowlisted renderer, sanitizer, hostile-input tests и publish gate.
- **Расхождение главной и статьи:** вручную изменённая карточка может перестать соответствовать материалу. **Снижение риска:** cards, SEO и related строятся из одного manifest.
- **Пропавшие media:** Pikabu hotlink может исчезнуть. **Снижение риска:** разрешённые owner-media копируются в owned asset route, provenance сохраняется, required files валидируются.
- **Устаревшие health claims:** популярный старый пост не является автоматически актуальным доказательством. **Снижение риска:** full-source writer route и отдельный primary-source review существенных утверждений.
- **Устаревший product CTA:** destination может измениться. **Снижение риска:** versioned product-owned registry, отсутствие цен/личных условий, CI resolution test и обычный code release при смене ссылки.
- **Частичный выпуск шести статей:** наполовину заполненная главная может выглядеть готовой. **Снижение риска:** все шесть publishable artifacts и production smoke обязательны до объявления выпуска.
- **Расширение identity-scope:** cookies могут выглядеть как небольшая доработка CTA. **Снижение риска:** identity остаётся в отдельном research/spec/migration track.

## Accepted Decisions
- Выбран тезис hero «Пишу о питании, похудении и пищевых привычках, чтобы сделать ваше похудение проще»: это утверждённая владельцем компактная формулировка.
- Как обратимое техническое допущение используется существующее owner-изображение из блока «Об авторе» (`https://static.tildacdn.com/tild6131-3761-4733-b863-653238373732/image.png`): пользователь попросил фотографию, после пакета вопросов сказал, что на всё ответил, а этот точный принадлежащий ему asset уже найден. Само изображение не изменяется; адаптивно меняется только crop.
- Для первого пакета выбраны три основные статьи о похудении и три фактурно другие темы — вода, Брайан Джонсон и мёд; три почти повторяющих друг друга статьи о начале похудения отклонены.
- Выбраны устойчивые рубрики «Личное» и «ЗОЖ» вместо неинформативного общего «Прочее»; мёд относится к «Качеству питания».
- Статьи индексируются сразу, потому что владелец ещё не продвигал URL и явно попросил публичную публикацию.
- CTA первого выпуска назначается редакционно по таблице; cookie-based guessing отклонён до отдельного утверждения identity-системы.
- Для первой версии выбран Git-backed Markdown плюс manifest: это соответствует handoff писаря и не требует преждевременной миграции или админки.
- Короткие server-rendered directives выбраны вместо raw HTML/JavaScript, чтобы компоненты оставались безопасными, адаптивными и централизованно управляемыми.
- Related задаются явно по таблице вместо непрозрачного similarity-алгоритма, чтобы рекомендации были содержательными и тестируемыми.
- CTA registry разрешается из versioned code во время validation/rendering и не обращается к БД: это проще и не связывает доступность публичной статьи с PostgreSQL; обновление ссылки выполняется обычным code release.

## Testing

**Unit tests:** нужны — manifest/schema, slug, anchors, порог TOC, directives, hostile arguments, sanitization, media и related являются чистой детерминированной логикой; unit-уровень быстрее и точнее всего локализует ошибку без HTTP/browser шума.

**Integration tests:** нужны — homepage/article HTTP routes, 404, canonical/OG, component output, assets и proxy paths зависят от соединения router/template/static/Caddy contract, поэтому pure unit не доказывает пользовательский ответ.

**E2E tests:** нужны пропорциональные browser/visual checks — responsive geometry, light/dark и клавиатурное поведение TOC проявляются только в DOM/CSS/JS; более дешёвые тесты не доказывают их. Cross-service identity E2E вне scope.

## Verification

### Agent Verification

| Step | Expected Result |
|------|-----------------|
| Валидировать шесть writer packs и manifest | Exact source IDs, `pass` artifacts, уникальные slugs, валидные categories/assets/related/CTA; нет Pikabu/comment bait tails |
| Запустить backend unit/integration и policy tests | Все новые и существующие blog/content/deploy checks проходят |
| Отрендерить главную на 360, 430, 768 и 1440 в light/dark | Утверждённая геометрия header/hero/cards, читаемый текст, жёлтый hover темы, нет overflow |
| Открыть каждую статью и проверить TOC/components | Стабильные anchors, безопасные адаптивные components, правильные CTA/related/footer и единая тема |
| Проверить response metadata и source | Indexable response, один canonical, обязательные OG fields, нет raw directives/unsafe markup |
| Выпустить через main и выполнить production smoke | Главная, шесть URL, assets и CTA destinations отвечают; сбой идёт по существующему rollback path |
| Проверить component contract и editorial workflow | Документы называют единственный синтаксис/owner, разовый и пакетный потоки и не противоречат manifest/schema/module cards |

### User Verification
- Посмотреть production-главную и одну статью на desktop/mobile для субъективной оценки визуального результата.
- Просмотреть шесть статей и подтвердить сохранность авторского голоса; CTA и related проверяются не по субъективной «уместности», а по зафиксированной таблице initial manifest contract.
