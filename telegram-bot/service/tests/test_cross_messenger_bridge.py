from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.cross_messenger_bridge import (
    mapped_max_message,
    mapped_telegram_message,
    max_pair,
    mirror_text,
    telegram_pair,
)
from app.database import Base
from app.models import MessagingBridgeMessage, MessagingBridgePair


def make_session() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_mirror_text_marks_source_without_exposing_profile_data():
    assert mirror_text("telegram", "Вика <admin>", "Тарелка <готова>") == (
        "<b>Из Telegram · Вика &lt;admin&gt;</b>\nТарелка &lt;готова&gt;"
    )


def test_pair_lookup_uses_only_enabled_chat_pairs():
    with make_session() as session:
        active = MessagingBridgePair(
            key="sprint-test",
            status="active",
            telegram_channel_id="-10001",
            max_channel_id="101",
            telegram_practice_chat_id="-10002",
            max_practice_chat_id="102",
        )
        paused = MessagingBridgePair(
            key="paused",
            status="paused",
            telegram_channel_id="-10003",
            max_channel_id="103",
            telegram_practice_chat_id="-10004",
            max_practice_chat_id="104",
        )
        session.add_all((active, paused))
        session.commit()

        assert telegram_pair(session, "-10002").id == active.id
        assert max_pair(session, "101").id == active.id
        assert telegram_pair(session, "-10004") is None
        assert max_pair(session, "103") is None


def test_message_mapping_finds_parent_by_each_platform_id():
    with make_session() as session:
        pair = MessagingBridgePair(
            key="main",
            status="test",
            telegram_channel_id="-10001",
            max_channel_id="101",
            telegram_practice_chat_id="-10002",
            max_practice_chat_id="102",
        )
        session.add(pair)
        session.flush()
        message = MessagingBridgeMessage(
            pair_id=pair.id,
            kind="practice",
            telegram_message_id="22",
            max_message_id="max-22",
            source_platform="telegram",
            source_author_name="Вика",
        )
        session.add(message)
        session.commit()

        assert mapped_telegram_message(session, pair.id, "22").id == message.id
        assert mapped_max_message(session, pair.id, "max-22").id == message.id
