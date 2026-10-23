"""Render a read-only personal calendar from a JSON file kept outside Git."""

from __future__ import annotations

import argparse
import calendar
from datetime import date
from html import escape
import json
import os
from pathlib import Path
import tempfile


MONTHS = ("", "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
          "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь")
WEEKDAYS = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")
STATUSES = {"busy": "Занята", "free": "Свободна", "partial": "Частично", "unknown": "Нет графика"}


def render(data: dict) -> str:
    start, end = date.fromisoformat(data["start"]), date.fromisoformat(data["end"])
    anchor = date.fromisoformat(data["cycle_start"])
    cycle_length = int(data["cycle_length"])
    period_days = int(data["period_days"])
    if not 1 <= period_days < cycle_length or end < start:
        raise ValueError("Invalid calendar range or cycle parameters")
    events = data.get("days", {})
    title = escape(data["title"])
    sections = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        first = start.day if (year, month) == (start.year, start.month) else 1
        last = min(calendar.monthrange(year, month)[1], end.day) if (year, month) == (end.year, end.month) else calendar.monthrange(year, month)[1]
        cells = ['<div class="blank" aria-hidden="true"></div>'] * date(year, month, first).weekday()
        for day in range(first, last + 1):
            current = date(year, month, day)
            info = events.get(current.isoformat(), {})
            status = info.get("status", "unknown")
            if status not in STATUSES:
                raise ValueError(f"Unknown status on {current}")
            elapsed = (current - anchor).days
            cycle_day = elapsed % cycle_length + 1 if elapsed >= 0 else None
            phase, label = "plain", "День цикла"
            if cycle_day is None:
                label = "Цикл: —"
            elif cycle_day <= period_days:
                phase, label = "period", "Месячные"
            elif 10 <= cycle_length - cycle_day + 1 <= 16:
                phase, label = "ovulation", "Овуляция"
            number = str(cycle_day) if cycle_day is not None else ""
            comment = escape(info.get("note", ""))
            comment_html = f'<div class="comment">{comment}</div>' if comment else ""
            cells.append(f'''<div class="day" data-date="{current.isoformat()}">
<div class="date">{day} · {WEEKDAYS[current.weekday()]}</div>
<div class="status {status}">{STATUSES[status]}</div>
<div class="phase {phase}"><span>{label}</span><span>{number}</span></div>
{comment_html}</div>''')
        sections.append(f'<section><h2>{MONTHS[month]} {year}</h2><div class="grid">{"".join(cells)}</div></section>')
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    details = escape(data.get("forecast_note", ""))
    return f'''<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow,noarchive"><meta name="referrer" content="no-referrer">
<title>{title}</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#fafaf9;color:#252525;font:15px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}}
main{{max-width:1100px;padding:28px 20px 48px;margin:auto}}h1{{font-size:25px;font-weight:600;margin:0 0 8px}}h2{{font-size:20px;font-weight:600;margin:28px 0 14px}}
.subtitle,.plain,.unknown,details{{color:#666}}.subtitle,details{{font-size:13px}}.legend{{display:flex;flex-wrap:wrap;gap:8px 16px;margin-top:14px;font-size:13px}}
.legend span{{display:flex;align-items:center;gap:6px}}.swatch{{width:11px;height:11px;border-radius:3px}}
.grid{{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:12px 8px}}.day{{display:flex;flex-direction:column;gap:7px;min-width:0;min-height:155px;padding-top:9px;border-top:1px solid #deded9;font-size:13px}}
.date{{font-weight:600}}.status,.phase{{padding:4px 6px;border-radius:4px}}.busy,.partial{{background:#e6e6e3}}.free{{background:#d8efdc}}.period{{background:#f8d9dc}}.ovulation{{background:#d7edfa}}
.unknown{{padding-left:0}}.phase{{display:flex;justify-content:space-between;gap:4px;white-space:nowrap}}.comment{{margin-top:auto;overflow-wrap:anywhere;padding:4px 0}}details{{margin-top:26px}}summary{{cursor:pointer}}details p{{max-width:780px}}
@media(max-width:760px){{main{{padding:20px 12px 36px}}.grid{{grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}}.blank{{display:none}}.day{{min-height:145px}}}}
</style></head><body><main><h1>{title}</h1>
<div class="subtitle">{start.strftime('%d.%m.%Y')} — {end.strftime('%d.%m.%Y')} · Цикл: прогноз {cycle_length} дней от {anchor.strftime('%d.%m')}</div>
<div class="legend"><span><i class="swatch busy"></i>Занята</span><span><i class="swatch free"></i>Свободна</span><span><i class="swatch period"></i>Месячные</span><span><i class="swatch ovulation"></i>Окно овуляции</span></div>
{"".join(sections)}
<details><summary>О прогнозе</summary><p>{details}</p></details>
</main></body></html>'''


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    page = render(json.loads(args.source.read_text(encoding="utf-8")))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=args.output.parent, delete=False) as temp:
            temp_path = Path(temp.name)
            temp.write(page)
        temp_path.chmod(0o644)
        os.replace(temp_path, args.output)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
