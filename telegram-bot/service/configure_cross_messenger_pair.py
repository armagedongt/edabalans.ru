from __future__ import annotations

import argparse

from sqlalchemy import select

from app.database import SessionLocal
from app.models import MessagingBridgePair


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Create or update one Telegram/MAX channel-and-practice-chat pair.",
    )
    result.add_argument("--key", required=True, help="Stable internal key, for example sprint-test")
    result.add_argument("--telegram-channel-id", required=True)
    result.add_argument("--max-channel-id", required=True)
    result.add_argument("--telegram-practice-chat-id", required=True)
    result.add_argument("--max-practice-chat-id", required=True)
    result.add_argument("--status", choices=("draft", "test", "active", "paused"), default="test")
    return result


def main() -> None:
    args = parser().parse_args()
    with SessionLocal() as session:
        pair = session.scalar(select(MessagingBridgePair).where(MessagingBridgePair.key == args.key))
        values = {
            "status": args.status,
            "telegram_channel_id": str(args.telegram_channel_id),
            "max_channel_id": str(args.max_channel_id),
            "telegram_practice_chat_id": str(args.telegram_practice_chat_id),
            "max_practice_chat_id": str(args.max_practice_chat_id),
        }
        if pair is None:
            pair = MessagingBridgePair(key=args.key, **values)
            session.add(pair)
        else:
            for field, value in values.items():
                setattr(pair, field, value)
        session.commit()
        print({"ok": True, "key": pair.key, "status": pair.status, "pair_id": pair.id})


if __name__ == "__main__":
    main()
