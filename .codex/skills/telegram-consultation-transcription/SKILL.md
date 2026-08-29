---
name: telegram-consultation-transcription
description: Расшифровывает Telegram Desktop ZIP/папку или указанную папку с локальными видео и аудио, выдаёт timeline.md. Используется для технической расшифровки или хронологии. Не использовать для анализа консультации, рекомендаций или клиентской карточки.
---

# Расшифровка Telegram и локальных медиа

Это техническая расшифровка, не разбор консультации. Не делать выводов о человеке, не менять исходный ZIP/папку с медиа и не добавлять исходные данные в Git.

1. Выбрать вход: Telegram — ZIP или папка с `result.json`; локальные медиа — точный существующий путь к папке. Результаты класть вне репозитория в `C:\Users\Segey\Documents\ChatGPT\private-consultations\imports`. Если среда просит разрешение на запись в эту приватную папку, запросить его перед запуском.
2. Проверить, что `OPENAI_API_KEY` задан. Если ключа нет, попросить владельца настроить его, не записывать и не просить прислать ключ в чат.
3. Запустить из `backend`:

   ```powershell
   python -m app.importers.telegram_consultations <путь-к-архиву> --output "C:\Users\Segey\Documents\ChatGPT\private-consultations\imports"
   ```

   Для папки с MP4/MOV/MKV и обычными аудиофайлами:

   ```powershell
   python -m app.importers.local_media <путь-к-папке> --output "C:\Users\Segey\Documents\ChatGPT\private-consultations\imports"
   ```

4. Для видео FFmpeg временно извлекает и режет аудио локально; оригинал не меняется. Вернуть пользователю числа файлов/сообщений, длительность, успешных расшифровок, список ошибок и полный путь к `timeline.md`. Передать для дальнейшего анализа только `timeline.md` и `messages.json` либо `media.json`; raw export и аудио не анализировать и не удалять.

Модель меняется только через `OPENAI_TRANSCRIPTION_MODEL`; по умолчанию используется `gpt-4o-mini-transcribe`.