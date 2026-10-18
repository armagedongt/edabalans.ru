"""The channel link constructor in the existing administrative shell."""
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.security import HTTPBasicCredentials
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import admin_identity, require_admin, security
from app.channel_entry_service import (LinkIn, LinkUpdateIn, PLATFORMS, SOURCES, create_link,
    link_payload, resolve_entry, update_link)
from app.config import get_settings
from app.channel_entry_analytics import enrich_visits
from app.database import get_db
from app.models import TelegramTrackingEvent, TelegramTrackingLink

router = APIRouter()


@router.get('/admin/channel-links', include_in_schema=False)
def constructor_page(request: Request, credentials: HTTPBasicCredentials | None = Depends(security)):
    if not admin_identity(request, credentials):
        return RedirectResponse('/admin?next=/admin/channel-links', status_code=303)
    return FileResponse(Path(__file__).resolve().parent / 'static/admin.html', headers={'Cache-Control': 'no-store'})


@router.get('/admin/api/channel-links')
def list_channel_links(_: str = Depends(require_admin), db: Session = Depends(get_db)):
    for code in SOURCES:
        resolve_entry(db, code)
    rows = db.scalars(select(TelegramTrackingLink).where(TelegramTrackingLink.target_kind == 'channel_entry')
                      .order_by(TelegramTrackingLink.created_at.desc()))
    return {'platforms': PLATFORMS, 'links': [link_payload(db, row, get_settings().telegram_test_bot_username) for row in rows]}


@router.post('/admin/api/channel-links')
def create_channel_link(body: LinkIn, admin: str = Depends(require_admin), db: Session = Depends(get_db)):
    row = create_link(db, body, admin)
    return link_payload(db, row, get_settings().telegram_test_bot_username)


@router.put('/admin/api/channel-links/{link_id}')
def edit_channel_link(link_id: str, body: LinkUpdateIn, admin: str = Depends(require_admin), db: Session = Depends(get_db)):
    row = update_link(db, link_id, body, admin)
    return link_payload(db, row, get_settings().telegram_test_bot_username)


@router.get('/admin/api/channel-links/report')
def channel_link_report(date_from: date = Query(alias='from'), date_to: date = Query(alias='to'),
    platform: str = '', link_id: str = '', _: str = Depends(require_admin), db: Session = Depends(get_db)):
    if date_to < date_from or (date_to - date_from).days > 730:
        raise HTTPException(400, 'Выберите период до двух лет')
    tz = ZoneInfo('Europe/Moscow')
    start = datetime.combine(date_from, time.min, tzinfo=tz).astimezone(timezone.utc)
    end = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=tz).astimezone(timezone.utc)
    query = select(TelegramTrackingEvent).where(TelegramTrackingEvent.event_type.like('channel_%'),
        TelegramTrackingEvent.occurred_at >= start, TelegramTrackingEvent.occurred_at < end)
    events = list(db.scalars(query.order_by(TelegramTrackingEvent.occurred_at, TelegramTrackingEvent.id).limit(30001)))
    truncated = len(events) > 30000
    events = events[:30000]
    visits = {}
    for event in events:
        meta = event.metadata_json or {}
        key = meta.get('visit')
        if not key:
            continue
        visit = visits.setdefault(key, {'id': key, 'at': event.occurred_at.isoformat(),
            'link_id': event.tracking_link_id, 'code': meta.get('code'), 'platform': meta.get('source'),
            'placement': meta.get('placement'), 'telegram_user_id': event.telegram_user_id,
            'user_id': str(event.user_id) if event.user_id else None, 'events': []})
        visit['events'].append({'kind': event.event_type, 'at': event.occurred_at.isoformat(), **meta})
    # The period selects entries, not callbacks from visits opened on an earlier day.
    visits = {key: visit for key, visit in visits.items()
              if any(e['kind'] == 'channel_entry_open' for e in visit['events'])}
    truncated = enrich_visits(db, list(visits.values()), start, end) or truncated
    selected = [v for v in visits.values() if (not platform or v['platform'] == platform)
                and (not link_id or v['link_id'] == link_id)]
    groups = {}
    sources = {}
    for visit in selected:
        opened = next((e for e in visit['events'] if e['kind'] == 'channel_entry_open'), None)
        if not opened:
            continue
        key = (visit['link_id'] or visit['code'] or 'unknown', visit['platform'], visit['placement'])
        group = groups.setdefault(key, {'link_id': visit['link_id'], 'code': visit['code'],
            'platform': visit['platform'], 'placement': visit['placement'], 'entries': 0,
            'people': set(), 'known': 0, 'permission_yes': 0, 'permission_no': 0,
            'permission_unknown': 0, 'channel_requested': 0, 'permission_not_requested': 0,
            'already_allowed': 0, 'server_allowed': 0, 'bot_starts': 0, 'subscriptions_observed': 0,
            'article_opened': 0, 'article_read': 0, 'homepage_opened': 0, 'new_contacts_allowed': 0})
        group['entries'] += 1
        group['people'].add(visit['telegram_user_id'])
        group['known'] += int(opened.get('known_contact') is True)
        visit['known_contact'] = opened.get('known_contact') is True
        group['new_contacts_allowed'] += int(not visit['known_contact'] and visit.get('permission_confirmed_at') is not None)
        result = next((e for e in visit['events'] if e['kind'] == 'channel_permission_result'), None)
        group['permission_yes'] += int(result is not None and result.get('client_granted') is True)
        group['permission_no'] += int(result is not None and result.get('client_granted') is False)
        group['permission_unknown'] += int(opened['request_write_access'] and (result is None or result.get('client_granted') is None))
        group['permission_not_requested'] += int(not opened['request_write_access'])
        group['already_allowed'] += int(opened.get('already_allowed') is True)
        for field, metric in [('permission_confirmed_at','server_allowed'),('bot_start_at','bot_starts'),
            ('subscription_observed_at','subscriptions_observed'),('article_opened_at','article_opened'),('homepage_opened_at','homepage_opened')]:
            group[metric] += int(visit.get(field) is not None)
        group['article_read'] += int((visit.get('article_read_percent') or 0)>75)
        group['channel_requested'] += int(any(e['kind'] == 'channel_open_requested' for e in visit['events']))
    rows = []
    for group in groups.values():
        group['unique_people'] = len(group.pop('people'))
        rows.append(group)
        key = group['platform'] or 'unknown'
        source = sources.setdefault(key, {'platform': key, **{k: 0 for k in (
            'entries', 'known', 'permission_yes', 'permission_no', 'permission_unknown', 'channel_requested',
            'permission_not_requested', 'already_allowed', 'server_allowed', 'bot_starts', 'subscriptions_observed',
            'article_opened', 'article_read', 'homepage_opened', 'new_contacts_allowed')}})
        for k in source.keys() - {'platform'}:
            source[k] += group[k]
    for source in sources.values():
        source['unique_people'] = len({v['telegram_user_id'] for v in selected if (v['platform'] or 'unknown') == source['platform']})
    for visit in selected:
        visit['events'] = [{k: e[k] for k in ('kind','at','client_granted','server_granted','subscribed','automatic_message_sent') if k in e} for e in visit['events']]
    return {'links': rows, 'platforms': list(sources.values()), 'visits': selected[:500],
        'visits_truncated': len(selected)>500, 'homepage_reading_collection': 'not_connected',
        'truncated': truncated, 'timezone': 'Europe/Moscow',
        'note': 'Ответ Mini App — наблюдение клиента. Отсутствие ответа не доказывает отказ; запрос перехода не доказывает подписку.'}
