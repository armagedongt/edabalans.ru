"""Resolve a selected Markdown file's local image attachments without altering its original."""
from __future__ import annotations

from dataclasses import dataclass
import base64
import hashlib
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit


IMAGE_SUFFIXES = {".png": "png", ".jpg": "jpg", ".jpeg": "jpg", ".webp": "webp"}
IMAGE = re.compile(r'!\[\[(?P<wiki>[^\]\n]+)\]\]|!\[(?P<alt>[^\]\n]*)\]\((?P<target><[^>\n]+>|[^\s)]+)(?P<title>\s+"[^"\n]*")?\)')
INLINE_CODE = re.compile(r'`+[^`\n]*`+')


def code_ranges(markdown: str) -> list[tuple[int, int]]:
    ranges = [(match.start(), match.end()) for match in INLINE_CODE.finditer(markdown)]
    opening = None
    for match in re.finditer(r'(?m)^[ \t]{0,3}(`{3,}|~{3,})([^\n]*)(?:\n|$)', markdown):
        fence, tail = match.groups()
        if opening is None:
            if fence[0] != '`' or '`' not in tail:
                opening = (match.start(), fence)
        elif fence[0] == opening[1][0] and len(fence) >= len(opening[1]) and not tail.strip():
            ranges.append((opening[0], match.end()))
            opening = None
    if opening is not None:
        ranges.append((opening[0], len(markdown)))
    return ranges


@dataclass(frozen=True)
class LocalImage:
    start: int
    end: int
    path: Path
    relative: str
    raw: bytes
    sha256: str
    extension: str
    alt: str
    title: str


def local_images(root: Path, file: Path, markdown: str, *, server_prefixes: tuple[str, ...] = ()) -> list[LocalImage]:
    root, file = root.resolve(), file.resolve()
    if not file.is_relative_to(root):
        raise ValueError("Материал находится вне папки Obsidian")
    code = code_ranges(markdown)
    images = []
    for match in IMAGE.finditer(markdown):
        if any(start <= match.start() < end for start, end in code):
            continue
        wiki = match.group("wiki")
        target = (wiki.split("|", 1)[0] if wiki is not None else match.group("target").strip("<>"))
        target = unquote(target)
        if urlsplit(target).scheme in {"https", "http"} or (wiki is None and target.startswith("/") and not target.startswith("//")):
            continue
        if urlsplit(target).scheme or target.startswith(("//", "\\")) or "\x00" in target:
            raise ValueError("Недопустимый локальный путь картинки")
        target_path = Path(target)
        primary = ((file.parent if wiki is None else root) / target_path).resolve()
        if not primary.is_relative_to(root):
            raise ValueError("Картинка должна находиться внутри папки Obsidian")
        if primary.is_file():
            found = {primary}
        else:
            fallback = ((root if wiki is None else file.parent) / target_path).resolve()
            found = {fallback} if fallback.is_relative_to(root) and fallback.is_file() else set()
        if wiki is not None and target_path.name == target:
            found = {path.resolve() for path in root.rglob(target) if path.is_file()}
        if any(not candidate.is_relative_to(root) for candidate in found):
            raise ValueError("Ссылка картинки выходит за папку Obsidian")
        # Existing Git render profiles already serve their packaged assets on the site.
        if not found and wiki is None and target.startswith(server_prefixes):
            continue
        if len(found) != 1:
            raise ValueError("Картинка не найдена или её имя неоднозначно: " + target)
        path = found.pop()
        extension = IMAGE_SUFFIXES.get(path.suffix.casefold())
        if extension is None:
            raise ValueError("Поддерживаются картинки PNG, JPG и WebP: " + target)
        raw = path.read_bytes()
        if not 0 < len(raw) <= 1024 * 1024:
            raise ValueError("Картинка должна занимать до 1 MiB: " + target)
        alias = wiki.split("|", 1)[1] if wiki is not None and "|" in wiki else ""
        alt = match.group("alt") if wiki is None else ("" if re.fullmatch(r"\d+(?:x\d+)?", alias) else alias)
        images.append(LocalImage(match.start(), match.end(), path, path.relative_to(root).as_posix(), raw,
                                 hashlib.sha256(raw).hexdigest(), extension, alt, match.group("title") or ""))
    unique = {image.sha256: image for image in images}
    if len(unique) > 8 or sum(len(image.raw) for image in unique.values()) > 4 * 1024 * 1024:
        raise ValueError("Картинки выбранного материала превышают 4 MiB")
    return images


def rendered_source(markdown: str, images: list[LocalImage], scope: str) -> str:
    token = base64.urlsafe_b64encode(scope.encode()).decode().rstrip("=")
    for image in reversed(images):
        url = f"https://edabalans.ru/editorial-media/{token}/{image.sha256}.{image.extension}"
        alt = image.alt
        if "[" in alt or "]" in alt:
            raise ValueError("В подписи картинки квадратные скобки пока не поддерживаются")
        markdown = markdown[:image.start] + f"![{alt}]({url}{image.title})" + markdown[image.end:]
    return markdown


def unchanged(images: list[LocalImage]) -> bool:
    return all(image.path.is_file() and hashlib.sha256(image.path.read_bytes()).hexdigest() == image.sha256 for image in images)


def working_source(remote: str, local: str, images: list[LocalImage], scope: str) -> str:
    for image in images:
        wire = rendered_source(local[image.start:image.end], [LocalImage(
            0, image.end-image.start, image.path, image.relative, image.raw, image.sha256,
            image.extension, image.alt, image.title)], scope)
        remote = remote.replace(wire, local[image.start:image.end])
    return remote


def upload(api, scope: str, images: list[LocalImage]) -> None:
    seen = set()
    for image in images:
        if image.sha256 in seen:
            continue
        api.request("POST", "/admin/api/editorial/media", {
            "scope": scope, "name": f"{image.sha256}.{image.extension}",
            "content_base64": base64.b64encode(image.raw).decode(),
            "alt": image.alt, "provenance": "owner-upload; attachment: " + image.relative,
        })
        seen.add(image.sha256)
