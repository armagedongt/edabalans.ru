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
| МК: полный прогон материалов / `01a05a0a-ddf3-7b81-9d4e-21a39834a7ef` | `products.masterclass.course`, `platform.content`; `C:/Users/Segey/.codex/worktrees/46d8/edabalans.ru`, `codex/course-md-authoring-20260917`, HEAD `130c976`; вход `content/masterclass/editorial/README.md`, handoff `work/masterclass-endurance-comparison-2026-09-17/README.md` | 221 кандидат задания в локальном `program.md`, анализ книги и семейные черновики не приняты/не опубликованы. Предложение семейного материала после дня 6 пока только в переписке. Сохранять весь анализ и программу; старый checkout не использовать для переустановки Писаря |
| Предложеня МК / `01a0497b-1519-7092-8211-2fa4f560334f` | `platform.content` / `products.masterclass.course`; корень `codex/markiting`; книги `content/external-references/the-endurance-diet{,-integration-map}.md`, скрипт `content/masterclass/source-current/51-how-we-will-lose-weight-video-script.txt` | Справочные идеи не являются принятыми вставками в курс. Исторический handoff брать из commit `947be5b`, `work/integration-handoff.md`, ветка `codex/masterclass-first-video-handoff-20260829`; текущий одноимённый файл другой задачи не использовать. Сохранять исходную книгу и связанный прогон 46d8 |
| Каталог Постов / `01a048a1-bcc5-7693-a82d-cc4859ebba79` | `platform.content`; корень `codex/markiting`; старые ветка `codex/content-catalog-server` и папка `C:/Users/Segey/Documents/ChatGPT/edabalans.ru/.codex-worktrees/content-catalog-server`; канон `docs/CONTENT_CATALOG.md` | Старые реализация `70c84d6` и handoff `46a89aa` не доказаны эквивалентными текущему remote/main. Папка существует, но не зарегистрирована как отдельный worktree: сохранять, не объявлять мусором. Сохранять `work/content-authoring-system`; корневой одноимённый integration-handoff принадлежит другой работе |
| Реализовать Telegram AI Agent / `01a0551d-7806-7c80-b3bc-f10087950e6c` | Корень `codex/markiting`; два отдельных исследования `work/telegram-ai-agent-control/` и `work/telegram-voice-idea-assistant/`, включая `logs/userspec/` | Только untracked-исследования, реализации/приёма в main нет. Предложенный `platform.knowledge.telegram-intake` не зарегистрирован; это не готовый дополнительный голосовой маршрут. Control-plane и voice intake не дубли: обе папки сохранять |

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
- В main проверено наличие книги `the-endurance-diet.md` и скрипта первого видео,
  но старые `63951f8` / `947be5b` не входят в ancestry текущего main. Наличие файла
  не доказывает полную эквивалентность старой ветки; её также сохранять.
- Повторно использованные старые `work/integration-handoff.md` читать только
  из названного исторического commit/сохранённой копии, не по текущему пути в корне.

## Полнота

Получены адресные ответы всех 11 задач первой группы, плюс прежний ответ
Robokassa о завершённой копии. Это не все задачи Codex и не полный дамп их
контекста. Следующий отдельно согласованный контур художника пока оформляется
его владельцем; новые источники не объявляются принятыми до проверки main.
Неизвестные зависимости и все старые версии сохраняются до отдельного решения.
