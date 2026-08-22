from __future__ import annotations

import html
import re


ALLOWED_TAG = re.compile(r"&lt;(/?)(b|strong|i|em|u|s|del|blockquote)&gt;", re.I)
ALLOWED_LINK = re.compile(r'&lt;a\s+href=&quot;(https?://[^&]+?)&quot;&gt;(.*?)&lt;/a&gt;', re.I | re.S)


def to_telegram_html(source: str) -> str:
    """Convert the small LeadTeh mixed-markup subset without allowing arbitrary HTML."""
    value = html.escape(source or "", quote=True)
    value = re.sub(r"&lt;br\s*/?&gt;", "\n", value, flags=re.I)
    value = ALLOWED_LINK.sub(lambda m: f'<a href="{m.group(1)}">{m.group(2)}</a>', value)
    value = ALLOWED_TAG.sub(lambda m: f"<{m.group(1)}{m.group(2).lower()}>", value)
    value = re.sub(r"\[([^\]]+)]\((https?://[^\s)]+)\)", r'<a href="\2">\1</a>', value)
    value = re.sub(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])", r"<b>\1</b>", value)
    value = re.sub(r"(?<![\w_])_([^_\n]+)_(?![\w_])", r"<i>\1</i>", value)
    value = re.sub(r"(?<![\w~])~([^~\n]+)~(?![\w~])", r"<s>\1</s>", value)
    return value
