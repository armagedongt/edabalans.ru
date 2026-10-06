"""Temporary article entry for both messengers; no scheduled marketing."""
from __future__ import annotations

from types import SimpleNamespace
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import Broadcast, Contact, ContentItem, CrmTag, CrmUser, CrmUserTag, TrackingEvent, Sequence, SequenceVersion, SequenceRun

CONTENT_CODE = "tpl_temporary_intensive_entry"
NAVIGATION_CODE = "tpl_onepage_entry_navigation"
VIDEO_PATH = "/app/media/intensive-entry-2026-09-13-57s80.mp4"
BUTTON_TEXT = "Читать прямо сейчас"
POOL_CODE = "temporary_intensive_entry_20261005"
POOL_NAME = "Временный вход — единый интенсив"
BLOCKED_STATUSES = {"blocked", "stopped"}
MARKETING_CODES = {"start_attribution_entry", "welcome_intensive", "prepurchase_nurture", "prepurchase_masterclass", "postmasterclass_nurture"}
ENTRY_RULES = (("blocked", "silent"), ("has_masterclass", "normal"), ("stop_presale", "silent"))
# Existing canonical CRM code; the visible name can be edited independently.
STOP_TAG_CODE = "rule2_стоп_до_покупки_мастер_класса_64631f8d"
LEGACY_BODY = (
    "<b>Посмотрите на своё питание и похудение совершенно другими глазами — развидеть это потом будет невозможно!</b>\n\n"
    "Похудеть — не трудно! Трудно — сделать так, чтобы не приходилось худеть каждый год заново!\n\n"
    "Посмотрите на похудение не как на преодоление себя, а как на набор навыков и привычек. "
    "Чем больше навыков и здоровых пищевых привычек вы освоите, тем легче будет похудение "
    "и тем меньше понадобится силы воли.\n\n"
    'Чтобы познакомиться с моим подходом, прочитайте статью <a href="{{personal_intensive_url}}">«Как сделать похудение проще!?»</a>.\n\n'
    "<b>Хватит откладывать, начните прямо сейчас 👇</b>"
)
BODY = (
    "<b>Есть всего два типа людей, которые реально худеют (см. видео)!</b>\n\n"
    "Если вам трудно побороть тягу к сладкому, сложно переносить голод, заколебали срывы на диете и вообще не понятно, как полюбить долбанную здоровую еду — расслабьтесь!\n\n"
    "<b>Это НЕ ваша черта как личности!</b> Это просто недостаток навыков, как вести себя во время похудения!\n\n"
    "Я расскажу, что это за навыки, научу, как их освоить, покажу, как применять, и создам вокруг вас обстановку, чтобы эти навыки закрепились!\n\n"
    '✅ Начните с моей статьи <b><a href="{{personal_intensive_url}}">«Как сделать похудение проще!»</a></b>, в конце которой забирайте 4 задания, чтобы начать худеть по-новому уже сегодня!!'
)
NAVIGATION_BODY = (
    "📌 Навигация!\n\n"
    '<a href="https://t.me/Fitness_Talks">Telegram-канал</a> | <a href="https://max.ru/id230409966750_biz">Канал в MAX</a>\n\n'
    'Обязательно к прочтению: <a href="{{personal_intensive_url}}">«Что надо сделать, чтобы похудение стало проще, а силы воли надо было меньше!»</a>\n\n'
    "Нравится мой подход?👇\n\n"
    'Залетайте на Мастер-класс по изменению питания и пищевых привычек: <a href="{{personal_masterclass_url}}">похудение-это-есть.рф</a>\n\n'
    'По любым вопросам: <a href="https://t.me/Fitness_Talks">Telegram</a> /<a href="https://max.ru/u/f9LHodD0cOJjmbADdxMaO0UzEfR_55NRvOSwSuS3C6mWE5T27DPcpczbvEw"> MAX</a>'
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
    item = session.scalar(select(ContentItem).where(ContentItem.code == CONTENT_CODE))
    if not item:
        item = ContentItem(
            code=CONTENT_CODE, title="Вход — видео и единый интенсив", body_source=BODY,
            source_format="telegram_html", editorial_status="approved", status="published",
            media_kind="video", media_path=VIDEO_PATH,
            purpose="Выдать согласованное видео и персональную ссылку после навигации.",
            writer_brief="Дословный текст Сергея 07.10.2026. Кнопка «Читать прямо сейчас». Без кружка и без продолжения старой рассылки.",
        )
        session.add(item)
    elif item.body_source == LEGACY_BODY:
        # Replace only the unchanged approved placeholder, never later owner edits.
        item.body_source = BODY
        item.title = "Вход — видео и единый интенсив"
        item.media_kind = "video"
        item.media_path = VIDEO_PATH
        item.telegram_file_id = None
        item.content_version = (item.content_version or 0) + 1
        item.purpose = "Выдать согласованное видео и персональную ссылку после навигации."
        item.writer_brief = "Дословный текст Сергея 07.10.2026. Кнопка «Читать прямо сейчас»."
    if not session.scalar(select(ContentItem).where(ContentItem.code == NAVIGATION_CODE)):
        session.add(ContentItem(
            code=NAVIGATION_CODE, title="Вход — навигационный закреп", body_source=NAVIGATION_BODY,
            source_format="telegram_html", editorial_status="approved", status="published",
            purpose="Навигация перед видео; закрепить в Telegram, отключить превью.",
            writer_brief="Согласованный навигационный текст Сергея. Персональные ссылки на интенсив и Мастер-класс.",
        ))
    session.flush()


def entry_decision(session: Session, contact: Contact) -> str:
    from app.engine import has_paid_product
    from app.start_router import MASTERCLASS_CODES
    user = session.get(CrmUser, contact.user_id) if contact.user_id else None
    stop_tag = session.scalar(select(CrmTag).where(CrmTag.code == STOP_TAG_CODE))
    if stop_tag is None:
        stop_tag = session.scalar(select(CrmTag).where(CrmTag.name == "Стоп - До покупки мастер-класса", CrmTag.status == "active"))
    visited = set()
    while stop_tag and stop_tag.merged_into_tag_id and stop_tag.id not in visited:
        visited.add(stop_tag.id)
        stop_tag = session.get(CrmTag, stop_tag.merged_into_tag_id)
    facts = {
        "blocked": contact.status in BLOCKED_STATUSES or bool(user and user.status == "blocked"),
        "stop_presale": bool(contact.user_id and session.scalar(
            select(CrmUserTag.id).join(CrmTag, CrmTag.id == CrmUserTag.tag_id).where(
                CrmUserTag.user_id == contact.user_id, CrmTag.status == "active",
                CrmTag.id == stop_tag.id,
            )
        )) if stop_tag else False,
    }
    for fact, decision in ENTRY_RULES:
        if fact == "has_masterclass":
            facts[fact] = has_paid_product(session, contact, MASTERCLASS_CODES, "masterclass")
        if facts.get(fact):
            return decision
    return "article"


def send_temporary_entry(session: Session, contact: Contact, sender, receipt_id: str, platform: str, public_url: str) -> dict:
    from app.content_formatting import content_is_runtime_ready, replace_template_values
    from app.engine import personalized_delivery
    from app.intensive_access import get_or_create_intensive_access_link
    item = session.scalar(select(ContentItem).where(ContentItem.code == CONTENT_CODE))
    navigation = session.scalar(select(ContentItem).where(ContentItem.code == NAVIGATION_CODE))
    tag = session.scalar(select(CrmTag).where(CrmTag.code == POOL_CODE, CrmTag.status == "active"))
    if not item or not navigation or item.status != "published" or not tag or not contact.user_id:
        raise RuntimeError("Temporary entry content or pool is unavailable")
    if not content_is_runtime_ready(item) or not content_is_runtime_ready(navigation):
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
        nav_content, nav_config = personalized_delivery(session, contact, navigation, {
            "buttons": [{"text": "Перейти в канал", "url": "https://t.me/Fitness_Talks"}], "link_preview": False,
        })
        session.commit()
        navigation_id = sender.send_content(contact.chat_id, nav_content, nav_config)
        event.metadata_json = {**event.metadata_json, "navigation_message_id": str(navigation_id)}
        session.commit()
        if hasattr(sender, "pin_message"):
            sender.pin_message(contact.chat_id, navigation_id)
        video_content = SimpleNamespace(
            code=item.code, source_format="telegram_html",
            body_source=replace_template_values(item.body_source, {"personal_intensive_url": url}),
            media_kind=item.media_kind, media_path=item.media_path, telegram_file_id=item.telegram_file_id,
        )
        message_id = sender.send_content(contact.chat_id, video_content,
            {"buttons": [{"text": BUTTON_TEXT, "url": url}], "link_preview": False})
        if platform == "telegram" and video_content.telegram_file_id:
            item.telegram_file_id = video_content.telegram_file_id
    except Exception:
        event.metadata_json = {**event.metadata_json, "delivery_status": "uncertain"}
        session.commit()
        raise
    event.metadata_json = {**event.metadata_json, "delivery_status": "sent", "message_id": str(message_id)}
    session.commit()
    return {"ok": True, "temporary_entry": True}
