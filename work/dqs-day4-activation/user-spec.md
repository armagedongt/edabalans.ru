---
created: 2026-09-19
status: draft
type: feature
---

# User-spec: dqs-day4-activation

> **Executor instruction.** If the project has Project Knowledge, first read its main `SKILL.md`,
> then only the materials it routes to for this task. Read `decisions.md` if it exists. Work from
> the root of the project this spec belongs to. Implement the entire user-spec. Use the execution
> skills appropriate to the work.

## What We Are Building

Переводим DQS с модели «право сразу открывает прямой URL» на модель
«право выдано при покупке, приложение раскрывается в шаге `day-04-dqs`». Первое
допустимое открытие одновременно раскрывает DQS во всех пользовательских входах и
не более одного раза ставит в очередь Telegram-сообщение с обычной ссылкой и
Web App-кнопкой.

Работа использует существующие `user_accesses`, `masterclass_events`, DQS routes,
шаг курса, outbox и контентный слот. Новая база, локальная DQS-авторизация,
отдельный бот или второй реестр прав не создаются.

## Why

Сейчас покупатель Мастер-класса получает право `dqs` и может открыть прямой
`/dqs` до четвёртого дня, хотя продукт должен появиться вместе с учебным
материалом. Отправка удобной ссылки в Telegram уже существует, но требует второй
кнопки и допускает повторные сообщения. Единый reveal-контракт восстанавливает
порядок курса, сохраняет общий вход и даёт участнику постоянную ссылку без спама.

## Expected Behavior

1. Подтверждённая покупка Мастер-класса выдаёт право `dqs`; до reveal приложение
   имеет состояние `entitled_locked`.
2. До шага `day-04-dqs` прямой URL, карточка ЛК и Mini App не открывают дневник и
   объясняют, что он появится в материале дня 4.
3. В открытом дне 4 после завершения предыдущих обязательных шагов участник
   нажимает одну кнопку «Открыть приложение».
4. Сервер проверяет право, день, шаг, предыдущие шаги и актуальные legal
   acceptances. Без legal acceptances он показывает общий gate и не записывает
   reveal/notification.
5. Допустимый запрос атомарно и идемпотентно создаёт `app_revealed_dqs` и при
   активном связанном Telegram — одну notification для существующего слота
   `tpl_postpurchase_dqs_app_link`.
6. DQS открывается в существующем интерфейсе и запускает туториал. Завершение
   шага курса по-прежнему зависит от конца туториала, а не от одного reveal.
7. После reveal DQS доступен из ЛК, `/dqs`, Telegram/MAX Mini App и меню
   приложений. Все входы читают один серверный availability guard.
8. Повторный, одновременный или повторённый после сетевого сбоя запрос не создаёт
   второй reveal или вторую автоматическую доставку.
9. Если Telegram не связан, DQS всё равно открывается, а интерфейс сообщает, что
   ссылка не отправлена. Автоматической отправки после будущей привязки и ручной
   кнопки повторной отправки в этой версии нет.
10. До cutover одноразовый backfill создаёт reveal для прежних пользователей по
    старым событиям открытия/reveal и пользовательским/импортированным состояниям
    со `start_date` или непустыми днями, исключая `admin_open`. После cutover
    `dqs_states` не участвует в решении о доступности.
11. Управляемое открытие `/admin/dqs` не создаёт пользовательский reveal, не
    ставит сообщение в очередь и продолжает писать аудит изменений.
12. ЛК, прямой `/dqs`, материал курса и Telegram/MAX получают состояние и
    пояснение из одного серверного application-access resolver-а. До reveal DQS
    имеет `entitled_locked` / `course_step_pending`, статус «Куплено, откроется
    позже» и пояснение о материале четвёртого дня.
13. Клиенты не хранят собственные копии access-copy. Resolver собирает entitlement,
    прогресс курса и reveal из их настоящих источников, а готовые тексты — из
    одного серверного каталога по `reason_code`.
14. Существующий `GET /api/account-auth/account` возвращает полный access payload
    внутри `applications`; direct/embed и межсервисный Telegram/MAX-адаптер
    используют тот же resolver. Межсервисный запрос не принимает непроверенный
    email или `user_id` от клиента.
15. Шаг `day-04-dqs` получает в manifest поле `access_condition_label` со
    значением `DQS четвёртого дня Мастер-класса`; именно из него resolver формирует
    конкретное условие, а DQS, ЛК и bot его не дублируют.
16. `action` имеет форму `null | {code, label, url}`. До reveal DQS возвращает
    `continue_course`, после reveal — `open_app` и `app_url`.
17. Telegram/MAX вызывают resolver через закрытую service-auth границу backend.
    Worker передаёт проверенную messenger identity; backend сам разрешает её в
    `user_id`. Публичный запрос с выбранным email/user_id запрещён.
18. Этот slice мигрирует только DQS. Для strength, recipes и metabolism общий
    resolver не меняет production-поведение, пока у каждого модуля не появится
    проверенная policy entry.

## Acceptance Criteria

- [ ] Пользователь с активным правом `dqs`, но без reveal, не может открыть DQS
      через `/dqs`, ЛК, Telegram Mini App или MAX Mini App.
- [ ] Reveal принимается только для фактического `day-04-dqs` открытого дня 4
      после всех предыдущих обязательных шагов.
- [ ] Без актуальных юридических согласий reveal и notification не создаются.
- [ ] Первый допустимый запрос создаёт один `app_revealed_dqs`; при активном
      Telegram создаёт одну outbox notification с устойчивым idempotency key.
- [ ] Два одновременных допустимых запроса и последующий retry оставляют в БД
      один reveal и не более одной notification.
- [ ] Telegram dispatcher после transient ошибки повторяет ту же notification;
      успешный retry не создаёт новое сообщение.
- [ ] Текстовая ссылка и Web App-кнопка ведут на
      `https://edabalans.ru/dqs`.
- [ ] При отсутствии связанного активного Telegram приложение открывается, а UI
      честно сообщает, что ссылка не отправлена; поздней автоматической доставки
      нет.
- [ ] Прежняя отдельная кнопка отправки ссылки удалена из материала DQS.
- [ ] Одноразовый backfill сохраняет доступ прежним пользователям, но новое
      состояние `admin_open` после cutover не раскрывает клиентский DQS.
- [ ] Reveal сам по себе не завершает шаг; шаг завершается только событием конца
      существующего DQS-туториала.
- [ ] Admin runtime продолжает открывать профиль по admin session + target user,
      не создаёт reveal/notification и пишет `admin_app_edits`.
- [ ] До reveal карточка ЛК и прямой `/dqs` показывают «Куплено, откроется позже»
      и точное условие четвёртого дня; они не используют «Доступ закрыт» или
      «Скоро».
- [ ] Telegram/MAX объясняют состояние купленного DQS до reveal и предлагают
      продолжить Мастер-класс; приложение не исчезает из пользовательского
      объяснения и не получает открывающую кнопку раньше времени.
- [ ] ЛК, direct gate, курс и мессенджеры используют один resolver и один набор
      `reason_code`/access-copy; тест меняет серверную формулировку и видит её во
      всех адаптерах без правки frontend-констант.
- [ ] `GET /api/account-auth/account` возвращает для DQS `state`, `owned`,
      `available`, `reason_code`, `status_label`, `explanation`,
      `condition_label`, `action` и `app_url`; до reveal `app_url` отсутствует.
- [ ] `course_step_pending` использует `access_condition_label` шага
      `day-04-dqs`; изменение этого поля меняет пояснение во всех адаптерах без
      изменения DQS/ЛК/bot-констант.
- [ ] Межсервисный resolver endpoint отклоняет запрос без service auth и не
      принимает произвольный клиентский email/user_id как identity.
- [ ] Регрессионные тесты подтверждают, что доступность strength, recipes и
      metabolism не изменилась после DQS cutover.
- [ ] Финальный Telegram content slot отредактирован через `edabalans-writer` и
      явно подтверждён владельцем до production deploy trigger-а.

## Constraints

- PostgreSQL, общий `user_id`, собственная серверная сессия и существующее право
  `dqs` остаются единственными источниками identity/entitlement.
- Reveal — единственный runtime-источник фактической доступности после cutover.
- Manifest курса владеет местом шага; DQS не копирует порядок курса.
- Пользовательский access payload и тексты состояний принадлежат общему resolver-у;
  отдельные приложения передают ему только код ресурса и своё точное условие.
- Telegram consumer не выдаёт право и не раскрывает приложение.
- Переиспользуются `tpl_postpurchase_dqs_app_link` и `pp_dqs_app_link`; второй
  slot/trigger не создаётся.
- Методика категорий и формулы не меняются этой задачей.
- Массовая рассылка реальным людям не выполняется; live-проверка ограничена одним
  контролируемым тестовым аккаунтом после обычного разрешения на выпуск.

## Risks

- **Закрыть DQS прежнему пользователю.** Снижение: одноразовый backfill до
  включения gate и проверка выборки без персональных данных.
- **Открыть DQS из-за состояния, созданного админом.** Снижение: исключить
  `admin_open` из backfill и никогда не читать `dqs_states` в runtime guard после
  cutover.
- **Отправить два сообщения при двойном клике.** Снижение: уникальный ключ reveal
  и стабильный idempotency key notification в одной транзакции.
- **Получить reveal без работающей доставки.** Снижение: reveal не откатывается;
  outbox хранит и повторяет ту же notification, UI не обещает отправку до enqueue.
- **Разойтись текстовой ссылкой и кнопкой.** Снижение: один URL в конфигурации и
  существующая dispatcher-проверка совпадения.

## Accepted Decisions

- DQS получает отдельный канонический README и долговременный чат, но не отдельную
  БД, auth или Telegram-движок.
- Entitlement выдаётся при покупке, availability появляется только после
  `app_revealed_dqs`.
- Legal acceptance предшествует reveal и постановке сообщения.
- Без Telegram DQS открывается, но отложенная или ручная повторная доставка не
  входит в эту версию.
- Прежний доступ переносится одноразово; `dqs_states` не становится постоянным
  вторым guard.
- Канонический пользовательский URL — `https://edabalans.ru/dqs`.
- Существующий Telegram slot переиспользуется, но production блокируется до
  утверждения его новой редакции.

## Testing

**Unit tests:** helper фактической доступности DQS, правила backfill-кандидатов и
стабильный idempotency key — нужны для явной границы состояний.

**Integration tests:** нужны для reveal route, legal gate, прямых DQS routes,
account payload, Telegram/MAX Mini App, bot menu, outbox и admin runtime.

**E2E tests:** нужен browser flow «день 4 → одна кнопка → legal при необходимости
→ DQS tutorial» и проверка заблокированного прямого URL до reveal.

## Verification

### Agent Verification

| Step | Expected Result |
|------|-----------------|
| Запустить focused backend tests DQS/Masterclass/auth/admin | Все gate, reveal, legal, migration и tutorial assertions проходят |
| Запустить focused Telegram tests app menu/dispatch | DQS скрыт до reveal; одна notification даёт сообщение и одну кнопку на единый URL |
| Отправить два параллельных reveal-запроса в integration test | В БД один reveal и не более одной notification |
| Смоделировать transient dispatcher error и retry | Повторяется та же notification, второго сообщения нет |
| Запустить browser flow до и после дня 4 | До reveal дневник закрыт; после одной кнопки открыт, туториал работает |
| Проверить admin runtime | Профиль управляется с аудитом, но reveal/notification не создаются |
| Проверить module inventory и diff | Новые/изменённые компоненты имеют правильного владельца, generated-файлы не редактировались вручную |

### User Verification

- На одном тестовом аккаунте дойти до DQS дня 4, нажать одну кнопку и проверить
  открытие дневника и одно Telegram-сообщение. Ручная проверка нужна только для
  реальной доставки/рендера Telegram и утверждения текста.
