from pathlib import Path


def test_cross_messenger_migration_continues_the_current_alembic_chain():
    migration = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "versions"
        / "20260920_0046_cross_messenger_bridge.py"
    ).read_text(encoding="utf-8")

    assert 'revision = "20260920_0046"' in migration
    assert 'down_revision = "20260919_0045"' in migration
    for table_name in (
        "messaging_bridge_pairs",
        "messaging_bridge_messages",
        "messaging_bridge_receipts",
        "messaging_bridge_deliveries",
    ):
        assert f"CREATE TABLE {table_name}" in migration
        assert f"DROP TABLE IF EXISTS {table_name}" in migration
