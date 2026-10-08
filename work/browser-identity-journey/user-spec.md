---
# Creation date (YYYY-MM-DD)
created: 2026-10-08

# Status: draft | approved
status: approved

# Work type: feature | bug | refactoring
type: feature
---

# User-spec: browser-identity-journey

> **Executor instruction.** If the project has Project Knowledge, first read the documentation
> entrypoint declared by its `AGENTS.md` or existing router (for example `docs/README.md` or a
> Project Knowledge `SKILL.md`), then only the materials relevant to this task.
> Read `decisions.md` if it exists. Work from
> the root of the project this spec belongs to. Implement the entire user-spec. Use the execution
> skills appropriate to the work.

## What We Are Building
Единую историю браузера в публичной экосистеме: анонимные посещения сохраняются, персональная ссылка Telegram/MAX связывает их с существующим CRM-контактом. Между доменами передаётся защищённый идентификатор посетителя; контакт и путь сопровождают покупку и уведомления о незавершённой/отклонённой оплате.

## Why
Сергей видит контакт человека, рекламный источник и путь до оплаты без ожидания ручной привязки мессенджера в платном кабинете.

## Expected Behavior
1. Публичные управляемые страницы создают first-party visitor cookie и связь персонального контакта до принятия cookie-уведомления, по прямому решению владельца08.10.2026. Просмотры страниц и остальные browser actions сохраняются только после cookie-accept. Срок cookie и технической браузерной истории365дней; старые browser tracking записи удаляются, CRM-контакты и оплаты не затрагиваются. Значение непрозрачно; источники UTM/yclid/канального перехода сохраняются отдельно от личности.
2. Старт Telegram/MAX уже создаёт CRM user и MessengerAccount. Подготовленный переход в бота сохраняет visitor context в существующей journey metadata.
3. Открытие действительного персонального кода связывает visitor с владельцем кода. Ранее анонимные события браузера входят в его CRM-историю; последняя персональная ссылка определяет новые события, уже идентифицированные события другого пользователя не переприсваиваются; контакты и исходный бот уже известны.
4. Ссылка между публичными доменами несёт короткоживущий защищённый carrier. На следующем домене устанавливается его first-party cookie с тем же серверным visitor. Ранее независимый анонимный visitor назначения также присоединяется при переходе. Отдельно набранные адреса без общего перехода/идентификации не могут быть связаны автоматически.
5. При создании счёта сохраняется снимок наблюдаемого контакта и пути. UTM не удаляют контакт. Покупатель, email, пароль и права определяются существующей платёжной логикой; browser identity не является login.
6. Owner alerts обоим аккаунтам через @fitpostgpbot содержат сумму, продукт с тарифом, место покупки, email, Telegram/MAX контакт, источник связи, исходный бот и ссылку CRM. Подтверждённые MessengerAccount сохраняются; наблюдаемый контакт другой CRM identity не переносит её права.
7. Через 30 минут обычного pending счёта присылается одно «Оплата не завершена», если нет признака успешно проведённой/обрабатываемой операции. Счёт не отменяется и поздняя оплата остаётся возможной.
8. OpStateExt опрашивается с 5 минут после создания обычного прямого счёта. Подтверждённые коды10/60 создают отдельное failed уведомление; недоступность сервиса или отсутствие операции не считается отказом. HOLD/зачисление/приостановка и успех не получают уведомление «не оплачено». Дочерние recurring счета сохраняют существующий reconciler.

## Acceptance Criteria
- [ ] Telegram и MAX: анонимные события до персонального перехода доступны в CRM владельца кода.
- [ ] Публичные текущие домены/поддомены проекта продолжают общий visitor при переходах; чужие сайты, админка и отдельные клиентские/здоровье-проекты исключены.
- [ ] Переход сайта в бот сохраняет связь с текущим visitor в journey; старт бота известен до LK-link.
- [ ] Возврат на главную по внутренним ссылкам и повторное посещение сохраняют contact и источник; очищенные cookies/иной браузер узнаются только после нового связующего перехода.
- [ ] При покупке с новым email наблюдаемый messenger доступен в уведомлении и CRM без перепривязки authenticated account или выдачи прав владельцу ссылки.
- [ ] Валидные UTM одновременно с source_context сохраняют оба факта.
- [ ] Pending30мин уведомление ровно одно; поздний paid проходит; confirmedfailed отдельное, повторwebhook/worker не создаёт дубль.
- [ ] Сообщения содержат только доступные Robokassa причины; недостаток средств не выдумывается.
- [ ] Страница/checkout работают при отказе tracker; неизвестный carrier не авторизует и не раскрывает PII.

- [ ] До cookie-accept создаются только visitor и персональная связь; pageviews/actions отсутствуют. Послеaccept события начинают сохраняться.
- [ ] При очистке истории старше365дней удаляются только visitor-state/browser events; CRM/MessengerAccount/Payment и bot acquisition history остаются.

## Constraints
Единый user_id, существующие bot/CRM/payment engines и outbox. Не менять домены/DNS, платные права, Tilda hooks и загрузчик ради скорости. Реализовать поверх текущего общего сервера и существующих managed loaders. Браузерные ограничения обходить передачей carrier при переходе, не third-party cookie и не fingerprinting. Токены и приватные URL не записывать в общие логи/историю.

## Risks
- Пересланная персональная ссылка: владелец явно принимает погрешность CRM/атрибуции; не предоставлять по ней платный вход.
- Несвязанные root domains/разные браузеры: carrier и first-party cookies; не обещать автоматическое узнавание без перехода.
- Недоступность tracker/API: не задерживать страницу или оплату; не трактовать сетевые ошибки как платёжный отказ.
- Гонка bind/events и поздний paid: транзакционная привязка и idempotent outbox; отдельный незавершённый event не меняет payment.status.

## Accepted Decisions
- Полная реализация разрешена сообщением Сергея от08.10.2026; повторное согласование раскрытого маршрута не требуется.
- Погрешность пересланной ссылки принята для наблюдаемого контакта/истории.
- Единый серверный visitor с first-party cookies на каждом rootdomain; общая literal cookie технически невозможна.
- Срок visitor365дней подтверждён владельцем; binding до cookie-accept, остальная аналитика после. Примечания о порядке в публичный код сайта не добавлять. Внутренняя документация описывает фактическое правило. Текущие login cookies сохраняют отдельное назначение.
- Reuse tg_tracking_events/JSON/индексированный deduplication_key, Payment.raw_payload и owner outbox; без новой базы, сервиса или migration.
- Ускорение Tilda HTML и окончательный переход на похудение.рф остаются отдельными задачами.

## Testing
**Unit tests:** carrier подпись/expiry/purpose, visitor state/binding, invoice classification.
**Integration tests:** SQLite anon→bind→backfill, observedcontactsnapshot/paymentbuyer независимость, UTM+personalcontext, pending/fail/retry/dedup/latepaid.
**Retention/consent checks:** API+browser: безaccept проверить наличие visitor/bind и отсутствие page/action; нажатьaccept и проверить события. Integration fixedclock: записи366дней и свежие, вместе с CRM/контактами/оплатами; purge удаляет только старый technicalvisitor/event.
**E2E tests:** реальные управляемые JS loaders, две origins и cookies/carrier, путь main→bot→personalentry→homepage→checkout. Проверять critical browser boundary синтетически без реальных покупок/учётных записей.

## Verification
### Agent Verification
| Step | Expected Result |
|------|-----------------|
| Anonymous visit→personal token→CRM | История и known messenger в CRM, без account credential/right изменения |
| Domain A→Domain B→repeat | Связанный visitor сохранён в first-party storage |
| UTM+visitor+checkout | Источник и контакт сохранены отдельно |
| Pending30min→paid later | Два разных корректных events, оплаченный доступ выдан штатно |
| Final OpStateExt10/60/errors | Только подтверждённый отказ создаёт failed event |
| No cookieaccept→accept | Доaccept толькоvisitor/bind, послеpage/action events |
| Fixedclock365дней→purge | Старыеbrowser events исчезли, CRM/покупки/контакты сохранены |
| Full selected reviews/CI→production | Готовые docs/registry, целевой код опубликован, сервисready |
| Actual livehomepage loader | Tracker загружается без отдельной перепубликации Tilda или явно указан требуемый этап установки |
