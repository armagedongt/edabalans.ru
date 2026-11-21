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


def test_morning_today_evening_tomorrow_links_done_history_and_seven_day_reminder():
    entries = [entry(title="Сегодня <встреча>", note="Адрес & время", url="https://example.test/pay?a=1&b=2"),
        entry("tomorrow", date="2026-11-22", title="Завтра"), entry("done", done=True, title="Сделано"),
        entry("history", cat="history", title="История"),
        entry("payment", cat="finance", date="2026-11-28", title="Подписка 500 ₽", note="Карта 1234")]
    morning = current_slot(datetime(2026, 11, 21, 3, tzinfo=UTC))
    messages, ids, day = render_messages(entries, morning)
    text = "\n".join(messages)
    assert day.isoformat() == "2026-11-21" and ids == ["one", "payment"]
    for expected in ["Сегодня &lt;встреча&gt;", "Адрес &amp; время", 'href="https://example.test/pay?a=1&amp;b=2"',
                     "Через 7 дней", "Подписка 500 ₽", "Карта 1234", "статус оплаты проверьте отдельно"]:
        assert expected in text
    assert all(x not in text for x in ["Сделано", "История", "Завтра"])
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
