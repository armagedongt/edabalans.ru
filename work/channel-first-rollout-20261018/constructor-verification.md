# Конструктор и наблюдения —19.10.2026

## Итог локальной проверки

Реализация проверена и ожидает интеграции после выпуска доменного чата.
После объединения с c213894 полный набор бота: 411 passed (217,9 с).
Отдельный интеграционный набор сайта: 105 passed; исправленный canonical assert
также прошёл. Действующий Telegram API подтвердил пять команд и роль administrator
в собственном канале. Обе действующие страницы /c вернули HTTP200 без redirect.
Расширенный backend-набор: 95 passed, один старый строковый assert посадочной
исправлен и перепроверен вместе с 19 constructor cases: 20 passed. Bot: 46 passed.
Node bridge: 17 passed. Полный direct-intensive Playwright прошёл: кнопки, QR,
Mini App URL, MAX, fallback, UTM и мобильные переходы.

Обе волны: code/security/test/docs/layout. Исправлены caller посадочной, повторное
использование U, граница следующего входа, callback вне периода, вёрстка фильтров
и устаревший статус подписного блока. Security/docs/layout второй волны чистые.
После второй волны локально исправлены мобильный URL-предикат теста и группировка
по (link, platform, placement), чтобы смена площадки не переписывала историю.
Прямые regression cases прошли; третьей волны не было.

Итоговая визуальная evidence: `D:/Codex/evidence/channel-constructor-20261019-d`,
20 ширин 360–1501, documentWidth равен viewportWidth. Прежний комплект c ниже —
промежуточный. Посадочная теперь использует Telegram alias ya, MAX сохраняет BMB6Y.
При выпуске открыть список конструктора для создания девяти профильных кодов.

Baseline-исправления выделены в b3b76f2 и приняты доменным чатом в b0389a5.
Ниже сохранён промежуточный журнал, а не текущий статус выпуска.

База7fc88a6; текущий срез ещё не опубликован. Website+greeting уже в main и
production7fc88a6, targetedtests passed; CI7fc manifest-only пропустил runtime.
Новыйсодержательныйсрез backend+bot должен пройти оба полныхнабора дофинала.

## Граница

- Новый экран общейадминки /admin/channel-links, старый /bot#links сохранён архивным.
- Существующие link/alias/session/event tables, новые ORM mappings только существующих
  физических таблиц/полей; конфигmanaged documents с version/history. Migrationнет.
- Стабильныйкод6символов либо прежнийпрофильный2–4символа; запросразрешенияпоумолчанию,
  выключательпереходабеззапроса. ПодписаннаяSDKпроверка, цели только ownchannelposts.
- RawinitDataнесохраняется; первыйснимокконфига навесьвизит, клиентскиеcallbacks
  отделеныотwebhook. Отказ/нетответа/непросили/уже разрешено — разныенаблюдения.
- РекламныеU/QR открываютMiniApp напрямую, контекстyclid/UTM/browser/tag_id сохранён;
  U расходуетсяодинраз, callbacksиспользуютснимок. ПозднийStartвосстанавливаетsource.
- Ownchannelmembership безinvite фиксируетсяиобновляетсвежийMessengerAccount.
- Отчётпо Москве, ссылкам/площадкам, входывключаябезStart, хронология последующих
  действий, статьяcourse_events и главнаяbrowser_page. Unknownнефальшивый0.
- MAXканальныйMiniAppнетregisteredadapter: невыдаватьфальшивыессылки; действующие
  MAXlinksнеизменены. Связьперсональногочтенияглавнойнеподключена — задачаDirect/VSL
  послеэтого выпуска. Серверноеwritepermissionне запускаетавтоматическуюрассылку.

## Проверки

Backend32bridge/constructorpassed; расширенныйmarketing/browser набор56passedдо
последнихмалыхнормализаций; финальныйповторзапущен. Bot46entry/trackingpassed.
Node17bridgecasespassed: callbacks true/false, analytics failureнеблокируетканал,
провереннаядругаяцель. UIcreate/edit+stableURLpassedнаlocalSQLite, syntheticdataonly.
Visualcapture: D:/Codex/evidence/channel-constructor-20261019-c (20widths),
channel-constructor-filled-20261019-a (4widthsfullpage). C — послеисправленияформы
checkbox/input; A/B — ранняяevidence, не окончательныйвид. Authcapture helper—
временнаякопияcapture.mjs с fakeBasicextraheader длялокальногоpreview, неGit.

## Попутные ошибки CI предыдущего среза

- block-mapfree-intensive.fields теперьtitle; параграф принадлежитобщемуисточнику,
  полный textSlotsdigestсохранён длясовместимости старыхpublishedhomepage.
- blogaddresseshistorytest сравниваеттолькоdraft/publishedversionsданнойподсистемы,
  не новыеlegitimatesharedseedдокументы. Directchecks23passed.
- Чатпереносадомена отдельноисправляет4legacyCTAexpectations вtest_blog_draft_authoring;
  туже canonicalsourceпараллельно не правим. Его1696d59ещёнепринятвнашHEAD.
