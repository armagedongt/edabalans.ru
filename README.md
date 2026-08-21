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

Следующая задача — переносить существующие приложения по одному: структура Google Sheets,
Apps Script и код Tilda становятся PostgreSQL-схемой и API-методами без изменения
пользовательского поведения.

Технические инструкции и результаты проверок: `docs/OPERATIONS.md`.
