import hashlib
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

from sqlalchemy.orm import Session

from app.database import Base, make_engine
from app.intensive_access import (
    PURPOSE,
    create_intensive_access_link,
    get_or_create_intensive_access_link,
    intensive_token,
    personal_tracking_values,
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
            public_url="https://edabalans.ru/intensive",
            now=issued,
        )
        session.commit()

        parsed = urlparse(telegram_url)
        query = parse_qs(parsed.query)
        token = query["i"][0]
        assert len(token) == 9
        assert query == {"i": [token], "from": ["tg"], "entry": ["bot"]}
        assert parsed.path == "/intensive/start"
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
            public_url="https://edabalans.ru/intensive",
        )
        assert parse_qs(urlparse(max_url).query) == {
            "i": [intensive_token(row.id)],
            "from": ["max"],
            "entry": ["bot"],
        }
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
            public_url="https://edabalans.ru/intensive",
        )
        second_url, second_row = get_or_create_intensive_access_link(
            session,
            user_id=user.id,
            platform="telegram",
            public_url="https://edabalans.ru/intensive",
        )

        assert first_url == second_url
        assert first_row.id == second_row.id
        assert session.query(MessengerLinkToken).count() == 1


def test_personal_destinations_reuse_one_opaque_code(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'personal-destinations.sqlite'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        user = CrmUser(display_name="Участник", status="active", data_origin="native")
        session.add(user)
        session.flush()

        values = personal_tracking_values(
            session,
            user_id=user.id,
            platform="telegram",
            public_url="https://edabalans.ru/intensive",
            channel_post_numbers={260, 732, 734},
        )

        intensive_code = parse_qs(urlparse(values["personal_intensive_url"]).query)["i"][0]
        masterclass_code = urlparse(values["personal_masterclass_url"]).path.rsplit("/", 1)[-1]
        post_code = urlparse(values["personal_channel_post_260_url"]).path.rsplit("/", 1)[-1]
        assert intensive_code == masterclass_code == post_code
        assert values["personal_intensive_url"] == (
            f"https://edabalans.ru/intensive/start?i={intensive_code}&from=tg&entry=bot"
        )
        assert values["personal_channel_post_732_url"].endswith(f"/p/732/{intensive_code}")
        assert values["personal_channel_post_734_url"].endswith(f"/p/734/{intensive_code}")
        assert session.query(MessengerLinkToken).count() == 1


def test_intensive_start_path_is_not_duplicated(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'intensive-start.sqlite'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        user = CrmUser(display_name="Участник", status="active", data_origin="native")
        session.add(user)
        session.flush()

        url, _ = create_intensive_access_link(
            session,
            user_id=user.id,
            platform="max",
            public_url="https://edabalans.ru/intensive/start",
        )

        assert urlparse(url).path == "/intensive/start"
