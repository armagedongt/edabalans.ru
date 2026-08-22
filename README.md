# edabalans.ru

## Текущее состояние

Production-фундамент развёрнут на Timeweb Cloud:

- `https://api.edabalans.ru/health` — FastAPI;
- `https://api.edabalans.ru/ready` — проверка связи API с PostgreSQL;
- `https://data.edabalans.ru` — закрытая регистрация NocoDB для просмотра таблиц;
- Caddy автоматически обслуживает HTTPS;
- PostgreSQL доступен только внутри Docker-сети;
- ежедневные резервные копии двух баз уходят в Yandex Object Storage;
- восстановление обеих баз из S3 реально проверено до импорта персональных данных.

Следующая задача — создать единый CRM/Core: пользователей, messenger accounts,
покупки, продукты и доступы. После этого существующие приложения по одному
переводятся с Google Sheets/Apps Script на общий `user_id`, PostgreSQL и API без
изменения пользовательского поведения.

Технические инструкции и результаты проверок: `docs/OPERATIONS.md`.

Проект CRM/Core и mapping двух legacy-таблиц: `docs/CRM_CORE_DESIGN.md`.

Локальный read-only экспорт сценариев LeadTeh: `leadteh-export/README.md`.

Изолированный фундамент Telegram-модуля и локальный прототип: `telegram-bot/README.md`.
