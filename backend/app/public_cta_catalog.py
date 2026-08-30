"""Stable public CTA facts owned by product and Telegram modules."""
from __future__ import annotations

from dataclasses import dataclass

from app.intensive_public_cta import INTENSIVE_PUBLIC_CTA
from app.masterclass_public_cta import MASTERCLASS_PUBLIC_CTA
from app.telegram_public_cta import TELEGRAM_PUBLIC_CTA


@dataclass(frozen=True)
class PublicCta:
    key: str
    owner_module: str
    eyebrow: str
    title: str
    copy: str
    button_label: str
    destination: str
    tracking_key: str


PUBLIC_CTAS = {
    facts["key"]: PublicCta(**facts)
    for facts in (INTENSIVE_PUBLIC_CTA, MASTERCLASS_PUBLIC_CTA, TELEGRAM_PUBLIC_CTA)
}


def public_cta(key: str) -> PublicCta | None:
    return PUBLIC_CTAS.get(key)
