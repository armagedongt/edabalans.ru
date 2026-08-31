from __future__ import annotations


STAGE_BY_PLACEMENT = {
    "day-1-offer": "early",
    "day-2-offer": "early",
    "recipes-part-1-gate": "early",
    "recipes-part-2-gate": "second",
    "closing-review": "review",
    "post-review": "last_week",
    # Legacy names stay valid for already published embeds and signed links.
    "day-15-offer": "early",
    "day-17-offer": "second",
    "day-19-offer": "review",
    "day-21-offer": "last_week",
}

WINDOW_START_PLACEMENTS = {
    "early": {"recipes-part-1-gate", "day-15-offer"},
    "second": {"recipes-part-2-gate", "day-17-offer"},
    "review": {"closing-review", "day-19-offer"},
}

WINDOW_START_EVENTS = {
    "early": "recipes_part_1_offer_opened",
    "second": "recipes_part_2_offer_opened",
    "review": "day_19_offer_opened",
}

OFFER_STAGE_DURATIONS = {
    "early": 72,
    "second": 72,
    "review": 72,
    "last_week": 168,
    "standard": None,
}

PASSIVE_OFFER_PLACEMENTS = {
    "day-1-offer",
    "day-2-offer",
    "day-21-offer",
    "post-review",
    "offers-hub",
}

OFFER_STAGE_ADMIN_RULES = {
    "early": "День 6 запускает 72 часа; дни 7–8 показывают тот же срок без продления.",
    "second": "День 14 запускает 72 часа; дни 15–16 показывают тот же срок без продления.",
    "review": "День 19 запускает 72 часа и сразу фиксирует следующую семидневную ступень.",
    "last_week": "Автоматически начинается в review.expires_at и длится 168 часов; финальный день 20 только показывает остаток.",
    "standard": "Автоматически включается после last_week.expires_at; срока и скидки нет.",
}

EMBED_PLACEMENTS = tuple(STAGE_BY_PLACEMENT) + ("offers-hub",)
