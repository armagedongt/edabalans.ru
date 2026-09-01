# Калорийный курс

`course.json` — seed и локальный fallback структуры Калорийного курса. После
первой публикации активная структура хранится в `managed_document_versions` с
ключом `calories`.

Тексты обычных материалов публикуются отдельно по стабильному `step.id`; замена
статьи не требует изменения структуры курса. Пока статья не опубликована,
интерфейс показывает редакционную заглушку из `summary`.

## Защита от преждевременного открытия

Курс появляется доступным участнику только при выполнении двух условий:

1. опубликованы все видимые статьи;
2. в редакторе структуры включён `launchReady`.

По умолчанию переключатель выключен. Поэтому загрузка черновиков и проверка
структуры не открывают недоделанный курс людям с уже существующим
`ACCESS_CALORIES`.

## Файлы, ID и публикация

Ниже зафиксирована привязка текущего пятиэтапного runtime к ближайшей совместимой
редакторской сборке v5. Эти тексты прошли внутренние проверки, но Сергей их не
принимал; публиковать их до отдельного авторского просмотра нельзя. Полная
текстовая v6, отвергнутый структурный checkpoint v7 и последняя сокращённая
программа v8 имеют другую четырёхэтапную архитектуру и описаны в
`work/calorie-course-rebuild/README.md`; автоматически подставлять их в эти ID нельзя.

| Этап | `step.id` | Файл черновика |
|---|---|---|
| 1 | `calories-stage-01-app` | `work/calorie-course-rebuild/rebuild-v5-editorial-2026-08-30/stage-01/01-app-tracking.md` |
| 1 | `calories-stage-01-food-cases` | `work/calorie-course-rebuild/rebuild-v5-editorial-2026-08-30/stage-01/02-counting-different-food.md` |
| 1 | `calories-stage-01-accuracy` | `work/calorie-course-rebuild/rebuild-v5-editorial-2026-08-30/stage-01/03-accuracy-baseline-diary.md` |
| 2 | `calories-stage-02-metrics` | `work/calorie-course-rebuild/rebuild-v5-editorial-2026-08-30/stage-02/01-app-metrics.md` |
| 2 | `calories-stage-02-sources` | `work/calorie-course-rebuild/rebuild-v5-editorial-2026-08-30/stage-02/02-calorie-sources.md` |
| 2 | `calories-stage-02-adjust` | `work/calorie-course-rebuild/rebuild-v5-editorial-2026-08-30/stage-02/03-adjust-current-diet.md` |
| 3 | `calories-stage-03-expenditure` | `work/calorie-course-rebuild/rebuild-v5-editorial-2026-08-30/stage-03/01-expenditure-calculator.md` |
| 3 | `calories-stage-03-activity` | `work/calorie-course-rebuild/rebuild-v5-editorial-2026-08-30/stage-03/02-steps-training-double-count.md` |
| 4 | `calories-stage-04-deficit` | `work/calorie-course-rebuild/rebuild-v5-editorial-2026-08-30/stage-04/01-phase-deficit-pace.md` |
| 4 | `calories-stage-04-data` | `work/calorie-course-rebuild/rebuild-v5-editorial-2026-08-30/stage-04/02-comparable-data.md` |
| 4 | `calories-stage-04-correction` | `work/calorie-course-rebuild/rebuild-v5-editorial-2026-08-30/stage-04/03-correct-the-model.md` |
| 5 | `calories-stage-05-catalog` | `work/calorie-course-rebuild/rebuild-v5-editorial-2026-08-30/stage-05/01-repeat-meals-household-measures.md` |
| 5 | `calories-stage-05-hunger` | `work/calorie-course-rebuild/rebuild-v5-editorial-2026-08-30/stage-05/02-rhythm-hunger-snacking.md` |
| 5 | `calories-stage-05-exit` | `work/calorie-course-rebuild/rebuild-v5-editorial-2026-08-30/stage-05/03-stop-tracking.md` |

Помимо четырнадцати статей, в этапе 3 есть обязательный технический шаг
`calories-stage-03-calculator`. Он открывает существующее приложение `metabolism`
внутри оболочки курса и не требует отдельного Markdown-файла. Право
`ACCESS_CALORIES` разрешает использовать этот инструмент; отдельная формула и
вторая копия пользовательских данных для курса не создаются.

Публикация одного проверенного файла:

```powershell
python tools/publish_course_material.py --course calories publish <step.id> <путь-к-файлу>
```

Скрипт сам получает текущую редакцию статьи и не перезаписывает параллельное
изменение молча.

Курс состоит из этапов, а не календарных дней. Следующий этап открывается после
прохождения обязательных материалов и подтверждения задания текущего этапа.
