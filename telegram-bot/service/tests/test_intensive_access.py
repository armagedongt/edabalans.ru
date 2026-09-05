import hashlib
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

from sqlalchemy.orm import Session

from app.database import Base, make_engine
from app.intensive_access import (
    PURPOSE,
    create_intensive_access_link,
    get_or_create_intensive_access_link,
)
from app.models import CrmUser, MessengerLinkToken


def test_intensive_link_is_personal_platform_bound_and_long_lived(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'intensive-access.sqlite'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        user = CrmUser(display_name="Участник", status="active", data_origin="native")
        session.add(user)
        session.flush()
        issued = datetime(2026, 9, 4, tzinfo=UTC)
        telegram_url, row = create_intensive_access_link(
            session,
            user_id=user.id,
            platform="telegram",
            public_url="https://go.похудение-это-есть.рф/i",
            now=issued,
        )
        session.commit()

        parsed = urlparse(telegram_url)
        query = parse_qs(parsed.query)
        token = parsed.path.rsplit("/", 1)[-1]
        assert "from" not in query
        assert parsed.path == f"/i/{token}"
        assert row.user_id == user.id
        assert row.platform == "telegram"
        assert row.purpose == PURPOSE
        assert row.consumed_at is None
        assert row.token_hash == hashlib.sha256(token.encode("ascii")).hexdigest()
        assert row.expires_at.year == 2126


def test_max_link_uses_same_contract_with_max_source(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'intensive-max.sqlite'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        user = CrmUser(display_name="Участник", status="active", data_origin="native")
        session.add(user)
        session.flush()
        max_url, row = create_intensive_access_link(
            session,
            user_id=user.id,
            platform="max",
            public_url="https://go.похудение-это-есть.рф/i",
        )
        assert "from" not in parse_qs(urlparse(max_url).query)
        assert row.platform == "max"


def test_reuses_same_recoverable_link_for_telegram_menu(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'intensive-menu.sqlite'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        user = CrmUser(display_name="Участник", status="active", data_origin="native")
        session.add(user)
        session.flush()

        first_url, first_row = get_or_create_intensive_access_link(
            session,
            user_id=user.id,
            platform="telegram",
            public_url="https://go.похудение-это-есть.рф/i",
        )
        second_url, second_row = get_or_create_intensive_access_link(
            session,
            user_id=user.id,
            platform="telegram",
            public_url="https://go.похудение-это-есть.рф/i",
        )

        assert first_url == second_url
        assert first_row.id == second_row.id
        assert session.query(MessengerLinkToken).count() == 1
