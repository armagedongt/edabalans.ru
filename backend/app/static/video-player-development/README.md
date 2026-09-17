---
document_status: current
module_id: products.masterclass.runtime
---

# Использование нашего видеоплеера: возможности, настройки и места подключения

Здесь описано использование кастомного видеоплеера, разработанного для edabalans.ru.
Любую задачу о видео начинать здесь. Это каталог и правила повторного
использования, не третий движок. **Два действующих исполняемых источника:**
учебный `standard` и публичный плеер с тремя зарегистрированными presets.
Простая видеоотзывная вставка и iframe Boomstream не являются их новыми версиями.

Ссылки на код ведут к принятому `main`: основная локальная папка может быть на
старой ветке или содержать чужие незавершённые изменения. Не переносить её код
в новый выпуск целиком. Правила продукта и аналитики остаются у своих владельцев.

## Готовые профили

| Профиль / где применять | Старт и источник | Шкала / перемотка | Главы и обложка | Аналитика |
|---|---|---|---|---|
| **Учебный** `standard`: видео дня МК | Ручной старт; один HTTPS MP4 | Честная; перемотка разрешена | Обложка из данных; кликабельные главы при наличии таймкодов | Нет публичной; просмотр не завершает шаг курса |
| **Главная — VSL** `homepage-vsl` | Короткий muted loop; клик запускает с нуля со звуком; затем полный MP4 с той же позиции | Опережающая; перемотка запрещена | Глав нет; оформление/кадр задаёт оболочка | Осознанный просмотр, одна сессия preview + full |
| **Главная — Аня** `anya-review` | Та же логика preview + full | Опережающая; перемотка запрещена | Глав нет; портретный кадр и отложенная загрузка оболочки | Отдельный ID ролика, тот же событийный контракт |
| **Интенсив — день 1** `intensive-day-1` | Один полный MP4; muted loop до клика; затем с нуля со звуком без loop | Честная; перемотка разрешена | Глав нет | Завершение по просмотренным интервалам, не по перемотке к концу |

Это готовые наборы функций, не четыре копии HTML. Смена ролика/таймкодов
не создаёт новый профиль. Профиль интенсива — уже согласованное исключение;
не переносить его автозапуск и публичную аналитику на все учебные видео.
У всех четырёх доступны play/pause, звук/громкость, скорости 1/1.25/1.5/1.75/2
и полноэкранный режим в поддерживающем браузере. Субтитры, PiP и выбор качества
скрыты в текущем интерфейсе: наличие резервного кода не делает их активной функцией.

## Набор функций и источники

Функции ниже — компоненты видео-контура, **не новые `module_id`**.

| Функция | Где включена | Единственный исполняемый источник / владелец |
|---|---|---|
| Ручное учебное воспроизведение, честная шкала, главы | `standard` | [player-standard-with-contents.html](https://github.com/armagedongt/edabalans.ru/blob/main/backend/app/static/video-player-development/player-standard-with-contents.html); `products.masterclass.runtime` |
| Публичный autoplay, включение звука, preview → full | VSL и Аня; интенсив использует однофайловое исключение | [vsl-player.html](https://github.com/armagedongt/edabalans.ru/blob/main/backend/app/static/homepage-preview/vsl-player.html), `MEDIA_PRESETS`; `products.public-site` |
| Скорости, play/pause, fullscreen | Оба плеера | Соответствующий HTML из двух строк выше; не копировать controls в каждую страницу |
| Осознанная публичная аналитика | Три публичных presets | [PUBLIC_VIDEO_ANALYTICS.md](https://github.com/armagedongt/edabalans.ru/blob/main/docs/knowledge-base/PUBLIC_VIDEO_ANALYTICS.md), [API](https://github.com/armagedongt/edabalans.ru/blob/main/backend/app/public_video_analytics_routes.py); `products.public-site` |
| Один активный источник звука на странице | Подключённые публичные iframe и локальные audio/video | [media-coordinator.js](https://github.com/armagedongt/edabalans.ru/blob/main/backend/app/static/homepage-preview/media-coordinator.js), [PUBLIC_SITE.md](https://github.com/armagedongt/edabalans.ru/blob/main/docs/knowledge-base/PUBLIC_SITE.md); `products.public-site` |
| Видео/обложка/таймкоды дня | МК | [структура курса](https://github.com/armagedongt/edabalans.ru/blob/main/docs/knowledge-base/modules/masterclass/COURSE_STRUCTURE_CONTRACT.md), [renderer](https://github.com/armagedongt/edabalans.ru/blob/main/backend/app/static/masterclass-first-days-preview.html); `products.masterclass.course` |
| Маска, размеры, положение, тень | Оболочка каждого размещения | Потребитель: [PUBLIC_SITE.md](https://github.com/armagedongt/edabalans.ru/blob/main/docs/knowledge-base/PUBLIC_SITE.md), [визуальный паспорт МК](https://github.com/armagedongt/edabalans.ru/blob/main/docs/knowledge-base/modules/masterclass/COURSE_VISUAL_SYSTEM.md) |
| Архивы и расшифровки | Библиотека, не конфигурация плеера | [media-catalog.md](https://github.com/armagedongt/edabalans.ru/blob/main/content/media-catalog.md), [KNOWLEDGE_LIBRARY.md](https://github.com/armagedongt/edabalans.ru/blob/main/docs/KNOWLEDGE_LIBRARY.md); `platform.knowledge` |

## Каталог размещений

| Место / адрес | Реальная реализация | Профиль / статус | Источник настроек и владелец |
|---|---|---|---|
| Главная: `/preview/homepage-release-candidate`, `hero-video`; Tilda через `/homepage.js` | [release-candidate.html](https://github.com/armagedongt/edabalans.ru/blob/main/backend/app/static/homepage-preview/release-candidate.html) → `/preview/homepage-mobile/vsl-player.html` | `homepage-vsl`, используется | `homepageVslPreset`; `products.public-site` |
| Главная: история Ани | Та же RC → тот же публичный HTML | `anya-review`, используется | `MEDIA_PRESETS['anya-review']`; `products.public-site` |
| Главная: `#review-circle-video` | Обычный `<video>` и обработчик RC, не VSL-плеер | Простой однофайловый отзыв: muted loop, звук, play/pause; без глав/скоростей/VSL-аналитики | `<source data-src>` и обработчик RC; `products.public-site` |
| Интенсив: `/intensive/day-1`; встроенный первый день в `/intensive` | [day-1.html](https://github.com/armagedongt/edabalans.ru/blob/main/backend/app/static/intensive/day-1.html), [index.html](https://github.com/armagedongt/edabalans.ru/blob/main/backend/app/static/intensive/index.html), [runtime.js](https://github.com/armagedongt/edabalans.ru/blob/main/backend/app/static/intensive/runtime.js) → тот же публичный HTML | `intensive-day-1`, используется; для дней 2–4 такое подключение не найдено в проверенной ревизии | Preset: `products.public-site`; место/доступ: `products.intensive` |
| МК: видео в шапке дня, `/apps/masterclass-course.html` | Renderer курса → `/apps/video-player.html` → учебный HTML | `standard`, используется для прямого MP4 | `videoId`, `image`, `timings` дня; структура: `products.masterclass.course`, плеер: `products.masterclass.runtime` |
| Калорийный курс: `/apps/calories-course.html` | `app_routes.py` адаптирует тот же renderer, поэтому сохраняет путь MP4 → `/apps/video-player.html` | Технический потребитель `standard`; фактическое наличие видео читать из активной структуры курса, не считать все этапы видеолекциями | Данные этапа: `products.calories`; общий плеер: `products.masterclass.runtime` |
| МК: Boomstream ID/страница в шапке дня | Renderer → iframe провайдера | Внешний плеер; таймкоды дня — список под видео без управления чужой перемоткой | Поля дня; playback-интерфейс принадлежит провайдеру |
| МК: старый путь `materialMedia` | Renderer → `media` | **Резерв, не предусмотренный текущей программой:** не передаёт обложку/главы материала | Историческое поле `videoId`; автоматически не включать |
| `/preview/homepage-mobile` | [mobile.html](https://github.com/armagedongt/edabalans.ru/blob/main/backend/app/static/homepage-preview/mobile.html) → тот же публичный HTML | Legacy/noindex-оболочка, не канон новой главной | `products.public-site`; новые решения — в RC |

`masterclass-first-days-preview.html` — историческое имя действующего renderer,
не отдельный экспериментальный курс. Старый слайдер Ани в RC находится внутри
неактивного `<template>`; действует отдельный блок вне него. Floating-код есть,
но `floatingEnabled=false`: не включать его под видом обычной настройки ролика.
Точный список дней с видео берётся из активной структуры через разрешённый
course API/редактор, не из seed `content/masterclass/course/course.json`.
Внешние исторические Tilda-вставки вне репозитория требуют отдельной сверки.

Автономная `player-autoplay-analytics-fast-progress.html` снята с текущих
исходников: действующих подключений в репозитории не найдено, её payload не
соответствовал нашему API и она создавала лишнюю реализацию. Старый файл доступен
[в истории Git](https://github.com/armagedongt/edabalans.ru/blob/39e1c04a41281cede529d174dfd5b5cb33eded7b/backend/app/static/video-player-development/player-autoplay-analytics-fast-progress.html),
но не является шаблоном для новых страниц. Ничего не удаляется из хранилищ роликов.

## Как новый чат выбирает вариант

1. Прочитать этот вход, карточку владельца, актуальный `main` и активный поток по
   [CHAT_WORKSTREAMS.md](https://github.com/armagedongt/edabalans.ru/blob/main/docs/CHAT_WORKSTREAMS.md).
   Для работы не требуется история задачи «Видео чисто» или отдельный постоянный
   чат разработки видео: инструкции и ссылки на исполняемый код находятся здесь
   и в связанных канонических документах. Любой чат может продолжить работу
   по канону, но два потока не правят один источник одновременно.
2. Если владелец назвал место/готовый профиль, применить строку каталога без
   повторного выбора. Если дал только цель и подходят разные варианты, сначала
   спросить одним вопросом: «Учебный с перемоткой и главами, публичный продающий
   с превью без перемотки или отдельный видео-пример?» Кратко рекомендовать вариант.
3. Собрать существующий плеер + данные ролика + оболочку. Не копировать HTML,
   не менять `PLAYER_MODE` ради нового профиля, не создавать новый module_id.
   Если требуемого поведения нет, назвать разницу и согласовать расширение
   соответствующего существующего источника.
4. Изменения данных, поведения и размещения разделять: данные дня — в структуре;
   публичные источники — в presets; playback — в одном из двух HTML; геометрия
   — у оболочки. Ни данные, ни стили не дублируются на каждую страницу.
5. При новом/удалённом размещении или изменении возможностей обновить его строку
   здесь и затронутый продуктовый контракт. При завершении назвать место, профиль,
   источник настроек, файлы, проверки и фактический статус main/production.

## Учебное видео и сторонние примеры

Сейчас учебное видео МК предусмотрено только у дня. Если владелец отдельно введёт
его в материале, использовать тот же `standard` с обложкой и главами. Сначала
реализовать передачу этих данных материала: старый `materialMedia` этого не делает.
Новый формат в рамках ремонта плеера не вводится.

Стороннее видео-пример определяется назначением, не расширением файла. Оно не
получает автоматически учебные главы, обложку, автозапуск, прогресс или VSL-учёт.
Использовать обычную ссылку либо уже согласованное встраивание конкретного места.
Если подходящего встраивания нет — согласовать его отдельно, не обходить sanitizer:
[ARTICLE_STANDARD.md](https://github.com/armagedongt/edabalans.ru/blob/main/docs/knowledge-base/ARTICLE_STANDARD.md)
и [article_markup.py](https://github.com/armagedongt/edabalans.ru/blob/main/backend/app/article_markup.py)
блокируют произвольный iframe. Новый маркер Markdown или провайдер — не простая
настройка плеера.

## Настройки без новых версий

**МК, редактор дня:** ссылка на видео (`videoId`), обложка (`image`), содержание
(`timings`, строка `00:00 — название`). Видео имеет приоритет над картинкой;
при пустом видео картинка самостоятельная; если пусты оба, медиа не показывается.
Прямой HTTPS MP4 идёт в учебный плеер параметрами `src`, `poster`, `chapters`.
Названия глав — обычный текст, не HTML. Без глав кнопки содержания нет.
Boomstream ID/страница остаются у провайдера; прямая ссылка на его MP4 — у нас.
Ссылка просмотра Google Drive не является прямым MP4.

**Публичный плеер:** iframe указывает зарегистрированный `context`; presets
задают короткий/полный MP4, стабильный `videoId`, громкость и исключения профиля.
Неизвестный явно переданный context не запускает чужой ролик: показывает ошибку.
Отсутствие context сохранено только для совместимости старого подключения VSL;
новое размещение всегда задаёт context явно. Новый публичный ID должен быть
принят серверным whitelist. Не менять ID ради битрейта того же содержимого.
Короткий файл должен совпадать с началом полного: это одна логическая сессия.
`parent_origin` допускает только доверенные origins, не `*` и не произвольный домен.

Большие ролики, персональные медиа и дампы не помещать в Git. Этот каталог
не переносит ownership аналитики/интенсива в МК и не является библиотекой медиа.

## Проверка и обслуживание

Проверять затронутый профиль в его оболочке: запуск/пауза, звук, нужная шкала
и перемотка, скорости, fullscreen; для учебного — главы, обложка и отсутствие
содержания без таймкодов; для публичного — preview/full, engagement и сессия;
для страницы — отключение других источников звука, включая unmute уже играющего
локального видео. Не считать пустой preview заменой работающему подключению.

[Браузерные проверки поведения](https://github.com/armagedongt/edabalans.ru/blob/main/backend/tests/browser/video-player.e2e.mjs)
запускаются через `test:video-player` в существующем browser-пакете и production CI.
Они используют настоящий DOM/фокус/postMessage, подставляют декодирование медиа
и перехватывают API: не отправляют события или персональные данные в production.
Дополнительно: [подключения курса](https://github.com/armagedongt/edabalans.ru/blob/main/backend/tests/test_app_assets.py),
[публичные подключения](https://github.com/armagedongt/edabalans.ru/blob/main/backend/tests/test_homepage_preview.py),
[серверная аналитика](https://github.com/armagedongt/edabalans.ru/blob/main/backend/tests/test_public_video_analytics.py).

Ремонт 17.09.2026: экранирование глав; скрытие содержания без таймкодов;
состояние/focus меню глав; отказ хранилища без срыва playback/сессии;
проверка сохранённого viewer UUID; явная ошибка неизвестного preset;
доставка сообщений доверенному parent; координация звука по play и volumechange.
Резервная публичная аналитика из учебного движка и неподключённая автономная
копия удалены. Не восстанавливать их из старой ветки вместо работы с этим каноном.
