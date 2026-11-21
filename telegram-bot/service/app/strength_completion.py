"""Owner delivery for strength events, using the shared outbox and Telegram receipts."""
from datetime import UTC, datetime
import hashlib
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy.exc import IntegrityError

from app.models import OwnerPaymentAlertDelivery
from app.telegram import TelegramClient, TelegramError


def deliver_completion(session, notification, settings) -> None:
    role = (notification.payload or {}).get("delivery_role") or settings.strength_completion_bot_role
    tokens = {"product": settings.telegram_test_bot_token,
              "technical": settings.technical_telegram_bot_token,
              "finance": settings.finance_telegram_bot_token}
    token = tokens.get(role)
    recipients = list(dict.fromkeys(x.strip() for x in (
        settings.strength_completion_recipient_ids or settings.technical_telegram_recipient_ids).split(",") if x.strip()))
    if not token or not recipients or any(not x.isdigit() for x in recipients):
        raise RuntimeError("strength owner notification route is not configured")
    telegram = TelegramClient(token, proxy_url=settings.telegram_proxy_url,
                              api_base_url=settings.telegram_api_base_url,
                              gateway_token=settings.telegram_gateway_token)
    try:
        bot = telegram.call("getMe", {})
    except Exception:
        raise ConnectionError("strength notification bot check temporarily unavailable") from None
    bot_id = str(bot["id"])
    if bot_id != token.split(":", 1)[0]:
        raise RuntimeError("strength notification bot identity does not match configuration")
    payload = dict(notification.payload or {})
    if payload.get("delivery_bot_id") and payload["delivery_bot_id"] != bot_id:
        raise RuntimeError("strength notification bot changed during delivery")
    recipients = payload.get("delivery_recipients") or recipients
    payload.update(delivery_role=role, delivery_bot_id=bot_id,
                   delivery_bot_username=bot["username"], delivery_recipients=recipients)
    notification.payload = payload
    session.commit()
    message = payload["message_text"]
    digest = hashlib.sha256(message.encode()).hexdigest()
    deliveries = dict(payload.get("deliveries") or {})
    failures = []
    for recipient in recipients:
        receipt_id = str(uuid5(NAMESPACE_URL, f"strength-completion:{notification.id}:{bot_id}:{recipient}"))
        receipt = session.get(OwnerPaymentAlertDelivery, receipt_id)
        if receipt:
            if receipt.message_digest != digest:
                raise RuntimeError("strength notification text changed during delivery")
            if receipt.status == "sent":
                continue
            if receipt.status in {"sending", "unconfirmed"}:
                failures.append("unconfirmed")
                continue
            if receipt.status == "failed":
                failures.append("rejected")
                continue
            receipt.status = "sending"
            receipt.attempt_count += 1
        else:
            receipt = OwnerPaymentAlertDelivery(notification_id=receipt_id, message_digest=digest,
                                                status="sending", attempt_count=1)
            session.add(receipt)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            failures.append("unconfirmed")
            continue
        try:
            message_id = telegram.send_html_message(recipient, message)
            if not message_id:
                raise RuntimeError("missing Telegram confirmation")
        except TelegramError as exc:
            # A definite API rejection can be retried; a lost ACK cannot safely be resent.
            receipt.status = "retry" if "429" in str(exc) else "failed"
            session.commit()
            failures.append("rate limit" if receipt.status == "retry" else "rejected")
            continue
        except Exception:
            receipt.status = "unconfirmed"
            session.commit()
            failures.append("unconfirmed")
            continue
        receipt.status = "sent"
        receipt.platform_message_id = str(message_id)
        deliveries[recipient] = {"receipt_id": receipt_id, "message_id": str(message_id),
                                 "sent_at": datetime.now(UTC).isoformat()}
        notification.payload = {**notification.payload, "deliveries": deliveries}
        session.commit()
    if failures:
        if "rate limit" in failures:
            raise RuntimeError("strength notification rate limit; some recipients still pending")
        raise RuntimeError("strength notification delivery is unconfirmed or rejected; inspect receipts before retry")
