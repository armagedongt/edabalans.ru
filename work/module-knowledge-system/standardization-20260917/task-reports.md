# Отчёты задач: что сохранять и где продолжать

Статус: `draft`
Снимок: 17.09.2026
Источник: адресные ответы задач на запрос только фактов, без реализации/очистки.

Это не общая память разговоров и не объявление черновика каноном. Защита относится
к самой задаче и её связанным копиям, а не только к текущему названию. Все
перечисленные материалы сохраняются; личные тексты в отчёт не включаются.

| Задача / стабильный ID | Контур и место продолжения | Принятое и незавершённое |
|---|---|---|
| Дизайн / `01a04f3e-145a-77d2-a63a-ad2b9132eec5` | `products.metabolism`; `D:/CodexTools/edabalans-metabolism-v2-publish-20260917`, `codex/metabolism-compact-food-local-20260917`; паспорт `docs/design-references/metabolism-mobile-v2-20260917/METABOLISM_VISUAL_V2.md`, локальный `COMPACT_FOOD_DRAFT.md` рядом | V2 принят в main (`f458798`); новые компактные варианты/расчёт питания локальны по запрету владельца. Сохранять визуализации и `D:/CodexTools/metabolism-compact-food-evidence-20260917` |
| Я.Директ! / `01a05eae-2663-7d93-a2a7-505db44f3b7a` | `operations.health` плюс консультации `marketing.analytics`/атрибуции; `C:/Users/Segey/.codex/worktrees/f932/edabalans.ru/max-health-20260916`, `infra/max-health-20260916`; вход `docs/runtime-health/README.md` | Health/DNS приняты в main. Сохранять `marketing-attribution`, `max-one-shot-chain` с уникальными остатками и `work/cross-site-identity-research/code-research.md`. Текущее дерево старее main: читать свежий Git-источник |
| VSL / `01a059ee-b8a0-7502-9215-033605958c68` | `products.public-site`; `C:/Users/Segey/.codex/worktrees/homepage-popup-conceptual-20260917`, `codex/homepage-popup-conceptual-20260917`; тексты `content/public-site/homepage/{program,recipes,consultation,calories,training}.md` | Принято в main (`092a294`, `4498bf7`); renderer `backend/app/static/public-program-card.{js,css}`. `program.md` не менять; приватный pack сохранять. Удалённая до нового запрета копия восстановлена и проверена |
| Идея спринтов / `01a0aaab-bb86-7311-99b8-c452c8beffa3` | `C:/Users/Segey/Documents/ChatGPT/edabalans-cross-messenger-bridge`, `codex/cross-messenger-bridge`; вход её `docs/knowledge-base/modules/catalog/messaging.cross-messenger.md`; `work/cross-messenger-bridge/` | Заявлен локальный `56f1ce7`, пересылка Telegram/MAX; не принято в main, медиа ждёт живого MAX-теста. Заявленный module ID отсутствует в принятом registry: не создавать второй принятый канон по одному ответу |
| Голосовые — приём и расшифровка (раньше «Разбор голоса») / `01a04ac0-c501-72b2-a624-09babd066512` | `platform.content`; `C:/Users/Segey/Documents/ChatGPT/edabalans.ru`, `codex/markiting`; локальный `docs/knowledge-base/VOICE_TRANSCRIPTION_WORKFLOW.md` | Новый регламент/правила пока локальные; отсутствие файла в main проверено. Приватные raw/derived/handoff и старые runs не переносить/не архивировать. Глобальный workflow локально изменён — не заменять старой копией |
| Собрать и распознать отзывы / `01a06015-34eb-70c2-be94-dd7a42834d2c` | `platform.content`; корень `codex/markiting`; приватный `work/review-catalog-batch/private/unified-review-archive-2026-09-12`; порядок стены `work/public-homepage-redesign/reviews-wall-exact-sequence-2026-09-11.md` | Исходники/транскрипты намеренно вне Git. Сохранять `D:/CodexWorktrees/edabalans-reviews-assets-20260911` и исходные Telegram-выгрузки. Задача main не проверяла; слово «принятые» в её ответе не делает локальный регламент принятым в main |
| Публикация в Блоге / `01a05492-5878-7312-b4ea-15b5fb4daee4` | `platform.blog`; `C:/Users/Segey/.codex/visualizations/2026/08/30/01a05492-5878-7312-b4ea-15b5fb4daee4/blog-audit-catalog`, `codex/blog-seo-analytics-20260917`; вход `docs/knowledge-base/modules/blog/README.md`; handoff `work/blog-seo-analytics/current-decisions.md` | `645fc01` в main; CI/deploy и девять URL подтверждены владельцем задачи. API/import, popup, analytics events, auto-related и author/date UI пока не реализованы; черновики ждут решения Сергея |
| Интегрировать Robokassa без Tilda / `01a06e1e-a8b2-7d72-b501-974f08da559b` | `platform.commerce`; маршрут `docs/ROBOKASSA_PAYMENTS.md` | Завершён `C:/Users/Segey/.codex-worktrees/commerce-owner-alerts`, HEAD `c29c7fe` в main. Копия с тестовыми файлами сохранена, не удалялась. Это ответ о конкретном проходе, не полный аудит платежей |

Пути внутри строки относительны к её рабочей копии, если не начинаются с диска.
Источники содержания не читались для копирования в отчёт. Личный архив не входит
в общий поиск просто потому, что известен его путь.

## Практические выводы

- У спринтов есть дополнительная защищённая копия вне снимка 84 деревьев одного
  проверяемого репозитория. Один `git worktree list` не описывает всю работу Codex.
- VSL использует старый homepage-проход: восстановление требовалось для сохранения
  его точного рабочего пути, даже при полностью принятом коде.
- Голосовой регламент пока не принят: не объявлять его правилом свежего main,
  не стирать как дубль и не вливать смешанный корень ради одного документа.
- Отзывы и голос не теряют приватные исходники ради «сохранения памяти» в Git.
  Здесь хранятся маршруты/границы, не медицинские сведения или клиентские тексты.

## Полнота

Запрошен короткий отчёт у 11 задач. Это не все задачи Codex и не полный дамп их
контекста. Дополнительные ответы ещё собираются; таблица содержит только уже
полученные сведения. Неизвестные зависимости сохраняются до проверки.
