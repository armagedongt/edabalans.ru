from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.calorie_application_delivery import (
    APPROVED_TEXT, APP_URL, CONTENT_CODE, SEQUENCE_CODE, STEP_KEY,
    seed_calorie_application_delivery,
)
from app.masterclass_dispatch import dispatch_due_masterclass_notifications
from app.models import ContentItem, MasterclassNotification, Sequence, SequenceStep
from test_masterclass_dispatch import (
    FakeSender, add_contact_and_content, explicit_telegram_payload, session_factory,
)


def test_seed_keeps_approved_message_and_graph_on_repeat(tmp_path):
    with session_factory(tmp_path) as db:
        seed_calorie_application_delivery(db)
        db.flush()
        item = db.scalar(select(ContentItem).where(ContentItem.code == CONTENT_CODE))
        assert item.body_source == APPROVED_TEXT
        assert item.editorial_status == "approved"
        item.body_source = "Редактор изменил сообщение"
        seed_calorie_application_delivery(db)
        db.flush()
        assert item.body_source == "Редактор изменил сообщение"
        assert db.scalar(select(func.count(Sequence.id)).where(Sequence.code == SEQUENCE_CODE)) == 1
        assert db.scalar(select(func.count(SequenceStep.id)).where(SequenceStep.step_key == STEP_KEY)) == 1


@pytest.mark.parametrize("access", [True, False])
@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_calculator_dispatch_requires_access_and_exact_recipient(tmp_path, access, platform):
    with session_factory(tmp_path) as db:
        add_contact_and_content(db)
        seed_calorie_application_delivery(db)
        user_id = "11111111-1111-1111-1111-111111111111"
        payload = explicit_telegram_payload(db, user_id)
        notification = MasterclassNotification(
            user_id=user_id, notification_kind="metabolism_app_link", content_code=CONTENT_CODE,
            deduplication_key="test-calorie-calculator", due_at=datetime.now(UTC)-timedelta(seconds=1),
            status="pending", payload=payload,
        )
        db.add(notification)
        db.commit()
        sender = FakeSender()
        result = dispatch_due_masterclass_notifications(
            db, sender, "", lambda *_: {"ACCESS_CALORIES"} if access else {"ACCESS_MASTERCLASS"},
            notification_kinds={"metabolism_app_link"}, platform=platform,
        )
        assert result["sent"] == (1 if access and platform == "telegram" else 0)
        if access and platform == "telegram":
            assert sender.sent == [("42", CONTENT_CODE, APPROVED_TEXT)]
            assert sender.configurations == [{"buttons": [{"text": "Открыть калькулятор", "url": APP_URL}]}]
            again = dispatch_due_masterclass_notifications(
                db, sender, "", lambda *_: {"ACCESS_CALORIES"}, notification_kinds={"metabolism_app_link"},
            )
            assert again["sent"] == 0
            assert len(sender.sent) == 1
        elif platform == "telegram":
            assert notification.status == "skipped"
