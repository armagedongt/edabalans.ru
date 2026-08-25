"""Create a local, fake-data database for visual master-class screen checks."""

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./masterclass_preview.db")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.database import Base, SessionLocal, engine
from app.models import OfferStage, Resource, User, UserAccess, UserEmail


STAGES = (
    ("early", "Первое предложение", 72, {"single": 2900, "bundle": {"1": 1900, "2": 3900, "3": 5900, "4": 7900}, "site_short": {"consultation_addon": 7000}}),
    ("second", "После второй части рецептов", 72, {"single": 3300, "bundle": {"1": 2500, "2": 4900, "3": 7400, "4": 9900}, "site_short": {"consultation_addon": 7000}}),
    ("review", "Саморевью", 72, {"single": 3500, "consultation": 7500, "bundle": {"1": 2900, "2": 5700, "3": 8500, "4": 11300}, "site_short": {"consultation_addon": 7200}}),
    ("last_week", "Последняя неделя", 168, {"single": 3800, "consultation": 8400, "bundle": {"1": 3600, "2": 7000, "3": 10400, "4": 13800}, "site_short": {"consultation_addon": 7900}}),
    ("standard", "Обычные цены", None, {"single": 3900, "consultation": 8900, "bundle": {"1": 3900, "2": 7800, "3": 11700, "4": 15600}, "site_short": {}}),
)


def main() -> None:
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        user = db.scalar(select(User).join(UserEmail).where(UserEmail.email_normalized == "preview@example.test"))
        if not user:
            user = User(display_name="Тестовый участник", status="active")
            db.add(user)
            db.flush()
            db.add(UserEmail(user_id=user.id, email_original="preview@example.test", email_normalized="preview@example.test", is_primary=True, source="preview"))
        masterclass = db.scalar(select(Resource).where(Resource.code == "ACCESS_MASTERCLASS"))
        if not masterclass:
            masterclass = Resource(code="ACCESS_MASTERCLASS", name="Мастер-класс", status="active")
            db.add(masterclass)
            db.flush()
        if not db.scalar(select(UserAccess).where(UserAccess.user_id == user.id, UserAccess.resource_id == masterclass.id)):
            db.add(UserAccess(user_id=user.id, resource_id=masterclass.id, source="preview", granted_at=datetime.now(timezone.utc)))
        for code, name, hours, pricing in STAGES:
            stage = db.scalar(select(OfferStage).where(OfferStage.code == code))
            if stage is None:
                db.add(OfferStage(code=code, name=name, duration_hours=hours, pricing=pricing, status="active"))
            else:
                stage.name = name
                stage.duration_hours = hours
                stage.pricing = pricing
        db.commit()
    print("Preview data ready: preview@example.test")


if __name__ == "__main__":
    main()
