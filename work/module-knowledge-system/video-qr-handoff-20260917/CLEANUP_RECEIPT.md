---
document_status: draft
module_id: admin.project-knowledge
date: 2026-09-17
---
# Квитанция уборки

## Удалены одиннадцать зарегистрированных рабочих копий

Перед удалением: точный путь и HEAD, чистый Git status с untracked,
HEAD предок origin/main, ignored только кэши/тестовые временные файлы,
нет внешних reparse targets и вложенных зарегистрированных деревьев.
Штатный git worktree remove завершился успешно.

- C:/Users/Segey/.codex/worktrees/d1a4/edabalans.ru — d2acee6f25834e6b7a0493907d067aacd0761545
- C:/Users/Segey/.codex/worktrees/favicon-release-20260909 — 548349844626bed412f4216beff180579c98109b
- C:/Users/Segey/Documents/ChatGPT/edabalans.ru/.codex-worktrees/app-reveal-max-20260909 — d2acee6f25834e6b7a0493907d067aacd0761545
- C:/Users/Segey/Documents/ChatGPT/edabalans.ru/.codex-worktrees/apps-admin-sync-20260908 — de78b8e404853097c24fd06017c34e7eb91ab33b
- C:/Users/Segey/Documents/ChatGPT/edabalans.ru/.codex-worktrees/apps-checkup-miniapp-20260908 — 0173eaa618419f2281c8459506918f487962a883
- C:/Users/Segey/Documents/ChatGPT/edabalans.ru/.codex-worktrees/apps-menu-20260909 — b60485cc4b91f3bd4a5095ba32037b2650df2a81
- C:/Users/Segey/Documents/ChatGPT/edabalans.ru/.codex-worktrees/bot-entry-audit-20260903 — 450d90b177d3a1a3ccd825f4ffb31c6e2c93c51e
- C:/Users/Segey/Documents/ChatGPT/edabalans.ru/.codex-worktrees/education-documents-main — 504641ae10c847886a8fba13b750f41a0633fad1
- C:/Users/Segey/Documents/ChatGPT/edabalans.ru/.codex-worktrees/timeweb-monitoring-20260904 — d8e5201261c3f03a04b36741c00bff98bda6ff34

Код этих версий восстанавливается из main/Git. Кэши создаются заново.
Истории задач и основная папка проекта не удалялись; Git-ветки не удалялись.

После сохранения handoff удалены также две чистые принятые вспомогательные копии:

- C:/Users/Segey/.codex/visualizations/2026/09/04/01a06df4-9ee9-7163-8046-3c8bf444487b/qr-main-integration — a619e35eccd51747841ddfb8cc56395374ade18e
- C:/Users/Segey/Documents/ChatGPT/edabalans.ru/.codex-worktrees/anya-aspect-ratio-20260908 — 49a37a8d89b877a90c45ad30f0448eeb9bc1afa4

После этого измерено 264306688 байт свободно на C (~252 МиБ),
что всё ещё меньше необходимых для возвращения архива 3,05 ГиБ.

## Частичное удаление

`C:/Users/Segey/Documents/ChatGPT/edabalans.ru/.codex-worktrees/telegram-proxy-runbook-integration`:
Git удалил регистрацию и .git, но оставил часть файлов из-за длинных путей.
После этого найдено 2239 обычных файлов / 140515145 байт и 68 внутренних
junctions зависимостей. Рекурсивное удаление остатка заблокировано средой,
обход не выполнялся. Это теперь папка-остаток, не действующий worktree.

## Сохранены

Я.Директ и связанные деревья; «Как проходит консультация — редакторская…»;
Design/Pricing/Train/редакторский МК; VSL и max-miniapp-home;
Robokassa и subscription recovery; погода.
«Сайт с погодой» переименована и помещена в раздел «Сторонние проекты»;
новый Git/worktree не создавался.

## Почему задачи ещё не архивированы

У «Прототип входа в интенсив», «Калории», «Интегратор дизайна» штатное
архивирование ранее вернуло os error17 (перемещение между дисками).
Подтверждено файловой системой и handoff «ПК менеджер»:
`C:/Users/Segey/.codex/archived_sessions` — junction на
`D:/Codex-Archive/archived_sessions`; sessions/worktrees обычные папки на C.
На D архив содержит 557 файлов / 3273171346 байт.
Других завершённых переносов данных Codex на D ПК-менеджер не подтвердил.

Доступного места на C для возвращения архива недостаточно:
измерения свободного менялись от 89 до 993 МБ во время работы.
Поэтому данные архива и junction не изменялись; D-копия не удалялась.
Предложенный безопасный возврат: отдельная копия на C, сверка имён и SHA-256,
переключение только junction, проверка истории/archive, затем удаление дубликата D.
Требуется предварительно достаточный стабильный запас места и безопасное окно.

Изменение свободного места не равно весу удалённых файлов: параллельная работа
меняет диск. Старый inventory — логические размеры, не измерение освобождённых кластеров.
