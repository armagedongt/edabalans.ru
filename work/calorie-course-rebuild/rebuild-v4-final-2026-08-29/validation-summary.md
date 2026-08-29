# Валидация финальной сборки

Дата: 2026-08-29.  
Инструмент: `tools/author_workflow.py` + `tools/validate_author_draft.py`.  
Результат: `pass` для 14 из 14 материалов.

Для каждого файла зафиксирован content contract: `develop_existing`, `full_source`, `authored_blocks_first`, учебная площадка `course_material`, строгий фактчек и полная карта преемственности курса. Ручные проверки закрыты содержательными пояснениями по роли материала, архитектуре, фактам и запрещённым утверждениям.

## Зафиксированные файлы

- `stage-01/01-app-tracking.md` — `5f6f1bf09bdf` — `pass`
- `stage-01/02-counting-different-food.md` — `8337ba63f88a` — `pass`
- `stage-01/03-accuracy-baseline-diary.md` — `567aa6b25ba7` — `pass`
- `stage-02/01-app-metrics.md` — `3287615bd3e7` — `pass`
- `stage-02/02-calorie-sources.md` — `fee5bd22bfb1` — `pass`
- `stage-02/03-adjust-current-diet.md` — `e5576ea0ec96` — `pass`
- `stage-03/01-expenditure-calculator.md` — `4a79d7817ee4` — `pass`
- `stage-03/02-steps-training-double-count.md` — `a1e731aa136a` — `pass`
- `stage-04/01-phase-deficit-pace.md` — `2739e1fd1152` — `pass`
- `stage-04/02-comparable-data.md` — `f1bfd35af14a` — `pass`
- `stage-04/03-correct-the-model.md` — `6cf0868b2812` — `pass`
- `stage-05/01-repeat-meals-household-measures.md` — `1848a3d5ce33` — `pass`
- `stage-05/02-rhythm-hunger-snacking.md` — `dc7113f54c69` — `pass`
- `stage-05/03-stop-tracking.md` — `9cf0d26be49b` — `pass`

Полные pack, review и validation JSON находятся во временном приватном каталоге, путь к которому печатает `validate_rebuild_v4.py`. Скрипт воспроизводит проверку из текущих файлов.
