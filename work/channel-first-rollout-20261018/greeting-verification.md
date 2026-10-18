# Приветствие19.10.2026

Полный выпуск0aa0f18 проверен CI39175149441 и production19.10.2026.
Меню прочитано обратно через Telegram API: guide/mk/channel/contact/stop.
Общий навигационный оригинал версии3 исправляет только личную Telegram-ссылку;
канальная ссылка сохранена, копии текста для команд не создавались.

Исходный кружок read-only проверен на production: tpl_entry_circle,
video_note, published/approved, welcome-intro-circle.mp4 существует и есть file_id.
Обычное видео сохраняется отдельно; новый текстовый слот не перезаписывает его.

Проверки:55 temporary/content passed; расширенныйнабор121 далединственное
устаревшее ожидание sendVideo в guide-test, заменено sendVideoNote+sendMessage.
Финальные32temporarytests passed (включая пересечениевходов иcampaign_live).
Code/test/docs reviews две волны, финалclean; замечанияcircleconcurrency и
отсутствующийтестlivecampaign устранены. Массовой отправки не было; новый вход
не создаёт SequenceRun,14-дневнаярассылка отложена.
