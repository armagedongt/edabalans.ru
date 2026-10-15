"""Private, versioned selected travel Markdown. Research library is never mounted here."""
from __future__ import annotations

import hashlib
import html
import json
import math
import os
import re
import threading
import uuid
from contextlib import contextmanager
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

import markdown

ROOT = Path(os.environ.get("TRAVEL_CALCULATOR_ROOT", "/srv/sergey-travel/calculator"))
ID = re.compile(r"^[a-z][a-z0-9-]{0,59}$")
LOCK = threading.Lock()
MAX_BYTES = 1_500_000
SETTINGS = {"foodWeek", "householdWeek", "transportWeek", "leisureWeek", "restaurantFrequency", "restaurantPrice", "common", "shopping"}


class TravelError(ValueError):
    pass


class Conflict(TravelError):
    pass


def identifier(value):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise TravelError("Недопустимый идентификатор")
    return value


def number(value, label="Цена"):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 100_000_000:
        raise TravelError(f"{label}: нужно неотрицательное число")
    return value


def text(value, limit=1000):
    if not isinstance(value, str) or len(value) > limit:
        raise TravelError("Некорректный текст")
    return value


def document(meta, body):
    return "---\n" + json.dumps(meta, ensure_ascii=False, indent=2, allow_nan=False) + "\n---\n" + body.strip() + "\n"


def parse(source):
    if not isinstance(source, str) or len(source.encode()) > 200_000:
        raise TravelError("Markdown слишком большой")
    match = re.match(r"\A---\r?\n(.*?)\r?\n---\r?\n(.*)\Z", source, re.S)
    if not match:
        raise TravelError("Ожидается Markdown с JSON-метаданными между ---")
    try:
        meta = json.loads(match[1])
    except (ValueError, RecursionError) as exc:
        raise TravelError("Некорректные метаданные Markdown") from exc
    if not isinstance(meta, dict):
        raise TravelError("Метаданные должны быть объектом")
    return meta, match[2]


def validate(model):
    if not isinstance(model, dict) or len(json.dumps(model, ensure_ascii=False, allow_nan=False).encode()) > MAX_BYTES:
        raise TravelError("Некорректный или слишком большой план")
    text(model.get("title"), 200)
    settings = model.get("settings", {})
    if not isinstance(settings, dict) or set(settings) != SETTINGS:
        raise TravelError("Неполный набор недельных настроек")
    for key, value in settings.items():
        number(value, key)
    if settings["restaurantFrequency"] > 14:
        raise TravelError("Частота ресторанов слишком велика")
    phases = model.get("phases")
    if not isinstance(phases, list) or not 1 <= len(phases) <= 30:
        raise TravelError("Нужно от 1 до 30 фаз")
    seen = set()
    previous_end = None
    for phase in phases:
        if not isinstance(phase, dict):
            raise TravelError("Некорректная фаза")
        pid = identifier(phase.get("id"))
        if pid in seen:
            raise TravelError("Повтор фазы")
        seen.add(pid)
        text(phase.get("title"), 200)
        text(phase.get("country"), 120)
        try:
            if any(not isinstance(phase.get(k), str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", phase[k]) for k in ("start", "end")):
                raise ValueError("Use YYYY-MM-DD")
            start, end = date.fromisoformat(phase["start"]), date.fromisoformat(phase["end"])
        except (KeyError, ValueError, TypeError) as exc:
            raise TravelError("Неверные даты") from exc
        if end <= start or (previous_end and previous_end != start):
            raise TravelError("Фазы должны идти без разрывов; выезд позже заезда")
        previous_end = end
        if not isinstance(phase.get("base"), bool):
            raise TravelError("Укажите, является ли фаза базовой остановкой")
        number(phase.get("nightRate"), "Цена ночи")
        if number(phase.get("includedHousingNights", 0), "Включённые ночи") > (end - start).days:
            raise TravelError("Включённых ночей больше длительности фазы")
        flight = phase.get("flight", {})
        if not isinstance(flight, dict):
            raise TravelError("Некорректное описание перелёта")
        number(flight.get("amount"), "Билет")
        text(flight.get("from", ""), 200)
        items = phase.get("items", [])
        if not isinstance(items, list) or len(items) > 80:
            raise TravelError("Слишком много пунктов")
        item_ids = set()
        for item in items:
            if not isinstance(item, dict):
                raise TravelError("Некорректный пункт")
            iid = identifier(item.get("id"))
            if iid in item_ids:
                raise TravelError("Повтор пункта")
            item_ids.add(iid)
            text(item.get("title"), 200)
            if item.get("bucket") not in {"fixed", "leisure", "sport", "restaurant", "included"}:
                raise TravelError("Неизвестная группа расходов")
            for flag in ("selected", "unknown"):
                if not isinstance(item.get(flag, False), bool):
                    raise TravelError("Некорректный переключатель")
            number(item.get("amount", 0))
            visits = number(item.get("includedRestaurantVisits", 0), "Включённые ужины")
            if visits > 10 or visits != int(visits) or (visits and item.get("bucket") != "included"):
                raise TravelError("Включённые ужины указываются только в составе пакета")
            number(item.get("excludedDays", 0), "Дни выезда")
            if item.get("excludedDays", 0) > (end - start).days + 1:
                raise TravelError("Дни выезда длиннее фазы")
            parts = item.get("parts", [])
            if not isinstance(parts, list) or len(parts) > 30:
                raise TravelError("Некорректная разбивка")
            for part in parts:
                if not isinstance(part, dict):
                    raise TravelError("Некорректная часть стоимости")
                text(part.get("label"), 200)
                number(part.get("amount"))
            source = item.get("source", "")
            text(source, 2000)
            if source and (urlsplit(source).scheme not in {"https", "http"} or urlsplit(source).username):
                raise TravelError("Некорректная ссылка источника")
            image = item.get("image")
            if image:
                if not isinstance(image, dict):
                    raise TravelError("Некорректная фотография")
                for name in ("url", "source"):
                    url = text(image.get(name), 2000)
                    if urlsplit(url).scheme != "https" or urlsplit(url).username:
                        raise TravelError("Фотография и её источник должны использовать HTTPS")
                text(image.get("alt", ""), 500)
                text(image.get("credit", ""), 200)
    if (date.fromisoformat(phases[-1]["end"]) - date.fromisoformat(phases[0]["start"])).days > 730:
        raise TravelError("Для этой версии срок не больше двух лет")
    if not isinstance(model.get("returnFlight"), dict):
        raise TravelError("Нужен обратный билет")
    number(model.get("returnFlight", {}).get("amount"), "Обратный билет")
    text(model.get("returnFlight", {}).get("from", ""), 200)
    return model


def file_check(files):
    if not isinstance(files, dict) or len(files) > 40 or "plan.md" not in files:
        raise TravelError("Нужен plan.md и Markdown фаз")
    for name, content in files.items():
        if name != "plan.md" and not re.fullmatch(r"phases/[a-z][a-z0-9-]{0,59}\.md", name):
            raise TravelError("Разрешены только plan.md и phases/<id>.md")
        if not isinstance(content, str):
            raise TravelError("Markdown должен быть текстом")
    if sum(len(v.encode()) for v in files.values()) > MAX_BYTES:
        raise TravelError("Пакет Markdown слишком большой")


def compile_files(files):
    file_check(files)
    plan, _ = parse(files["plan.md"])
    ids = plan.get("phaseIds")
    if not isinstance(ids, list) or not 1 <= len(ids) <= 30:
        raise TravelError("Некорректный перечень фаз")
    phases = []
    for pid in ids:
        identifier(pid)
        key = f"phases/{pid}.md"
        if key not in files:
            raise TravelError(f"Нет Markdown фазы {pid}")
        phase, _ = parse(files[key])
        if phase.get("id") != pid:
            raise TravelError("Идентификатор фазы не совпадает с файлом")
        phases.append(phase)
    model = {key: plan[key] for key in ("title", "settings", "returnFlight") if key in plan}
    model["phases"] = phases
    return validate(model)


def snapshot():
    current = ROOT / "current"
    if not current.exists():
        raise TravelError("Выбранный план ещё не опубликован")
    release_id = current.read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"[a-f0-9]{32}", release_id):
        raise TravelError("Некорректная версия плана")
    target = (ROOT / "releases" / release_id).resolve()
    releases = (ROOT / "releases").resolve()
    if not target.is_relative_to(releases):
        raise TravelError("Некорректный каталог выбранного плана")
    names = ["plan.md"] + sorted(f"phases/{p.name}" for p in (target / "phases").glob("*.md"))
    files = {}
    for name in names:
        path = target / name
        if path.is_symlink() or not path.resolve().is_relative_to(target):
            raise TravelError("Недопустимая ссылка в плане")
        files[name] = path.read_text(encoding="utf-8")
    digest = hashlib.sha256(json.dumps(files, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return files, digest


@contextmanager
def writing():
    ROOT.mkdir(parents=True, exist_ok=True)
    with LOCK, (ROOT / ".write.lock").open("a") as handle:
        if os.name != "nt":
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name != "nt":
                fcntl.flock(handle, fcntl.LOCK_UN)


def publish(files, expected):
    compile_files(files)
    with writing():
        actual = snapshot()[1] if (ROOT / "current").exists() else ""
        if actual != expected:
            raise Conflict("План изменился. Обновите страницу или сохраните отдельную копию JSON")
        release = ROOT / "releases" / uuid.uuid4().hex
        (release / "phases").mkdir(parents=True)
        for name, content in files.items():
            path = release / name
            path.write_text(content, encoding="utf-8")
        # Every revision remains immutable and can be republished for recovery.
        link = ROOT / (".current-" + uuid.uuid4().hex)
        link.write_text(release.name, encoding="utf-8")
        os.replace(link, ROOT / "current")
        return snapshot()[1]


def save_model(model, expected):
    validate(model)
    files, _ = snapshot()
    old_plan, body = parse(files["plan.md"])
    plan = {key: model[key] for key in ("title", "settings", "returnFlight")}
    plan["phaseIds"] = [p["id"] for p in model["phases"]]
    updated = {"plan.md": document(plan, body)}
    for phase in model["phases"]:
        key = f"phases/{phase['id']}.md"
        phase_body = parse(files[key])[1] if key in files else "# " + phase["title"] + "\n\n## overview | План\nПрограмма этой фазы ещё не заполнена."
        clean = {k: v for k, v in phase.items() if k not in {"article", "sections"}}
        updated[key] = document(clean, phase_body)
    return publish(updated, expected)


class SafeHTML(HTMLParser):
    tags = {"p", "ul", "ol", "li", "strong", "em", "h3", "h4", "blockquote", "a", "code", "pre", "table", "thead", "tbody", "tr", "td", "th", "hr", "br"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.output = []

    def handle_starttag(self, tag, attrs):
        if tag not in self.tags:
            return
        attribute = ""
        if tag == "a":
            href = dict(attrs).get("href", "")
            if urlsplit(href).scheme in {"http", "https"} and not urlsplit(href).username:
                attribute = ' href="' + html.escape(href, quote=True) + '" target="_blank" rel="noopener noreferrer"'
        self.output.append("<" + tag + attribute + ">")

    def handle_endtag(self, tag):
        if tag in self.tags:
            self.output.append("</" + tag + ">")

    def handle_data(self, data):
        self.output.append(html.escape(data))


def safe_markdown(body):
    parser = SafeHTML()
    parser.feed(markdown.markdown(html.escape(body), extensions=["tables"]))
    return "".join(parser.output)


def article(pid):
    identifier(pid)
    files, revision = snapshot()
    model = compile_files(files)
    phase = next((p for p in model["phases"] if p["id"] == pid), None)
    if not phase:
        raise TravelError("Фаза не найдена")
    _, body = parse(files[f"phases/{pid}.md"])
    sections = []
    for match in re.finditer(r"^## ([a-z][a-z0-9-]*)\s*\|[^\S\r\n]*([^\n]+)\n(.*?)(?=^## |\Z)", body, re.S | re.M):
        sections.append({"id": match[1], "title": match[2].strip(), "html": safe_markdown(match[3])})
    return {"phase": phase, "sections": sections, "revision": revision}
