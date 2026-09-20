from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import textwrap
import urllib.request
from pathlib import Path

from PIL import Image, ImageOps


ROOT = Path(__file__).resolve().parent
PRIVATE = Path(
    r"C:\Users\Segey\.codex\visualizations\2026\08\30\01a05492-5878-7312-b4ea-15b5fb4daee4\blog-audit-private"
)
PIKABU_SNAPSHOT = PRIVATE / "library-snapshot.json"
TELEGRAPH_SNAPSHOT = PRIVATE / "telegraph-current.json"
VC_SNAPSHOT = PRIVATE / "vc-current.json"


SPECS = [
    dict(source_id="11277666", slug="skrytye-zapory-i-banalnyy-syuzhet", title="Скрытые запоры и банальный сюжет", category="Ну, типа... ЗОЖ", cta="masterclass", visibility="public", excerpt="Почему попытка просто добавить побольше клетчатки иногда делает ситуацию только неприятнее — и что полезно проверить в питании сначала."),
    dict(source_id="11494317", slug="dieta-sryv-i-matematika", title="Диета. Срыв. И математика", category="Похудение", cta="masterclass", visibility="public", excerpt="Почему один незапланированный продукт не отменяет похудение — и как обычная математика помогает не превращать отклонение от плана в недельный срыв."),
    dict(source_id="11522121", slug="eti-dolbannye-10000-shagov", title="Эти долбанные 10 000 шагов", category="Тренировки", cta="intensive", visibility="public", excerpt="Откуда взялись 10 000 шагов, почему это не магическая норма и как подобрать полезный объём ходьбы под себя."),
    dict(source_id="11762932", slug="professionalnyy-edok", title="Профессиональный едок", category="Ну, типа... ЗОЖ", cta="masterclass", visibility="public", excerpt="Как участники соревнований по скоростному поеданию умудряются поглощать десятки тысяч килокалорий — и почему это совсем не инструкция для обычной жизни."),
    dict(source_id="12296286", slug="net-vremeni-obyasnyat-prosto-hudey", title="Нет времени объяснять. Просто худей!", category="Похудение", cta="masterclass", visibility="public", excerpt="Четыре сферы жизни, которые определяют, будет похудение посильным процессом или очередной короткой диетой на силе воли."),
    dict(source_id="13436070", slug="poterya-myshc-pri-pohudenii", title="Потеря мышц при похудении", category="Похудение", cta="masterclass", visibility="public", excerpt="Правда ли, что при дефиците организм первым делом уничтожает мышцы, и что действительно помогает сохранить мышечную массу."),
    dict(source_id="13785403", slug="tri-oshibki-v-nachale-pohudeniya", title="Три ошибки в начале похудения", category="Похудение", cta="intensive", visibility="public", excerpt="Три решения, которые выглядят логично в первый день похудения, но заметно повышают шанс быстро всё бросить."),
    dict(source_id="14021584", slug="sdelat-pohudenie-proshche", title="Сделать похудение проще", category="Похудение", cta="masterclass", visibility="public", excerpt="Похудение не обязано состоять из бесконечного списка запретов. Разбираемся, какие действия действительно дают основную часть результата."),
    dict(source_id="14102926", slug="hodit-chtoby-hudet", title="Ходить, чтобы худеть", category="Тренировки", cta="intensive", visibility="public", excerpt="Почему ходьба помогает похудению, сколько энергии она действительно расходует и где заканчивается польза идеи «просто больше ходить»."),
    dict(source_id="14183275", slug="hochesh-hudet-esh-kartoshku", title="Хочешь худеть? Заткнись и ешь картошку!", category="Качество питания", cta="masterclass", visibility="public", excerpt="Почему обычная картошка может оказаться удобным продуктом для похудения, если не путать её с фритюром и тазиком масла."),
    dict(source_id="CHernovik-08-18-3", slug="kak-sdelat-celnozernovoy-ris-sedobnym", title="Как сделать цельнозерновой рис съедобным", category="Качество питания", cta="masterclass", visibility="public", excerpt="Простой способ приготовить цельнозерновой рис так, чтобы его хотелось есть не из чувства долга, а потому что получилось вкусно."),
    dict(source_id="Dva-sousa-Krasnoe-i-beloe-03-18", slug="dva-sousa-krasnoe-i-beloe", title="Два соуса. Красное и белое", category="Качество питания", cta="masterclass", visibility="public", excerpt="Два быстрых домашних соуса: красный томатный и белый йогуртовый. Без сложной готовки и с понятным составом."),
    dict(source_id="12857458", slug="pravila-bezopasnosti-za-shvedskim-stolom", title="Правила безопасности за шведским столом", category="Качество питания", cta="masterclass", visibility="public", excerpt="Как отдохнуть в отеле со шведским столом, не превращая каждый приём пищи в соревнование и не привозя домой лишние килограммы."),
    dict(source_id="693339", slug="mozhno-li-pit-vo-vremya-edy", title="Можно ли пить во время еды?", category="Ну, типа... ЗОЖ", cta="masterclass", visibility="public", excerpt="Разбавляет ли вода желудочный сок, вредно ли есть всухомятку и когда напитки во время еды действительно могут иметь значение."),
    dict(source_id="Sahar-09-18", slug="saharozamenitel-vyzyvaet-rak-net", title="Сахарозаменитель в диетических напитках вызывает рак? Нет", category="Качество питания", cta="masterclass", visibility="public", excerpt="Что на самом деле означала классификация аспартама как возможного канцерогена и почему слово «возможно» нельзя читать отдельно от дозы."),
    dict(source_id="11553382", slug="kak-ya-100000-shagov-reshil-proyti", title="Как я 100 000 шагов решил пройти", category="Личное", cta="telegram", visibility="internal", excerpt="Личная история попытки пройти 100 000 шагов за сутки — с подготовкой, ошибками, ночёвкой в лесу и честным итогом."),
    dict(source_id="11207593", slug="glikemicheskiy-indeks-eto-lishnee", title="Гликемический индекс — это лишнее!", category="Качество питания", cta="masterclass", visibility="public", excerpt="Почему гликемический индекс отдельного продукта редко помогает принимать решения о реальном приёме пищи и похудении."),
    dict(source_id="10999474", slug="pp-recepty-eto-ploho", title="ПП-рецепты — это плохо. И вот почему", category="Качество питания", cta="masterclass", visibility="public", excerpt="Как ярлык «ПП» заставляет переоценивать полезность блюда и почему рецепт лучше оценивать по задаче, составу и порции."),
    dict(source_id="training-combined-2023", slug="kak-nachat-trenirovki-i-ne-brosit", title="Как начать тренировки и не бросить", category="Тренировки", cta="intensive", visibility="public", excerpt="История короткого бегового челленджа с Pikabu и практическая инструкция: как начать тренироваться, не перегореть и превратить активность в устойчивую привычку.", combined=["10276321", "10779442", "752179"]),
    dict(source_id="12922345", slug="a-mne-trener-posovetoval", title="А мне тренер посоветовал…", category="Тренировки", cta="masterclass", visibility="public", excerpt="Почему уверенный совет тренера по питанию ещё не становится правильным — и по каким признакам отличать опыт от компетентности."),
]


TRAIL_MARKERS = (
    "ещё посты на пикабу",
    "еще посты на пикабу",
    "можно подписаться на меня",
    "веду телеграм",
    "телеграм:",
    "сергей воронцов, тренер по питанию",
    "реклама. ип воронцов",
    "другие посты на пикабу",
    "больше постов тут",
    "телеграмм канал",
    "телеграм канал",
    "сергей воронцов. телеграм",
    "→ телеграм",
    "→ sergey vorontsov",
    "больше о питании",
    "осторожно, некоторые есть на пикабу",
    "вот несколько статей на пикабу",
    "*напомню, что плюс",
    "телеграм →",
    "мой телеграм-канал →",
    "сергей воронцов — пишу о питании",
    "у меня в тг канале есть цикл статей",
    "хочу пройти 100 000 шагов в эту субботу",
)
DROP_PATTERNS = (
    r"пишите в комментар",
    r"оставляйте комментар",
    r"делитесь выводами",
    r"постав(?:ь|ьте) плюс",
    r"подписывайтесь",
    r"мотивация писать питается только плюсами",
    r"в закрепе канала",
    r"всего голосов:",
    r"добро пожаловать в комментарии",
    r"предлагайте свои варианты в комментариях",
    r"фото часов .* в комментарии",
    r"более точное определение в этом комментарии",
    r"по мотивам комментариев .* закреплен",
)


def sha(value: str | bytes) -> str:
    if isinstance(value, str):
        value = value.encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def load_sources() -> dict[str, dict]:
    snapshot = json.loads(PIKABU_SNAPSHOT.read_text(encoding="utf-8"))
    result = {str(item["external_id"]): item for item in snapshot["items"]}
    for item in json.loads(TELEGRAPH_SNAPSHOT.read_text(encoding="utf-8")):
        telegraph_media = []
        for index, media in enumerate(item.get("media_links") or []):
            if isinstance(media, dict) and media.get("tag") != "img":
                continue
            value = (media.get("url") if isinstance(media, dict) else str(media)) or ""
            if value.startswith("/file/"):
                value = "https://telegra.ph" + value
            telegraph_media.append({"type": "image", "source_url": value, "position": index})
        result[str(item["path"])] = {
            "source": "telegraph",
            "external_id": item["path"],
            "canonical_url": item["url"],
            "title": item["title"],
            "text": item["text_plain"],
            "published_at": item.get("published_at"),
            "media": telegraph_media,
        }
    for item in json.loads(VC_SNAPSHOT.read_text(encoding="utf-8")):
        result[str(item["external_id"])] = {
            "source": "vc.ru",
            "external_id": item["external_id"],
            "canonical_url": item["url"],
            "title": item["title"],
            "text": item["text"],
            "published_at": item.get("published_at"),
            "media": item.get("media") or [],
        }
    return result


def strip_platform_tail(text: str) -> tuple[str, list[str]]:
    lines = [line.strip() for line in text.replace("\r", "").split("\n")]
    kept: list[str] = []
    removed: list[str] = []
    tail = False
    for line in lines:
        folded = line.casefold()
        if any(folded.startswith(marker) for marker in TRAIL_MARKERS):
            tail = True
        if tail:
            removed.append(line)
            continue
        if line in {"Пикабу", "●"} or re.fullmatch(r"\d{1,2}:\d{2}", line):
            removed.append(line)
            continue
        if any(re.search(pattern, folded) for pattern in DROP_PATTERNS):
            removed.append(line)
            continue
        kept.append(line)
    while kept and not kept[-1]:
        kept.pop()
    return "\n".join(kept), removed


def heading_line(line: str) -> str:
    line = line.strip()
    if not line:
        return ""
    if re.match(r"^день\s+\d+\b", line, re.I):
        return "## " + line
    if re.match(r"^\d+[.)]\s+\D", line) and len(line) <= 120:
        return "## " + re.sub(r"^(\d+)[.)]\s+", r"\1. ", line)
    if re.match(r"^#\d+[.)]?\s*", line) and len(line) <= 120:
        return "## " + re.sub(r"^#(\d+)[.)]?\s*", r"\1. ", line)
    known = {
        "а что тогда?", "мое предложение", "моё предложение", "почему это важно?",
        "как правильно выполнять растяжку", "что растяжка делает", "теперь о заминке:",
        "какие лично я преследую цели?", "подведем итог:", "подведём итог:",
        "резюме:", "итого:", "что делать?", "что в итоге?", "а теперь подробнее.",
    }
    if line.casefold() in known:
        return "## " + line.rstrip(":")
    section_starts = (
        "ошибка #", "уровень ", "причина №", "правило ", "совет ",
        "как ", "почему ", "что ", "откуда ", "сколько ", "зачем ",
        "в сухом остатке", "вместо выводов", "выводы", "ну и выводы",
        "пустяки", "уже срыв", "а вот это уже", "не только маркетологи",
        "вред от", "индекс насыщения", "маршрут", "обед", "смеркалось",
        "итак", "кстати", "до шведского стола", "на шведском столе",
        "а в чём вообще", "а в чем вообще", "начнём с", "начнем с",
        "а теперь к", "перестаньте смотреть", "для чего нужно",
        "возвращаемся к", "мораль сей басни",
    )
    folded = line.casefold()
    if len(line) <= 95 and not line.startswith(("→", "-", "*", "![")) and folded.startswith(section_starts):
        return "## " + line.rstrip(":")
    return line


def markdown_body(text: str, *, keep_pikabu_context: bool = False) -> tuple[str, list[str]]:
    text, removed = strip_platform_tail(text)
    replacements = {
        "Для ЛЛ —": "Коротко:",
        "Для ЛЛ -": "Коротко:",
        "залайканный комментарий": "популярный комментарий",
        "тут, на Пикабу, и у себя в телеграме — читайте на здоровье": "в других материалах",
        "на Пикабу в лиге о похудении": "читателям блога",
        "Пару зарубежных ссылок Пикабу почему-то банит, но вот": "Вот",
        "написать пост на Пикабу под заголовком": "написать пост под заголовком",
        " и собрать много плюсов (очень много)": "",
        " (пост про кроссовки на Пикабу)": "",
        " (пост на Пикабу)": "",
        "вот пост на Пикабу с фото и видео оттуда в мае": "в мае я уже показывал фото и видео оттуда",
        "Потому что питание всегда важнее тренировок, в тг есть отдельный пост с пояснениями.": "Потому что питание всё равно нельзя рассматривать отдельно от тренировок.",
        "Писал об этом в посте «Сколько времени нужно на похудение?» (пост в телеграме, не забудьте включить три буквы, а то не откроется).": "Подробнее об этом — в материале «Сколько времени нужно на похудение?»." ,
        "Базовый минимум абсолютно для всех — 4000 шагов, а лучше 5000 шагов. И только когда вы сможете сделать это частью вашей жизни, можете начинать думать о более высоких материях типа учета калорий, рецептов и пищевых привычек (обращайтесь).": "Базовый минимум абсолютно для всех — 4000 шагов, а лучше 5000 шагов. И только когда вы сможете сделать это частью вашей жизни, можете начинать думать о более высоких материях типа учета калорий, рецептов и пищевых привычек.",
        "Подробнее и о сбалансированном питании и о пищевых привычках — пишу в других постах и тут и в тг.": "Подробнее о сбалансированном питании и пищевых привычках — в других материалах блога.",
        "Можете подписаться =)": "",
        "Чтобы не спамить здесь публикую раз в неделю. Немного контекста в этом посте.": "Дальше — немного контекста.",
        "В комментариях мне помогли, а то чет забыл самое важное...": "И ещё один важный совет.",
        "Но об этом уже в других постах 🙂": "Эти принципы разобраны в других материалах блога.",
        "Писал об этом отдельный пост все ссылки будут в конце статьи.": "Эту тему отдельно разбираю в другом материале блога.",
    }
    for before, after in replacements.items():
        text = text.replace(before, after)
    lines = [heading_line(line) for line in text.splitlines()]
    if not keep_pikabu_context:
        lines = [
            re.sub(r"\bпикабушник(?:и|ам|ов)?\b", "читатель", line, flags=re.I)
            for line in lines
        ]
    blocks = []
    for line in lines:
        if not line:
            continue
        blocks.append(line)
    return "\n\n".join(blocks).strip() + "\n", removed


def media_urls(item: dict) -> list[str]:
    urls = []
    for media in item.get("media") or []:
        if isinstance(media, str):
            if media.startswith(("http://", "https://")):
                urls.append(media)
            continue
        if str(media.get("type") or media.get("media_type") or "image") != "image":
            continue
        url = media.get("source_url") or media.get("url") or media.get("src")
        if url and "/story/" in str(url) and "pikabu.ru" in str(url):
            continue
        if url and str(url).startswith(("http://", "https://")):
            urls.append(str(url))
    grouped: dict[str, str] = {}
    for url in urls:
        name = url.split("?", 1)[0].rsplit("/", 1)[-1]
        key = name.rsplit(".", 1)[0]
        current = grouped.get(key)
        if current is None or ("/big/" in url and "/big/" not in current):
            grouped[key] = url
    return list(grouped.values())


def download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 edabalans editorial import"})
    with urllib.request.urlopen(request, timeout=45) as response:
        return response.read()


def encode_webp(raw: bytes, *, card: bool = False) -> tuple[bytes, int, int]:
    with Image.open(io.BytesIO(raw)) as image:
        image.load()
        image = image.convert("RGB")
        if card:
            image = ImageOps.fit(image, (1280, 720), method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
        else:
            image.thumbnail((1800, 1800), Image.Resampling.LANCZOS)
        quality = 84
        while True:
            target = io.BytesIO()
            image.save(target, "WEBP", quality=quality, method=6)
            value = target.getvalue()
            if len(value) <= 900_000 or quality <= 58:
                return value, image.width, image.height
            quality -= 6


def yaml_quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def source_item(spec: dict, sources: dict[str, dict]) -> tuple[list[dict], str, list[str]]:
    ids = spec.get("combined") or [spec["source_id"]]
    items = [sources[value] for value in ids]
    removed: list[str] = []
    if spec.get("combined"):
        sections = []
        labels = ["История, с которой всё началось", "Челлендж-инструкция", "Восемь советов начинающим"]
        intro = (
            "Эта история началась на Pikabu с короткого бегового челленджа: парень решил бегать 30 дней, "
            "писал отчёты и остановился примерно через неделю. Я сначала ответил ему отдельным постом, "
            "а потом собрал собственный эксперимент и практические советы в одну последовательную инструкцию."
        )
        for label, item in zip(labels, items):
            body, cut = markdown_body(item["text"], keep_pikabu_context=True)
            removed.extend(cut)
            sections.append(f"## {label}\n\n{body}")
        return items, intro + "\n\n" + "\n\n".join(sections), removed
    body, removed = markdown_body(items[0]["text"])
    return items, body, removed


def insert_media(body: str, refs: list[tuple[str, str]]) -> str:
    if not refs:
        return body
    blocks = body.strip().split("\n\n")
    step = max(2, len(blocks) // (len(refs) + 1))
    offset = 0
    for index, (name, alt) in enumerate(refs, start=1):
        at = min(len(blocks), step * index + offset)
        blocks.insert(at, f"![{alt}](/media/{name})")
        offset += 1
    return "\n\n".join(blocks).strip() + "\n"


def main() -> None:
    sources = load_sources()
    articles_dir = ROOT / "articles"
    media_root = ROOT / "media"
    machine_dir = ROOT / "machine"
    source_dir = ROOT / "sources"
    for directory in (articles_dir, media_root, machine_dir, source_dir):
        directory.mkdir(parents=True, exist_ok=True)

    manifest = {"schema_version": "blog-editorial-batch-v2", "items": []}
    handoff = ["# Редакционный handoff: подтверждённая партия 20.09.2026", ""]
    failures = []

    for spec in SPECS:
        items, body, removed = source_item(spec, sources)
        all_urls: list[str] = []
        for item in items:
            all_urls.extend(media_urls(item))
        all_urls = list(dict.fromkeys(all_urls))
        media_dir = media_root / spec["slug"]
        media_dir.mkdir(parents=True, exist_ok=True)
        local_media = []
        for index, url in enumerate(all_urls[:8], start=1):
            try:
                name = f"{index:02d}.webp"
                target = media_dir / name
                if target.exists():
                    encoded = target.read_bytes()
                    with Image.open(io.BytesIO(encoded)) as image:
                        width, height = image.size
                else:
                    raw = download(url)
                    encoded, width, height = encode_webp(raw)
                    target.write_bytes(encoded)
                local_media.append({
                    "name": name,
                    "path": f"media/{spec['slug']}/{name}",
                    "source_url": url,
                    "sha256": sha(encoded),
                    "width": width,
                    "height": height,
                    "alt": f"Иллюстрация к материалу «{spec['title']}»",
                })
            except Exception as exc:
                failures.append({"slug": spec["slug"], "url": url, "error": str(exc)})

        hero = local_media[0]["name"] if local_media else None
        card = None
        if local_media:
            card_source = media_dir / local_media[-1]["name"]
            card_bytes, card_w, card_h = encode_webp(card_source.read_bytes(), card=True)
            card = "card.webp"
            (media_dir / card).write_bytes(card_bytes)
            local_media.append({
                "name": card,
                "path": f"media/{spec['slug']}/{card}",
                "source_url": local_media[-1]["source_url"],
                "sha256": sha(card_bytes),
                "width": card_w,
                "height": card_h,
                "alt": f"Обложка материала «{spec['title']}»",
                "derived": "16:9 card crop",
            })

        body_refs = [
            (f"{spec['slug']}/{item['name']}", item["alt"])
            for item in local_media[1:-1]
            if item["name"] != card
        ]
        body = insert_media(body, body_refs)
        source_urls = [item["canonical_url"] for item in items]
        source_ids = [str(item["external_id"]) for item in items]
        source_hashes = [sha(item["text"]) for item in items]
        frontmatter = [
            "---",
            f"title: {yaml_quote(spec['title'])}",
            f"slug: {yaml_quote(spec['slug'])}",
            f"excerpt: {yaml_quote(spec['excerpt'])}",
            f"category: {yaml_quote(spec['category'])}",
            f"visibility: {yaml_quote(spec['visibility'])}",
            "editorial_status: \"moderation\"",
            f"source_id: {yaml_quote(spec['source_id'])}",
            f"cta: {yaml_quote(spec['cta'])}",
            "adaptation_mode: \"full_source\"",
            "validation_status: \"pending\"",
            "review_status: \"pending\"",
            "---",
            "",
        ]
        article_path = articles_dir / f"{spec['slug']}.md"
        article_path.write_text("\n".join(frontmatter) + body, encoding="utf-8")

        for item in items:
            source_path = source_dir / f"{item['source']}-{item['external_id']}.txt"
            source_path.write_text(item["text"], encoding="utf-8")

        task = {
            "schema_version": "author-task-v1",
            "external_id": spec["source_id"],
            "note": f"Бережная структурная адаптация exact full source: {spec['title']}",
            "work_profile": "develop_existing",
            "source_basis": "full_source",
            "job": "education",
            "goal": "Самостоятельная Markdown-статья личного блога без площадочных хвостов и встроенного CTA.",
            "audience": "Читатель публичного блога Сергея Воронцова.",
            "surface_context": "site_article",
            "format_profile": "article",
            "edit_mode": "rewrite",
            "rewrite_goal": "Минимальная редактура: сохранить авторские формулировки и фактуру, убрать площадочные хвосты, структурировать Markdown, сохранить медиа.",
            "rewrite_preserve": ["central thesis", "author position", "examples", "media", "recognizable voice"],
            "preservation_anchors": [
                next(
                    line.strip()
                    for line in body.splitlines()
                    if line.strip() and not line.startswith(("## ", "!["))
                )
            ],
            "allow_link_media_changes": True,
            "retrieval_depth": "deep",
            "source_text": "\n\n".join(item["text"] for item in items),
            "source_sha256": sha("\n\n".join(item["text"] for item in items)),
            "source_url": source_urls,
            "required_facts": [],
            "forbidden_claims": ["Площадочный CTA", "Просьба писать комментарии", "Старая реклама или erid"],
            "media_context": all_urls,
            "desired_action": "Прочитать материал; CTA добавляется оболочкой блога.",
        }
        (machine_dir / f"{spec['slug']}.author-task.json").write_text(
            json.dumps(task, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        manifest["items"].append({
            **spec,
            "file": f"articles/{article_path.name}",
            "sources": source_urls,
            "source_external_ids": source_ids,
            "source_sha256": source_hashes,
            "media": local_media,
            "hero": hero,
            "card": card,
            "removed_platform_tail": removed,
            "validation": "pending",
            "review": "pending",
        })
        handoff.extend([
            f"## {spec['title']}",
            "",
            f"- Статус: {'служебный' if spec['visibility'] == 'internal' else 'публичный кандидат'}, на модерации.",
            f"- Источники: {', '.join(source_urls)}",
            f"- Удалено площадочных строк: {len(removed)}.",
            f"- Локальных изображений: {len([m for m in local_media if m['name'] != card])}; card: {'да' if card else 'нет'}.",
            "- Содержательные факты не исправлялись автоматически; риски идут отдельным factcheck.",
            "",
        ])

    (ROOT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (ROOT / "editorial-handoff.md").write_text("\n".join(handoff), encoding="utf-8")
    (ROOT / "media-download-report.json").write_text(json.dumps({"failures": failures}, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
