from __future__ import annotations

import html
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent
LESSONS = [
    ("01-course-plan--7058269", 7058269),
    ("02-bju-again--7058309", 7058309),
    ("03-track-workouts--7058285", 7058285),
    ("04-stage-one-tasks--7058281", 7058281),
    ("05-menu-and-recipes--7058441", 7058441),
    ("06-food-diary-app--7058293", 7058293),
    ("07-record-accurately--7058617", 7058617),
    ("08-simplify-calorie-tracking--7058621", 7058621),
    ("09-stage-two-tasks--7058465", 7058465),
    ("10-energy-balance--7058493", 7058493),
    ("11-set-calorie-deficit--7058497", 7058497),
    ("12-weight-loss-rate--7058513", 7058513),
    ("13-workout-supplement--7058541", 7058541),
    ("14-activity-bonus--7058553", 7058553),
    ("15-stage-three-tasks--7058561", 7058561),
    ("16-food-blocks-and-catalog--7058577", 7058577),
    ("17-hunger-snacking-grazing--7058585", 7058585),
    ("18-language-of-actions--7058589", 7058589),
]
VIDEOS = [
    ("01-intro--7058105", 7058105, "tg5Opyc4"),
    ("02-training-activity--7058537", 7058537, "DIQRLzFy"),
    ("03-periodization--7058605", 7058605, "IQgljaNX"),
]


def verify_lesson(folder: str, lecture_id: int) -> dict:
    lesson_dir = ROOT / "lessons" / folder
    source_path = lesson_dir / "source.md"
    raw_path = lesson_dir / "raw-blocks.json"
    assets_path = lesson_dir / "assets-manifest.json"
    errors: list[str] = []
    for path in (source_path, raw_path, assets_path):
        if not path.is_file():
            errors.append(f"Нет файла {path.name}")
    if errors:
        return {"folder": folder, "lectureId": lecture_id, "errors": errors}

    source = source_path.read_text(encoding="utf-8")
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    manifest = json.loads(assets_path.read_text(encoding="utf-8"))
    blocks = raw.get("blocks") or []
    image_blocks = [block for block in blocks if block.get("type") == "image"]
    unique_image_urls = list(dict.fromkeys((block.get("image") or {}).get("url") for block in image_blocks))
    unique_image_urls = [value for value in unique_image_urls if value]
    assets = manifest.get("assets") or []

    if raw.get("source", {}).get("lectureId") != lecture_id:
        errors.append("Tilda ID не совпадает с манифестом")
    if not blocks:
        errors.append("Нет исходных блоков")
    if len(assets) != len(unique_image_urls):
        errors.append(f"Картинки: {len(unique_image_urls)} URL, но {len(assets)} записей манифеста")
    if manifest.get("failures"):
        errors.append(f"Ошибки скачивания: {len(manifest['failures'])}")
    if "IMAGE DOWNLOAD FAILED" in source:
        errors.append("В Markdown остался маркер ошибки изображения")

    for asset in assets:
        local_path = lesson_dir / asset["localPath"]
        if not asset.get("downloaded"):
            errors.append(f"Не скачан {asset['sourceUrl']}")
        if not local_path.is_file() or local_path.stat().st_size == 0:
            errors.append(f"Нет локального файла {asset['localPath']}")
        if asset["localPath"] not in source:
            errors.append(f"Файл не привязан в Markdown: {asset['localPath']}")

    hrefs: list[str] = []
    for block in blocks:
        hrefs.extend(html.unescape(value) for value in re.findall(r'href=["\']([^"\']+)', block.get("sourceHtml") or block.get("contentHtml") or ""))
    for href in hrefs:
        if href and href not in source:
            errors.append(f"Ссылка потеряна в Markdown: {href}")

    return {
        "folder": folder,
        "lectureId": lecture_id,
        "title": raw.get("title"),
        "blocks": len(blocks),
        "imageBlocks": len(image_blocks),
        "uniqueImages": len(unique_image_urls),
        "localImages": len([asset for asset in assets if (lesson_dir / asset["localPath"]).is_file()]),
        "links": len(hrefs),
        "errors": errors,
    }


def verify_video(folder: str, lecture_id: int, video_id: str) -> dict:
    video_dir = ROOT / "videos" / folder
    source_path = video_dir / "source.md"
    raw_path = video_dir / "raw-video.json"
    errors: list[str] = []
    if not source_path.is_file():
        errors.append("Нет source.md")
    if not raw_path.is_file():
        errors.append("Нет raw-video.json")
    raw = json.loads(raw_path.read_text(encoding="utf-8")) if raw_path.is_file() else {}
    if raw.get("source", {}).get("lectureId") != lecture_id:
        errors.append("Tilda ID не совпадает")
    if raw.get("videoId") != video_id:
        errors.append("Boomstream ID не совпадает")
    return {"folder": folder, "lectureId": lecture_id, "title": raw.get("title"), "videoId": raw.get("videoId"), "errors": errors}


def main() -> None:
    lessons = [verify_lesson(folder, lecture_id) for folder, lecture_id in LESSONS]
    videos = [verify_video(folder, lecture_id, video_id) for folder, lecture_id, video_id in VIDEOS]
    all_errors = [error for row in lessons + videos for error in row["errors"]]
    result = {
        "schemaVersion": "1.0",
        "checkedAt": "2026-08-28",
        "courseId": 425521,
        "status": "passed" if not all_errors else "failed",
        "summary": {
            "textLessons": len(lessons),
            "videoLessons": len(videos),
            "blocks": sum(row.get("blocks", 0) for row in lessons),
            "imageBlocks": sum(row.get("imageBlocks", 0) for row in lessons),
            "uniqueImages": sum(row.get("uniqueImages", 0) for row in lessons),
            "localImages": sum(row.get("localImages", 0) for row in lessons),
            "links": sum(row.get("links", 0) for row in lessons),
            "errors": len(all_errors),
        },
        "lessons": lessons,
        "videos": videos,
    }
    (ROOT / "verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Проверка полной копии Tilda",
        "",
        f"Статус: `{'пройдена' if result['status'] == 'passed' else 'ошибка'}`  ",
        "Дата: 2026-08-28",
        "",
        "| Проверка | Результат |",
        "| --- | ---: |",
        f"| Текстовые лекции | {result['summary']['textLessons']} / 18 |",
        f"| Видеолекции | {result['summary']['videoLessons']} / 3 |",
        f"| Исходные блоки Tilda | {result['summary']['blocks']} |",
        f"| Блоки изображений | {result['summary']['imageBlocks']} |",
        f"| Уникальные изображения | {result['summary']['uniqueImages']} |",
        f"| Локальные файлы изображений | {result['summary']['localImages']} |",
        f"| Ссылки в исходных HTML-блоках | {result['summary']['links']} |",
        f"| Ошибки | {result['summary']['errors']} |",
        "",
        "## Поурочная сверка",
        "",
        "| № | Лекция | Блоки | Изображения | Ссылки | Статус |",
        "| ---: | --- | ---: | ---: | ---: | --- |",
    ]
    for index, row in enumerate(lessons, start=1):
        lines.append(f"| {index} | {row.get('title') or row['folder']} | {row.get('blocks', 0)} | {row.get('localImages', 0)} | {row.get('links', 0)} | {'OK' if not row['errors'] else '; '.join(row['errors'])} |")
    lines.extend(["", "## Видеокарточки", "", "| Лекция | Tilda ID | Boomstream ID | Статус |", "| --- | ---: | --- | --- |"]) 
    for row in videos:
        lines.append(f"| {row.get('title') or row['folder']} | {row['lectureId']} | `{row.get('videoId') or ''}` | {'OK' if not row['errors'] else '; '.join(row['errors'])} |")
    (ROOT / "verification.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(result["summary"] | {"status": result["status"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
