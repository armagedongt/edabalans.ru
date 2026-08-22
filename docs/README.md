# Навигатор по документации edabalans.ru

Статус: `current`  
Назначение: единая точка входа для владельца, нового сотрудника и нового ИИ-чата.

## С чего начать

1. `../PROJECT_CONTEXT.md` — зачем существует проект и какое состояние уже достигнуто.
2. `../ARCHITECTURE.md` — основные архитектурные решения и ограничения.
3. `../AGENTS.md` — обязательные правила безопасной работы с репозиторием.
4. Этот файл — где искать подробности по конкретной теме.
5. `knowledge-base/README.md` — предметная база знаний бизнеса и канонические описания.
6. `plans/README.md` — всё, что решено отложить на будущие версии.

## Карта действующих документов

| Тема | Канонический документ | Что в нём находится |
|---|---|---|
| Общая архитектура | `../ARCHITECTURE.md` | Компоненты платформы, границы модулей, общие принципы |
| Production и эксплуатация | `OPERATIONS.md` | Сервер, домены, Docker, backup, deploy и команды проверки |
| CRM и общая база клиентов | `CRM_CORE_DESIGN.md` | Правила идентификации, импорта, оплат, доступов и объединения людей |
| Таблицы CRM | `CRM_DATA_MODEL.md` | Назначение и связи таблиц общей БД |
| Клиентские приложения | `APPLICATION_PLATFORM.md` | DQS, силовые, метаболизм, доступы и Tilda-оболочка |
| Telegram-бот — фактический путь клиента | `TELEGRAM_BOT_CURRENT_LOGIC.md` | Вход, источник, цепочка, задержки, покупки, отправка и таблицы |
| Telegram-бот — модульная база знаний | `knowledge-base/modules/telegram/README.md` | Подмодули, канонические правила и состояние реализации |
| Telegram-бот — устройство модуля | `../telegram-bot/README.md` | Запуск сервиса, каталоги и техническая структура |
| Административные интерфейсы | `ADMIN_ARCHITECTURE.md` | Общая навигация и границы CRM/Telegram-админки |
| Платежи Tilda | `TILDA_PAYMENTS.md` | Приём webhook, нормализация и запись оплаты |
| Будущая синхронизация Tilda Members Area | `plans/TILDA_MEMBERS_SYNC.md` | Приоритет CRM, расхождения групп, ограничения API и вариант собственного кабинета |
| Архив LeadTeh | `../leadteh-export/README.md` | Локальный экспорт и правила работы с архивом |
| Legacy Google | `../legacy/google/README.md` | Исходный код и правила переноса старых приложений |

## Карта модулей: код и таблицы

Это краткий указатель. Подробное назначение полей и связи находятся в каноническом
документе соответствующего модуля.

| Модуль | Основные каталоги/файлы | Основные таблицы | Подробности |
|---|---|---|---|
| CRM/Core | `backend/app/models.py`, `crm_service.py`, `crm_routes.py` | `users`, `user_emails`, `user_phones`, `messenger_accounts`, `tags`, `user_tags`, `client_notes` | `CRM_DATA_MODEL.md` |
| Продукты, оплаты и доступы | `backend/app/models.py`, `tilda_service.py`, `tilda_routes.py` | `products`, `product_aliases`, `payments`, `resources`, `product_access_rules`, `user_accesses`, `attribution_events` | `CRM_DATA_MODEL.md`, `TILDA_PAYMENTS.md` |
| Telegram | `telegram-bot/service/app/` | все таблицы с префиксом `tg_`, плюс чтение `users`, `messenger_accounts`, `payments`, `products` | `TELEGRAM_BOT_CURRENT_LOGIC.md`, `../telegram-bot/README.md` |
| DQS | `backend/app/app_routes.py`, `app_service.py`, `static/apps/dqs.html`, legacy в `legacy/google/dqs/` | `dqs_states`; административные изменения — `admin_app_edits` | `APPLICATION_PLATFORM.md` |
| Силовые тренировки | `backend/app/app_routes.py`, `app_service.py`, `static/apps/strength.html`, legacy в `legacy/google/strength/` | `strength_states`, `strength_exercises`; административные изменения — `admin_app_edits` | `APPLICATION_PLATFORM.md` |
| Метаболизм | `backend/app/app_routes.py`, `app_service.py`, `static/apps/metabolism.html`, legacy в `legacy/google/metabolism/` | `metabolism_states`; административные изменения — `admin_app_edits` | `APPLICATION_PLATFORM.md` |
| Импорт и аудит | `backend/app/importers/` (включая приватные ручные оплаты через `manual_payments.py`), `tools/`, миграции | `import_batches`, `legacy_import_records`, `user_merge_events` | `CRM_DATA_MODEL.md`, `CRM_CORE_DESIGN.md` |
| Инфраструктура | `compose.yaml`, `infra/`, `.github/workflows/` | `alembic_version`; служебная БД NocoDB отдельно | `OPERATIONS.md` |

## Правила полноты документации

Не требуется вручную перечислять в одном README каждый CSS, тест или вспомогательную
функцию. Это породит неуправляемую и быстро устаревающую портянку. Вместо этого:

1. Каждый production-модуль обязан присутствовать в карте выше.
2. Каждая постоянная таблица обязана быть описана в паспорте данных своего модуля.
3. Для модуля указываются его основные точки входа, модели, сервисы, интеграции и
   канонический документ.
4. Вспомогательные файлы объясняются локальным README каталога или комментариями к
   коду, если без них назначение непонятно.
5. Полный машинный список файлов и таблиц в будущем должен проверяться автоматически;
   ТЗ находится в `plans/PROJECT_DOCUMENTATION_SYSTEM.md`.
6. Изменение поведения и обновление канонического описания входят в один коммит.

## Статусы документов

- `current` — описывает работающий сейчас факт и является источником истины;
- `draft` — материал собирается и ещё не подтверждён владельцем;
- `planned` — согласованное или предложенное будущее изменение, ещё не реализовано;
- `archived` — исторический материал, который нельзя принимать за актуальную логику.

Если документы противоречат друг другу, приоритет имеют фактический код и БД, затем
документ со статусом `current` и более новой датой. Противоречие нужно явно исправить,
а не молча выбирать удобную версию.
