"""Chronology after a verified entry; observations are not causal attribution."""
from datetime import datetime, timezone
from bisect import bisect_left
from collections import defaultdict
from urllib.parse import urlsplit
from sqlalchemy import or_, select
from app.models import CourseEvent, MessengerAccount, TelegramTrackingEvent


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def enrich_visits(db, visits, start, end):
    ids = {v['telegram_user_id'] for v in visits}
    accounts = {a.platform_user_id: a for a in db.scalars(select(MessengerAccount).where(
        MessengerAccount.platform == 'telegram', MessengerAccount.platform_user_id.in_(ids)))} if ids else {}
    user_ids = {a.user_id for a in accounts.values()}
    raw = list(db.scalars(select(TelegramTrackingEvent).where(
        or_(TelegramTrackingEvent.telegram_user_id.in_(ids), TelegramTrackingEvent.user_id.in_(user_ids)),
        TelegramTrackingEvent.occurred_at >= start, TelegramTrackingEvent.occurred_at < end,
    ).order_by(TelegramTrackingEvent.occurred_at).limit(30001))) if ids else []
    course = list(db.scalars(select(CourseEvent).where(CourseEvent.user_id.in_(user_ids),
        CourseEvent.course_code == 'intensive', CourseEvent.event_type.like('intensive_onepage_%'), CourseEvent.occurred_at >= start, CourseEvent.occurred_at < end,
    ).order_by(CourseEvent.occurred_at).limit(30001))) if user_ids else []
    truncated = len(raw) > 30000 or len(course) > 30000
    raw, course = raw[:30000], course[:30000]
    for visit in visits:
        account = accounts.get(visit['telegram_user_id'])
        if account:
            visit['user_id'] = str(account.user_id)
    by_person = {}
    for visit in visits:
        by_person.setdefault(visit['telegram_user_id'], []).append(visit)
    events_by_tg, events_by_user, reading_by_user = defaultdict(list), defaultdict(list), defaultdict(list)
    for event in raw:
        events_by_tg[event.telegram_user_id].append(event)
        if event.user_id:
            events_by_user[str(event.user_id)].append(event)
    for event in course:
        reading_by_user[str(event.user_id)].append(event)
    for person_visits in by_person.values():
        person_visits.sort(key=lambda v: v['at'])
        user_id = person_visits[0]['user_id']
        actor = sorted({e.id: e for e in events_by_tg[person_visits[0]['telegram_user_id']] + events_by_user[user_id]}.values(), key=lambda e: utc(e.occurred_at))
        actor_times = [utc(e.occurred_at) for e in actor]
        actor_reading = reading_by_user[user_id]
        reading_times = [utc(e.occurred_at) for e in actor_reading]
        for index, visit in enumerate(person_visits):
            lower = utc(datetime.fromisoformat(visit['at']))
            upper = utc(datetime.fromisoformat(person_visits[index+1]['at'])) if index+1 < len(person_visits) else end
            matching = actor[bisect_left(actor_times, lower):bisect_left(actor_times, upper)]
            reading = actor_reading[bisect_left(reading_times, lower):bisect_left(reading_times, upper)]
            start_event = next((e for e in matching if e.event_type.startswith('start_')), None)
            joined = next((e for e in matching if e.event_type == 'channel_membership'
                           and (e.metadata_json or {}).get('subscribed') is True), None)
            granted = next((e for e in matching if e.event_type == 'channel_write_allowed'), None)
            delivered = next((e for e in matching if e.event_type == 'temporary_intensive_entry'
                             and (e.metadata_json or {}).get('delivery_status') == 'sent'), None)
            site = next((e for e in matching if e.event_type == 'browser_page'
                         and urlsplit((e.metadata_json or {}).get('page_url', '')).path in ('', '/')), None)
            percentages = [e.details['viewed_percent'] for e in reading
                if e.event_type in ('intensive_onepage_progress','intensive_onepage_heading','intensive_onepage_reading_start')
                and type((e.details or {}).get('viewed_percent')) is int]
            visit.update(bot_start_at=start_event.occurred_at.isoformat() if start_event else None,
                subscription_observed_at=joined.occurred_at.isoformat() if joined else None,
                permission_confirmed_at=granted.occurred_at.isoformat() if granted else None,
                article_message_at=delivered.occurred_at.isoformat() if delivered else None,
                automatic_message_sent=(granted.metadata_json or {}).get("automatic_message_sent") if granted else None,
                article_opened_at=reading[0].occurred_at.isoformat() if reading else None,
                article_read_percent=max(percentages) if percentages else None,
                homepage_opened_at=site.occurred_at.isoformat() if site else None,
                homepage_read_percent=None)
            if start_event and joined:
                visit['order'] = 'channel_then_bot' if utc(joined.occurred_at) < utc(start_event.occurred_at) else 'bot_then_channel'
            else:
                visit['order'] = 'channel_only' if joined else 'bot_only' if start_event else 'not_observed'
    return truncated
