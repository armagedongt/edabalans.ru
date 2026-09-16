---
document_status: draft
module_id: admin.project-knowledge
date: 2026-09-17
---
# QR-переключатель: передача завершённого функционала

Получено от задачи «QR-переключатель Telegram/MAX» 17.09.2026.
Владелец функционала — products.public-site; он уже упомянут в
[карточке модуля](https://github.com/armagedongt/edabalans.ru/blob/main/docs/knowledge-base/modules/catalog/products.public-site.md)
и [PUBLIC_SITE.md](https://github.com/armagedongt/edabalans.ru/blob/main/docs/knowledge-base/PUBLIC_SITE.md).
Эта передача не заводит второй канон.

## Где подключать

- `backend/app/static/homepage-preview/direct-intensive.html` — реальная реализация.
- `backend/app/static/homepage-preview/direct-intensive-telegram-qr.svg`,
  `direct-intensive-max-qr.svg` — статические fallback-коды.
- `backend/app/app_routes.py` — preview/T123 маршруты.
- `backend/tests/browser/direct-intensive.e2e.mjs`,
  `backend/tests/test_homepage_preview.py` — проверки.
- Получение назначения: существующий `POST /api/messaging/start-link`.

При загрузке для TG/MAX готовятся ссылки с рекламной атрибуцией.
Текущий код main различает назначения: кнопка читает `payload.deep_link`
для входа в бота, QR читает `payload.qr_url` (`https://edabalans.ru/q/U...`);
`prepare(channel,'button')` и `prepare(channel,'qr')` имеют разные состояния.
Это отличается от упрощённой фразы исходного handoff/PUBLIC_SITE об одной ссылке:
повторное подключение должно следовать текущему коду и E2E, а расхождение канона
передать владельцу products.public-site, не чинить во время уборки.
Быстрый клик кнопки ждёт до 500 мс,
затем использует встроенный прямой B-fallback. Сеть, HTTP-ошибка и невалидный
ответ также не ломают переход. Desktop от 900 px: выбранный QR читаем,
второй закрыт/размыт; ниже 900 px QR-блок отсутствует.

Атрибуция: utm_source, utm_medium, utm_campaign, utm_content, utm_term, yclid;
sessionStorage `edb_direct_intensive_attribution_v1`. Значения реальных
пользователей сюда не выгружаются. Новый потребитель переиспользует
каноническую подготовку ссылок, а не собирает другой redirect/QR-контракт.

Интеграционный коммит `4c8e3f2f77b9e5637683e723f38191c8ef276c40`
повторно подтверждён как предок origin/main. По handoff исполнителя
незавершённого по этому функционалу нет; сервер в этой уборке не проверялся.

## Что пока нельзя удалить

Основное дерево задачи:
`C:/Users/Segey/.codex/worktrees/d4ba/edabalans.ru`.
В нём остаётся untracked `work/public-homepage-redesign/qr-messenger-prototype/`.
Исполнитель отметил его как чужой/непринятый прототип. Поэтому это дерево
не считается пустым: сохранить прототип или выяснить его владельца перед удалением.
Чистая вспомогательная копия qr-main-integration удалена после сохранения передачи;
её принятый код остаётся в main, основное дерево d4ba с прототипом сохранено.
