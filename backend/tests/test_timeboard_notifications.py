import os
from datetime import UTC, datetime
from html import unescape

import pytest
from sqlalchemy import select

os.environ.setdefault("DATABASE_URL", "sqlite://")
from app.models import MasterclassNotification
from app.timeboard_notifications import current_slot, day_entries, enqueue_summary, render_messages
from test_admin_apps import add_user, make_client


def entry(id="one", **values):
    return {"id": id, "cat": "work", "title": "Работа", "date": "2026-11-21", **values}


@pytest.mark.parametrize("utc,expected", [("2026-11-21T03:00:00", 6), ("2026-11-21T17:29:59", 20),
    ("2026-11-21T03:30:00", None), ("2026-11-21T16:59:59", None), ("2026-11-20T23:00:00", None)])
def test_only_current_moscow_slot_and_bounded_restart_catchup(utc, expected):
    slot = current_slot(datetime.fromisoformat(utc).replace(tzinfo=UTC))
    assert (slot.hour if slot else None) == expected


def test_morning_today_evening_tomorrow_links_done_history_and_explicit_reminder_dates():
    entries = [entry(title="Сегодня <встреча>", note="Адрес & время", url="https://example.test/pay?a=1&b=2"),
        entry("tomorrow", date="2026-11-22", title="Завтра"), entry("done", done=True, title="Сделано"),
        entry("history", cat="history", title="История"),
        entry("reminder", cat="finance", title="Через 7 дней: подписка 500 ₽", note="Карта 1234"),
        entry("payment", cat="finance", date="2026-11-28", title="Будущий платёж 500 ₽")]
    morning = current_slot(datetime(2026, 11, 21, 3, tzinfo=UTC))
    messages, ids, day = render_messages(entries, morning)
    text = "\n".join(messages)
    assert day.isoformat() == "2026-11-21" and ids == ["one", "reminder"]
    for expected in ["Сегодня &lt;встреча&gt;", "Адрес &amp; время", 'href="https://example.test/pay?a=1&amp;b=2"',
                     "<b>За 7 дней</b>", "1. подписка 500 ₽", "Карта 1234"]:
        assert expected in text
    assert all(x not in text for x in ["Сделано", "История", "Завтра", "Будущий платёж"])
    evening = current_slot(datetime(2026, 11, 21, 17, tzinfo=UTC))
    messages, ids, day = render_messages(entries, evening)
    assert day.isoformat() == "2026-11-22" and ids == ["tomorrow"]
    assert "Завтра" in messages[0] and "Подписка" not in "".join(messages)


def test_weekly_sonya_projection_and_override_match_board():
    slot = current_slot(datetime(2026, 11, 21, 3, tzinfo=UTC))
    weekly = entry("weekly", cat="sonya", date="2026-11-14", sonyaRole="weekly")
    indicator = entry("indicator", cat="sonya", sonyaRole="indicator")
    assert [e["id"] for e in day_entries([weekly, indicator], slot.date())] == ["weekly"]
    override = entry("override", cat="sonya", sonyaRole="override")
    assert [e["id"] for e in day_entries([weekly, indicator, override], slot.date())] == ["override"]


def test_long_hostile_notes_preserved_without_broken_entities_or_links():
    slot = current_slot(datetime(2026, 11, 21, 3, tzinfo=UTC))
    note = '<script>&🏋️' * 180
    messages, _, _ = render_messages([entry(note=note, url="https://example.test/" + "a" * 1500)], slot)
    assert len(messages) > 1
    assert all(len(m.encode("utf-16-le")) // 2 < 4000 for m in messages)
    assert sum(m.count('href="https://example.test/') for m in messages) == 1
    decoded = "".join(unescape(m.split('\n\n<a href="https://похудение-это-есть.рф/timeboard/">')[0]).replace("\n", "") for m in messages)
    assert note in decoded
    assert "<script>" not in "".join(messages)
    assert all(m.count("<b>") == m.count("</b>") for m in messages)
    assert decoded.count("🏋️") == 180


def test_slot_snapshot_is_atomic_deduplicated_across_restarts_and_edits():
    _, factory = make_client()
    with factory() as db:
        add_user(db, "armagedongt@gmail.com", "Владелец")
        db.commit()
        now = datetime(2026, 11, 21, 3, tzinfo=UTC)
        calls = []
        def snapshot():
            calls.append(True)
            return 17, [entry(note="&" * 2000)]
        count = enqueue_summary(db, now, snapshot)
        assert count > 1
        assert enqueue_summary(db, now, snapshot) == 0 and len(calls) == 1
        rows = list(db.scalars(select(MasterclassNotification)))
        assert len(rows) == count and {r.payload["board_revision"] for r in rows} == {17}
        ordered = list(db.scalars(select(MasterclassNotification).order_by(MasterclassNotification.due_at)))
        assert [r.payload["part"] for r in ordered] == list(range(1, count + 1))
        assert len({r.due_at for r in ordered}) == count
        assert all(r.notification_kind == "owner_planning_summary" and r.payload["delivery_role"] == "planning" for r in rows)
        assert enqueue_summary(db, datetime(2026, 11, 21, 16, tzinfo=UTC), snapshot) == 0
        assert enqueue_summary(db, datetime(2026, 11, 21, 17, tzinfo=UTC), lambda: (18, [])) == 1
        assert len(list(db.scalars(select(MasterclassNotification)))) == count + 1


def test_snapshot_failure_never_queues_false_empty_day():
    _, factory = make_client()
    with factory() as db:
        add_user(db, "armagedongt@gmail.com", "Владелец"); db.commit()
        def failed():
            raise OSError("unavailable")
        with pytest.raises(OSError):
            enqueue_summary(db, datetime(2026, 11, 21, 3, tzinfo=UTC), failed)
        assert db.scalar(select(MasterclassNotification)) is None


def test_summary_groups_topics_with_bold_headings_blank_lines_and_numbered_items():
    slot = current_slot(datetime(2026, 11, 21, 3, tzinfo=UTC))
    entries = [
        entry("late-payment", cat="finance", title="Облако · 500 ₽", time="19:00"),
        entry("call", cat="work", title="Валентина", time="12:30"),
        entry("early-payment", cat="finance", title="Банк · 1 000 ₽", time="08:00",
              note="До 28.11.2026", url="https://example.test/pay"),
        entry("no-time", cat="finance", title="Связь · 700 ₽"),
    ]
    messages, _, _ = render_messages(entries, slot)
    assert len(messages) == 1
    text = messages[0]
    assert "\n\n<b>Работа</b>\n1. 12:30 · Валентина" in text
    assert "\n\n<b>Финансы</b>\n1. 08:00 · Банк · 1 000 ₽\nДо 28.11.2026" in text
    assert text.count("<b>Финансы</b>") == 1
    assert text.index("<b>Работа</b>") < text.index("<b>Финансы</b>")
    assert 'Открыть запись</a>\n2. 19:00 · Облако · 500 ₽\n3. Связь · 700 ₽' in text
    assert "Без времени" not in text
    assert "<b>Тренировки</b>" not in text
    assert text.endswith('>Открыть доску</a>')


def test_week_reminders_share_one_section_without_repeating_marker_across_categories():
    slot = current_slot(datetime(2026, 11, 21, 3, tzinfo=UTC))
    messages, ids, _ = render_messages([
        entry("payment", cat="finance", title="Счёт сегодня"),
        entry("week-bank", cat="finance", title="Через 7 дней · Ozon · 13 100 ₽",
              note="До 28.11.2026", url="https://example.test/ozon"),
        entry("week-sim", cat="outside", title="Через 7 дней: Обновить SIM"),
        entry("week-cloud", cat="finance", title="Через 7 дней · Облако · 500 ₽"),
    ], slot)
    text = "\n".join(messages)
    assert len(ids) == 4
    assert text.count("<b>За 7 дней</b>") == 1
    assert "Через 7 дней" not in text
    for title in ["Обновить SIM", "Ozon · 13 100 ₽", "Облако · 500 ₽"]:
        assert text.count(title) == 1
        assert title not in text.split("<b>За 7 дней</b>", 1)[0]
    assert "<b>Финансы</b>\n1. Счёт сегодня" in text
    section = text.split("<b>За 7 дней</b>\n", 1)[1]
    assert section.startswith("1. Обновить SIM\n2. Ozon · 13 100 ₽\nДо 28.11.2026")
    assert 'Открыть запись</a>\n3. Облако · 500 ₽' in section
    assert text.index("Счёт сегодня") < text.index("<b>За 7 дней</b>")
