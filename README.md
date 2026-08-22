# edabalans.ru

Новый сотрудник или ИИ должен начинать с [docs/README.md](docs/README.md): там находится карта
канонических документов, модулей, таблиц и очередь будущих изменений.

## Текущее состояние

Production-фундамент развёрнут на Timeweb Cloud:

- `https://api.edabalans.ru/health` — FastAPI;
- `https://api.edabalans.ru/ready` — проверка связи API с PostgreSQL;
- `https://data.edabalans.ru` — закрытая регистрация NocoDB для просмотра таблиц;
- Caddy автоматически обслуживает HTTPS;
- PostgreSQL доступен только внутри Docker-сети;
- ежедневные резервные копии двух баз уходят в Yandex Object Storage;
- восстановление обеих баз из S3 реально проверено до импорта персональных данных.

Единый CRM/Core, общая модель пользователей, messenger accounts, покупок, продуктов и
доступов уже созданы. Текущий этап — довести перенос существующих приложений и
Telegram-модуля на общий `user_id`, PostgreSQL и API, сохраняя пользовательское
поведение. Незавершённые и будущие изменения собраны в `docs/plans/README.md`.

Технические инструкции и результаты проверок: `docs/OPERATIONS.md`.

Проект CRM/Core и mapping двух legacy-таблиц: `docs/CRM_CORE_DESIGN.md`.

Локальный read-only экспорт сценариев LeadTeh: `leadteh-export/README.md`.

Изолированный фундамент Telegram-модуля и локальный прототип: `telegram-bot/README.md`.
