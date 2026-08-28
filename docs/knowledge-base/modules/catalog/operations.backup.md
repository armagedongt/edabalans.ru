---
title: "Backup и восстановление"
summary: "Сохраняет зашифрованные резервные копии отдельно от VM и подтверждает возможность восстановления."
document_status: current
implementation_status: implemented
---

# Backup и восстановление

Создаёт ежедневные копии PostgreSQL, принимает уже зашифрованные artifacts
приватной памяти автора и подтверждает возможность восстановления.

## Функции

- хранить backup отдельно от основной VM с checksum;
- делать свежую копию перед migration, импортом персональных данных и Telegram startup seed;
- загружать зашифрованную память писателя в отдельный префикс Object Storage, не
  помещая туда recovery-key;

## Граница

Обычный code-only deploy не создаёт новый backup; ежедневная защита сохраняется.

## Источники истины

Backup scripts, restore procedure и `docs/OPERATIONS.md`.

Технические файлы, routes, таблицы, migrations и программные символы не
перечисляются вручную в карточке: они подставляются из generated inventory.

