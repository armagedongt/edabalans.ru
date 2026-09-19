# Code research: DQS day-4 activation

Исследована ревизия `origin/main` `6a891205b0aa63c164b43137a6f35b8f128c3e11`.

## Уже реализовано

- `products.dqs` зарегистрирован отдельным модулем и владеет клиентом DQS,
  таблицей `dqs_states`, прямым `/dqs`, API и DQS-админкой `/admin/dqs`.
- Покупка Мастер-класса выдаёт право `dqs` через общие product access rules.
- В seed структуры курса день 4 содержит шаг `day-04-dqs` с `kind/code=dqs` и
  завершением `tutorial_completed`.
- `POST /api/masterclass/apps/dqs/reveal` проверяет открытый день, правильный шаг,
  незаблокированный материал, предыдущие обязательные шаги и право `dqs`, затем
  идемпотентно создаёт `app: dqs :revealed` / `app_revealed_dqs`.
- Telegram/MAX app menu показывает DQS только при сочетании активного права и
  события `app_revealed_dqs`.
- Материал DQS умеет отдельно вызвать
  `POST /api/masterclass/dqs/link-to-telegram`. Route требует связанный активный
  Telegram и ставит notification `dqs_app_link` с content slot
  `tpl_postpurchase_dqs_app_link`.
- В postpurchase graph уже есть шаг `pp_dqs_app_link` с Web App-кнопкой. Dispatcher
  проверяет, что URL обычной ссылки в тексте совпадает с URL кнопки.
- Админский runtime использует admin session + target user и пишет аудит в
  `admin_app_edits`; пользовательский пароль не подменяется.
- Тесты покрывают DQS tutorial gate, legal gate, reveal route, невозможность
  подделать reveal общим events endpoint, очередь ручной ссылки и управляемый
  runtime.

## Расхождения с требованием

1. Прямые DQS routes проверяют право и legal acceptance, но не требуют
   `app_revealed_dqs`; купивший Мастер-класс может открыть `/dqs` до дня 4.
2. Открытие приложения и постановка Telegram-ссылки в очередь — два отдельных
   пользовательских действия.
3. `dqs/link-to-telegram` создаёт новый event key с UUID, поэтому повторное
   нажатие сознательно создаёт повторную доставку; автоматический сценарий должен
   получить стабильный idempotency key.
4. В ЛК приложение считается открываемым по праву/готовности; DQS-специфический
   reveal gate там не применяется.
5. Прямой Mini App-вход повторно проверяет entitlement, но не reveal.
6. Нет оформленного миграционного правила, которое сохранит вход прежним
   пользователям после включения нового gate.

## Переиспользуемые точки

- Не нужна новая таблица прав: использовать `user_accesses` +
  `masterclass_events`.
- Не нужен новый message slot: изменить назначение существующего
  `tpl_postpurchase_dqs_app_link` и trigger `pp_dqs_app_link`.
- Reveal route уже является правильной точкой проверки этапа; к нему нужно
  присоединить идемпотентную постановку delivery и единый DQS availability guard.
- Тот же guard должны читать прямой route, ЛК, Telegram/MAX Mini App и bot menu.
- Курс должен продолжать владеть только `day-04-dqs`; формула DQS, данные и
  прямой доступ остаются у `products.dqs`.

## Минимальный набор изменения

- общий helper фактической доступности DQS;
- применение helper во всех пользовательских входах, но не в managed admin mode;
- идемпотентная Telegram notification в транзакции reveal;
- UI состояния `entitled_locked` до дня 4 и честная ошибка доставки без Telegram;
- миграционный backfill или совместимый predicate для уже открывавших DQS;
- integration tests backend + bot и один browser flow шага дня 4.

