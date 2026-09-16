---
document_status: draft
module_id: admin.project-knowledge
date: 2026-09-17
---
# Видео: checkpoint и карта источников

## Вход в действующий канон

| Контур | Владелец | Канонический вход |
|---|---|---|
| Главный VSL, отзыв Ани, общий звук страницы | products.public-site | [PUBLIC_SITE.md](https://github.com/armagedongt/edabalans.ru/blob/main/docs/knowledge-base/PUBLIC_SITE.md) |
| Серверная статистика публичных просмотров | products.public-site | [PUBLIC_VIDEO_ANALYTICS.md](https://github.com/armagedongt/edabalans.ru/blob/main/docs/knowledge-base/PUBLIC_VIDEO_ANALYTICS.md) |
| Видео дня, обложка и главы МК | products.masterclass.runtime | [README плеера](https://github.com/armagedongt/edabalans.ru/blob/main/backend/app/static/video-player-development/README.md), [runtime курса](https://github.com/armagedongt/edabalans.ru/blob/main/docs/knowledge-base/modules/masterclass/COURSE_RUNTIME.md) |
| Видео/аудио, их тексты, архивы и происхождение | platform.knowledge | [media-catalog.md](https://github.com/armagedongt/edabalans.ru/blob/main/content/media-catalog.md), [KNOWLEDGE_LIBRARY.md](https://github.com/armagedongt/edabalans.ru/blob/main/docs/KNOWLEDGE_LIBRARY.md) |
| Явно отложенные доработки | products.masterclass.runtime | [VIDEO_PLAYER_DEFERRED.md](https://github.com/armagedongt/edabalans.ru/blob/main/docs/plans/VIDEO_PLAYER_DEFERRED.md) |

План и media-catalog содержат исторические формулировки: статус draft/planned
и старые ссылки не означают, что вся перечисленная работа ещё не внедрена.
Фактическое наличие функции проверять по текущему runtime и module registry,
а не запускать старый план автоматически.

## Реализация, которую можно переиспользовать

- Публичный плеер: `backend/app/static/homepage-preview/vsl-player.html`.
- Каноническая оболочка главной: `backend/app/static/homepage-preview/release-candidate.html`.
  T123 `/homepage.js` подключает `/preview/homepage-release-candidate?embed=tilda`.
  `mobile.html`/homepage-mobile — legacy/noindex, не новый источник решений.
- Единый источник звука: `backend/app/static/homepage-preview/media-coordinator.js`.
- Серверная аналитика: `backend/app/public_video_analytics_routes.py`;
  миграция `backend/migrations/versions/20260831_0033_public_video_analytics.py`.
- Учебный стандартный MP4: `backend/app/static/video-player-development/player-standard-with-contents.html`.
- Внешняя автономная заготовка: `backend/app/static/video-player-development/player-autoplay-analytics-fast-progress.html`.
- Встраивание медиа курса: `backend/app/static/masterclass.js`,
  `backend/app/masterclass_routes.py`.
- Данные и реальный renderer структуры курса принадлежат products.masterclass.course:
  `backend/app/static/masterclass-first-days-preview.html`,
  `backend/app/course_structure_routes.py`, `backend/app/course_structure_service.py`;
  контракт — `docs/knowledge-base/modules/masterclass/COURSE_STRUCTURE_CONTRACT.md`.
  `content/masterclass/course/course.json` — seed, не доказательство активной DB-версии.
- Проверки: `backend/tests/test_homepage_preview.py`,
  `backend/tests/test_public_video_analytics.py`,
  `backend/tests/test_masterclass_journey.py`, `backend/tests/test_masterclass_unlock_schedule.py`,
  `backend/tests/test_app_assets.py`; browser-проверки —
  `backend/tests/browser/`.

Это разные поддерживаемые контракты, не взаимозаменяемые копии одного файла.
Не заменять действующий runtime автономной заготовкой без проверки её интеграции.

## Ключевой контракт передачи

Публичные homepage-vsl и anya-review: короткий muted loop до взаимодействия,
длинный файл подключается после осознанного нажатия. Короткий файл должен быть
точным началом длинного с той же аудиодорожкой. Подмена не создаёт вторую
аналитическую сессию. Беззвучный autoplay не считается осознанным просмотром.

Первый день интенсива использует отдельный preset intensive-day-1: один полный
MP4, честная шкала и разрешённая перемотка. МК standard: ручной старт, обычная
шкала, главы с переходами, без публичной аналитики.

События между плеером и оболочкой:
`edabalans:player-active`, `edabalans:player-idle`,
`edabalans:pause-player`, `edabalans:video-analytics`.
Точный payload и проверки сообщений принадлежат текущей реализации.
Дополнительно существуют `edabalans:set-player-presentation` и
`edabalans:floating-dismiss`. Floating-код есть, но в канонической RC
`floatingEnabled=false`: нельзя объявлять режим включённым.
Координатор останавливает другие видео и аудио при ручном запуске звука;
беззвучное preview активным источником звука не становится.

Для floating нельзя создавать второй iframe/новый video_id/новую аналитику:
переиспользовать существующий живой экземпляр и внешнюю оболочку. Сохранения
позиции после перезагрузки из этого checkpoint не следует.

Видео МК задаётся данными дня: видео, обложка, таймкоды. Прямой HTTPS MP4
открывается штатным плеером; Boomstream ID/страница просмотра — iframe провайдера.
Для MP4 главы могут перематывать; внешний iframe не даёт безопасного
произвольного управления. Google Drive preview URL не является прямым MP4.
Header-видео дня не превращается автоматически в обязательный материал прогресса.
Для интенсива подтверждён preset первого дня; это не доказательство одинакового
подключения во всех четырёх днях. Владелец интенсива — products.intensive:
`backend/app/static/intensive/`, `backend/app/intensive_routes.py`,
`backend/app/intensive_web_access.py`, `docs/INTENSIVE_PAGES.md`.

Публичная статистика не доказывает готовую сквозную связь с auth, yclid,
Telegram или покупкой. Этот незавершённый контур не выдавать за реализованную воронку.

## Медиа и приватность

Сами большие видео не копировать в эту папку или Git. Канонические ссылки
публичных MP4 — в PUBLIC_SITE.md/runtime presets. Файлы, архивы и расшифровки —
по карте источников. Каталог содержит пути D:\Видео — проект и старые Obsidian
заметки: они не относятся к переносу архива Codex и не удалялись.
Клиентские отзывы и персональные расшифровки — приватные, исключённые из Git;
их маршрутом остаётся задача «Собрать и распознать отзывы».
Текстовые исходники: `content/masterclass/reference/transcripts/`,
`content/calories/reference/transcripts/`, `content/training/reference/transcripts/`.
Контентный каталог/медиа БД — platform.content, `docs/CONTENT_CATALOG.md`.
Коммерческий каталог записей — products.catalog, `backend/app/product_catalog_service.py`:
для ACCESS_CONSULTATION_RECORDINGS исполнитель подтвердил app=None/ready=False/planned;
работающий отдельный products.recordings этим исследованием не доказан.
Старые Boomstream-ресурсы не удалять, пока от них зависят Tilda-страницы.

## Принятие и ограничения

Коммит рамки Ани `49a37a8d89b877a90c45ad30f0448eeb9bc1afa4`
повторно подтверждён как предок origin/main. Задача «Видео чисто» ранее
сообщила его выпуск в production; в этой уборке сервер независимо не проверялся.

Полный новый ответ владельца получен 17.09.2026. Он сообщил совпадение
production с 453741ff и healthy backend на момент его сверки; в этом потоке
сервер не проверялся. Его аудит уникальных локальных файлов не завершён.

Отдельно проверены и СОХРАНЕНЫ две исторические ветки вне истории main:

- `codex/masterclass-first-video-handoff-20260829`, HEAD
  `947be5b2ec2eb0900f3a5229ac13494bea8b136d`: 18 коммитов вне истории main,
  включая сценарий первого видео, интеграционный handoff и другие материалы.
- `codex/recovered-video-preview-handoff-20260831`, HEAD
  `ccc3320c444257dbdf842dc356af8de2e47b3756`: один коммит Register video preview assets.
  Фактический diff этого коммита — только modules.toml и generated-карты,
  не сам код preview; наличие registration не доказывает сохранённый исходник.

В основной папке найден и СОХРАНЁН untracked оригинал
[video-player-white-bg-preview.html](../../../work/public-homepage-redesign/assets/video-player-white-bg-preview.html).
Это `work/public-homepage-redesign/assets/video-player-white-bg-preview.html`,
не канонический публичный renderer и не подтверждённая production-вставка.
Он не редактировался/не удалялся/не добавлялся в Git: папка public-homepage-redesign
связана с активным дизайном. Перед удалением или публикацией нужен разбор различий
и владения, а не предположение «регистрация означает всё сохранено».

Не-ancestor не доказывает смысловую уникальность: перенос мог быть cherry-pick.
Эти refs не удалялись и не вливались вслепую. Перед дальнейшей уборкой проверить
их handoff/preview относительно текущих источников; возможность чтения сохранилась в Git.
Целевой root-status с untracked для публичного player/coordinator/RC, учебной
папки плеера и work/modular-video-player — чистый. Это не полный аудит всех
архивов/любых видеофайлов компьютера; приватные источники не сканировались.
Задача не архивируется до доступного штатного архивирования и завершения
оговорённой проверки хвостов. Все старые видео-задумки реализованными не объявляются.
