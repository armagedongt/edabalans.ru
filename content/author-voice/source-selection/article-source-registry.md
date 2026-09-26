# Единый реестр семей длинных статей

Статус: `current`  
Модуль: `platform.content`  
Обновлено: 25.09.2026

Машиночитаемый канон решений — [`article-source-registry.json`](article-source-registry.json). Полные тексты остаются в собственных источниках и серверном Knowledge Library; этот реестр хранит только маршрутизацию, provenance и семейные связи.
Актуальный поимённый разбор владельца: [единый файл семей](ARTICLE_FAMILIES.md). Категории deferred_kind ниже — исторический результат классификатора, а не последняя команда о публикации; приоритет у article-owner-decisions.json и owner_source_decisions.

## Сводка

- В блоге: **44** канонические семьи.
- В известном внешнем корпусе: **282** проявления — Pikabu 105, Telegraph 163, VC.ru 14.
- Уже привязано к канонам блога: **51** внешних проявлений.
- Дополнительно прочитано статей старого интенсива: **13**; подтверждённые источники канона не создают вторую семью.
- Отложено как отдельные безопасные семьи до подтверждения дублей: **243**.
- Возможных пар пересечения: **75**; это очередь проверки, а не автоматически склеенные дубли.
- Короткие посты имеют отдельное представление; ссылки из канала и длинные Telegram-версии связаны с семьями через приватную карту `article-channel-links.json` (см. ARTICLE_SOURCE_LINKING.md).

## Канон в блоге

| Статья | Канон | Привязанные внешние проявления | Возможные версии на проверку |
|---|---|---:|---:|
| 10 дебильных фактов о вредных продуктах для похудения | [blog:10-debilnyh-faktov-o-vrednyh-produktah](https://blog.похудение-это-есть.рф/articles/10-debilnyh-faktov-o-vrednyh-produktah) | 1 | 0 |
| 15 советов тем, кто худеет — по одному на килограмм лишнего веса | [blog:15-sovetov-tem-kto-hudeet](https://blog.похудение-это-есть.рф/articles/15-sovetov-tem-kto-hudeet) | 1 | 0 |
| «Сладкоежка — увеличьте дозу витаминов!» | [blog:sladkoezhka-uvelichte-dozu-vitaminov](https://blog.похудение-это-есть.рф/articles/sladkoezhka-uvelichte-dozu-vitaminov) | 1 | 0 |
| А мне тренер посоветовал… | [blog:a-mne-trener-posovetoval](https://blog.похудение-это-есть.рф/articles/a-mne-trener-posovetoval) | 1 | 1 |
| Борьба с лишним весом: почему одних шагов недостаточно | [blog:borba-s-lishnim-vesom-pochemu-shagov-nedostatochno](https://blog.похудение-это-есть.рф/articles/borba-s-lishnim-vesom-pochemu-shagov-nedostatochno) | 1 | 0 |
| Великий пост, похудение и здоровье | [blog:velikiy-post-pohudenie-i-zdorove](https://blog.похудение-это-есть.рф/articles/velikiy-post-pohudenie-i-zdorove) | 1 | 0 |
| Весы — инструкция по применению | [blog:vesy-instrukciya-po-primeneniyu](https://blog.похудение-это-есть.рф/articles/vesy-instrukciya-po-primeneniyu) | 1 | 0 |
| Главные ошибки в похудении: что нужно знать до того, как испытывать голод | [blog:glavnye-oshibki-v-pohudenii-do-goloda](https://blog.похудение-это-есть.рф/articles/glavnye-oshibki-v-pohudenii-do-goloda) | 1 | 0 |
| Гликемический индекс — это лишнее! | [blog:glikemicheskiy-indeks-eto-lishnee](https://blog.похудение-это-есть.рф/articles/glikemicheskiy-indeks-eto-lishnee) | 1 | 1 |
| Диета. Срыв. И математика | [blog:dieta-sryv-i-matematika](https://blog.похудение-это-есть.рф/articles/dieta-sryv-i-matematika) | 1 | 0 |
| Задача — похудеть. Уровень сложности — ЗИМА | [blog:zadacha-pohudet-uroven-slozhnosti-zima](https://blog.похудение-это-есть.рф/articles/zadacha-pohudet-uroven-slozhnosti-zima) | 3 | 0 |
| Измеряем вашу жирность | [blog:izmeryaem-vashu-zhirnost](https://blog.похудение-это-есть.рф/articles/izmeryaem-vashu-zhirnost) | 2 | 0 |
| Интуитивное питание — вы всё неправильно поняли | [blog:intuitivnoe-pitanie-vy-vse-nepravilno-ponyali](https://blog.похудение-это-есть.рф/articles/intuitivnoe-pitanie-vy-vse-nepravilno-ponyali) | 2 | 0 |
| Как начать тренировки и не бросить | [blog:kak-nachat-trenirovki-i-ne-brosit](https://blog.похудение-это-есть.рф/articles/kak-nachat-trenirovki-i-ne-brosit) | 3 | 3 |
| Как я решил пройти 100 000 шагов за один день | [blog:kak-ya-reshil-proyti-100000-shagov](https://blog.похудение-это-есть.рф/articles/kak-ya-reshil-proyti-100000-shagov) | 1 | 1 |
| Какая самая вредная диета? | [blog:kakaya-samaya-vrednaya-dieta](https://blog.похудение-это-есть.рф/articles/kakaya-samaya-vrednaya-dieta) | 2 | 0 |
| Минус 12 килограммов за 2 месяца | [blog:minus-12-kilogrammov-za-2-mesyaca](https://blog.похудение-это-есть.рф/articles/minus-12-kilogrammov-za-2-mesyaca) | 1 | 0 |
| Можно ли пить во время еды? | [blog:mozhno-li-pit-vo-vremya-edy](https://blog.похудение-это-есть.рф/articles/mozhno-li-pit-vo-vremya-edy) | 1 | 2 |
| Мусорная рыба или мусорные нутрициологи? | [blog:musornaya-ryba-ili-musornye-nutriciologi](https://blog.похудение-это-есть.рф/articles/musornaya-ryba-ili-musornye-nutriciologi) | 2 | 0 |
| Неприятная правда про мёд | [blog:nepriyatnaya-pravda-pro-med](https://blog.похудение-это-есть.рф/articles/nepriyatnaya-pravda-pro-med) | 1 | 0 |
| Нет времени объяснять. Просто худей! | [blog:net-vremeni-obyasnyat-prosto-hudey](https://blog.похудение-это-есть.рф/articles/net-vremeni-obyasnyat-prosto-hudey) | 1 | 0 |
| Нутрициолог или диетолог — кому верить? | [blog:nutriciolog-ili-dietolog-komu-verit](https://blog.похудение-это-есть.рф/articles/nutriciolog-ili-dietolog-komu-verit) | 1 | 0 |
| О ярлыках | [blog:o-yarlykah](https://blog.похудение-это-есть.рф/articles/o-yarlykah) | 1 | 0 |
| Один небольшой прыжок — большие перемены в жизни | [blog:odin-nebolshoy-pryzhok-bolshie-peremeny](https://blog.похудение-это-есть.рф/articles/odin-nebolshoy-pryzhok-bolshie-peremeny) | 1 | 1 |
| Потеря мышц при похудении | [blog:poterya-myshc-pri-pohudenii](https://blog.похудение-это-есть.рф/articles/poterya-myshc-pri-pohudenii) | 1 | 0 |
| Похудение начинается не с похудения | [blog:pohudenie-nachinaetsya-ne-s-pohudeniya](https://blog.похудение-это-есть.рф/articles/pohudenie-nachinaetsya-ne-s-pohudeniya) | 1 | 2 |
| Почему люди худеют и снова набирают вес | [blog:pochemu-lyudi-hudeyut-i-snova-nabirayut-ves](https://blog.похудение-это-есть.рф/articles/pochemu-lyudi-hudeyut-i-snova-nabirayut-ves) | 1 | 0 |
| Почему японцы худые, а ты нет? | [blog:pochemu-yapontsy-hudye-a-ty-net](https://blog.похудение-это-есть.рф/articles/pochemu-yapontsy-hudye-a-ty-net) | 1 | 1 |
| ПП-рецепты — это плохо. И вот почему | [blog:pp-recepty-eto-ploho](https://blog.похудение-это-есть.рф/articles/pp-recepty-eto-ploho) | 1 | 2 |
| Правила безопасности за шведским столом | [blog:pravila-bezopasnosti-za-shvedskim-stolom](https://blog.похудение-это-есть.рф/articles/pravila-bezopasnosti-za-shvedskim-stolom) | 1 | 1 |
| Правило 30-ти растений | [blog:pravilo-30-rasteniy](https://blog.похудение-это-есть.рф/articles/pravilo-30-rasteniy) | 1 | 0 |
| Профессиональный едок | [blog:professionalnyy-edok](https://blog.похудение-это-есть.рф/articles/professionalnyy-edok) | 1 | 0 |
| Самый здоровый человек на планете | [blog:samyy-zdorovyy-chelovek-na-planete](https://blog.похудение-это-есть.рф/articles/samyy-zdorovyy-chelovek-na-planete) | 1 | 0 |
| Сахарозаменитель в диетических напитках вызывает рак? Нет | [blog:saharozamenitel-vyzyvaet-rak-net](https://blog.похудение-это-есть.рф/articles/saharozamenitel-vyzyvaet-rak-net) | 1 | 1 |
| Сделать похудение проще | [blog:sdelat-pohudenie-proshche](https://blog.похудение-это-есть.рф/articles/sdelat-pohudenie-proshche) | 1 | 0 |
| Сколько времени нужно на похудение? | [blog:skolko-vremeni-nuzhno-na-pohudenie](https://blog.похудение-это-есть.рф/articles/skolko-vremeni-nuzhno-na-pohudenie) | 1 | 0 |
| Скрытые запоры и банальный сюжет | [blog:skrytye-zapory-i-banalnyy-syuzhet](https://blog.похудение-это-есть.рф/articles/skrytye-zapory-i-banalnyy-syuzhet) | 1 | 0 |
| Температура воды для приёма внутрь | [blog:temperatura-vody-dlya-priema-vnutr](https://blog.похудение-это-есть.рф/articles/temperatura-vody-dlya-priema-vnutr) | 1 | 1 |
| Три ошибки в начале похудения | [blog:tri-oshibki-v-nachale-pohudeniya](https://blog.похудение-это-есть.рф/articles/tri-oshibki-v-nachale-pohudeniya) | 1 | 0 |
| Уколол и похудел: Оземпик, Семавик и нюансы | [blog:ukolol-i-pohudel-ozempik-semavik-nyuansy](https://blog.похудение-это-есть.рф/articles/ukolol-i-pohudel-ozempik-semavik-nyuansy) | 1 | 1 |
| Ходить, чтобы худеть | [blog:hodit-chtoby-hudet](https://blog.похудение-это-есть.рф/articles/hodit-chtoby-hudet) | 1 | 0 |
| Хочешь худеть? Заткнись и ешь картошку! | [blog:hochesh-hudet-esh-kartoshku](https://blog.похудение-это-есть.рф/articles/hochesh-hudet-esh-kartoshku) | 1 | 0 |
| Что вы не понимаете о формировании привычек? | [blog:chto-vy-ne-ponimaete-o-formirovanii-privychek](https://blog.похудение-это-есть.рф/articles/chto-vy-ne-ponimaete-o-formirovanii-privychek) | 4 | 0 |
| Эти долбанные 10 000 шагов | [blog:eti-dolbannye-10000-shagov](https://blog.похудение-это-есть.рф/articles/eti-dolbannye-10000-shagov) | 1 | 0 |

## Отложенный корпус по типам

| Тип | Количество | Что означает |
|---|---:|---|
| `deferred_not_now` | 18 | Владелец прямо решил пока не брать. |
| `editorial_review` | 93 | Полная статья-кандидат: проверить семейство, пользу, актуальность и выбрать основу. |
| `incomplete_draft` | 14 | Черновик/заметка: не считать готовой статьёй. |
| `obsolete_product_archive` | 4 | Неактуальный архив старого МК: сохранить для истории, не предлагать к публикации и не использовать как актуальную авторскую основу. |
| `owner_review_later` | 3 | Нужен отдельный просмотр владельцем. |
| `private_product_material` | 43 | Курс или Мастер-класс: не публиковать автоматически. |
| `short_reserve` | 43 | Материал 3000–3999 знаков: сначала решить, является ли самостоятельной статьёй. |
| `technical_or_service` | 25 | Техническая страница, сценарий, услуга, продажная или посторонняя сущность. |

## Все отложенные материалы

| ID | Источник | Материал | Статус | Возможные версии |
|---|---|---|---|---:|
| A041 | pikabu | ["Что я ем за день, при снижении веса, едим сытно!"](https://pikabu.ru/story/chto_ya_em_za_den_pri_snizhenii_vesa_edim_syitno_11141342) | `editorial_review` | 0 |
| A237 | telegraph | [(не) Только калории](https://telegra.ph/ne-Tolko-kalorii-07-16) | `editorial_review` | 0 |
| A107 | telegraph | [10 000 и 1 шаг. Сказка про здоровый образ жизни. Или нет?](https://telegra.ph/10-000-i-1-shag-Skazka-pro-zdorovyj-obraz-zhizni-Ili-net-06-16) | `deferred_not_now` | 1 |
| A004 | pikabu | [10 000 и 1 шаг. Так должна называться сказка про здоровый образ жизни. Или нет?](https://pikabu.ru/story/10_000_i_1_shag_tak_dolzhna_nazyivatsya_skazka_pro_zdorovyiy_obraz_zhizni_ili_net_10190123) | `deferred_not_now` | 1 |
| A062 | pikabu | [100 000 шагов за ОДИН день](https://pikabu.ru/story/100_000_shagov_za_odin_den_11528528) | `editorial_review` | 0 |
| A119 | telegraph | [100 способов сжечь жир](https://telegra.ph/22-05-29-5) | `incomplete_draft` | 0 |
| A016 | pikabu | [13 правил для организации домашних тренировок1](https://pikabu.ru/story/13_pravil_dlya_organizatsii_domashnikh_trenirovok_10425659) | `editorial_review` | 1 |
| A050 | pikabu | [55 дней до лета. Похудеть на 10 кг уже вряд ли выйдет, но вот 4-5-6 вполне реально!!](https://pikabu.ru/story/55_dney_do_leta_pokhudet_na_10_kg_uzhe_vryad_li_vyiydet_no_vot_456_vpolne_realno_11296380) | `short_reserve` | 1 |
| A026 | pikabu | [7 способов как восстанавливаться между тренировками на 100%](https://pikabu.ru/story/7_sposobov_kak_vosstanavlivatsya_mezhdu_trenirovkami_na_100_10715268) | `deferred_not_now` | 0 |
| A125 | telegraph | [8 советов тем, кто начинает бегать](https://telegra.ph/8-sovetov-tem-kto-nachinaet-begat-06-16) | `editorial_review` | 2 |
| A154 | telegraph | [empty](https://telegra.ph/Kachestvo-pitaniya-07-28) | `private_product_material` | 0 |
| A209 | telegraph | [VSL](https://telegra.ph/VSL-02-09) | `technical_or_service` | 0 |
| A273 | vc.ru | [«Поменять жизнь за 140 дней» ](https://vc.ru/flood/1520842-pomenyat-zhizn-za-140-dnei) | `short_reserve` | 1 |
| A217 | telegraph | [«У взрослой женщины не должно быть ###»](https://telegra.ph/ZHenshchina-dolzhna-06-21) | `editorial_review` | 0 |
| A076 | pikabu | [«У взрослой женщины не должно быть перекусов»](https://pikabu.ru/story/u_vzrosloy_zhenshchinyi_ne_dolzhno_byit_perekusov_11906015) | `editorial_review` | 0 |
| A126 | telegraph | [А мне тренер посоветовал...](https://telegra.ph/A-mne-trener-posovetoval-07-04) | `editorial_review` | 1 |
| A127 | telegraph | [Алексей золотов про запуски статья](https://telegra.ph/Aleksej-zolotov-pro-zapuski-statya-12-07) | `technical_or_service` | 0 |
| A043 | pikabu | [Белый рис, воровство, куры и витамин B1. А причем тут здоровое питание... ?](https://pikabu.ru/story/belyiy_ris_vorovstvo_kuryi_i_vitamin_b1_a_prichem_tut_zdorovoe_pitanie__11188875) | `short_reserve` | 0 |
| A228 | telegraph | [Блоки в питании и каталог приемов пищи](https://telegra.ph/feedback-04-04) | `editorial_review` | 0 |
| A049 | pikabu | [В своем уме, что ли? Фрукты... ограничивать... просто так, без мед. показаний?!](https://pikabu.ru/story/v_svoem_ume_chto_li_fruktyi_ogranichivat_prosto_tak_bez_med_pokazaniy_11294636) | `short_reserve` | 0 |
| A238 | telegraph | [Вам не надо худеть, вам надо кое-что другое...](https://telegra.ph/ne-hudet-07-12) | `editorial_review` | 0 |
| A271 | vc.ru | [Вам не нужен ПП-кулич!! ](https://vc.ru/flood/1159178-vam-ne-nuzhen-pp-kulich) | `short_reserve` | 1 |
| A263 | telegraph | [ввв](https://telegra.ph/vvv-04-24-44) | `technical_or_service` | 0 |
| A216 | telegraph | [Взгляд в будущее](https://telegra.ph/Vzglyad-v-budushchee-03-02) | `private_product_material` | 0 |
| A211 | telegraph | [Видео про фрукты](https://telegra.ph/Video-pro-frukty-07-24) | `incomplete_draft` | 0 |
| A210 | telegraph | [Видео. Последний жир в области живота. План действий⁠⁠](https://telegra.ph/Video-Poslednij-zhir-v-oblasti-zhivota-Plan-dejstvij-08-13) | `incomplete_draft` | 2 |
| A212 | telegraph | [Витамин N](https://telegra.ph/Vitamin-N-11-16) | `incomplete_draft` | 0 |
| A214 | telegraph | [Вода](https://telegra.ph/Voda-01-07-2) | `private_product_material` | 0 |
| A037 | pikabu | [Вот вам и ОЛИВЬЕ!1](https://pikabu.ru/story/vot_vam_i_olive_10978866) | `short_reserve` | 0 |
| A002 | pikabu | [Все знают, никто не делает](https://pikabu.ru/story/vse_znayut_nikto_ne_delaet_10123213) | `editorial_review` | 0 |
| A250 | telegraph | [Гайд по добавленному сахару](https://telegra.ph/slipnetsa-01-25) | `private_product_material` | 1 |
| A018 | pikabu | [Гарвардская тарелка курильщика и алкоритмы Пикабу!](https://pikabu.ru/story/garvardskaya_tarelka_kurilshchika_i_alkoritmyi_pikabu_10510751) | `short_reserve` | 0 |
| A110 | telegraph | [Где справедливость?](https://telegra.ph/111-07-23-18) | `incomplete_draft` | 0 |
| A149 | telegraph | [Гигиена питания](https://telegra.ph/Help-01-01-29) | `incomplete_draft` | 2 |
| A227 | telegraph | [Гигиена питания](https://telegra.ph/eating-hygiene-04-12) | `editorial_review` | 2 |
| A164 | telegraph | [Гид по добавленному сахару](https://telegra.ph/Mini-gajd-po-dobavlennomu-saharu-02-05) | `private_product_material` | 1 |
| A147 | telegraph | [Гликемический индекс — это лишнее!](https://telegra.ph/GI-and-GL-03-09) | `editorial_review` | 1 |
| A148 | telegraph | [Глобальный промт-инструкция для работы ИИ-агента с Пользователем](https://telegra.ph/Globalnyj-promt-instrukciya-dlya-raboty-II-agenta-s-Polzovatelem-11-19) | `technical_or_service` | 0 |
| A143 | telegraph | [Два соуса. Красное и белое. ](https://telegra.ph/Dva-sousa-Krasnoe-i-beloe-03-18) | `private_product_material` | 0 |
| A194 | telegraph | [День 1. Отчеты.](https://telegra.ph/Reports-12-11-2) | `private_product_material` | 0 |
| A239 | telegraph | [День 10. Организация питания](https://telegra.ph/organozacia-pitania-04-10) | `private_product_material` | 0 |
| A134 | telegraph | [День 3 — Читаем этикетки](https://telegra.ph/CHitaem-ehtiketki-12-16) | `private_product_material` | 0 |
| A200 | telegraph | [День последний... Советы!](https://telegra.ph/Sovety-12-28) | `private_product_material` | 2 |
| A141 | telegraph | [День №2 — То, что не важно.](https://telegra.ph/Den-2-12-15) | `private_product_material` | 0 |
| A213 | telegraph | [Детоксы, витамины, минералы, анализы](https://telegra.ph/Vitamins-01-20) | `private_product_material` | 0 |
| A142 | telegraph | [Диеты — знакомимся и прощаемся](https://telegra.ph/Diety-11-27) | `editorial_review` | 0 |
| A224 | telegraph | [Договор-оферта на оказание услуг](https://telegra.ph/dogovor-oferta-09-10) | `technical_or_service` | 1 |
| A091 | pikabu | [Долбанная бедность. Часть 21](https://pikabu.ru/story/dolbannaya_bednost_chast_2_13202834) | `editorial_review` | 0 |
| A078 | pikabu | [Долбанная бедность1](https://pikabu.ru/story/dolbannaya_bednost_11989790) | `short_reserve` | 0 |
| A169 | telegraph | [Дополнительные материалы к видео о метаболизме](https://telegra.ph/Nedelya-1--Dopolnitelnye-materialy-k-video-07-18) | `private_product_material` | 1 |
| A129 | telegraph | [Дополнительные материалы по тренировкам](https://telegra.ph/Bonus-urok-4-02-07) | `private_product_material` | 1 |
| A116 | telegraph | [Если ты большой, это не значит что ты говоришь правду](https://telegra.ph/11111-07-31-5) | `editorial_review` | 0 |
| A104 | pikabu | [Ждать идеального момента чтобы что-то начать — это нормально](https://pikabu.ru/story/zhdat_idealnogo_momenta_chtobyi_chtoto_nachat__yeto_normalno_14165768) | `short_reserve` | 0 |
| A031 | pikabu | [Жиросжигающая зона не работает!](https://pikabu.ru/story/zhiroszhigayushchaya_zona_ne_rabotaet_10797468) | `short_reserve` | 2 |
| A281 | vc.ru | [Жиросжигающая зона не работает!⁠⁠ И вот почему ](https://vc.ru/flood/912323-zhiroszhigayushaya-zona-ne-rabotaet-i-vot-pochemu) | `editorial_review` | 2 |
| A057 | pikabu | [Защищайте детей правильно! Начните с себя!](https://pikabu.ru/story/zashchishchayte_detey_pravilno_nachnite_s_sebya_11469990) | `editorial_review` | 0 |
| A219 | telegraph | [Звонок 03.02.2026](https://telegra.ph/Zvonok-03022026-02-03) | `technical_or_service` | 0 |
| A068 | pikabu | [Идеальный завтрак за 96 рублей и три минуты времени](https://pikabu.ru/story/idealnyiy_zavtrak_za_96_rubley_i_tri_minutyi_vremeni_11693580) | `deferred_not_now` | 1 |
| A229 | telegraph | [Идеальный завтрак за 96 рублей и три минуты времени](https://telegra.ph/grechka-s-morozhenim-08-10) | `deferred_not_now` | 1 |
| A150 | telegraph | [Идеи для рекламных постов Пикабу](https://telegra.ph/Idei-dlya-reklamnyh-postov-Pikabu-11-18) | `technical_or_service` | 0 |
| A003 | pikabu | [Из каждого утюга доносятся рецепты ПП Куличей. Но зачем?](https://pikabu.ru/story/iz_kazhdogo_utyuga_donosyatsya_retseptyi_pp_kulichey_no_zachem_10142066) | `short_reserve` | 0 |
| A151 | telegraph | [Итоги](https://telegra.ph/Itogi-12-29-3) | `private_product_material` | 0 |
| A145 | telegraph | [Как быстро вы едите?](https://telegra.ph/FAQ-09-10-9) | `incomplete_draft` | 0 |
| A223 | telegraph | [Как вести дневник питания](https://telegra.ph/dnevnik-eda-06-15) | `editorial_review` | 0 |
| A033 | pikabu | [Как выбрать подходящие тренировки/упражнения для обычного человека?](https://pikabu.ru/story/kak_vyibrat_podkhodyashchie_trenirovkiuprazhneniya_dlya_obyichnogo_cheloveka_10840474) | `deferred_not_now` | 0 |
| A032 | pikabu | [Как замотивировать себя на тренировки?](https://pikabu.ru/story/kak_zamotivirovat_sebya_na_trenirovki_10797523) | `deferred_not_now` | 0 |
| A155 | telegraph | [Как можно на самом деле повлиять на долголетие, а не вот эти все БАДы](https://telegra.ph/Kak-mozhno-na-samom-dele-povliyat-na-dolgoletie-a-ne-vot-ehti-vse-BADy-08-18) | `short_reserve` | 0 |
| A012 | pikabu | [Как на меня напали собаки в лесу](https://pikabu.ru/story/kak_na_menya_napali_sobaki_v_lesu_10369434) | `editorial_review` | 1 |
| A156 | telegraph | [Как на меня напали собаки в лесу](https://telegra.ph/Kak-na-menya-napali-sobaki-v-lesu-06-17) | `editorial_review` | 1 |
| A115 | telegraph | [Как назначить себе дефицит калорий](https://telegra.ph/111-12-07-34) | `editorial_review` | 0 |
| A027 | pikabu | [Как начать тренироваться и... продолжить!!](https://pikabu.ru/story/kak_nachat_trenirovatsya_i_prodolzhit_10756513) | `short_reserve` | 0 |
| A100 | pikabu | [Как перестать жаловаться и начать считать калории?](https://pikabu.ru/story/kak_perestat_zhalovatsya_i_nachat_schitat_kalorii_13894066) | `editorial_review` | 0 |
| A240 | telegraph | [Как подготовить хорошие фотографии для вашего отеля на обычный смартфон](https://telegra.ph/photo-05-25-31) | `technical_or_service` | 0 |
| A157 | telegraph | [Как пользоваться калькулятором и как подобрать себе дефицит калорий](https://telegra.ph/Kak-polzovatsya-kalkulyatorom-i-kak-podobrat-sebe-deficit-kalorij-07-11) | `editorial_review` | 0 |
| A024 | pikabu | [Как правильно взвешиваться?](https://pikabu.ru/story/kak_pravilno_vzveshivatsya_10676580) | `short_reserve` | 0 |
| A131 | telegraph | [Как сделать цельнозерновой рис съедобным](https://telegra.ph/CHernovik-08-18-3) | `private_product_material` | 0 |
| A158 | telegraph | [Как стать толстым ЗОЖ-ником и не заметить этого. Мой личный опыт.](https://telegra.ph/Kak-stat-tolstym-ZOZH-nikom-i-ne-zametit-ehtogo-Moj-opyt-06-09) | `deferred_not_now` | 1 |
| A011 | pikabu | [Как стать толстым ЗОЖ-ником и не заметить этого. Мой опыт](https://pikabu.ru/story/kak_stat_tolstyim_zozhnikom_i_ne_zametit_yetogo_moy_opyit_10312971) | `deferred_not_now` | 1 |
| A064 | pikabu | [Как я 100 000 шагов решил пройти2](https://pikabu.ru/story/kak_ya_100_000_shagov_reshil_proyti_11553382) | `editorial_review` | 1 |
| A159 | telegraph | [Как, куда и когда жаловаться на туроператора или турагента...](https://telegra.ph/Kanikulyarnye-daty-protiv-puteshestvennikov-10-07) | `editorial_review` | 0 |
| A218 | telegraph | [Качественный образ жизни](https://telegra.ph/ZOZH-12-24) | `private_product_material` | 0 |
| A246 | telegraph | [Качество, количество и разнообразие](https://telegra.ph/raznoobrazie-04-08-2) | `editorial_review` | 1 |
| A247 | telegraph | [Качество, количество и разнообразие](https://telegra.ph/raznoobrazie-12-19) | `private_product_material` | 1 |
| A042 | pikabu | [Каши, каши, каши, каши и Похудение. Ъуъ!](https://pikabu.ru/story/kashi_kashi_kashi_kashi_i_pokhudenie_u_11163377) | `deferred_not_now` | 0 |
| A153 | telegraph | [КБЖУУ + клетчатка](https://telegra.ph/KBZHUU-12-16) | `private_product_material` | 0 |
| A160 | telegraph | [Кейс Марии. Как сбросить 52 кг за 4 года! Но есть нюанс.](https://telegra.ph/Kejs-Kak-hudet-dolgo-no-na-dolgo-10-03) | `technical_or_service` | 0 |
| A161 | telegraph | [Кое-что об эффективном жиросжигании](https://telegra.ph/Koe-chto-o-zhiroszhiganii-11-04) | `short_reserve` | 2 |
| A162 | telegraph | [Конструктор целей. План. Система.](https://telegra.ph/Konstruktor-celej-Plan-Sistema-01-02) | `editorial_review` | 0 |
| A248 | telegraph | [Контролируем сладкое](https://telegra.ph/sladkoe-12-23) | `private_product_material` | 1 |
| A085 | pikabu | [Короче, я застраховал маму от онкологии](https://pikabu.ru/story/koroche_ya_zastrakhoval_mamu_ot_onkologii_12269678) | `short_reserve` | 0 |
| A121 | telegraph | [Курс "Только Калории" — Бонус к активности](https://telegra.ph/222-08-29-5) | `private_product_material` | 1 |
| A120 | telegraph | [Курс "Только Калории" — Урок #3 Часть 2.](https://telegra.ph/221-11-21-2) | `private_product_material` | 0 |
| A122 | telegraph | [Курс "Только Калории" — Урок #3/Часть 1](https://telegra.ph/22222-07-31) | `private_product_material` | 0 |
| A163 | telegraph | [Кухонные дела](https://telegra.ph/Kuhnya-12-26) | `obsolete_product_archive` | 0 |
| A167 | telegraph | [Летом есть две проблемы!](https://telegra.ph/Nabrosok-07-18) | `incomplete_draft` | 0 |
| A025 | pikabu | [Лимонная, блин, вода... поговорим о святом!](https://pikabu.ru/story/limonnaya_blin_voda_pogovorim_o_svyatom_10715248) | `short_reserve` | 1 |
| A262 | telegraph | [Лимонная, блин, вода... поговорим о святом!⁠⁠](https://telegra.ph/voda-10-08-2) | `short_reserve` | 1 |
| A221 | telegraph | [Лучшее время для похудения — ВЧЕРА!](https://telegra.ph/chasiki-tikaut-04-07) | `editorial_review` | 1 |
| A058 | pikabu | [Лучшие продукты для завтрака](https://pikabu.ru/story/luchshie_produktyi_dlya_zavtraka_11476051) | `short_reserve` | 0 |
| A235 | telegraph | [макароны](https://telegra.ph/makarony-08-06) | `short_reserve` | 0 |
| A056 | pikabu | [Мама, с днем рождения!!!](https://pikabu.ru/story/mama_s_dnem_rozhdeniya_11448583) | `short_reserve` | 0 |
| A023 | pikabu | [Мой личный ТОП 3 недооцененных и переоцененных продуктов для похудения!](https://pikabu.ru/story/moy_lichnyiy_top_3_nedootsenennyikh_i_pereotsenennyikh_produktov_dlya_pokhudeniya_10668718) | `short_reserve` | 0 |
| A128 | telegraph | [Моя опорная точка прямо сейчас](https://telegra.ph/Base-Point-again-03-10) | `private_product_material` | 0 |
| A020 | pikabu | [Мы все едим фрукты (не) правильно!](https://pikabu.ru/story/myi_vse_edim_fruktyi_ne_pravilno_10554025) | `editorial_review` | 2 |
| A166 | telegraph | [Мы все едим фрукты (не) правильно!⁠⁠](https://telegra.ph/My-vse-edim-frukty-ne-pravilno-12-28) | `editorial_review` | 2 |
| A278 | vc.ru | [Мы все едим фрукты (не) правильно!⁠⁠ ](https://vc.ru/flood/793473-my-vse-edim-frukty-ne-pravilno) | `editorial_review` | 2 |
| A069 | pikabu | [Необоснованный голод и кулинарная импотенция](https://pikabu.ru/story/neobosnovannyiy_golod_i_kulinarnaya_impotentsiya_11741121) | `short_reserve` | 0 |
| A079 | pikabu | [Нет времени заняться здоровьем1](https://pikabu.ru/story/net_vremeni_zanyatsya_zdorovem_12053073) | `short_reserve` | 0 |
| A080 | pikabu | [Никому не рассказывайте4](https://pikabu.ru/story/nikomu_ne_rasskazyivayte_12083509) | `deferred_not_now` | 0 |
| A039 | pikabu | [Новогодние обещания и день, когда вы сдадитесь!](https://pikabu.ru/story/novogodnie_obeshchaniya_i_den_kogda_vyi_sdadites_11020485) | `short_reserve` | 0 |
| A171 | telegraph | [Ограничения, которые реально нужны](https://telegra.ph/Ogranicheniya-01-21-2) | `editorial_review` | 0 |
| A005 | pikabu | [Один небольшой прыжок на велосипеде = большие перемены в жизни1](https://pikabu.ru/story/odin_nebolshoy_pryizhok_na_velosipede__bolshie_peremenyi_v_zhizni_10197439) | `editorial_review` | 1 |
| A173 | telegraph | [Оземпик, Семавик, наболело](https://telegra.ph/Ozempik-Semavik-nabolelo-10-24) | `editorial_review` | 1 |
| A266 | telegraph | [Окна голода и блоки в питании](https://telegra.ph/windows-08-17) | `editorial_review` | 0 |
| A267 | telegraph | [Окна голода и блоки в питании](https://telegra.ph/zadanie-02-14) | `private_product_material` | 0 |
| A205 | telegraph | [Опорные точки в питании](https://telegra.ph/Tochka-12-22) | `private_product_material` | 0 |
| A172 | telegraph | [Определение калорийности рациона](https://telegra.ph/Opredelenie-kalorijnosti-raciona-07-26) | `incomplete_draft` | 0 |
| A270 | vc.ru | [Осталось 42 дня ](https://vc.ru/flood/1137022-ostalos-42-dnya) | `short_reserve` | 1 |
| A035 | pikabu | [Ответ Tim979 в «4 ПРАВИЛА, КОТОРЫЕ ПОМОГУТ УБРАТЬ ЖИВОТ»2](https://pikabu.ru/story/otvet_tim979_v_4_pravila_kotoryie_pomogut_ubrat_zhivot_10878221) | `short_reserve` | 0 |
| A060 | pikabu | [Ответ на пост «"Алкоголь – наркотик и яд!"(с) Точно? Давайте разбираться.)»3](https://pikabu.ru/story/otvet_na_post_alkogol__narkotik_i_yads_tochno_davayte_razbiratsya_11516118) | `short_reserve` | 0 |
| A008 | pikabu | [Ответ на пост «Как работает дефицит калорий?»1](https://pikabu.ru/story/otvet_na_post_kak_rabotaet_defitsit_kaloriy_10254127) | `editorial_review` | 1 |
| A017 | pikabu | [Ответ на пост «Легкое похудение без каких либо трудностей и силы воли: опыт»3](https://pikabu.ru/story/otvet_na_post_legkoe_pokhudenie_bez_kakikh_libo_trudnostey_i_silyi_voli_opyit_10510640) | `short_reserve` | 0 |
| A055 | pikabu | [Ответ на пост «Никто меня не предупредил о последствиях похудения на 40 кг»2](https://pikabu.ru/story/otvet_na_post_nikto_menya_ne_predupredil_o_posledstviyakh_pokhudeniya_na_40_kg_11439327) | `deferred_not_now` | 0 |
| A073 | pikabu | [Ответ на пост «Поменять жизнь за 140 дней»1](https://pikabu.ru/story/otvet_na_post_pomenyat_zhizn_za_140_dney_11851805) | `short_reserve` | 1 |
| A007 | pikabu | [Ответ на пост «Правильное питания на работе»1](https://pikabu.ru/story/otvet_na_post_pravilnoe_pitaniya_na_rabote_10217755) | `deferred_not_now` | 0 |
| A082 | pikabu | [Ответ на пост «Совет от потливости»2](https://pikabu.ru/story/otvet_na_post_sovet_ot_potlivosti_12189205) | `editorial_review` | 0 |
| A006 | pikabu | [Ответ на пост «Что делать если выпирает живот»6](https://pikabu.ru/story/otvet_na_post_chto_delat_esli_vyipiraet_zhivot_10214825) | `short_reserve` | 0 |
| A268 | telegraph | [Ответы на вопросы и дополнения](https://telegra.ph/zapas-02-10) | `private_product_material` | 0 |
| A192 | telegraph | [Ответы на вопросы. Часть 1.](https://telegra.ph/Questions-01-04-4) | `private_product_material` | 0 |
| A170 | telegraph | [Оферта об оказании платных услуг](https://telegra.ph/Oferta-10-13) | `technical_or_service` | 1 |
| A178 | telegraph | [Оффер интенсива](https://telegra.ph/Pitanie-01-01-2) | `technical_or_service` | 0 |
| A193 | telegraph | [Первые шаги!](https://telegra.ph/Razberites-s-ehtim-DO-pohudeniya-05-06) | `editorial_review` | 0 |
| A176 | telegraph | [Перекусы видео](https://telegra.ph/Perekusy-video-07-30) | `incomplete_draft` | 0 |
| A022 | pikabu | [Перекусы худеть мешают или помогают?](https://pikabu.ru/story/perekusyi_khudet_meshayut_ili_pomogayut_10614153) | `deferred_not_now` | 2 |
| A175 | telegraph | [Перекусы худеть мешают или помогают?](https://telegra.ph/Perekusy-hudet-meshayut-ili-pomogayut-08-16) | `deferred_not_now` | 2 |
| A276 | vc.ru | [Перекусы худеть мешают или помогают? ](https://vc.ru/flood/744943-perekusy-hudet-meshayut-ili-pomogayut) | `deferred_not_now` | 2 |
| A177 | telegraph | [Пикадильо по-мексикански](https://telegra.ph/Picadillo-03-31) | `short_reserve` | 0 |
| A047 | pikabu | [Пикадильо по-мексикански (и немного по-холостяцки)](https://pikabu.ru/story/pikadilo_pomeksikanski_i_nemnogo_pokholostyatski_11276080) | `short_reserve` | 0 |
| A013 | pikabu | [План на велосипеде с 0 до 100-200. А может быть и больше!](https://pikabu.ru/story/plan_na_velosipede_s_0_do_100200_a_mozhet_byit_i_bolshe_10379941) | `deferred_not_now` | 0 |
| A185 | telegraph | [Повелитель цифр](https://telegra.ph/Povelitel-cifr-01-30) | `editorial_review` | 0 |
| A146 | telegraph | [Политика конфиденциальности и согласие на обработку персональных данных](https://telegra.ph/Fitness-Talks-bot-privacy-09-10) | `technical_or_service` | 1 |
| A254 | telegraph | [Политика конфиденциальности и согласие на обработку персональных данных](https://telegra.ph/svorontsov-privacy-policy-06-19) | `technical_or_service` | 1 |
| A019 | pikabu | [Последний жир в области живота. План действий](https://pikabu.ru/story/posledniy_zhir_v_oblasti_zhivota_plan_deystviy_10532723) | `editorial_review` | 2 |
| A183 | telegraph | [Последний жир на животе. План действий⁠⁠](https://telegra.ph/Poslednij-zhir-na-zhivote-Plan-dejstvij-03-07) | `editorial_review` | 2 |
| A184 | telegraph | [Пост 2026](https://telegra.ph/Post-02-22-12) | `editorial_review` | 0 |
| A152 | telegraph | [Пост про блиц запасной текст](https://telegra.ph/Jghj-05-20) | `incomplete_draft` | 1 |
| A106 | telegraph | [Пост чужой с пикабу](https://telegra.ph/-02-04-28320) | `technical_or_service` | 0 |
| A132 | telegraph | [Похудение начинается не с голода!](https://telegra.ph/CHernovik-10-14-3) | `editorial_review` | 1 |
| A092 | pikabu | [Похудение начинается не с голода!2](https://pikabu.ru/story/pokhudenie_nachinaetsya_ne_s_goloda_13251257) | `editorial_review` | 1 |
| A252 | telegraph | [Похудение начинается не с похудения!](https://telegra.ph/stop-golod-04-05) | `editorial_review` | 0 |
| A256 | telegraph | [Похудение начинается не с похудения!](https://telegra.ph/teksty-10-31) | `incomplete_draft` | 2 |
| A272 | vc.ru | [Похудение начинается не с похудения!⁠⁠ ](https://vc.ru/flood/1169131-pohudenie-nachinaetsya-ne-s-pohudeniya) | `editorial_review` | 2 |
| A040 | pikabu | [Похудеть не получается... какая самая частая причина?](https://pikabu.ru/story/pokhudet_ne_poluchaetsya_kakaya_samaya_chastaya_prichina_11118483) | `owner_review_later` | 1 |
| A230 | telegraph | [Похудеть не получается... какая самая частая причина?⁠⁠](https://telegra.ph/hochu-hudet-03-21) | `owner_review_later` | 1 |
| A181 | telegraph | [Почему дефицит калорий не работает?](https://telegra.ph/Pochemu-deficit-kalorij-ne-rabotaet-06-16) | `editorial_review` | 1 |
| A071 | pikabu | [Почему питание всегда важнее тренировок!!](https://pikabu.ru/story/pochemu_pitanie_vsegda_vazhnee_trenirovok_11801517) | `short_reserve` | 0 |
| A182 | telegraph | [Почему японцы худые, а ты нет?](https://telegra.ph/Pochemu-yaponcy-hudye-a-ty-net-11-07) | `editorial_review` | 1 |
| A174 | telegraph | [ПП рецепты — это плохо И вот почему!](https://telegra.ph/PP-recepty--hren-i-vot-pochemu-01-03) | `editorial_review` | 2 |
| A053 | pikabu | [ПП-кулич — вам не нужен!](https://pikabu.ru/story/ppkulich__vam_ne_nuzhen_11385251) | `short_reserve` | 1 |
| A196 | telegraph | [Правила безопасности за шведским столом](https://telegra.ph/SHS-06-18-2) | `editorial_review` | 1 |
| A255 | telegraph | [Правило Гарвардской "Здоровой Тарелки"](https://telegra.ph/tarelka-12-17-3) | `obsolete_product_archive` | 0 |
| A136 | telegraph | [Правильные действия](https://telegra.ph/Calories-only-09-09) | `editorial_review` | 0 |
| A189 | telegraph | [Привычки для увеличения удовольствия](https://telegra.ph/Privychki-dlya-uvelicheniya-udovolstviya-03-02) | `private_product_material` | 0 |
| A234 | telegraph | [Прикладные способы усилить насыщение ничего не меняя в тарелке (ну почти)](https://telegra.ph/kakakaka-08-10) | `private_product_material` | 0 |
| A138 | telegraph | [Пример заполнения дневника качества питания](https://telegra.ph/DQS-example-08-29) | `editorial_review` | 0 |
| A187 | telegraph | [Пример медиакита Кристина ест](https://telegra.ph/Primer-mediakita-08-30) | `technical_or_service` | 0 |
| A232 | telegraph | [Пришлось даже оглавление сделать](https://telegra.ph/in-far-far-galaxy-02-12) | `editorial_review` | 0 |
| A244 | telegraph | [Программа Мастер-класса](https://telegra.ph/programma-04-04-3) | `technical_or_service` | 0 |
| A190 | telegraph | [Промт: обработка данных из дневника питания](https://telegra.ph/Promt-obrabotka-dannyh-iz-dnevnika-pitaniya-02-03) | `technical_or_service` | 0 |
| A124 | telegraph | [Пять вкусов еды](https://telegra.ph/5-vkusov-12-25) | `obsolete_product_archive` | 0 |
| A065 | pikabu | [Разбор бреда: «5 вещей, которые я не буду делать как нутрициолог»](https://pikabu.ru/story/razbor_breda_5_veshchey_kotoryie_ya_ne_budu_delat_kak_nutritsiolog_11583796) | `short_reserve` | 0 |
| A010 | pikabu | [Разбудить любого и спросить: "Можно ли кушать на ночь?"](https://pikabu.ru/story/razbudit_lyubogo_i_sprosit_mozhno_li_kushat_na_noch_10293844) | `short_reserve` | 0 |
| A021 | pikabu | [Резинки для тренировок!](https://pikabu.ru/story/rezinki_dlya_trenirovok_10573917) | `editorial_review` | 1 |
| A195 | telegraph | [Резинки для тренировок!⁠⁠](https://telegra.ph/Rezinki-09-01) | `editorial_review` | 1 |
| A118 | telegraph | [Сахар. Начало 🍫](https://telegra.ph/1ertyu-07-04) | `private_product_material` | 0 |
| A015 | pikabu | [Сахарозаменитель в "диетических напитках" вызывает рак (нет!)](https://pikabu.ru/story/sakharozamenitel_v_dieticheskikh_napitkakh_vyizyivaet_rak_net_10424398) | `editorial_review` | 1 |
| A198 | telegraph | [Сделай приятно своей спине](https://telegra.ph/Sdelaj-priyatno-svoej-spine-07-27) | `short_reserve` | 0 |
| A191 | telegraph | [Сделай сегодня — скажи себе спасибо завтра](https://telegra.ph/Prostejshie-12-izmenenij-v-vashej-zhizni-08-11) | `editorial_review` | 0 |
| A199 | telegraph | [Синдром отложенной жизни. СОЖ против ЗОЖ!](https://telegra.ph/Sindrom-otlozhennoj-zhizni-SOZH-protiv-ZOZH-06-27) | `deferred_not_now` | 0 |
| A137 | telegraph | [Система оценки качества диеты—DQS](https://telegra.ph/DQS-04-08) | `editorial_review` | 0 |
| A139 | telegraph | [Система оценки качества питания](https://telegra.ph/DQS-new-01-21) | `editorial_review` | 1 |
| A140 | telegraph | [Система оценки качества питания. Размер порций и разбор категорий.](https://telegra.ph/DQS-size-08-27) | `editorial_review` | 1 |
| A034 | pikabu | [Сколько пользы РЕАЛЬНО остается в молоке, которое мы пьем?!?](https://pikabu.ru/story/skolko_polzyi_realno_ostaetsya_v_moloke_kotoroe_myi_pem_10877887) | `editorial_review` | 1 |
| A236 | telegraph | [Сколько РЕАЛЬНО пользы в молоке, которое мы пьем?!?](https://telegra.ph/molokkko-03-21) | `editorial_review` | 1 |
| A029 | pikabu | [Список плохих идей для похудения1](https://pikabu.ru/story/spisok_plokhikh_idey_dlya_pokhudeniya_10778290) | `short_reserve` | 0 |
| A202 | telegraph | [Способы восстановление поле тренировки Часть 2.](https://telegra.ph/Sposoby-vosstanovlenie-pole-trenirovki-CHast-2-08-11) | `editorial_review` | 0 |
| A249 | telegraph | [Способы сокращения ВРЕДА от сладкого.](https://telegra.ph/sladkoe-ne-pomeha-04-12) | `private_product_material` | 0 |
| A231 | telegraph | [Способы сокращения КОЛИЧЕСТВА сладкого](https://telegra.ph/hvatit-sladkogo-04-11) | `editorial_review` | 1 |
| A203 | telegraph | [Средиземноморская диета](https://telegra.ph/Sredizemnomorskaya-dieta-12-07) | `obsolete_product_archive` | 0 |
| A102 | pikabu | [Средиземноморская диета — это вообще что?!?!](https://pikabu.ru/story/sredizemnomorskaya_dieta__yeto_voobshche_chto_14062380) | `short_reserve` | 0 |
| A251 | telegraph | [Срывы и зажоры. В чем разница, что с ними делать и причем тут чит-милы.](https://telegra.ph/sriv-sriv-sriv-04-11) | `private_product_material` | 0 |
| A112 | telegraph | [Сценарий видео калории Урок 4. Учет тренировочной активности](https://telegra.ph/111-07-27-11) | `technical_or_service` | 0 |
| A168 | telegraph | [Сценарий только калории Видео #1. Введение.](https://telegra.ph/Nachalo-07-20-4) | `technical_or_service` | 0 |
| A109 | telegraph | [Сценарий Только калории Видео №2. Как считать.](https://telegra.ph/111-07-17-14) | `technical_or_service` | 0 |
| A264 | telegraph | [Сценарий только калории Что дальше](https://telegra.ph/whatnext-07-20) | `technical_or_service` | 0 |
| A001 | pikabu | [Так можно пить во время еды или нет?](https://pikabu.ru/story/tak_mozhno_pit_vo_vremya_edyi_ili_net_10098880) | `editorial_review` | 2 |
| A204 | telegraph | [Так можно пить во время еды или нет?](https://telegra.ph/Tak-mozhno-pit-vo-vremya-edy-ili-net-06-16) | `editorial_review` | 2 |
| A114 | telegraph | [Тексты шортсы](https://telegra.ph/111-11-20-48) | `technical_or_service` | 0 |
| A269 | vc.ru | [Температура воды (для приема внутрь)⁠⁠ ](https://vc.ru/flood/1112254-temperatura-vody-dlya-priema-vnutr) | `short_reserve` | 1 |
| A083 | pikabu | [Техника безопасности (питания) за новогодним столом!1](https://pikabu.ru/story/tekhnika_bezopasnosti_pitaniya_za_novogodnim_stolom_12193581) | `editorial_review` | 0 |
| A220 | telegraph | [Только калории](https://telegra.ph/calories-only-09-11) | `technical_or_service` | 0 |
| A206 | telegraph | [Только калории - Считаем съеденное](https://telegra.ph/Tolko-kalorii---Schitaem-sedennoe-07-18) | `editorial_review` | 1 |
| A258 | telegraph | [Только калории - Упрощаем подсчеты](https://telegra.ph/uproshaem-07-19) | `editorial_review` | 1 |
| A226 | telegraph | [Тренировочная активность. Дополнительные материалы](https://telegra.ph/dop4-02-07) | `private_product_material` | 1 |
| A088 | pikabu | [Убираем тягу к сладкому1](https://pikabu.ru/story/ubiraem_tyagu_k_sladkomu_12869107) | `short_reserve` | 0 |
| A225 | telegraph | [Урок #2 — Дополнительные материалы](https://telegra.ph/dop2-02-07) | `private_product_material` | 1 |
| A215 | telegraph | [Урок #2 — Дополнительные материалы.](https://telegra.ph/Vol2-add-08-28) | `private_product_material` | 0 |
| A259 | telegraph | [Урок #3 часть два — Считаем/упрощаем](https://telegra.ph/urok3-chast2-02-07) | `private_product_material` | 1 |
| A260 | telegraph | [Урок #3 часть один — считаем съеденное](https://telegra.ph/urok31-02-07) | `private_product_material` | 1 |
| A208 | telegraph | [Урок #4 — Дополнительные материалы](https://telegra.ph/VO2Max-07-20) | `private_product_material` | 1 |
| A179 | telegraph | [Урок #5 — Дополнительные материалы](https://telegra.ph/Plan-02-07-5) | `private_product_material` | 1 |
| A265 | telegraph | [Урок #5 — Дополнительные материалы](https://telegra.ph/whatnext-08-30) | `private_product_material` | 1 |
| A207 | telegraph | [Услуги. Сопровождение. Консультации.](https://telegra.ph/Uslugi-Soprovozhdenie-Konsultacii-05-20) | `technical_or_service` | 0 |
| A261 | telegraph | [ууууууу](https://telegra.ph/uuuuuuu-10-28-2) | `technical_or_service` | 2 |
| A241 | telegraph | [Часть #2. Пищевое поведение.](https://telegra.ph/pishevoe-povedenie-02-07) | `private_product_material` | 0 |
| A201 | telegraph | [Челлендж-Инструкция 30 дней бега. Неделя 1.](https://telegra.ph/Spisok-plohih-idej-dlya-pohudeniya-10-28) | `editorial_review` | 2 |
| A014 | pikabu | [Чем отличаются "плохие", "хорошие" и "быстрые" завтраки](https://pikabu.ru/story/chem_otlichayutsya_plokhie_khoroshie_i_byistryie_zavtraki_10405059) | `editorial_review` | 1 |
| A279 | vc.ru | [Чем отличаются «‎плохие»‎, «‎хорошие»‎ и «‎быстрые»‎ завтраки ](https://vc.ru/flood/801045-chem-otlichayutsya-plohie-horoshie-i-bystrye-zavtraki) | `editorial_review` | 1 |
| A133 | telegraph | [Чистка печени](https://telegra.ph/CHistka-pecheni-11-10) | `editorial_review` | 0 |
| A135 | telegraph | [Чит-милы](https://telegra.ph/CHitmil-07-11) | `editorial_review` | 1 |
| A222 | telegraph | [Читмилы и другие формы "расслабления" на диете](https://telegra.ph/chitmil-09-18) | `private_product_material` | 1 |
| A188 | telegraph | [Что вы НЕ понимаете о формировании привычек](https://telegra.ph/Privychki-21-den-Trenirovki-10-21) | `editorial_review` | 0 |
| A097 | pikabu | [Что надо делать, чтобы похудеть на 12кг2](https://pikabu.ru/story/chto_nado_delat_chtobyi_pokhudet_na_12kg_13741138) | `short_reserve` | 0 |
| A242 | telegraph | [Что не так с ПП рецептами и почему?](https://telegra.ph/pp-eda-03-21) | `editorial_review` | 2 |
| A067 | pikabu | [Чёрный пояс по прохождению верхнего Ларса2](https://pikabu.ru/story/chyornyiy_poyas_po_prokhozhdeniyu_verkhnego_larsa_11684797) | `editorial_review` | 0 |
| A113 | telegraph | [Энергетический баланс](https://telegra.ph/111-09-28-22) | `editorial_review` | 0 |
| A144 | telegraph | [Эфир «Вредная еда»](https://telegra.ph/EHfir-Vrednaya-eda-09-21) | `editorial_review` | 0 |
| tilda-post:e4441ism91 | tilda | [⛔️ Почему эффекта плато не существует](https://xn-----jlceacr3bggd8ajed5a6kl.xn--p1ai/intensiv_old/tpost/e4441ism91-pochemu-effekta-plato-ne-suschestvuet) | `editorial_review` | 0 |
| tilda-post:knian4e971 | tilda | [✍️ Ваш новый план похудения](https://xn-----jlceacr3bggd8ajed5a6kl.xn--p1ai/intensiv_old/tpost/knian4e971-vash-novii-plan-pohudeniya) | `editorial_review` | 0 |
| tilda-post:a75rtx6go1 | tilda | [🍔 Что надо поменять в питании, чтобы лучше насыщаться?](https://xn-----jlceacr3bggd8ajed5a6kl.xn--p1ai/intensiv_old/tpost/a75rtx6go1-chto-nado-pomenyat-v-pitanii-chtobi-luc) | `editorial_review` | 0 |
| tilda-post:sgpfzdvvy1 | tilda | [🍭 Вы едите 31кг сахара в год!](https://xn-----jlceacr3bggd8ajed5a6kl.xn--p1ai/intensiv_old/tpost/sgpfzdvvy1-vi-edite-31kg-sahara-v-god) | `editorial_review` | 0 |
| A117 | telegraph | [💎 13 правил  для организации домашних тренировок⁠⁠](https://telegra.ph/13-pravil-09-18) | `editorial_review` | 1 |
| tilda-post:amkbo7kgg1 | tilda | [💪 Зачем нужны тренировки (кроме похудения)](https://xn-----jlceacr3bggd8ajed5a6kl.xn--p1ai/intensiv_old/tpost/amkbo7kgg1-zachem-nuzhni-trenirovki-krome-pohudeni) | `editorial_review` | 0 |
| tilda-post:pxukhjlca1 | tilda | [📸 Как вести дневник питания БЕЗ калорий](https://xn-----jlceacr3bggd8ajed5a6kl.xn--p1ai/intensiv_old/tpost/pxukhjlca1-kak-vesti-dnevnik-pitaniya-bez-kalorii) | `editorial_review` | 0 |
| tilda-post:7siam7t8k1 | tilda | [😎 Как сократить тягу к сладкому и как есть сладкое с меньшим вредом для здоровья!](https://xn-----jlceacr3bggd8ajed5a6kl.xn--p1ai/intensiv_old/tpost/7siam7t8k1-kak-sokratit-tyagu-k-sladkomu-i-kak-est) | `editorial_review` | 0 |
| A111 | telegraph | [😡 Привычка за 21 день — это ложь!](https://telegra.ph/111-07-23-19) | `incomplete_draft` | 0 |
| tilda-post:x5ykn0tjc1 | tilda | [🤦‍♂️ Три главные ошибки в начале похудения](https://xn-----jlceacr3bggd8ajed5a6kl.xn--p1ai/intensiv_old/tpost/x5ykn0tjc1-tri-glavnie-oshibki-v-nachale-pohudeniy) | `editorial_review` | 0 |
| tilda-post:jajp12c7j1 | tilda | [🥄 Просто кладите ложку на стол!](https://xn-----jlceacr3bggd8ajed5a6kl.xn--p1ai/intensiv_old/tpost/jajp12c7j1-prosto-kladite-lozhku-na-stol) | `editorial_review` | 0 |
| tilda-post:5kegfp3o71 | tilda | [🥐 Примеры реальных дневников](https://xn-----jlceacr3bggd8ajed5a6kl.xn--p1ai/intensiv_old/tpost/5kegfp3o71-primeri-realnih-dnevnikov) | `owner_review_later` | 0 |
| A130 | telegraph | [🥕 Правило 30-ти растений](https://telegra.ph/CHast-2-08-08) | `incomplete_draft` | 1 |
| tilda-post:hbfozma3y1 | tilda | [🥕 Правило 30-ти растений](https://xn-----jlceacr3bggd8ajed5a6kl.xn--p1ai/intensiv_old/tpost/hbfozma3y1-pravilo-30-ti-rastenii) | `editorial_review` | 0 |
| A123 | telegraph | [🥕Правило 40-ка растений](https://telegra.ph/30rastei-01-26) | `editorial_review` | 1 |
| tilda-post:m0epglvrp1 | tilda | [🧮 Зачем на самом деле надо считать калории](https://xn-----jlceacr3bggd8ajed5a6kl.xn--p1ai/intensiv_old/tpost/m0epglvrp1-zachem-na-samom-dele-nado-schitat-kalor) | `editorial_review` | 0 |

## Непокрытые источники и синхронизация

- В текущем локальном корпусе нет источников Дзен. Нужен отдельный discovery по аккаунту/экспорту, если такие публикации существуют.
- Производная карта зарегистрирована в серверном Библиотекаре: `knowledge://resource/article-family-routing`. Она хранит маршруты, ссылки и очередь сравнения; неподтверждённые пары не повышены до доказанных дублей.
- Telegraph: известные 211 страниц были перечитаны 17.09.2026, но свежий список аккаунта без токена не подтверждён.
- Pikabu: использованы серверная библиотека и локальные полные корпуса; публикации после даты снимка требуют следующего refresh.

