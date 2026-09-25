from datetime import datetime

from sqlalchemy.orm import Session

from app.masterclass_routes import course_event, preferred_messenger_account, queue_notification
from app.models import User


def reveal_metabolism(db: Session, user: User, now: datetime) -> None:
    """Reuse the application reveal/menu and exact-recipient delivery used by DQS."""
    event = course_event(
        db, user.id, "app:metabolism:revealed", "app_revealed_metabolism",
        placement="calories-expenditure-material",
        details={"app_code": "metabolism", "course_code": "calories"},
    )
    account = preferred_messenger_account(db, user.id)
    if account:
        queue_notification(
            db, user.id, event, "metabolism_app_link", now,
            content_code="tpl_postpurchase_metabolism_app_link",
            payload={
                "target_platform": account.platform,
                "target_messenger_account_id": str(account.id),
                "target_platform_user_id": account.platform_user_id,
            },
        )
