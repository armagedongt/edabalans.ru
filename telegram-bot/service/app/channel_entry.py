"""Server observations for the existing Telegram channel-entry path."""
from datetime import UTC, datetime
from sqlalchemy import select, or_
from app.models import TrackingEvent, CrmMessengerAccount


def latest_entry(session, telegram_id, messenger="telegram"):
    return session.scalar(select(TrackingEvent).where(
        TrackingEvent.telegram_user_id == str(telegram_id),
        TrackingEvent.event_type == 'channel_entry_open',
        or_(TrackingEvent.metadata_json['messenger'].as_string() == messenger,
            TrackingEvent.metadata_json['messenger'].as_string().is_(None)) if messenger == 'telegram'
        else TrackingEvent.metadata_json['messenger'].as_string() == messenger,
    ).order_by(TrackingEvent.occurred_at.desc(), TrackingEvent.id.desc()))


def server_observation(session, *, telegram_id, kind, key, contact=None, details=None):
    entry = latest_entry(session, telegram_id)
    metadata = dict(entry.metadata_json or {}) if entry else {}
    metadata.update(details or {})
    metadata['attribution_basis'] = 'last_observed_miniapp' if entry else 'unattributed'
    account = session.scalar(select(CrmMessengerAccount).where(
        CrmMessengerAccount.platform == 'telegram',
        CrmMessengerAccount.platform_user_id == str(telegram_id)))
    session.add(TrackingEvent(tracking_link_id=entry.tracking_link_id if entry else None,
        contact_id=contact.id if contact else None,
        user_id=contact.user_id if contact else (account.user_id if account else None),
        telegram_user_id=str(telegram_id), event_type=kind, deduplication_key=key,
        metadata_json=metadata))
    if kind == 'channel_membership' and account:
        account.subscription_status = 'subscribed' if metadata['subscribed'] else 'not_subscribed'
        account.subscription_checked_at = datetime.now(UTC)


def pending_entry(session, telegram_id, messenger="telegram"):
    entry = latest_entry(session, telegram_id, messenger)
    if not entry or not entry.tracking_link_id:
        return None, {}
    from app.models import TrackingLink
    link = session.get(TrackingLink, entry.tracking_link_id)
    if not link or link.status != 'active' or not link.is_active:
        return None, {}
    return link, dict(entry.metadata_json or {})
