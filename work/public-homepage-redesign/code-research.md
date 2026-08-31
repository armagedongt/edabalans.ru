# Техническое исследование: публичная главная

> **Уточнение границы от 30.08.2026.** Ниже зафиксирован существующий server
> pricing/checkout как доступный платформенный механизм. После уточнения владельца
> он не выбран для новой главной: публичная страница сохраняет штатные purchase
> actions и корзину Tilda, а серверный интерфейс остаётся внутри `/lk`.
> Рекомендации ниже о подключении `GET/POST /api/pricing/site` не являются
> принятым решением.
>
> **Уточнение сборки от 30.08.2026.** Паттерн «короткий T123 → server bundle»
> принят только для отдельной `noindex` preview-страницы. Production-главная
> собирается из того же repo-source в один автономный T123 со всем HTML/CSS/JS и
> текстом, без runtime-зависимости от app-домена; это не схема `/lk`.

Дата: 30.08.2026  
Статус: `current` для подготовки user-spec  
Исследуемая граница: новая публичная главная на Tilda с серверным кодом,
существующей корзиной Tilda и постепенным уходом публичного сайта с Tilda.

Документ фиксирует фактический технический контур. Он не определяет визуальный
дизайн и не является источником текстов, цен или состава продуктов.

## Рекомендуемая техническая граница

Устойчивый владелец новой главной — отдельный модуль `products.public-site`.
Он должен владеть только исходниками публичной страницы, её Tilda-loader,
адаптивным представлением, SEO-представлением и page-level интеграцией. Он
потребляет, но не копирует:

- `platform.content` — опубликованные тексты и авторский голос;
- `products.catalog` — названия и дескрипшны продуктов/тарифов;
- `platform.commerce` — цены, состав прав, checkout и payment webhook;
- `platform.auth` — ссылку на существующий вход в Tilda Members Area;
- `products` — общий `site-footer.js` и серверную раздачу пользовательских assets.

Ближайшая реализация должна оставлять Tilda оболочкой и маршрутизатором домена:
отдельная непоисковая Tilda-страница содержит короткий T123-loader серверного
bundle, один штатный `ST100` и mount общего подвала. Весь большой HTML/CSS/JS не
следует хранить внутри T123: это создаст второй непроверяемый источник кода и
усложнит rollback.

## 1. Entry Points

### Опубликованная Tilda-страница

- `https://похудение-это-есть.рф/` — текущая production-главная, Tilda project
  `9532923`, page `70714769`. Фактические 66 records, SEO и внешние подключения
  перечислены в `work/public-homepage-redesign/current-homepage-inventory.md`.
- `https://похудение-это-есть.рф/lk` — закрытая Tilda Members Area страница.
  Новая главная только ссылается на неё; логин, группа и серверный ЛК не входят в
  область редизайна.

### Публичные server assets

- `backend/app/app_routes.py::public_asset(path: Path, stable_loader: bool = False) -> FileResponse`
  — общая раздача публичных assets. Для stable loaders задаёт
  `Cache-Control: no-cache` и `Access-Control-Allow-Origin: *`.
- `backend/app/app_routes.py::embed_loader() -> FileResponse` — `GET /embed.js`,
  постоянный загрузчик приложений из T123.
- `backend/app/app_routes.py::site_footer_loader() -> FileResponse` —
  `GET /site-footer.js`, отдельный стабильный загрузчик публичного подвала.
- `backend/app/app_routes.py::app_fragment(app_code: str) -> Response` —
  `GET /apps/{app_code}.html`; allowlist уже включает `masterclass-sales`, но
  отдельного app/page entry point для новой главной пока нет.

### Цены и checkout

- `backend/app/pricing_routes.py::public_site_pricing(db, settings) -> dict` —
  `GET /api/pricing/site`; возвращает только включённые `site_tariffs` активной
  версии, добавляя названия/описания из продуктового каталога.
- `backend/app/pricing_routes.py::public_site_checkout(body: PublicCheckoutIn, db, settings) -> dict`
  — `POST /api/pricing/site/checkout`; принимает только стабильный `price_code`,
  создаёт двухчасовой `OfferCheckout` и возвращает Tilda `cart_command`.
- `backend/app/pricing_routes.py::safe_order_name(value: str) -> str` — удаляет
  из имени заказа символы, способные повредить синтаксис `#order:`.
- `backend/app/static/apps/masterclass-sales.html` — существующий server-rendered
  блок трёх тарифов. Загружает `/api/pricing/site`, создаёт checkout и передаёт
  полученную команду Tilda через `location.hash`; это ближайший повторно
  используемый образец, но его нынешний визуальный слой не является дизайном
  новой главной.

### Payment webhook

- `backend/app/tilda_routes.py::tilda_payment(request, db, settings) -> dict[str, str]`
  — `POST /integrations/tilda/payments`; принимает только form-urlencoded body до
  256 KiB и проверяет `X-Tilda-Webhook-Token` constant-time сравнением.
- `backend/app/tilda_service.py::process_tilda_payment(db, payload) -> dict[str, str]`
  — находит checkout/продукт, сохраняет payment, выдаёт права и сохраняет
  attribution по referer.
- `backend/app/tilda_service.py::validate_checkout(checkout, user, amount, event_at, existing_payment=None) -> None`
  — проверяет срок, одноразовость, email-владельца и точную сумму. Для
  `checkout_kind="public_site"` привязывает первоначально анонимный checkout к
  пользователю из подтверждённого Tilda webhook.

### Общий подвал

- `backend/app/static/site-footer.js::boot()` — монтирует подвал во все
  `[data-edabalans-site-footer]`.
- `backend/app/static/site-footer.js::mount(root, index)` — идемпотентно строит
  разметку, контакты, интенсив и юридические ссылки; признак
  `data-edabalans-site-footer-mounted` защищает от повторного монтажа.
- T123-контракт: `<div data-edabalans-site-footer></div>` и
  `<script src="https://app.edabalans.ru/site-footer.js" defer></script>`.

## 2. Data Layer

- `backend/app/models.py::PricingVersion` / `pricing_versions` — номер версии,
  статус `draft|active|archived`, даты действия, авторы публикации. Активная
  версия неизменяема; изменение начинается с нового draft.
- `backend/app/models.py::PriceEntry` / `price_entries` — стабильный `code`,
  `section`, `product_code`, `resource_codes`, три вида суммы, валюта,
  `enabled`, порядок. Уникальность: `(version_id, code)`.
- `backend/app/models.py::OfferCheckout` / `offer_checkouts` — анонимный или
  пользовательский checkout, версия и код цены, снимок ресурсов, сумма, срок,
  статус и связанный payment. Public-site checkout живёт два часа.
- `backend/app/models.py::Payment` / `payments` — payment snapshot, внешние order
  и payment IDs, email на момент покупки, исходный product string, amount,
  status, pricing provenance и raw webhook. Уникальности обеспечивают
  идемпотентность по source + внешнему order/payment ID.
- `backend/app/models.py::UserAccess` / `user_accesses` — выданное право на
  ресурс, источник, payment, срок и отзыв. Уникальность защищает повторную выдачу
  одного ресурса по одному payment.
- `backend/app/product_catalog_service.py::tariff_public(db, code) -> dict | None`
  — выдаёт публичные поля тарифа из `managed_document_versions`; цены и
  технические права в этом документе отсутствуют.

Миграция `backend/migrations/versions/20260823_0020_pricing_catalog.py` создала
стабильные коды `site.masterclass.basic`, `site.masterclass.recipes` и
`site.masterclass.consult`. Суммы в migration — начальный seed, а не живой
источник: production-значения принадлежат активной версии PostgreSQL.

Новая главная не требует новой таблицы. Контентная структура страницы может
первоначально жить как версионируемый repo-source владельца
`products.public-site`; продуктовые названия и деньги должны приходить от своих
существующих владельцев.

## 3. Similar Features

### Server bundle внутри Tilda

- `backend/app/static/embed.js` — находит `[data-edabalans-app]`, получает
  fragments с `app.edabalans.ru` и внедряет их без iframe. Это подтверждённый
  паттерн «короткий T123 → version-controlled server code».
- `backend/app/static/apps/masterclass-sales.html` — готовый публичный pricing →
  checkout → Tilda cart flow. Для главной следует переиспользовать его API и
  event sequence, а не текущую CSS-разметку или локальные суммы.
- `backend/app/static/site-footer.js` — отдельный публичный компонент с прозрачным
  фоном и наследованием typography/color. Новая главная предоставляет ему
  подходящий окружающий фон и цвет, но не копирует markup/links.

### Существующий homepage prototype

- `prototypes/homepage-redesign/build-previews.ps1` — читает полный локальный
  HTML-снимок из `D:\сайт`, переписывает assets на локальный server, удаляет
  production analytics и внедряет общие/вариантные CSS и `preview.js`.
- `prototypes/homepage-redesign/serve-preview.ps1` — loopback-only TCP preview
  для `/version-a` и `/version-b`; assets также читаются из `D:\сайт`.
- `prototypes/homepage-redesign/common.css`, `version-a.css`, `version-b.css` —
  две визуальные интерпретации поверх старой Tilda DOM-структуры.
- `prototypes/homepage-redesign/preview.js` — вставляет новые секции, header и
  pricing cards в существующие `rec*` nodes.

Этот prototype нельзя продолжать как production foundation:

1. он зависит от локальных абсолютных путей и нестабильных Tilda `rec*` IDs;
2. `preview.js` жёстко хранит маркетинговые тексты и цены `6 800 / 9 800 / 16 800`;
3. pricing cards копируют исходные live `#order:` links;
4. README прямо говорит, что нажатие открывает действующую production-корзину;
5. исходный снимок и assets не находятся в Git, а `dist/` игнорируется;
6. палитра и структура были приняты до нового решения «сначала смысл, затем
   референсы».

Prototype остаётся evidence отдельных приёмов и regression reference, но новая
страница должна иметь собственный семантический DOM и безопасный checkout adapter.

## 4. Integration Points

### Tilda page shell

Для отдельной preview-страницы нужны:

- один T123 с mount и versioned server script/style;
- один штатный `ST100`, подключённый к действующему payment receiver;
- mount существующего `site-footer.js`;
- отключение глобальных Header/Footer страницы, если они назначены в проекте;
- запрет индексации preview-страницы;
- отдельный URL, не назначенный главной страницей проекта.

По официальной документации Tilda header/footer отключаются в
`Настройки страницы → Дополнительно`, индексация — в
`Настройки страницы → SEO → Отображение в поисковой выдаче`, а главная выбирается
в `Настройки сайта → Главная страница`. Следовательно, preview и переключение
можно выполнить без смены домена и без редиректа текущей страницы.

### Cart and checkout

Последовательность после включения нового каталога:

```text
page bundle → GET /api/pricing/site
            → POST /api/pricing/site/checkout {price_code}
            → location.hash = server cart_command
            → Tilda ST100 / Robokassa
            → POST /integrations/tilda/payments
            → payment + exact accesses in PostgreSQL
```

`PRICING_CATALOG_ENABLED=false` сейчас намеренно заставляет оба public pricing
endpoint отвечать `503`. Поэтому визуальную preview можно собирать раньше, но
боевое end-to-end тестирование трёх новых тарифов невозможно до отдельного
согласованного переключения feature flag и Tilda-настроек.

### Auth and `/lk`

Публичной главной авторизация не нужна. Она ведёт на существующий `/lk`; Tilda
Members Area остаётся единственным клиентским входом. Нельзя подключать к новой
главной challenge/email/code flow из общих приложений или создавать новую
session только ради ссылки на кабинет.

### SEO and analytics

- Tilda владеет page Title, Description, OG и canonical на переходном этапе.
- Семантический server DOM должен содержать единственный H1, последовательные
  H2/H3, alt для контентных изображений и реальные ссылки без JS-only навигации.
- Preview должна быть `noindex`; production metadata выставляется только после
  утверждения содержания.
- Текущая страница подключает Яндекс Метрику, Mail.ru, Tilda Stat и внешние video
  embeds. Новый bundle не должен повторно инициализировать те же счётчики.
- Planned attribution из `docs/plans/WEBSITE_CLICK_PURCHASE_ATTRIBUTION.md` не
  добавляется автоматически; payment webhook уже сохраняет referer/UTM при
  наличии этих полей.

## 5. Existing Tests

Фреймворк — `pytest` + FastAPI `TestClient`; БД-тесты используют SQLite memory
engine и dependency overrides.

- `backend/tests/test_pricing_catalog.py::test_public_checkout_binds_new_tilda_user_and_keeps_pricing_snapshot()`
  — полный public pricing → checkout → paid webhook → точные права и provenance.
- `backend/tests/test_pricing_catalog.py::test_public_checkout_rejects_tampered_amount_without_creating_payment()`
  — изменённая сумма не создаёт payment/access.
- `backend/tests/test_pricing_catalog.py::test_draft_is_editable_but_does_not_change_public_prices()`
  — при выключенном feature flag public API возвращает 503.
- `backend/tests/test_app_assets.py::test_stable_site_footer_loader_is_public()`
  — loader, cache policy, ссылки, idempotent mount и интерактивность подвала.
- `backend/tests/test_app_assets.py::test_stable_embed_loader_is_public()` —
  публичность и no-cache общего Tilda loader.
- `backend/tests/test_tilda_payments.py` — токен webhook, нормализация payload,
  idempotency, выдача прав и пограничные payment cases.

Пока отсутствуют:

- tests собственного homepage bundle/loader;
- DOM/component tests единственного H1, доступной навигации и CTA;
- test, что preview mode не создаёт checkout и не открывает production cart;
- E2E новой страницы с настоящим Tilda ST100;
- автоматическая проверка SEO metadata, analytics deduplication и footer mount на
  новой странице;
- visual/responsive regression для новой семантической DOM-структуры.

## 6. Shared Utilities

- `app_routes.public_asset()` — стабильная раздача публичного JS/CSS/HTML с
  подходящей cache policy.
- `pricing_service.active_pricing_version()` и
  `pricing_service.pricing_entry_map()` — единая выборка живой версии и строк;
  page layer не должен выполнять собственные queries.
- `product_catalog_service.tariff_public()` — public naming/descriptor по
  стабильному product code.
- `tilda_service.find_offer_checkout()` — разрешение полного и короткого checkout
  ID из строки товара Tilda.
- `tilda_service.attribution_from_url()` — извлечение UTM/ref из referer.
- `site-footer.js::boot()` — повторно вызываемый mount после динамической вставки
  DOM.

## 7. Potential Problems

1. **Prototype может открыть реальную корзину.** Локальные A/B версии сохраняют
   production `#order:` links. Нельзя давать их как безопасный кликабельный
   preview; checkout CTA должен быть disabled либо работать в отдельном явно
   тестовом режиме.
2. **Устаревшие hardcoded факты.** Prototype хранит собственные цены, названия и
   маркетинговые формулировки; опубликованная страница и VSL также не являются
   живым коммерческим каноном.
3. **Public checkout write-amplification.** `POST /api/pricing/site/checkout` не
   требует auth и не имеет видимого rate limit; после включения автоматические
   запросы смогут создавать множество pending rows. До широкого запуска нужны
   наблюдаемость/очистка expired checkout и решение о rate limiting.
4. **Feature flag является release boundary.** При `false` server sales block
   показывает ошибку; при `true` сразу начинает создавать реальные checkout.
   Включать его до трёх тестовых покупок и настройки одной общей Tilda-группы
   нельзя.
5. **Tilda editor state не версионируется Git.** Page ID, ST100 receiver,
   noindex, Header/Footer и назначение homepage существуют во внешнем UI. Перед
   выпуском нужен зафиксированный release checklist и снимок исходной страницы.
6. **Два источника footer.** `embed.js` содержит минимальный legal footer для
   приложений, а `site-footer.js` — публичный footer сайта. На главной используется
   только второй; подключение app footer создаст дубликат юридического блока.
7. **Analytics duplication.** Tilda уже подключает project-level counters. Если
   bundle повторит loader/counter, один просмотр/CTA будет считаться несколько
   раз.
8. **CSP отсутствует в исследованном page contract.** T123 и динамические external
   video/scripts расширяют supply-chain boundary; внешние origins и embeds нужно
   перечислить явно и не добавлять новые без необходимости.
9. **Server asset cache.** Stable loader раздаётся с `no-cache`, но вложенный
   bundle должен иметь versioned URL/content hash; иначе Tilda и браузер могут
   смешать loader новой версии со старыми CSS/assets.
10. **Нестабильные `rec*` IDs.** Любая реализация, завязанная на текущие Tilda
    records, сломается при редактировании/копировании страницы. Новый root должен
    быть один и принадлежать server bundle.
11. **Переключение homepage — существенное production-изменение.** Оно требует
    отдельного подтверждения владельца, заранее проверенного rollback и не должно
    совмещаться с первым включением ещё непроверенного pricing flag.

## 8. Constraints & Infrastructure

- Tilda остаётся публичным доменным shell, корзиной, Members Area и текущим login.
- На странице покупки остаётся штатный Tilda `ST100`; новый checkout не заменяет
  Robokassa Result URL и payment receiver.
- `PRICING_CATALOG_ENABLED` по умолчанию `false`; это production environment
  variable, секреты/реальные данные в Git не попадают.
- Допустимые CORS origins задаются `ALLOWED_ORIGINS`; config автоматически
  добавляет IDNA-вариант кириллического домена. Public asset routes отдельно
  выставляют `Access-Control-Allow-Origin: *`.
- `app.edabalans.ru` и API доступны только через Caddy/HTTPS; backend/PostgreSQL
  наружу не публикуются.
- Репозиторий имеет грязный рабочий tree и активные параллельные потоки;
  `docs/modules.toml`, `site-footer.js` и связанные canonical docs нельзя менять
  из этого потока до интеграционного checkpoint.
- `prototypes/homepage-redesign/dist/` игнорируется общим `.gitignore`; исходные
  локальные Tilda assets находятся вне repo и не являются reproducible build
  input.
- Публикация/перепубликация Tilda и изменение payment settings — внешние
  production mutations, требующие отдельного подтверждения по правилам проекта.

### Безопасный preview → release

1. Создать repo-owned homepage source и versioned public bundle без цен в HTML.
2. Добавить отдельную Tilda-страницу с одним mount/T123, одним `ST100` и
   `site-footer.js`.
3. Отключить на странице global Header/Footer, запретить индексацию и не назначать
   её главной.
4. В preview mode блокировать checkout либо использовать явный test adapter;
   никакие CTA не должны молча открывать production order.
5. Проверить desktop/mobile, keyboard, reduced motion, media, footer, SEO DOM,
   отсутствие двойной аналитики и ссылки на `/lk`.
6. После отдельного согласования подключить production pricing API и выполнить
   по одной тестовой покупке каждого тарифа с разными email; проверить payment,
   pricing snapshot, exact accesses и вход в общую группу/ЛК.
7. Сохранить прежнюю страницу опубликованной как rollback target. Только затем в
   Tilda `Настройки сайта → Главная страница` выбрать новую страницу и
   перепубликовать затронутые страницы.
8. После переключения проверить `/`, cart, webhook, `/lk`, counters, canonical,
   sitemap/robots и footer; при сбое вернуть прежнее назначение homepage.

## 9. External Libraries and Services

Новых внешних библиотек для этого контура не требуется.

- **Tilda** — page shell, ST100 cart, Members Area и homepage switch. Проверены
  официальные инструкции: [главная страница](https://help-ru.tilda.cc/homepage),
  [header/footer](https://help-ru.tilda.cc/header-footer),
  [SEO и noindex](https://help-ru.tilda.cc/search-engine).
- **Robokassa через Tilda** — неизменяемая для этой задачи payment boundary;
  Result URL остаётся Tilda URL.
- **Vidalytics/Boomstream** — текущие/каталожные video providers. Репозиторий не
  содержит единого production homepage-player adapter; решение о плеере,
  analytics и миграции видео остаётся открытым до отдельного media inventory.
- **FastAPI / SQLAlchemy** — уже используемый backend; новые API для первой
  версии главной не нужны, если существующие pricing/product/footer contracts
  достаточны.

## Открытые вопросы для user-spec

1. Нужен ли preview mode, в котором CTA полностью disabled, или отдельный
   sandbox product/cart Tilda? Первый вариант безопаснее до финального E2E.
2. Будет ли homepage source одним self-contained server fragment через текущий
   `embed.js` или отдельным `homepage.js` + versioned CSS? Отдельный loader даёт
   более чистую ownership boundary и не тянет клиентскую auth-логику.
3. Какой video provider остаётся на первой версии и какие события просмотра
   действительно нужны?
4. Какие project-level counters остаются каноническими и какие CTA events нужно
   добавить без дублирования?
5. Какая точная старая Tilda page остаётся rollback target и какой её запасной
   URL после назначения новой главной?
6. Регистрируется ли `products.public-site` до реализации или на
   интеграционном checkpoint после освобождения `docs/modules.toml`?
