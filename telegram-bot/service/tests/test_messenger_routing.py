from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.database import Base, make_engine
from app.messenger_resolver import preferred_destination
from app.delivery_registry import PROACTIVE_PRODUCERS, validate_body, validate_registry
from app.models import BotInstance, Contact, CrmMessengerAccount, CrmUser


def _session(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'routing.sqlite'}")
    Base.metadata.create_all(engine)
    return Session(engine)


def _linked(session: Session, *, user_id: str, platform: str, platform_user_id: str, preferred: bool):
    bot = BotInstance(
        code="max" if platform == "max" else "telegram",
        username=f"{platform}-bot",
        display_name=platform,
        token_env_name=f"{platform.upper()}_TOKEN",
        is_active=True,
    )
    session.add(bot)
    session.flush()
    contact = Contact(
        bot_instance_id=bot.id,
        user_id=user_id,
        telegram_user_id=platform_user_id,
        chat_id=platform_user_id,
        status="active",
    )
    account = CrmMessengerAccount(
        user_id=user_id,
        platform=platform,
        platform_user_id=platform_user_id,
        source="test",
        linked_at=datetime.now(UTC),
        is_deliverable=True,
        is_preferred=preferred,
    )
    session.add_all([contact, account])
    session.flush()
    return contact, account


def test_preferred_destination_uses_exact_selected_identity(tmp_path):
    with _session(tmp_path) as session:
        user = CrmUser(display_name="Client", status="active", data_origin="native")
        session.add(user)
        session.flush()
        _linked(session, user_id=user.id, platform="telegram", platform_user_id="tg-42", preferred=False)
        max_contact, max_account = _linked(
            session, user_id=user.id, platform="max", platform_user_id="max-84", preferred=True
        )
        session.commit()

        destination = preferred_destination(session, user.id)

        assert destination is not None
        assert destination.platform == "max"
        assert destination.account_id == max_account.id
        assert destination.contact_id == max_contact.id
        assert destination.platform_user_id == "max-84"


def test_preferred_destination_never_guesses_between_two_channels(tmp_path):
    with _session(tmp_path) as session:
        user = CrmUser(display_name="Client", status="active", data_origin="native")
        session.add(user)
        session.flush()
        _linked(session, user_id=user.id, platform="telegram", platform_user_id="tg-42", preferred=False)
        _linked(session, user_id=user.id, platform="max", platform_user_id="max-84", preferred=False)
        session.commit()

        assert preferred_destination(session, user.id) is None


def test_single_linked_channel_is_implicitly_usable(tmp_path):
    with _session(tmp_path) as session:
        user = CrmUser(display_name="Client", status="active", data_origin="native")
        session.add(user)
        session.flush()
        contact, account = _linked(
            session, user_id=user.id, platform="telegram", platform_user_id="tg-42", preferred=False
        )
        session.commit()

        destination = preferred_destination(session, user.id)

        assert destination is not None
        assert destination.account_id == account.id
        assert destination.contact_id == contact.id


def test_inactive_or_historical_identity_is_never_selected(tmp_path):
    with _session(tmp_path) as session:
        user = CrmUser(display_name="Client", status="active", data_origin="native")
        session.add(user)
        session.flush()
        contact, current = _linked(
            session, user_id=user.id, platform="telegram", platform_user_id="tg-current", preferred=True
        )
        historical = CrmMessengerAccount(
            user_id=user.id,
            platform="telegram",
            platform_user_id="tg-old",
            source="test",
            linked_at=datetime.now(UTC),
            is_deliverable=False,
            is_preferred=False,
        )
        session.add(historical)
        session.commit()

        contact.status = "blocked"
        session.commit()
        assert preferred_destination(session, user.id) is None

        contact.status = "active"
        current.is_deliverable = False
        current.is_preferred = False
        session.commit()
        assert preferred_destination(session, user.id) is None


def test_delivery_registry_requires_both_renderers_and_shared_authored_limit():
    validate_registry()
    assert PROACTIVE_PRODUCERS
    assert all(
        contract.telegram_renderer and contract.max_renderer
        for contract in PROACTIVE_PRODUCERS.values()
    )
    validate_body("course_stalled_72h", "короткий текст")
    try:
        validate_body("course_stalled_72h", "x" * 4097)
    except RuntimeError as exc:
        assert "shared limit" in str(exc)
    else:
        raise AssertionError("oversized authored post must fail validation")
