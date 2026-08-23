import os
from datetime import datetime, timezone
from types import SimpleNamespace


os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("ADMIN_PASSWORD", "test-app-secret")
os.environ.setdefault("APP_AUTH_SECRET", "test-client-session-secret")

from app.masterclass_routes import course_timezone, next_local_unlock_at  # noqa: E402


def progress(*, opened_at: datetime, completed_at: datetime | None):
    return SimpleNamespace(
        first_opened_at=opened_at,
        completed_at=completed_at,
        timezone_name="Europe/Moscow",
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
