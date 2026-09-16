# Общие блоки текстовых материалов

Статус: `draft` · владелец: `platform.content` · реализация: `in_development`.

Это редактируемые **источники**, не установленная копия навыка и не выгрузка
публикуемых статей. Сейчас подключены непосредственно только в локальном стенде.
Главный контракт: [Markdown → материалы](../../docs/knowledge-base/MARKDOWN_MATERIAL_TRANSFER.md).
Общее оформление: [ARTICLE_STANDARD](../../docs/knowledge-base/ARTICLE_STANDARD.md).

| Роль | Где редактировать сейчас | Что меняется централизованно |
|---|---|---|
| Жёлтая плашка | [note.css](note.css) | Фон, интервалы, форма |
| Подсветка, зачёркивание, линия, изображение | [formatting.css](formatting.css) | Общие визуальные ограничения |
| Копируемый блок | [copy.css](copy.css); demo/md-copy.js | Блок/кнопка; только текст блока |
| Кнопки-ссылки | [actions.css](actions.css) | Stack/row/center; финальный дизайн интегрирует Design |
| Положительный/отрицательный список | [status-list.css](status-list.css) | Исходные знаки с главной, не чекбоксы |
| Простая адаптивная таблица | [table.css](table.css) | Таблица → карточки строк на телефоне |
| Цитата | ARTICLE_STANDARD; пока demo/lk-preview.css | Штатная цитата, не жёлтая note |
| Спойлер | content/masterclass/components/article-spoiler/spoiler.css | Уже существующий продуктовый компонент |

Рендерер новых ролей пока в `work/masterclass-obsidian-publishing/demo/serve_demo.py`.
Это переходный адаптер, **не готовый публичный SDK**. При интеграции извлечь общий
adapter в platform.content и перестать использовать work как runtime-источник.
CSS ограничен `#article`; интегратор должен дать всем оболочкам согласованный
корневой selector, не копировать файлы и не расширять стили на весь LK.

Каталог оригинальных вставок: `content/masterclass/components/README.md`.
В старом checkout этот путь может отсутствовать: доверенный полный исходник есть
в Git `f151218ee685857ffd32ae02dc75b915328093a9`, не вторая вручную созданная копия.
Спойлер стенд читает из этого pinned ref; изменения рабочего файла специального
компонента не будут видны до переключения источника интегратором. Общие CSS выше
читаются с диска при запросе и видны после обновления браузера.

Иконки перенесены из **реального исходника**, не со скриншота:
`work/public-homepage-redesign/homepage-local.html` worktree
`homepage-block-approval-20260910`, HEAD `037fbc586d364ae4f2c858b4b9a3fa3141736ada`,
`.proof-list li::before` / `.proof-list__item--warning::before`.
32px, radius9, ✓19px #299b57/#d7f2e0, ×25px #d34f42/#ffe4df.
Меняются через токены одной библиотеки, не разметкой каждой статьи.

[Шпаргалка](OBSIDIAN_CHEATSHEET.md) · [Передача Design](DESIGN_HANDOFF.md)
· [Нативные шаблоны](obsidian-templates/).
