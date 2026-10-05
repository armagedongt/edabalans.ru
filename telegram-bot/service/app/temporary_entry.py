"""Temporary article entry for both messengers; no scheduled marketing."""
from __future__ import annotations

from types import SimpleNamespace
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import Broadcast, Contact, ContentItem, CrmTag, CrmUser, CrmUserTag, TrackingEvent, Sequence, SequenceVersion, SequenceRun

CONTENT_CODE = "tpl_temporary_intensive_entry"
POOL_CODE = "temporary_intensive_entry_20261005"
POOL_NAME = "Временный вход — единый интенсив"
BLOCKED_STATUSES = {"blocked", "stopped"}
MARKETING_CODES = {"start_attribution_entry", "welcome_intensive", "prepurchase_nurture", "prepurchase_masterclass", "postmasterclass_nurture"}
ENTRY_RULES = (("blocked", "silent"), ("has_masterclass", "normal"), ("stop_presale", "silent"))
BODY = (
    "<b>Посмотрите на своё питание и похудение совершенно другими глазами — развидеть это потом будет невозможно!</b>\n\n"
    "Похудеть — не трудно! Трудно — сделать так, чтобы не приходилось худеть каждый год заново!\n\n"
    "Посмотрите на похудение не как на преодоление себя, а как на набор навыков и привычек. "
    "Чем больше навыков и здоровых пищевых привычек вы освоите, тем легче будет похудение "
    "и тем меньше понадобится силы воли.\n\n"
    'Чтобы познакомиться с моим подходом, прочитайте статью <a href="{{personal_intensive_url}}">«Как сделать похудение проще!?»</a>.\n\n'
    "<b>Хватит откладывать, начните прямо сейчас 👇</b>"
)


def pause_marketing(session: Session) -> int:
    runs = list(session.scalars(select(SequenceRun).join(
        SequenceVersion, SequenceVersion.id == SequenceRun.sequence_version_id,
    ).join(Sequence, Sequence.id == SequenceVersion.sequence_id).where(
        Sequence.code.in_(MARKETING_CODES), SequenceRun.status.in_(("active", "waiting", "error")),
    )))
    for run in runs:
        run.status = "paused"
        run.context = {**(run.context or {}), "paused_reason": "temporary_intensive_entry"}
    for broadcast in session.scalars(select(Broadcast).where(Broadcast.status.in_(("scheduled", "sending")))):
        broadcast.status = "paused"
    return len(runs)


def temporary_response(session: Session, contact: Contact, sender, receipt_id: str, platform: str, public_url: str) -> dict | None:
    decision = entry_decision(session, contact)
    if decision == "normal":
        return None
    if decision == "silent":
        session.commit()
        return {"ok": True, "temporary_entry": True, "excluded": True}
    return send_temporary_entry(session, contact, sender, receipt_id, platform, public_url)


def seed_temporary_entry(session: Session) -> None:
    if not session.scalar(select(CrmTag).where(CrmTag.code == POOL_CODE)):
        session.add(CrmTag(code=POOL_CODE, name=POOL_NAME, category="manual", status="active"))
    if not session.scalar(select(ContentItem).where(ContentItem.code == CONTENT_CODE)):
        session.add(ContentItem(
            code=CONTENT_CODE, title="Временный вход — статья о похудении", body_source=BODY,
            source_format="telegram_html", editorial_status="approved", status="published",
            purpose="Направить входящего в единую статью без старой рассылки.",
            writer_brief="Текст согласован Сергеем 05.10.2026. Без оглавления, видео и скидки. Одна ссылка и кнопка «Читать статью».",
        ))
    session.flush()


def entry_decision(session: Session, contact: Contact) -> str:
    from app.engine import has_paid_product
    from app.start_router import MASTERCLASS_CODES
    user = session.get(CrmUser, contact.user_id) if contact.user_id else None
    facts = {
        "blocked": contact.status in BLOCKED_STATUSES or bool(user and user.status == "blocked"),
        "stop_presale": bool(contact.user_id and session.scalar(
            select(CrmUserTag.id).join(CrmTag, CrmTag.id == CrmUserTag.tag_id).where(
                CrmUserTag.user_id == contact.user_id, CrmTag.status == "active",
                CrmTag.name == "Стоп - До покупки мастер-класса",
            )
        )),
    }
    for fact, decision in ENTRY_RULES:
        if fact == "has_masterclass":
            facts[fact] = has_paid_product(session, contact, MASTERCLASS_CODES, "masterclass")
        if facts.get(fact):
            return decision
    return "article"


def send_temporary_entry(session: Session, contact: Contact, sender, receipt_id: str, platform: str, public_url: str) -> dict:
    from app.content_formatting import content_is_runtime_ready, replace_template_values
    from app.intensive_access import get_or_create_intensive_access_link
    item = session.scalar(select(ContentItem).where(ContentItem.code == CONTENT_CODE))
    tag = session.scalar(select(CrmTag).where(CrmTag.code == POOL_CODE, CrmTag.status == "active"))
    if not item or item.status != "published" or not tag or not contact.user_id:
        raise RuntimeError("Temporary entry content or pool is unavailable")
    if not content_is_runtime_ready(item):
        raise RuntimeError("Temporary entry content is not approved and ready")
    # Two messengers can contact the same CRM user concurrently.
    session.scalar(select(CrmUser).where(CrmUser.id == contact.user_id).with_for_update())
    if not session.scalar(select(CrmUserTag.id).where(CrmUserTag.user_id == contact.user_id, CrmUserTag.tag_id == tag.id)):
        session.add(CrmUserTag(user_id=contact.user_id, tag_id=tag.id, source="system"))
    url, _ = get_or_create_intensive_access_link(session, user_id=contact.user_id, platform=platform, public_url=public_url)
    event = TrackingEvent(
        contact_id=contact.id, user_id=contact.user_id, telegram_user_id=contact.telegram_user_id,
        event_type="temporary_intensive_entry", deduplication_key=f"temporary_entry:{receipt_id}",
        metadata_json={"messenger": platform, "delivery_status": "pending", "tag_id": tag.id},
    )
    session.add(event)
    # Keep the receipt and pool durable before sending. A lost API response must
    # not make a replayed webhook send the same invitation again.
    session.commit()
    try:
        message_id = sender.send_content(contact.chat_id, SimpleNamespace(
            code=item.code, source_format="telegram_html",
            body_source=replace_template_values(item.body_source, {"personal_intensive_url": url}),
            media_kind=None, media_path=None, telegram_file_id=None,
        ), {"buttons": [{"text": "Читать статью", "url": url}], "link_preview": False})
    except Exception:
        event.metadata_json = {**event.metadata_json, "delivery_status": "uncertain"}
        session.commit()
        raise
    event.metadata_json = {**event.metadata_json, "delivery_status": "sent", "message_id": str(message_id)}
    session.commit()
    return {"ok": True, "temporary_entry": True}
