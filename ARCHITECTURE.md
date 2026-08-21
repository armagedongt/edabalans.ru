# ARCHITECTURE.md

## 1. Назначение

Этот репозиторий — единая техническая база проекта **edabalans.ru**.

Цель: постепенно перенести ключевую инфраструктуру с Google Apps Script / Google Sheets / LeadTeh / Tilda-зависимой логики на собственный российский сервер, сохранив Tilda как переходную оболочку там, где это удобно.

Репозиторий строится как **монорепозиторий**: backend, приложения, Telegram/MAX, инфраструктура и документация находятся в одном месте и используют общие сущности пользователей, покупок, доступов и базы данных.

## 2. Общая архитектура

```text
Пользователь
    ↓
Tilda / будущий собственный сайт
    ↓
Frontend приложений
    ↓
https://api.edabalans.ru
    ↓
Backend API
    ↓
PostgreSQL
    ↓
├── DQS
├── Силовые тренировки
├── Telegram
├── MAX
├── покупки и доступы
├── пользователи
└── административные функции
```

Инфраструктура:

```text
Российская VM
├── Docker
│   ├── backend
│   ├── PostgreSQL
│   └── NocoDB или Baserow
├── reverse proxy / HTTPS
├── backups
└── monitoring
```

GitHub хранит код и документацию. Сервер запускает код. GitHub не используется как база пользовательских данных.

## 3. Домены

Основной технический домен: `edabalans.ru`.

Предварительная структура:

```text
edabalans.ru       → будущий основной сайт
api.edabalans.ru   → backend / API
app.edabalans.ru   → frontend-приложения
data.edabalans.ru  → техническая табличная админка PostgreSQL
lk.edabalans.ru    → будущий собственный личный кабинет
bot.edabalans.ru   → возможная специализированная админка ботов
```

Текущий публичный сайт может продолжать работать на `похудение-это-есть.рф` и на Tilda.

## 4. Переходная роль Tilda

На первом этапе Tilda сохраняется как:

- публичный сайт;
- страницы;
- Members Area;
- текущая авторизация;
- формы;
- текущая покупочная инфраструктура;
- оболочка для закрытых страниц.

Приложения постепенно выносятся из больших T123-блоков.

Предпочтительная схема:

```text
Tilda T123
    ↓
короткий загрузочный код
    ↓
JS/CSS приложения с app.edabalans.ru
    ↓
API api.edabalans.ru
```

Код приложения живёт в GitHub и на сервере, а Tilda только подключает его в страницу.

На переходном этапе приложение может использовать Tilda Members Area для определения текущего пользователя. Email Tilda не должен становиться вечным внутренним ID системы: у каждого пользователя должен быть собственный `user_id`.

## 5. Будущая роль Tilda

```text
Этап 1:
Tilda = сайт + ЛК + авторизация + продажи
Server = приложения + база + backend + боты

Этап 2:
Tilda = публичный сайт + продажи
Server = ЛК + авторизация + приложения + данные + боты

Этап 3:
Server = весь сайт + ЛК + авторизация + приложения + интеграции
Tilda = не используется либо остаётся только для отдельных лендингов
```

Полный переезд с Tilda не является обязательным условием.

## 6. Backend

Предварительный стек:

```text
Python
FastAPI
PostgreSQL
Docker
```

Backend отвечает за пользователей, авторизацию, покупки, доступы, DQS, силовые тренировки, Telegram, MAX, цепочки сообщений, условия, рассылки, webhook Tilda, webhook платёжных систем, административный API, health-check и журналирование ошибок.

## 7. PostgreSQL

PostgreSQL — основной источник истины для структурированных данных.

Предполагаемые общие таблицы:

```text
users
messenger_accounts
products
purchases
accesses
subscriptions
tags
user_tags
```

Все приложения используют общий внутренний `user_id`.

## 8. Центральный пользователь

Один человек должен существовать в системе один раз.

Пример:

```text
users
----------------------------
id
email
created_at
status
```

Связанные аккаунты:

```text
messenger_accounts
-------------------------------------
user_id
platform
platform_user_id
username
preferred_channel
```

Покупки, DQS, силовые и доступы связываются по `user_id`.

## 9. Покупки и доступы

Telegram-теги не являются источником истины для покупок.

Основные таблицы:

```text
products
purchases
accesses
subscriptions
```

После подтверждённой оплаты backend обновляет доступ пользователя. Обработка платежей должна быть идемпотентной: повторный webhook не должен создавать повторную покупку.

## 10. Tilda и оплаты

Tilda может отправлять формы/заказы на backend через webhook:

```text
Tilda
    ↓
https://api.edabalans.ru/tilda/form
    ↓
PostgreSQL
```

Для факта оплаты предпочтительный источник — серверное уведомление самой платёжной системы:

```text
Robokassa
    ↓ webhook
Backend
    ↓
PostgreSQL
    ↓
выдача доступа
    ↓
Telegram / MAX / личный кабинет
```

## 11. Авторизация

Переходный этап:

```text
Tilda Members Area
    ↓
закрытая страница
    ↓
frontend получает текущего пользователя
    ↓
backend
```

Будущая схема:

```text
login.edabalans.ru / lk.edabalans.ru
    ↓
собственная авторизация
    ↓
session / token
    ↓
все приложения
```

Backend не должен в долгосрочной перспективе доверять только email, найденному JavaScript на странице.

## 12. DQS

DQS постепенно переносится с:

```text
Tilda frontend + Google Apps Script + Google Sheets
```

на:

```text
frontend app + FastAPI backend + PostgreSQL
```

DQS остаётся отдельным модулем общей платформы.

## 13. Силовые тренировки

Приложение силовых тренировок также переносится на общий backend и PostgreSQL.

Сохраняются проектные правила: до 3 типов тренировок, plan/fact, вес, повторения, RPE, дата, заметки, каталог упражнений, календарь, аналитика и расчётный 8RM.

Формула:

```text
RIR = 10 - RPE
W8 = weight × (1 + (reps + 10 - RPE) / 30) / (1 + 8 / 30)
```

Первая разминка исключается из анализа.

## 14. Telegram-бот

Цель — постепенно отказаться от LeadTeh как основной платформы бота.

Основные функции:

- pre-purchase цепочка;
- post-purchase цепочка;
- условия по покупкам;
- задержки;
- сообщения;
- фото;
- видео;
- видеокружки;
- голосовые;
- кнопки;
- переходы;
- остановка цепочки;
- массовые рассылки;
- сегментация;
- теги;
- статистика;
- blocked/error.

## 15. Цепочки сообщений

Цепочки не должны быть жёстко зашиты в Python-код. Контент и структура хранятся в PostgreSQL.

Пример:

```text
[1] MESSAGE immediately
[2] DELAY 24h
[3] CONDITION has_product?
    YES -> post_purchase
    NO  -> step 4
[4] VIDEO
[5] DELAY 2d
[6] MESSAGE
```

Типы блоков:

```text
MESSAGE
DELAY
CONDITION
PHOTO
VIDEO
VIDEO_NOTE
VOICE
BUTTONS
GOTO
STOP
```

Изменение текста, задержек и порядка существующих блоков должно делаться без изменения backend-кода.

## 16. Состояние пользователя в цепочке

```text
bot_user_state
------------------------------------
user_id
platform
sequence_id
step_id
next_send_at
status
```

Scheduler регулярно находит пользователей, которым пора отправить следующий шаг. На первом этапе PostgreSQL можно использовать как очередь; Redis не обязателен.

## 17. Telegram media

Файл можно загрузить в Telegram один раз, сохранить `file_id` и использовать его для последующих отправок. Это уменьшает трафик и нагрузку на сервер.

## 18. Миграция с LeadTeh

```text
1. Создать отдельного тестового Telegram-бота.
2. Реализовать backend и цепочки.
3. Протестировать отправки и условия.
4. Получить экспорт пользователей из LeadTeh.
5. Сохранить Telegram user_id / chat_id.
6. Импортировать пользователей в PostgreSQL.
7. Остановить активные отправки LeadTeh.
8. Переключить webhook реального бота на свой backend.
9. Проверить.
10. Запустить новые кампании.
```

Точный старый шаг пользователя в LeadTeh сохранять необязательно, если после миграции запускаются новые кампании.

## 19. LeadTeh на переходном этапе

Бизнес-условия желательно уже переносить на свой backend:

```text
LeadTeh
    ↓ HTTP
/api/check-product
    ↓
backend
    ↓
PostgreSQL
    ↓
JSON true/false
    ↓
LeadTeh branch
```

Позже тот же метод используется напрямую Telegram-движком.

## 20. MAX

MAX не является отдельной полной системой. Используется общий messaging engine:

```text
backend/
    messaging/
        telegram_adapter
        max_adapter
        sequences
        broadcasts
        conditions
        scheduler
```

Покупки и доступы общие для всех каналов.

## 21. Telegram + MAX

```text
Telegram
     ↘
      Backend -> PostgreSQL
     ↗
MAX
```

Если пользователь купил продукт, изменение фиксируется один раз в PostgreSQL. Можно использовать `preferred_channel = telegram / max`, чтобы не дублировать сообщения.

## 22. Связка пользователя после покупки

Предпочтительно использовать одноразовый токен, а не сырой email в deep-link.

```text
https://t.me/SomeBot?start=abc123...
```

Backend сопоставляет токен с `user_id` и привязывает messenger account.

## 23. Массовые рассылки

Рассылка — операционная сущность, а не изменение кода.

Пример API:

```text
POST /admin/broadcasts
```

Поля:

```text
channel
segment
text
media
buttons
scheduled_at
```

Перед массовой отправкой желательно явное подтверждение.

## 24. Админка

Нужно различать две админки.

**Техническая:** NocoDB/Baserow — смотреть таблицы, исправлять отдельные данные, диагностировать PostgreSQL.

**Специализированная:** собственный UI для `Sequences`, `Broadcasts`, `Users`, `Purchases`, `Products`, `Accesses`, `Stats`, `Errors`.

## 25. GitHub

GitHub — официальный источник кода и технической документации.

Не хранить в GitHub:

- пользовательскую базу;
- бэкапы PostgreSQL;
- секретные ключи;
- bot tokens;
- пароли;
- production `.env`;
- персональные данные клиентов.

Хранить:

- backend;
- frontend;
- Docker-конфигурацию;
- миграции;
- тесты;
- документацию;
- безопасные примеры env.

## 26. Монорепозиторий

Предварительная структура:

```text
edabalans.ru/
│
├── README.md
├── AGENTS.md
│
├── docs/
│   ├── ARCHITECTURE.md
│   ├── DQS.md
│   ├── STRENGTH.md
│   ├── MESSAGING.md
│   ├── AUTH.md
│   └── DEPLOYMENT.md
│
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── core/
│   │   ├── users/
│   │   ├── products/
│   │   ├── purchases/
│   │   ├── access/
│   │   ├── dqs/
│   │   ├── strength/
│   │   └── messaging/
│   │       ├── engine/
│   │       ├── telegram/
│   │       └── max/
│   ├── tests/
│   └── requirements/
│
├── apps/
│   ├── dqs/
│   ├── strength/
│   └── admin/
│
├── infra/
│   ├── docker/
│   ├── proxy/
│   ├── deploy/
│   └── backup/
│
└── scripts/
```

Структура может меняться по мере развития проекта.

## 27. AGENTS.md

`AGENTS.md` должен давать Codex постоянные инструкции проекта.

Базовые правила:

```text
- PostgreSQL является источником истины.
- Не добавлять новые внешние SaaS без явного решения.
- Секреты не коммитить.
- Перед изменением схемы БД создавать migration.
- Перед production deploy запускать tests.
- Обновлять docs при изменении архитектуры.
- Не менять публичные API без migration plan.
```

## 28. Git workflow

Предварительная схема:

```text
main     -> production
test     -> staging / тестовая среда
```

Рабочий процесс:

```text
задача
↓
Codex изменяет код
↓
tests
↓
commit
↓
test environment
↓
проверка
↓
main
↓
production deploy
```

Экспериментальные изменения не должны автоматически попадать прямо в production.

## 29. Autodeploy

```text
GitHub main
    ↓
deploy
    ↓
server
    ↓
Docker rebuild / restart backend
```

Обычно достаточно перезапустить backend-container; PostgreSQL остаётся работать.

## 30. Server / VM

Сервер — обычная Linux VM в российском дата-центре.

Ориентировочный старт:

```text
2 vCPU
4 GB RAM
30–50 GB SSD/NVMe
Ubuntu
```

Перед покупкой нужно перепроверить актуальные цены и требования.

Рассматриваемые провайдеры:

```text
Timeweb Cloud
Yandex Cloud
Selectel
```

Архитектура не должна зависеть от конкретного провайдера.

## 31. Docker

```text
docker compose
├── backend
├── postgres
└── nocodb
```

Контейнеры должны автоматически перезапускаться после сбоя, например `restart: unless-stopped`.

## 32. Мониторинг

Нужно контролировать:

- доступность API;
- RAM;
- диск;
- ошибки backend;
- PostgreSQL;
- успешность backup;
- ошибки Telegram/MAX;
- заполнение логов.

Желательные уведомления:

```text
API недоступен
RAM > 85%
Disk > 80%
backup failed
critical backend error
```

Health endpoint: `GET /health`.

## 33. Backups

PostgreSQL должен автоматически бэкапиться ежедневно. Бэкапы желательно хранить отдельно от основной VM, предпочтительно в российском объектном хранилище.

Нужно периодически проверять не только создание backup, но и возможность восстановления.

## 34. Масштабирование

Одна VM — нормальная production-архитектура для текущего масштаба.

Сейчас:

```text
VM
├── backend
├── postgres
└── nocodb
```

Позже:

```text
VM 1 -> backend
VM 2 / managed service -> PostgreSQL
VM 3 -> admin / supporting services
```

При правильной конфигурации приложения не должны требовать переписывания при таком переносе.

## 35. Принцип работы с Codex

Официальная память проекта должна находиться не только в чатах, а в репозитории.

Codex должен:

1. читать `AGENTS.md`;
2. читать релевантные файлы в `docs/`;
3. изучать существующий код перед изменениями;
4. не коммитить секреты;
5. обновлять документацию при изменении архитектуры;
6. запускать тесты;
7. показывать, что изменено;
8. не выкатывать опасные изменения в production без явного решения.

## 36. Типы изменений

**Изменение системы/движка** — новый тип блока Telegram, изменение авторизации, новый payment provider. Требует изменения кода → GitHub → tests → deploy.

**Изменение контента** — текст сообщения, задержка, перестановка существующих шагов. Должно делаться через БД/admin API без изменения кода.

**Разовая операция** — например массовая рассылка. Должна создаваться через backend/admin API, а не через новый commit.

## 37. Ближайший порядок реализации

```text
1. GitHub repository.
2. ARCHITECTURE.md и AGENTS.md.
3. Выбор российского облачного провайдера.
4. Создание VM.
5. Ubuntu + базовая безопасность.
6. Привязка api.edabalans.ru.
7. Docker.
8. PostgreSQL.
9. FastAPI skeleton.
10. /health.
11. HTTPS / reverse proxy.
12. backups.
13. monitoring.
14. GitHub autodeploy.
15. NocoDB/Baserow.
16. общая модель users/products/purchases/accesses.
17. тестовый Telegram-бот.
18. messaging engine.
19. LeadTeh condition API.
20. перенос DQS.
21. перенос силовых.
22. MAX.
23. собственный ЛК и авторизация.
24. при необходимости перенос публичного сайта с Tilda.
```

## 38. Главный архитектурный принцип

Публичный сайт, Tilda, Telegram, MAX, DQS и силовые — не отдельные несвязанные проекты. Это интерфейсы одной платформы.

Центр системы:

```text
PostgreSQL
+
Backend API
+
единый user_id
+
единая система purchases/accesses
```

Внешние интерфейсы:

```text
Tilda
Website
DQS
Strength
Telegram
MAX
Admin
```

Это позволяет постепенно менять Tilda, LeadTeh, серверного провайдера и другие внешние компоненты без полной переделки всей системы.
