# DQS_TEST: безопасная схема Google Sheets

Источник: [Google Sheet](https://docs.google.com/spreadsheets/d/13Ms00YmGP_IPW3FgzagMlx6rsuNFHV-aNxDkt1IkwqE/edit)

Проверено 22.08.2026. Сняты только metadata и первая строка каждой вкладки.
Пользовательские строки не читались и не сохранялись.

| Вкладка | sheetId | Размер сетки | Заголовки |
|---|---:|---:|---|
| `DQS_Data` | 483767951 | 1000 × 34 | `email`, `start_date`, `created_at`, `updated_at`, `day_01` … `day_30` |
| `Allowed_Emails` | 987654321 | 1005 × 3 | `email`, `status (active / block / blank)`, `comment` |
| `Category_Help` | 425231084 | 1000 × 26 | `Категория`, `Шпаргалка` |

`Category_Help` — legacy-вкладка. Актуальный Apps Script сообщает, что runtime-подсказки
из неё удалены; норматив категорий хранится в `../dqs/PRODUCT_CATEGORIES.md`.

Перед миграцией данных нужно отдельно проверить типы и реальные варианты JSON в
`day_01` … `day_30` на контролируемой обезличенной выборке, не коммитя значения.
