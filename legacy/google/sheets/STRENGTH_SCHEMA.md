# Силовые тренировки: безопасная схема Google Sheets

Источник: [Google Sheet](https://docs.google.com/spreadsheets/d/1lcuFzG8T4aHhctCE5PXPjc3IjVnXhzUptrX_silrVIE/edit)

Проверено 22.08.2026. Сняты только metadata и первая строка каждой вкладки.
Пользовательские строки не читались и не сохранялись.

| Вкладка | sheetId | Заголовки |
|---|---:|---|
| `Users` | 535849831 | `user_id`, `email`, `display_name`, `status`, `created_at`, `source` |
| `Workout_Types` | 782627173 | `user_id`, `workout_type`, `title`, `active`, `sort_order` |
| `Exercise_Catalog` | 304851765 | `user_id`, `workout_type`, `exercise_id`, `exercise_name`, `active`, `sort_order`, `source` |
| `Sessions` | 957111900 | `session_id`, `user_id`, `workout_type`, `session_number`, `date`, `status`, `legacy_group`, `source`, `created_at`, `updated_at` |
| `Session_Exercises` | 671084302 | `session_id`, `user_id`, `workout_type`, `session_number`, `exercise_id`, `exercise_name`, `sort_order`, `note`, `source` |
| `Sets` | 1554170547 | `session_id`, `user_id`, `workout_type`, `session_number`, `exercise_id`, `exercise_name`, `set_number`, `plan_weight`, `plan_reps`, `fact_weight`, `fact_reps`, `rpe`, `plan_weight_raw`, `plan_reps_raw`, `fact_weight_raw`, `fact_reps_raw`, `rpe_raw`, `source` |
| `Legacy_Valentina_Raw` | 1286109588 | первая ячейка: `**Упражнение**`; legacy-сетка 1000 × 134 |
| `Meta` | 1563702065 | `key`, `value`, `note` |

`Legacy_Valentina_Raw` содержит реальные legacy-данные и в Git не переносится.
Для импорта использовать контролируемый migration script после повторной проверки backup
и восстановления. Не придумывать отсутствующие даты; сохранять `*_raw` при небезопасном
числовом преобразовании.
