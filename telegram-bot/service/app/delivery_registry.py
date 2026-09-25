from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProducerContract:
    content_kind: str
    telegram_renderer: str
    max_renderer: str
    proactive: bool = True
    routing: str = "preferred"


PROACTIVE_PRODUCERS = {
    "sequence_message": ProducerContract("authored_post", "portable_html", "portable_html"),
    "scheduled_broadcast": ProducerContract("authored_post", "portable_html", "portable_html"),
    "messenger_identity": ProducerContract("technical_payload", "portable_html", "portable_html"),
    "messenger_questionnaire": ProducerContract("technical_payload", "portable_html", "portable_html"),
    "closing_review_copy": ProducerContract("technical_payload", "portable_html", "portable_html"),
    "current_diet_questionnaire": ProducerContract("technical_payload", "portable_html", "portable_html"),
    "dqs_app_link": ProducerContract(
        "technical_payload", "portable_html", "portable_html", routing="explicit_exact"
    ),
    "metabolism_app_link": ProducerContract(
        "technical_payload", "portable_html", "portable_html", routing="explicit_exact"
    ),
    "course_stalled_72h": ProducerContract("authored_post", "portable_html", "portable_html"),
    "course_day_unopened_18h": ProducerContract("authored_post", "portable_html", "portable_html"),
    "sales_last_chance_due": ProducerContract("authored_post", "portable_html", "portable_html"),
    "recipes_followup": ProducerContract("authored_post", "portable_html", "portable_html"),
}

EXCLUDED_PRODUCERS = {
    "owner_closing_review": "owner_alert",
    "dqs_support": "owner_or_reactive_service",
    "review_followup": "owner_or_non_delivery_state",
    "post_review_day_2": "owner_or_non_delivery_state",
    "post_review_day_4": "owner_or_non_delivery_state",
    "post_review_day_7": "owner_or_non_delivery_state",
}

PORTABLE_AUTHORED_LIMIT = 4096


def contract_for(kind: str) -> ProducerContract | None:
    return PROACTIVE_PRODUCERS.get(kind)


def validate_registry() -> None:
    for kind, contract in PROACTIVE_PRODUCERS.items():
        if contract.content_kind not in {"authored_post", "technical_payload"}:
            raise RuntimeError(f"invalid content_kind for {kind}")
        if not contract.telegram_renderer or not contract.max_renderer:
            raise RuntimeError(f"both renderers are required for {kind}")
        if contract.routing not in {"preferred", "explicit_exact"}:
            raise RuntimeError(f"invalid routing for {kind}")


def validate_body(kind: str, body: str) -> None:
    contract = contract_for(kind)
    if contract is None:
        if kind in EXCLUDED_PRODUCERS:
            return
        raise RuntimeError(f"proactive producer is not registered: {kind}")
    if contract.content_kind == "authored_post" and len(body) > PORTABLE_AUTHORED_LIMIT:
        raise RuntimeError(
            f"authored post exceeds the Telegram/MAX shared limit: {kind} ({len(body)})"
        )


validate_registry()
