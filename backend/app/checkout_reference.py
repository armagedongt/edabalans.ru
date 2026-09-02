from __future__ import annotations

from decimal import Decimal
import re
import uuid


CHECKOUT_REFERENCE_HEX_LENGTH = 8
LEGACY_CHECKOUT_REFERENCE = re.compile(r"^EB-([0-9a-fA-F]{32})(?:\s|$)")
SHORT_CHECKOUT_REFERENCE = re.compile(
    rf"(?:^|\s)№([0-9a-fA-F]{{{CHECKOUT_REFERENCE_HEX_LENGTH}}})(?:\s|$)"
)


def checkout_reference(checkout_id: uuid.UUID) -> str:
    """Return the compact reference shown to a customer in the Tilda cart."""
    return checkout_id.hex[:CHECKOUT_REFERENCE_HEX_LENGTH].upper()


def checkout_display_name(title: str, checkout_id: uuid.UUID) -> str:
    return f"{title} · №{checkout_reference(checkout_id)}"


def checkout_reference_from_product(raw_product: str) -> tuple[str, str] | None:
    """Parse current compact references while preserving permanent legacy support."""
    legacy_match = LEGACY_CHECKOUT_REFERENCE.match(raw_product)
    if legacy_match:
        return "full", legacy_match.group(1).lower()
    short_match = SHORT_CHECKOUT_REFERENCE.search(raw_product)
    if short_match:
        return "short", short_match.group(1).lower()
    return None


def tilda_order_command(title: str, checkout_id: uuid.UUID, amount: Decimal | int) -> str:
    clean_title = re.sub(r"[=:#\n\r]+", " ", title).strip()
    amount_text = format(Decimal(amount), "f").rstrip("0").rstrip(".") or "0"
    return f"#order:{checkout_display_name(clean_title, checkout_id)}={amount_text}"
