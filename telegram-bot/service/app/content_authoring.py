from __future__ import annotations

import re
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.content_formatting import SUPPORTED_SOURCE_FORMATS, is_placeholder_text, validate_telegram_html
from app.masterclass_triggers import TRIGGERS
from app.models import ContentItem, Sequence, SequenceStep, SequenceVersion


START_ONLY_CONTENT_CODES = {
    "tpl_maintenance_notice",
    "tpl_start_has_masterclass",
    "tpl_start_intensive_waiting",
    "tpl_start_intensive_complete",
}
START_CONTEXT = {
    "tpl_maintenance_notice": ("Источник и факт покупки определены", "Стоп до окончания ремонта"),
    "tpl_start_has_masterclass": ("Подтверждён доступ к мастер-классу", "Стоп; Welcome не запускается"),
    "tpl_start_intensive_waiting": ("Найден активный Welcome run", "Стоп; расписание продолжает работать"),
    "tpl_start_intensive_complete": ("Доставлен четвёртый день интенсива", "Стоп; интенсив не перезапускается"),
}
SILENT_EVENTS = {
    "owner_closing_review": "Внутренняя задача владельцу; клиентское сообщение не требуется.",
    "dqs_support": "Архивное событие без автоматической клиентской отправки.",
}
ALLOWED_VARIABLES_BY_CONTENT_CODE = {
    "tpl_start_intensive_waiting": {"next_message_at", "wait_interval", "channel_link"},
    "tpl_postpurchase_identity": {"email", "telegram_username", "masterclass_tariff", "purchase_date", "account_url", "questionnaire_formatted"},
    "tpl_postpurchase_current_diet": {"current_diet_formatted"},
    "tpl_postpurchase_day_unopened": {"day_number", "day_title", "day_url"},
    "tpl_postpurchase_tempo_late": {"day_number", "day_title", "day_url"},
    "tpl_postpurchase_recipes_missing": {"offers_url", "offer_expires_at"},
    "tpl_postpurchase_recipes_owned": {"offers_url"},
    "tpl_postpurchase_review_no_consultation": {"offers_url", "offer_expires_at"},
    "tpl_postpurchase_final_offer": {"offers_url"},
}


def template_variables(body: str) -> list[str]:
    return sorted(set(re.findall(r"{{\s*([a-zA-Z0-9_]+)\s*}}", body or "")))


def allowed_variables(content_code: str) -> list[str]:
    return sorted(ALLOWED_VARIABLES_BY_CONTENT_CODE.get(content_code, set()))


def content_usages(session: Session) -> dict[str, list[dict]]:
    usages: dict[str, list[dict]] = defaultdict(list)
    sequences = list(session.scalars(select(Sequence).where(Sequence.status != "archived")))
    for sequence in sequences:
        version = session.scalar(
            select(SequenceVersion)
            .where(SequenceVersion.sequence_id == sequence.id)
            .order_by(
                (SequenceVersion.status == "published").desc(),
                SequenceVersion.version_no.desc(),
            )
        )
        if not version:
            continue
        steps = session.execute(
            select(SequenceStep, ContentItem)
            .outerjoin(ContentItem, ContentItem.id == SequenceStep.content_item_id)
            .where(SequenceStep.sequence_version_id == version.id, SequenceStep.enabled.is_(True))
            .order_by(SequenceStep.position)
        ).all()
        for index, (step, content) in enumerate(steps):
            if step.kind not in {"MESSAGE", "PHOTO", "VIDEO", "VIDEO_NOTE", "VOICE"}:
                continue
            content_key = content.code if content else f"__missing__:{sequence.code}:{step.step_key}"
            usages[content_key].append(
                {
                    "kind": "sequence",
                    "module": sequence.code,
                    "version": version.version_no,
                    "step": step.step_key,
                    "position": step.position,
                    "step_kind": step.kind,
                    "label": step.label,
                    "previous": steps[index - 1][0].label if index > 0 else "Вход в цепочку",
                    "next": steps[index + 1][0].label if index + 1 < len(steps) else "Выход из цепочки",
                }
            )
    for trigger in TRIGGERS:
        usages[trigger["content_code"]].append(
            {
                "kind": "trigger",
                "module": "postpurchase_masterclass",
                "trigger": trigger["trigger"],
                "step": trigger["step_key"],
                "condition": trigger["condition"],
                "recipient": trigger["recipient"],
                "previous": f"Событие: {trigger['trigger']}",
                "next": "Определяется модулем после покупки",
            }
        )
    for code in START_ONLY_CONTENT_CODES:
        previous, next_step = START_CONTEXT[code]
        usages[code].append({
            "kind": "start_router",
            "module": "start_attribution",
            "step": code.removeprefix("tpl_"),
            "previous": previous,
            "next": next_step,
        })
    return dict(usages)


def readiness(item: ContentItem, usages: list[dict] | None = None) -> tuple[str, list[str]]:
    issues: list[str] = []
    if not (item.purpose or "").strip() or not (item.writer_brief or "").strip():
        issues.append("missing_brief")
    if item.source_format not in SUPPORTED_SOURCE_FORMATS:
        issues.append("unsupported_format")
    else:
        try:
            validate_telegram_html(item.body_source or "")
        except ValueError:
            issues.append("invalid_html")
    media_only = bool(item.media_kind == "video_note" and (item.media_path or item.telegram_file_id))
    if is_placeholder_text(item.body_source) and not media_only:
        issues.append("placeholder")
    unknown = set(template_variables(item.body_source)) - set(allowed_variables(item.code))
    if unknown:
        issues.append("unknown_variables")
    media_step_required = any(
        usage.get("step_kind") in {"PHOTO", "VIDEO", "VIDEO_NOTE", "VOICE"}
        for usage in (usages or [])
    )
    if (item.media_kind or media_step_required) and not (item.media_path or item.telegram_file_id):
        issues.append("missing_media")
    if (item.editorial_status or "needs_writing") == "approved" and item.status != "published":
        issues.append("runtime_not_published")
    status = item.editorial_status or "needs_writing"
    if "placeholder" in issues:
        status = "placeholder"
    elif "missing_brief" in issues:
        status = "needs_writing"
    return status, issues


def authoring_payload(item: ContentItem, usages: list[dict]) -> dict:
    current_status, issues = readiness(item, usages)
    return {
        "id": item.id,
        "code": item.code,
        "title": item.title,
        "purpose": item.purpose,
        "writer_brief": item.writer_brief,
        "body_source": item.body_source,
        "html_source": item.body_source,
        "source_format": item.source_format,
        "runtime_status": item.status,
        "editorial_status": current_status,
        "content_version": item.content_version,
        "media_kind": item.media_kind,
        "media_path": item.media_path,
        "labels": item.labels,
        "variables": template_variables(item.body_source),
        "allowed_variables": allowed_variables(item.code),
        "usages": usages,
        "issues": issues,
        "runtime_readiness": "ready" if current_status == "approved" and not issues else "blocked" if issues else "not_approved",
    }


def audit_content(session: Session) -> dict:
    usages = content_usages(session)
    content_codes = [code for code in usages if not code.startswith("__missing__:")]
    existing = {
        item.code: item
        for item in session.scalars(select(ContentItem).where(ContentItem.code.in_(content_codes)))
    }
    items: list[dict] = []
    for code in sorted(usages):
        item = existing.get(code)
        if not item:
            items.append(
                {
                    "code": None if code.startswith("__missing__:") else code,
                    "missing_reference": code,
                    "editorial_status": "missing_content",
                    "issues": ["missing_content"],
                    "usages": usages[code],
                }
            )
        else:
            items.append(authoring_payload(item, usages[code]))
    counts: dict[str, int] = defaultdict(int)
    for item in items:
        counts[item["editorial_status"]] += 1
    writer_queue = [
        item for item in items
        if item["editorial_status"] in {"placeholder", "needs_writing", "draft"}
    ]
    return {
        "counts": dict(sorted(counts.items())),
        "total": len(items),
        "items": items,
        "writer_queue": writer_queue,
        "approved_skipped": sum(item.get("editorial_status") == "approved" for item in items),
        "runtime_blocked": sum(item.get("runtime_readiness") == "blocked" for item in items),
        "intentionally_silent": [
            {"event": event, "reason": reason} for event, reason in SILENT_EVENTS.items()
        ],
    }
