"""Keep browser links on their current site; external integrations use configured origins."""
from __future__ import annotations

from html import escape, unescape
from html.parser import HTMLParser
import os
import re
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit


def public_site_origin() -> str:
    value = urlsplit(os.getenv("ACCOUNT_PUBLIC_URL", "https://xn-----jlceacr3bggd8ajed5a6kl.xn--p1ai/lk"))
    host = (value.hostname or "").encode("idna").decode("ascii")
    authority = host + (":" + str(value.port) if value.port else "")
    return urlunsplit((value.scheme, authority, "", "", ""))


def admin_site_origin() -> str:
    value = urlsplit(public_site_origin())
    return urlunsplit((value.scheme, "admin." + value.netloc, "", "", ""))


def site_hostnames() -> set[str]:
    host = urlsplit(public_site_origin()).hostname or ""
    return {host, "www." + host, "admin." + host}


def relative_site_url(value: str) -> str:
    """Convert exact public backend aliases, never admin/archive/third-party hosts."""
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return value
        if parsed.username or parsed.password or parsed.port not in {None, 443 if parsed.scheme == "https" else 80}:
            return value
        host = parsed.hostname.encode("idna").decode("ascii").lower()
        primary = urlsplit(public_site_origin()).hostname or ""
        hosts = {primary.encode("idna").decode("ascii").lower(),
                 "www." + primary.encode("idna").decode("ascii").lower(),
                 "edabalans.ru", "www.edabalans.ru", "app.edabalans.ru",
                 "xn-----jlceacr3bggd8ajed5a6kl.xn--p1ai",
                 "www.xn-----jlceacr3bggd8ajed5a6kl.xn--p1ai"}
        path = parsed.path or "/"
        decoded = unquote(path)
        if (host not in hosts or decoded.startswith("//") or "\\" in decoded
                or any(ord(c) < 32 for c in unquote(value))
                or path == "/sherbakova" or path.startswith("/sherbakova/")):
            return value
        return urlunsplit(("", "", path, parsed.query, parsed.fragment))
    except (ValueError, UnicodeError):
        return value


def relative_media_url(value: str) -> str:
    relative = relative_site_url(value)
    try:
        path = urlsplit(relative).path
    except ValueError:
        return value
    if relative.startswith("/") and not relative.startswith("//") and path.startswith((
        "/media/reviews/", "/preview/homepage-mobile/", "/editorial-media/",
        "/course-assets/", "/blog/media/", "/assets/",
    )):
        return relative
    return value


_ATTR = re.compile(r"(?P<name>\b(?:href|src|poster|action|data-src))\s*=\s*(?P<quote>[\"'])(?P<value>.*?)(?P=quote)", re.I | re.S)


def relative_site_html(value: str) -> str:
    """Rewrite URL attributes in tags only, preserving copy, scripts and saved revisions."""
    class Links(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=False)
            self.edits = []
            self.lines = [0]
            self.lines.extend(match.end() for match in re.finditer("\n", value))

        def handle_starttag(self, tag, attrs):
            if tag.lower() not in {"a", "img", "audio", "video", "source", "iframe", "script", "form"}:
                return
            original = self.get_starttag_text()
            def replace(match):
                old = unescape(match["value"])
                new = relative_site_url(old) if tag.lower() in {"a", "form"} else relative_media_url(old)
                if tag.lower() == "iframe" and old.startswith("/course-assets/masterclass/audio-player?"):
                    parts = urlsplit(old)
                    query = [(key, relative_media_url(val) if key in {"src", "avatar"} else val)
                             for key, val in parse_qsl(parts.query, keep_blank_values=True)]
                    new = urlunsplit(("", "", parts.path, urlencode(query), parts.fragment)) if not parts.netloc else new
                if old == new:
                    return match[0]
                return match["name"] + "=" + match["quote"] + escape(new, quote=True) + match["quote"]
            replacement = _ATTR.sub(replace, original)
            if replacement != original:
                line, column = self.getpos()
                start = self.lines[line - 1] + column
                self.edits.append((start, start + len(original), replacement))

        handle_startendtag = handle_starttag

    parser = Links()
    parser.feed(value)
    parser.close()
    for start, end, replacement in reversed(parser.edits):
        value = value[:start] + replacement + value[end:]
    return value
