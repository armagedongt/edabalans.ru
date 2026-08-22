import os
from decimal import Decimal
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://test:test@127.0.0.1:5432/test")

from app.importers.manual_payments import extract_username, parse_amount, parse_ledger


def test_parse_amount_handles_russian_spaces() -> None:
    assert parse_amount("12\u00a0700 ₽") == Decimal("12700")
    assert parse_amount("0 ₽") is None


def test_extract_username_from_mixed_name() -> None:
    assert extract_username("Ольга @malintesso") == "malintesso"
    assert extract_username("Ольга") is None


def test_parse_ledger_only_keeps_paid_positive_rows(tmp_path: Path) -> None:
    source = tmp_path / "ledger.tsv"
    source.write_text(
        "Месяц\tИмя\tОкончание\t\tДата оплаты\tНаписал\tОплатил\tЧек?\tИтого\tСумма\tЧек\tКомментарий\n"
        "Май\t@client_name\t\t\t01.05.2025\tTRUE\tTRUE\tTRUE\tСбер\t5 600 ₽\turl\tСопровождение\n"
        "\tНе платил\t\t\t\tFALSE\tFALSE\tFALSE\t\t9 900 ₽\t\t\n",
        encoding="utf-8",
    )
    rows = parse_ledger(source)
    assert len(rows) == 1
    assert rows[0].payer_name == "@client_name"
    assert rows[0].amount == Decimal("5600")
    assert rows[0].paid_at is not None
