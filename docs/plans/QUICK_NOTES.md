# Короткие будущие изменения

Статус: `current`

Здесь находятся только небольшие пожелания, которые владелец явно отложил на
будущее. Строка `planned` обязательно содержит канонический `Module ID`, дату и
`owner-explicit`; иначе она не попадает в активную очередь планов.

| ID | Module ID | Статус | Пожелание | Дата | Origin | Источник |
|---|---|---|---|---|---|---|
| Q-001 | admin.project-knowledge | `archived` | Интерфейс просмотра базы знаний поверх канонических данных | 2026-08-25 | implemented | Реализовано картой системы `/admin/knowledge-base` |
| Q-002 | admin.project-knowledge | `archived` | Автоматически находить постоянные таблицы и production-модули, не включённые в карту | 2026-08-25 | implemented | Реализовано генератором `tools/module_inventory.py` |
| Q-003 | platform.content | `planned` | Собрать единый каталог всех когда-либо опубликованных постов со ссылками на оригиналы и статусом актуальности | 2026-08-22 | owner-explicit | Решение владельца |
| Q-004 | planned.marketing-catalog | `planned` | Создать каталог рекламных площадок, кабинетов, кампаний и креативов без хранения секретов в Git | 2026-08-22 | owner-explicit | Решение владельца |
| Q-005 | operations.proxy | `planned` | После отдельной проверки резервного SSH-входа отключить вход на production-сервер по паролю и оставить ключи | 2026-08-22 | owner-explicit | Решение владельца отложить усиление доступов; `docs/OPERATIONS.md` |
| Q-006 | products.masterclass.course | `archived` | Старый автономный предпросмотр трёх тем удалён после утверждения клиентского шаблона | 2026-08-25 | implemented | `MASTERCLASS_WEB_APP_SPEC.md`; `/admin/courses/masterclass-21/structure` |
| Q-007 | products.masterclass.messenger-links | `archived` | Отдельно спроектировать сохранение материала с сайта и отправку пользователю через Telegram или MAX | 2026-08-23 | unconfirmed-idea | Идея обсуждалась, но отдельного распоряжения владельца положить её в планы не найдено |
| Q-008 | messaging.telegram.intensive | `archived` | Заменить повторные проверки подписки на событийное состояние членства | 2026-08-23 | unapproved-audit | Архитектурное предложение не было отдельно утверждено владельцем |
| Q-009 | messaging.telegram.engine | `archived` | Распространить общий dispatch-time policy на остальные продающие сообщения | 2026-08-23 | unapproved-audit | Архитектурное предложение, а не поручение владельца |
| Q-010 | products.masterclass.questionnaires | `archived` | Вынести названия вопросов в общий registry backend и Telegram | 2026-08-23 | unapproved-audit | Архитектурное предложение, а не поручение владельца |
| Q-011 | messaging | `archived` | Перед подключением MAX сделать общий messaging-router | 2026-08-23 | unapproved-audit | Архитектурное предложение; отдельной задачи на MAX нет |
| Q-012 | products.masterclass.runtime | `archived` | Открывать следующий день в 06:00 по часовому поясу прохождения | 2026-08-24 | implemented | Реализовано; `../knowledge-base/modules/masterclass/COURSE_RUNTIME.md` |
| Q-013 | products.masterclass.runtime | `planned` | Старым владельцам Мастер-класса назначить `fully_unlocked`, а недавно зарегистрированным вычислить стартовый день без ложного выполнения материалов | 2026-08-24 | owner-explicit | Решение владельца; требуется migration после финального CSV Tilda |
| Q-014 | products.masterclass.course | `archived` | Добавление, удаление и перестановку материалов и редактор тел статей вынести в отдельное безопасное расширение | 2026-08-25 | expanded-to-spec | Активная задача развёрнута без дублирования в `COURSE_EDITOR_DEFERRED.md` |
| Q-015 | products.masterclass.offers | `planned` | Вручную отредактировать и при необходимости расширить полноэкранные текстовые презентации доппродуктов: длинную продающую версию, программу, медиа и размещение ссылок в карточках комплектов | 2026-08-25 | owner-explicit | Базовые текстовые экраны реализованы в offer module; визуал и текст будут уточняться после просмотра |
