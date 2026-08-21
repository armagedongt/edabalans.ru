# Силовые тренировки: структура данных и логика

> Статус: требования для миграции; сверять с кодом и схемой
> Источник: https://docs.google.com/document/d/1xqybBOMvFvW3cmXmGvWeuyW7sIkUYASi4YDjsTG0E-8/edit
> Импортировано: 22.08.2026. Содержимое является снимком legacy-системы; актуальные решения определяются корневыми `PROJECT_CONTEXT.md` и `ARCHITECTURE.md`.

Силовые тренировки — структура данных и логика


1. Назначение
Приложение ведёт силовой дневник клиента внутри Tilda Members Area. Клиент и тренер работают с одной базой. Клиент заполняет факт: вес, повторения, RPE и примечания. План хранится отдельно от факта. Тренер управляет упражнениями, порядком, скрытием и копированием плана/факта в следующую тренировку.


2. Авторизация
Tilda авторизует пользователя в Members Area.
Frontend получает email пользователя.
Apps Script ищет email в листе Users.
Если пользователь активен — возвращает user_id и данные.
Пароль Tilda в приложение не передаётся.


3. Структура Google Sheets


Users
user_id
email
display_name
status
created_at
source


Workout_Types
user_id
workout_type
title
active
sort_order


Exercise_Catalog
user_id
workout_type
exercise_id
exercise_name
active
sort_order
source


Sessions
session_id
user_id
workout_type
session_number
date
status
legacy_group
source
created_at
updated_at


Session_Exercises
session_id
user_id
workout_type
session_number
exercise_id
exercise_name
sort_order
note
source


Sets
session_id
user_id
workout_type
session_number
exercise_id
exercise_name
set_number
plan_weight
plan_reps
fact_weight
fact_reps
rpe
plan_weight_raw
plan_reps_raw
fact_weight_raw
fact_reps_raw
rpe_raw
source


Legacy_Valentina_Raw
Полная копия исходной старой таблицы Валентины без потери исходных текстов и нестандартных значений.


Meta
Версия схемы, параметры импорта и зафиксированные расчётные правила.


4. Стабильные идентификаторы
У каждого упражнения есть постоянный exercise_id.
Порядок упражнения определяется sort_order.
Скрытие не удаляет упражнение и его историю: меняется active.
История никогда не связывается с позицией упражнения в массиве.


5. Правило заполненной тренировки
Тренировка считается заполненной, если хотя бы в одном подходе указан RPE.


6. Примечания
Примечание относится к конкретному упражнению в конкретной тренировке и хранится в Session_Exercises.note.
Клиент может изменять примечание.
В тренерском режиме примечание читается без редактирования.


7. Копирование следующей тренировки
Копирование разрешено только из последней тренировки.
«Скопировать план → следующая» создаёт новую тренировку и переносит plan_weight / plan_reps.
«Скопировать факт → следующая» создаёт новую тренировку и переносит fact_weight / fact_reps прошлого дня в план новой тренировки.
Существующая историческая тренировка никогда не перезаписывается.


8. Статистика — календарь
Календарь показывает по 7 дней в строке.
Тренировка 1, 2 и 3 имеют разные цвета.
Нажатие на день открывает базовое окно тренировки за эту дату.


9. Статистика — анализ упражнения
Анализ строится только для одного выбранного упражнения.
Основная метрика: расчётный максимум ×8 (расчётный 8RM).


Стандарт расчёта:
1) первый подход упражнения исключается как разминочный;
2) рассматриваются только последующие подходы, где заполнены фактический вес, повторения и RPE;
3) сначала выбирается подход с самым большим фактическим весом;
4) если подходов с этим весом несколько — используется тот, у которого выше расчётный 8RM.


Формула:
RIR = 10 − RPE
effective_reps = reps + RIR
estimated_1RM = weight × (1 + effective_reps / 30)
estimated_8RM = estimated_1RM / (1 + 8 / 30)


Итог:
estimated_8RM = weight × [1 + (reps + 10 − RPE) / 30] ÷ [1 + 8 / 30]


Интерпретация:
Это прогноз веса, который человек предположительно мог бы выполнить на 8 повторений в свежем рабочем подходе после разминки. Это аналитическая метрика, а не измеренный максимум.


Научная основа:
RPE/RIR используется как способ оценки повторов в запасе.
Прогнозные формулы по весу и числу повторений используются для оценки силового потенциала, но имеют индивидуальную погрешность.


Ссылки:
https://pubmed.ncbi.nlm.nih.gov/26049792/
https://pubmed.ncbi.nlm.nih.gov/27531969/
https://pubmed.ncbi.nlm.nih.gov/7500624/


10. Импорт Валентины
Исходная таблица перенесена полностью в Legacy_Valentina_Raw.
Дополнительно данные преобразованы в нормализованные листы Exercise_Catalog, Sessions, Session_Exercises и Sets.
В исходном файле нет дат тренировок, поэтому даты исторических сессий не были придуманы и оставлены пустыми.
Последовательность колонок сохранена как legacy_group / session_number.
Исходные текстовые значения сохранены в *_raw, даже если значение нельзя безопасно преобразовать в число.


11. Текущая база
Google Sheets:
https://docs.google.com/spreadsheets/d/1lcuFzG8T4aHhctCE5PXPjc3IjVnXhzUptrX_silrVIE/edit


12. API Apps Script
GET:
?action=ping
?action=openUser&email=...
?action=getWorkout&email=...&type=1
?action=getStats&email=...&type=1&exercise_id=squat
?action=adminListUsers&admin_email=...


POST JSON:
action=saveSession
action=saveExerciseSettings
action=addExercise


Ответы всегда JSON:
{ok:true,...}
или
{ok:false,error:"..."}
