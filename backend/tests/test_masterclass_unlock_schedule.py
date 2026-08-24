import os
from datetime import datetime, timezone
from types import SimpleNamespace


os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("ADMIN_PASSWORD", "test-app-secret")
os.environ.setdefault("APP_AUTH_SECRET", "test-client-session-secret")

from app.masterclass_routes import (  # noqa: E402
    course_timezone,
    next_local_unlock_at,
    unopened_day_reminder_due,
)


class NoTestProfile:
    def get(self, *_args):
        return None


def progress(*, opened_at: datetime, completed_at: datetime | None, timezone_name: str = "Europe/Moscow"):
    return SimpleNamespace(
        first_opened_at=opened_at,
        completed_at=completed_at,
        timezone_name=timezone_name,
    )


def test_completion_before_local_midnight_opens_next_day_at_six():
    item = progress(
        opened_at=datetime(2026, 8, 24, 17, tzinfo=timezone.utc),
        completed_at=datetime(2026, 8, 24, 20, 30, tzinfo=timezone.utc),
    )

    assert next_local_unlock_at(
        item, datetime(2026, 8, 24, 20, 30, tzinfo=timezone.utc)
    ) == datetime(2026, 8, 25, 3, tzinfo=timezone.utc)


def test_completion_after_local_midnight_moves_opening_one_morning():
    item = progress(
        opened_at=datetime(2026, 8, 24, 17, tzinfo=timezone.utc),
        completed_at=datetime(2026, 8, 24, 21, 30, tzinfo=timezone.utc),
    )

    assert next_local_unlock_at(
        item, datetime(2026, 8, 24, 21, 30, tzinfo=timezone.utc)
    ) == datetime(2026, 8, 26, 3, tzinfo=timezone.utc)


def test_incomplete_day_timer_moves_after_local_midnight():
    item = progress(
        opened_at=datetime(2026, 8, 24, 17, tzinfo=timezone.utc),
        completed_at=None,
    )

    assert next_local_unlock_at(
        item, datetime(2026, 8, 24, 20, 30, tzinfo=timezone.utc)
    ) == datetime(2026, 8, 25, 3, tzinfo=timezone.utc)
    assert next_local_unlock_at(
        item, datetime(2026, 8, 24, 21, 30, tzinfo=timezone.utc)
    ) == datetime(2026, 8, 26, 3, tzinfo=timezone.utc)


def test_unknown_or_invalid_timezone_falls_back_to_moscow():
    assert course_timezone("Unknown/Nowhere")[0] == "Europe/Moscow"
    assert course_timezone("../etc/passwd")[0] == "Europe/Moscow"


def test_unopened_day_reminder_is_at_local_eighteen_on_unlock_day():
    item = progress(
        opened_at=datetime(2026, 8, 24, 17, tzinfo=timezone.utc),
        completed_at=datetime(2026, 8, 24, 20, 30, tzinfo=timezone.utc),
    )
    due = unopened_day_reminder_due(
        NoTestProfile(),
        "11111111-1111-1111-1111-111111111111",
        item,
        datetime(2026, 8, 24, 20, 30, tzinfo=timezone.utc),
    )
    assert due == datetime(2026, 8, 25, 15, tzinfo=timezone.utc)


def test_unopened_day_reminder_uses_participant_timezone():
    item = progress(
        opened_at=datetime(2026, 8, 24, 8, tzinfo=timezone.utc),
        completed_at=datetime(2026, 8, 24, 9, tzinfo=timezone.utc),
        timezone_name="Asia/Yekaterinburg",
    )
    due = unopened_day_reminder_due(
        NoTestProfile(),
        "11111111-1111-1111-1111-111111111111",
        item,
        datetime(2026, 8, 24, 9, tzinfo=timezone.utc),
    )
    assert due == datetime(2026, 8, 25, 13, tzinfo=timezone.utc)
