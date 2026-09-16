# Проверки текущего MD-контракта

Дата: 16.09.2026. Только локальный прототип, не production/API-интеграция.

- 11 unittest-тестов проходят; code-reviewer и security-auditor независимо
  повторили их. Их свежие проверки изменённых границ — clean.
- Chromium smoke на 360/430/768/1440px: NOTE-minus раскрывается, ✓/× без input,
  del того же цвета/opacity1, таблица mobile:block / desktop:table-cell,
  CTA row на desktop / column mobile. documentWidth равен viewport.
- Clipboard забирает только свой pre/code. Windows CRLF сравниваются как логические
  LF, другие символы/строки не меняются. Отказ Clipboard показан, gap до кнопки16px,
  перекрытия нет. Проверки воспроизводимы через demo/smoke.mjs с установленным Playwright.
- capture.mjs: 360/430/619/620/621/768/899/900/901/1440px, #article,
  Inter400/600/800. На всех десяти assets.evidenceComplete/stable/mutationQuiet=true,
  обе картинки разрешены, ширина документа равна viewport.
- Основной поток просмотрел полные article360/1440 и отдельные mobile-table,
  desktop-actions, copy-denied360. Внешние evidence-файлы не сохраняются в Git.

Артефакты:
`C:/Users/Segey/AppData/Local/Temp/mk-md-contract-final-20260916-2301/`
и `C:/Users/Segey/AppData/Local/Temp/mk-md-contract-smoke-final-20260916-2308/`.
Test review первой волны выявил слабые assertions для связи пункта с ✓/×
и фактического размещения CTA. Исправлены именно проверки, не поведение:
Python связывает статус с исходным текстом, browser smoke проверяет glyph,
текст пункта и stack/row/center direction/align. Повторный smoke прошёл;
подготовлены open-spoiler PNG на всех четырёх ширинах. Layout review — clean.
Первый smoke использовал не тот accessible name кнопки, а первый capture —
неверный разделитель font аргумента; эти неуспешные запуски не используются
как финальное доказательство. Оба диагностических параметра исправлены.

Reviews одного набора запускаются последовательно на той же итоговой ревизии:
старые completed agent threads занимают доступные slots. Это ограничение
параллельного запуска, не заявленная параллельная проверка.
Публикационная авторизация, серверный DB/restore, вся грамматика Markdown,
UI приложения Obsidian, подключение Templates и deploy не проверялись.

Итог второй, последней волны: code/security/test/layout — clean. Documentation
review обнаружил одну неточность перехода ARTICLE_STANDARD: перечисление старых
правил было взято из прежнего checkout, а не свежего main. Исправлен только
переходный абзац: явно указан приоритет нового контракта, отсутствие заголовка
NOTE и мобильные карточки вместо прежнего scroll. Нижние правила и production
не переключались. Эта локальная документальная коррекция проверена основным
потоком по двум документам; третья волна не запускалась.
