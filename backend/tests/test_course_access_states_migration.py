from pathlib import Path


MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "versions"
    / "20260925_0047_course_access_states_and_direct_credentials.py"
)


def test_course_access_state_migration_preserves_legacy_records() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert 'revision = "20260925_0047"' in source
    assert 'down_revision = "20260921_0047"' in source
    assert "WHERE email.user_id = link.user_id" in source
    assert "'legacy-link-' || link.id::text || '@invalid.local'" in source
    assert "UPDATE user_course_policies SET start_mode = 'open'" in source
