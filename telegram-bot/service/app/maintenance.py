from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Contact, TrackingEvent


MAINTENANCE_CONTENT_CODE = "tpl_maintenance_notice"
MAINTENANCE_WAITLIST_STATUS = "maintenance_waitlist"
DEFAULT_MAINTENANCE_MESSAGE = (
    "<b>Бот временно на небольшом ремонте</b> 🛠\n\n"
    "Я сейчас переношу сюда материалы и обновляю программу. "
    "Я уже сохранил, что вы заходили — повторно нажимать Start не нужно.\n\n"
    "В ближайшие пару дней всё доделаю и сам пришлю вам сообщение, когда бот снова будет готов.\n\n"
    "Если у вас есть вопрос или нужен доступ к уже купленным материалам, "
    "напишите мне: @FitnessSergey"
)


def allowed_telegram_ids(raw_value: str) -> frozenset[str]:
    return frozenset(part.strip() for part in raw_value.split(",") if part.strip())


def maintenance_allows(maintenance_mode: bool, raw_allowed_ids: str, telegram_user_id: str) -> bool:
    return not maintenance_mode or str(telegram_user_id) in allowed_telegram_ids(raw_allowed_ids)


def record_maintenance_contact(
    session: Session,
    contact: Contact,
    update_id: str,
    interaction_type: str,
    metadata: dict | None = None,
) -> None:
    contact.status = MAINTENANCE_WAITLIST_STATUS
    session.add(TrackingEvent(
        contact_id=contact.id,
        user_id=contact.user_id,
        telegram_user_id=contact.telegram_user_id,
        event_type="maintenance_contact",
        deduplication_key=f"maintenance:{update_id}",
        metadata_json={"interaction_type": interaction_type, **(metadata or {})},
    ))
