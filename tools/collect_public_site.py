"""Read-only local collector for a small public website.

It discovers same-site pages through robots.txt, sitemap.xml and ordinary internal
links, then saves an auditable private snapshot. It never submits forms, follows
external sites or changes the source website.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urldefrag, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from lxml import etree, html


SKIP_SUFFIXES = {
    ".7z", ".avi", ".css", ".doc", ".docx", ".gif", ".gz", ".ico", ".jpeg",
    ".jpg", ".js", ".mov", ".mp3", ".mp4", ".pdf", ".png", ".rar", ".svg",
    ".tar", ".webm", ".webp", ".xls", ".xlsx", ".xml", ".zip",
}
MEDIA_XPATH = (
    "//img/@src | //img/@data-original | //img/@data-src | //video/@src | "
    "//video/@poster | //audio/@src | //source/@src | //iframe/@src"
)


def canonical_url(value: str) -> str:
    """Normalize a discovered URL without changing its meaningful query."""
    no_fragment, _ = urldefrag(value)
    parsed = urlsplit(no_fragment)
    path = parsed.path or "/"
    host = parsed.hostname or ""
    ascii_host = host.lower().encode("idna").decode("ascii")
    netloc = ascii_host
    if parsed.port is not None:
        netloc = f"{netloc}:{parsed.port}"
    return urlunsplit((parsed.scheme.lower(), netloc, path, parsed.query, ""))


def hostname(value: str) -> str:
    host = urlsplit(value).hostname or ""
    return host.lower().encode("idna").decode("ascii")


def is_internal_page(value: str, allowed_hosts: set[str]) -> bool:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or hostname(value) not in allowed_hosts:
        return False
    path = parsed.path.lower()
    return not any(path.endswith(suffix) for suffix in SKIP_SUFFIXES)


def fetch(url: str, timeout: int) -> tuple[str, str]:
    request = Request(url, headers={"User-Agent": "edabalans-content-catalog/1.0 (read-only)"})
    with urlopen(request, timeout=timeout) as response:  # nosec B310: target is owner-approved public site
        charset = response.headers.get_content_charset() or "utf-8"
        return response.geturl(), response.read().decode(charset, errors="replace")


def sitemap_urls(root: str, timeout: int) -> set[str]:
    candidates = {urljoin(root, "/sitemap.xml")}
    try:
        _, robots = fetch(urljoin(root, "/robots.txt"), timeout)
        for value in re.findall(r"(?im)^sitemap:\s*(\S+)", robots):
            candidates.add(value.strip())
    except Exception:
        pass

    found: set[str] = set()
    for sitemap in candidates:
        try:
            _, payload = fetch(sitemap, timeout)
            tree = etree.fromstring(payload.encode("utf-8"))
            found.update(value.strip() for value in tree.xpath("//*[local-name()='loc']/text()") if value.strip())
        except Exception:
            continue
    return found


def extract_page(url: str, payload: str) -> dict[str, object]:
    document = html.fromstring(payload)
    for node in document.xpath("//script|//style|//noscript|//svg|//template"):
        node.drop_tree()

    title = " ".join(document.xpath("//title/text()")).strip()
    description = " ".join(document.xpath("//meta[@name='description']/@content")).strip()
    headings = [" ".join(node.text_content().split()) for node in document.xpath("//h1|//h2|//h3")]
    plain_text = " ".join(document.text_content().split())
    links = sorted({canonical_url(urljoin(url, value)) for value in document.xpath("//a/@href") if value})
    media = sorted({canonical_url(urljoin(url, value)) for value in document.xpath(MEDIA_XPATH) if value})
    return {
        "url": url,
        "title": title,
        "meta_description": description,
        "headings": headings,
        "plain_text": plain_text,
        "word_count": len(re.findall(r"[\wЁёА-Яа-я-]+", plain_text, re.UNICODE)),
        "links": links,
        "media_links": media,
    }


def classify(page: dict[str, object]) -> str:
    path = urlsplit(str(page["url"])).path.rstrip("/") or "/"
    if path in {"/intensiv_d1", "/intensiv_d2", "/intensiv_d3", "/intensiv_d4"}:
        return "free_intensive_lesson"
    if path in {"/", "/master-klass"}:
        return "sales_or_offer"
    if path in {"/intensiv", "/intensiv_1", "/intensive_pohodenye"}:
        return "free_intensive"
    if path in {"/dp", "/jpn", "/starts"}:
        return "article_or_editorial"
    if path in {"/podgotovka", "/podgotovka2", "/skorost_pohudeniya"}:
        return "ad_landing_short"
    if path.startswith("/tproduct/"):
        return "product_card_low_context"
    if path.startswith(("/admin", "/payment", "/page", "/calc", "/dqs", "/hello", "/lk", "/oferta", "/privacy", "/qwerty", "/tests", "/tg", "/train", "/upgrade")):
        return "technical_or_utility"
    haystack = " ".join([str(page["title"]), str(page["meta_description"]), *page["headings"]]).lower()
    if "интенсив" in haystack:
        return "free_intensive"
    if any(marker in haystack for marker in ("статья", "блог", "разбор", "пост")):
        return "article_or_editorial"
    if any(marker in haystack for marker in ("тариф", "купить", "мастер-класс", "консультац", "курс")):
        return "sales_or_offer"
    return "needs_editorial_review"


def ensure_private(output: Path) -> Path:
    resolved = output.expanduser().resolve()
    repo = Path(__file__).resolve().parents[1]
    if resolved == repo or repo in resolved.parents:
        raise ValueError("site snapshot must be outside Git")
    return resolved


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, help="Public site root URL")
    parser.add_argument("--output", required=True, type=Path, help="Private output folder outside Git")
    parser.add_argument("--max-pages", type=int, default=60)
    parser.add_argument("--pause-seconds", type=float, default=0.25)
    parser.add_argument("--timeout", type=int, default=20)
    args = parser.parse_args()
    if args.max_pages < 1:
        raise ValueError("--max-pages must be positive")

    root = canonical_url(args.root)
    allowed_hosts = {hostname(root)}
    if hostname(root).startswith("www."):
        allowed_hosts.add(hostname(root)[4:])
    else:
        allowed_hosts.add("www." + hostname(root))
    output = ensure_private(args.output)
    raw_dir = output / "raw-html"
    raw_dir.mkdir(parents=True, exist_ok=True)

    queue = deque([root])
    queue.extend(sorted(canonical_url(value) for value in sitemap_urls(root, args.timeout) if is_internal_page(value, allowed_hosts)))
    seen: set[str] = set()
    pages: list[dict[str, object]] = []
    errors: list[dict[str, str]] = []

    while queue and len(pages) < args.max_pages:
        current = canonical_url(queue.popleft())
        if current in seen or not is_internal_page(current, allowed_hosts):
            continue
        seen.add(current)
        try:
            final_url, payload = fetch(current, args.timeout)
            final_url = canonical_url(final_url)
            page = extract_page(final_url, payload)
            page["source"] = "tilda_site"
            page["page_kind_auto"] = classify(page)
            digest = hashlib.sha256(final_url.encode("utf-8")).hexdigest()[:16]
            raw_file = raw_dir / f"{digest}.html"
            raw_file.write_text(payload, encoding="utf-8")
            page["raw_html_file"] = str(raw_file)
            pages.append(page)
            for link in page["links"]:
                if is_internal_page(link, allowed_hosts) and link not in seen:
                    queue.append(link)
        except Exception as error:
            errors.append({"url": current, "error": f"{type(error).__name__}: {error}"})
        time.sleep(args.pause_seconds)

    output.mkdir(parents=True, exist_ok=True)
    pages_path = output / "pages.jsonl"
    pages_path.write_text("\n".join(json.dumps(page, ensure_ascii=False) for page in pages) + "\n", encoding="utf-8")
    report = {
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "root": root,
        "allowed_hosts": sorted(allowed_hosts),
        "pages": len(pages),
        "errors": errors,
        "unvisited_internal_candidates": len(queue),
        "max_pages": args.max_pages,
        "pages_file": str(pages_path),
    }
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
