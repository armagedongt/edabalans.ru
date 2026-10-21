from datetime import datetime, timezone
from urllib.parse import urlsplit, parse_qs

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.auth import require_admin
from app.channel_bridge_routes import router as bridge_router
from app.channel_entry_routes import router
from app.config import Settings, get_settings
from app.database import Base, get_db
from app.models import (TelegramTrackingEvent, TelegramTrackingLink, TelegramTrackingLinkAlias,
                        TelegramTrackingSession, User, MessengerAccount, CourseEvent)
from test_channel_bridge import signed_data, TOKEN


@pytest.fixture
def entry():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    app = FastAPI()
    app.include_router(router)
    app.include_router(bridge_router)
    def database():
        with Session(engine) as db:
            yield db
    app.dependency_overrides[get_db] = database
    app.dependency_overrides[require_admin] = lambda: 'owner-test'
    app.dependency_overrides[get_settings] = lambda: Settings(database_url='sqlite://', telegram_test_bot_token=TOKEN)
    with TestClient(app) as client:
        yield client, engine, app
    engine.dispose()


def create(client, **values):
    result = client.post('/admin/api/channel-links', json={'name': 'Скорость похудения', 'platform': 'pikabu',
        'placement': 'Статья о скорости', **values})
    assert result.status_code == 200, result.text
    return result.json()


def test_constructor_has_stable_single_parameter_and_editable_permission(entry):
    client, engine, _ = entry
    row = create(client)
    url = urlsplit(row['url'])
    assert url.path == '/Fitness_Talks_bot/channel'
    assert parse_qs(url.query) == {'startapp': [row['code']]}
    assert len(row['code']) == 6 and row['request_write_access'] is True
    changed = client.put('/admin/api/channel-links/' + row['id'], json={
        'name': 'Изменённое название', 'platform': 'pikabu', 'placement': 'Новый пост',
        'destination': 'https://t.me/Fitness_Talks/123', 'request_write_access': False,
        'expected_version': row['version']})
    assert changed.status_code == 200, changed.text
    assert changed.json()['url'] == row['url']
    verified = client.post('/apps/channel-bridge/verify', json={'init_data': signed_data(entry_code=row['code'])})
    assert verified.json() == {'destination': 'https://t.me/Fitness_Talks/123',
                               'request_write_access': False, 'source': 'pikabu'}
    with Session(engine) as db:
        assert db.scalar(select(TelegramTrackingLinkAlias.token)) == row['code']
        assert db.scalar(select(func.count()).select_from(User)) == 0
        assert db.scalar(select(func.count()).select_from(MessengerAccount)) == 0
    stale = client.put('/admin/api/channel-links/' + row['id'], json={
        'name': 'Старая вкладка', 'platform': 'youtube', 'expected_version': 1})
    assert stale.status_code == 409
    with Session(engine) as db:
        assert db.get(TelegramTrackingLink, row['id']).platform == 'pikabu'


@pytest.mark.parametrize('values', [{'destination':'https://example.com'},
    {'destination':'https://t.me/Fitness_Talks/260?url=https://example.com'},
    {'destination':'https://t.me/SomeoneElse/260'}, {'platform':'typo'}, {'name':'   '},
    {'request_write_access':'false'}])
def test_invalid_settings_do_not_create_links(entry, values):
    client, engine, _ = entry
    result = client.post('/admin/api/channel-links', json={'name':'Пост', 'platform':'pikabu', **values})
    assert result.status_code == 422
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(TelegramTrackingLink)) == 0


def test_existing_reserved_links_keep_edits_and_legacy_catalog_rows(entry):
    client, engine, _ = entry
    with Session(engine) as db:
        db.add(TelegramTrackingLink(token='BOLD', name='Старая ссылка', platform='pikabu',
                                   placement='Старый пост', target_kind='bot_start', status='active'))
        db.commit()
    listing = client.get('/admin/api/channel-links').json()
    assert len(listing['links']) == 9
    assert all(row['code'] != 'BOLD' for row in listing['links'])
    ig = next(row for row in listing['links'] if row['code'] == 'ig')
    client.put('/admin/api/channel-links/' + ig['id'], json={
        'name':'Instagram новый', 'platform':'instagram', 'request_write_access':False, 'expected_version':1})
    again = client.get('/admin/api/channel-links').json()
    assert next(row for row in again['links'] if row['code']=='ig')['request_write_access'] is False
    with Session(engine) as db:
        assert db.scalar(select(TelegramTrackingLink.name).where(TelegramTrackingLink.token=='BOLD')) == 'Старая ссылка'


def test_events_require_signature_opening_and_deduplicate_without_starting_bot(entry):
    client, engine, _ = entry
    row = create(client)
    data = signed_data(entry_code=row['code'])
    endpoint = '/apps/channel-bridge/event'
    assert client.post(endpoint, json={'init_data':data,'event':'channel_permission_result','granted':True}).status_code == 409
    assert client.post(endpoint, json={'init_data':signed_data(token='forged'),'event':'channel_open_requested'}).status_code == 401
    for _ in range(2):
        assert client.post('/apps/channel-bridge/verify', json={'init_data':data}).status_code == 200
        assert client.post(endpoint,json={'init_data':data,'event':'channel_permission_result','granted':False}).status_code == 204
        assert client.post(endpoint,json={'init_data':data,'event':'channel_open_requested'}).status_code == 204
    with Session(engine) as db:
        events = list(db.scalars(select(TelegramTrackingEvent)))
        assert {e.event_type for e in events} == {'channel_entry_open','channel_permission_result','channel_open_requested'}
        assert len(events) == 3
        assert all(e.user_id is None and e.telegram_user_id == '1234567' for e in events)
        assert all('init_data' not in e.metadata_json for e in events)


def test_visit_keeps_target_and_mode_snapshot_after_edit(entry):
    client, engine, _ = entry
    row = create(client)
    data = signed_data(entry_code=row['code'])
    client.post('/apps/channel-bridge/verify',json={'init_data':data})
    changed = client.put('/admin/api/channel-links/' + row['id'],json={'name':'Другой пост','platform':'youtube',
        'destination':'https://t.me/Fitness_Talks/999','request_write_access':False,'expected_version':1})
    assert changed.status_code == 200
    client.post('/apps/channel-bridge/event',json={'init_data':data,'event':'channel_open_requested'})
    with Session(engine) as db:
        event=db.scalar(select(TelegramTrackingEvent).where(TelegramTrackingEvent.event_type=='channel_open_requested'))
        assert event.metadata_json['destination']=='https://t.me/Fitness_Talks/260'
        assert event.metadata_json['source']=='pikabu'
        assert event.metadata_json['request_write_access'] is True


def test_report_includes_people_without_bot_start_and_separates_unknown(entry):
    client, engine, _ = entry
    row=create(client)
    data=signed_data(entry_code=row['code'])
    client.post('/apps/channel-bridge/verify',json={'init_data':data})
    day=datetime.now(timezone.utc).astimezone(__import__('zoneinfo').ZoneInfo('Europe/Moscow')).date().isoformat()
    report=client.get('/admin/api/channel-links/report',params={'from':day,'to':day}).json()
    assert report['links'][0]['entries']==1
    assert report['links'][0]['permission_unknown']==1
    assert report['links'][0]['permission_no']==0
    assert report['visits'][0]['user_id'] is None
    client.post('/apps/channel-bridge/event',json={'init_data':data,'event':'channel_permission_result','granted':False})
    report=client.get('/admin/api/channel-links/report',params={'from':day,'to':day}).json()
    assert report['links'][0]['permission_unknown']==0
    assert report['links'][0]['permission_no']==1
    assert report['platforms'][0]['platform']=='pikabu'
    assert client.get('/admin/api/channel-links/report',params={'from':day,'to':day,'platform':'youtube'}).json()['links']==[]


def test_constructor_mutations_require_existing_admin(entry):
    client, engine, app = entry
    app.dependency_overrides.pop(require_admin)
    assert client.get('/admin/api/channel-links').status_code==401
    assert client.post('/admin/api/channel-links',json={'name':'Пост','platform':'pikabu'}).status_code==401


def test_report_tracks_observed_order_reading_and_site_for_same_person_only(entry):
    from datetime import timedelta
    client, engine, _ = entry
    row=create(client)
    data=signed_data(entry_code=row['code'])
    client.post('/apps/channel-bridge/verify',json={'init_data':data})
    at=datetime(2026,10,19,8,tzinfo=timezone.utc)
    with Session(engine) as db:
        opening=db.scalar(select(TelegramTrackingEvent).where(TelegramTrackingEvent.event_type=='channel_entry_open'))
        opening.occurred_at=at
        user=User(status='active'); other=User(status='active')
        db.add_all([user,other]);db.flush()
        db.add(MessengerAccount(user_id=user.id,platform='telegram',platform_user_id='1234567',source='test'))
        for index,kind,meta in [(1,'channel_write_allowed',{'server_granted':True}),
            (2,'channel_membership',{'subscribed':True}),(3,'start_first',{}),
            (4,'temporary_intensive_entry',{'delivery_status':'sent'}),
            (5,'browser_page',{'page_url':'https://xn-----jlceacr3bggd8ajed5a6kl.xn--p1ai/'})]:
            db.add(TelegramTrackingEvent(user_id=user.id,telegram_user_id='1234567',event_type=kind,
                metadata_json=meta,occurred_at=at+timedelta(seconds=index)))
        db.add(CourseEvent(user_id=user.id,course_code='intensive',event_key='read-own',
            event_type='intensive_onepage_progress',details={'viewed_percent':80},occurred_at=at+timedelta(seconds=6)))
        db.add(CourseEvent(user_id=other.id,course_code='intensive',event_key='read-other',
            event_type='intensive_onepage_progress',details={'viewed_percent':100},occurred_at=at+timedelta(seconds=7)))
        db.add(TelegramTrackingEvent(user_id=user.id, event_type='homepage_observation',
            metadata_json={'action':'section_seen','section_id':'pricing','scroll_percent':65}, occurred_at=at+timedelta(seconds=8)))
        db.add(TelegramTrackingEvent(user_id=user.id, event_type='homepage_observation',
            metadata_json={'action':'scroll_depth','section_id':'page_open','scroll_percent':100}, occurred_at=at+timedelta(seconds=9)))
        db.commit()
    report=client.get('/admin/api/channel-links/report',params={'from':'2026-10-19','to':'2026-10-19'}).json()
    visit=report['visits'][0]
    assert visit['order']=='channel_then_bot'
    assert visit['article_read_percent']==80
    assert visit['homepage_opened_at'] is not None
    assert visit['homepage_read_percent'] == 100
    assert visit['homepage_farthest_section'] == {'id':'pricing','name':'Тарифы'}
    assert visit['homepage_seen_sections'] == [{'id':'pricing','name':'Тарифы'}]
    assert report['homepage_reading_collection']=='section_observations'
    assert report['links'][0]['new_contacts_allowed']==1
    assert report['links'][0]['server_allowed']==1
    assert report['links'][0]['bot_starts']==1
    assert report['links'][0]['subscriptions_observed']==1
    assert report['links'][0]['article_read']==1


def test_skip_permission_is_not_counted_as_unknown_refusal(entry):
    client, _, _ = entry
    row=create(client,request_write_access=False)
    client.post('/apps/channel-bridge/verify',json={'init_data':signed_data(entry_code=row['code'])})
    day=datetime.now(timezone.utc).astimezone(__import__('zoneinfo').ZoneInfo('Europe/Moscow')).date().isoformat()
    report=client.get('/admin/api/channel-links/report',params={'from':day,'to':day}).json()
    assert report['links'][0]['permission_not_requested']==1
    assert report['links'][0]['permission_unknown']==0
    assert report['links'][0]['permission_no']==0


def test_advertising_u_session_is_consumed_once_but_same_signed_visit_keeps_snapshot(entry):
    import hashlib
    import uuid
    from datetime import timedelta
    client,engine,_=entry
    link=create(client,destination='https://t.me/Fitness_Talks/123')
    payload='UadvertisingJourney'
    with Session(engine) as db:
        alias=db.scalar(select(TelegramTrackingLinkAlias).where(TelegramTrackingLinkAlias.tracking_link_id==link['id']))
        journey=TelegramTrackingSession(id=str(uuid.uuid4()),tracking_link_id=link['id'],alias_id=alias.id,
            start_token_hash=hashlib.sha256(payload.encode()).hexdigest(),raw_query={'yclid':'click-one'},
            resolved_tag_ids=['existing-source-tag'],expires_at=datetime.now(timezone.utc)+timedelta(days=7))
        db.add(journey);db.commit();journey_id=journey.id
    data=signed_data(entry_code=payload)
    for _ in range(2):
        result=client.post('/apps/channel-bridge/verify',json={'init_data':data})
        assert result.status_code==200
        assert result.json()['destination']=='https://t.me/Fitness_Talks/123'
        assert result.json()['source']=='pikabu'
    client.post('/apps/channel-bridge/event',json={'init_data':data,'event':'channel_open_requested'})
    with Session(engine) as db:
        assert db.get(TelegramTrackingSession,journey_id).consumed_at is not None
        event=db.scalar(select(TelegramTrackingEvent).where(TelegramTrackingEvent.event_type=='channel_entry_open'))
        assert event.metadata_json['raw_query']=={'yclid':'click-one'}
        assert event.metadata_json['session_tag_ids']==['existing-source-tag']
        assert db.scalar(select(func.count()).select_from(TelegramTrackingEvent))==2


def test_consumed_and_expired_advertising_sessions_cannot_attribute_a_new_signed_visit(entry):
    import hashlib
    import time
    import uuid
    from datetime import timedelta
    client, engine, _ = entry
    link = create(client, destination='https://t.me/Fitness_Talks/123')
    with Session(engine) as db:
        alias = db.scalar(select(TelegramTrackingLinkAlias).where(TelegramTrackingLinkAlias.tracking_link_id == link['id']))
        for payload, expired in [('Uused', False), ('Uexpired', True)]:
            db.add(TelegramTrackingSession(id=str(uuid.uuid4()), tracking_link_id=link['id'], alias_id=alias.id,
                start_token_hash=hashlib.sha256(payload.encode()).hexdigest(), raw_query={'yclid':'private-click'},
                resolved_tag_ids=['source-tag'], expires_at=datetime.now(timezone.utc)+timedelta(days=-1 if expired else 7)))
        db.commit()
    original = signed_data(entry_code='Uused')
    assert client.post('/apps/channel-bridge/verify', json={'init_data':original}).json()['source'] == 'pikabu'
    for payload in ['Uused', 'Uexpired']:
        fresh = signed_data(entry_code=payload, timestamp=int(time.time())-2)
        result = client.post('/apps/channel-bridge/verify', json={'init_data':fresh})
        assert result.status_code == 200
        assert result.json()['source'] is None
        assert result.json()['destination'] == 'https://t.me/Fitness_Talks/260'
    with Session(engine) as db:
        unattributed = list(db.scalars(select(TelegramTrackingEvent).where(TelegramTrackingEvent.tracking_link_id.is_(None))))
        assert len(unattributed) == 2
        assert all(not e.metadata_json.get('journey_id') and not e.metadata_json.get('raw_query')
                   and not e.metadata_json.get('session_tag_ids') for e in unattributed)


def test_report_stops_each_link_at_next_entry_even_when_filtering_platform(entry):
    from datetime import timedelta
    client, engine, _ = entry
    first = create(client)
    second = create(client, platform='youtube', name='Видео')
    at = datetime(2026,10,19,8,tzinfo=timezone.utc)
    for row in (first, second):
        client.post('/apps/channel-bridge/verify', json={'init_data':signed_data(entry_code=row['code'])})
    with Session(engine) as db:
        for index, row in enumerate((first, second)):
            opening = db.scalar(select(TelegramTrackingEvent).where(TelegramTrackingEvent.tracking_link_id == row['id']))
            opening.occurred_at = at+timedelta(minutes=index*10)
        user = User(status='active'); db.add(user); db.flush()
        db.add(MessengerAccount(user_id=user.id,platform='telegram',platform_user_id='1234567',source='test'))
        db.add(TelegramTrackingEvent(user_id=user.id,telegram_user_id='1234567',event_type='start_first',
            occurred_at=at+timedelta(minutes=11)))
        db.add(CourseEvent(user_id=user.id,course_code='intensive',event_key='after-second',
            event_type='intensive_onepage_progress',details={'viewed_percent':90},occurred_at=at+timedelta(minutes=12)))
        db.commit()
    params = {'from':'2026-10-19','to':'2026-10-19'}
    report = client.get('/admin/api/channel-links/report',params=params).json()
    rows = {row['link_id']:row for row in report['links']}
    assert rows[first['id']]['bot_starts'] == rows[first['id']]['article_read'] == 0
    assert rows[second['id']]['bot_starts'] == rows[second['id']]['article_read'] == 1
    filtered = client.get('/admin/api/channel-links/report',params={**params,'platform':'pikabu'}).json()
    assert filtered['links'][0]['bot_starts'] == filtered['links'][0]['article_read'] == 0


def test_report_does_not_include_callback_for_entry_outside_selected_period(entry):
    client, engine, _ = entry
    row = create(client)
    data = signed_data(entry_code=row['code'])
    client.post('/apps/channel-bridge/verify',json={'init_data':data})
    client.post('/apps/channel-bridge/event',json={'init_data':data,'event':'channel_permission_result','granted':True})
    with Session(engine) as db:
        for event in db.scalars(select(TelegramTrackingEvent)):
            event.occurred_at = datetime(2026,10,18 if event.event_type=='channel_entry_open' else 19,8,tzinfo=timezone.utc)
        db.commit()
    report = client.get('/admin/api/channel-links/report',params={'from':'2026-10-19','to':'2026-10-19'}).json()
    assert report['links'] == report['platforms'] == report['visits'] == []


def test_platform_totals_keep_historical_source_when_stable_link_is_edited(entry):
    import time
    client, _, _ = entry
    row = create(client)
    client.post('/apps/channel-bridge/verify',json={'init_data':signed_data(entry_code=row['code'])})
    changed = client.put('/admin/api/channel-links/'+row['id'],json={
        'name':'Видео','platform':'youtube','placement':'Профиль','expected_version':1})
    assert changed.status_code == 200
    client.post('/apps/channel-bridge/verify',json={'init_data':signed_data(entry_code=row['code'],timestamp=int(time.time())-2)})
    day = datetime.now(timezone.utc).astimezone(__import__('zoneinfo').ZoneInfo('Europe/Moscow')).date().isoformat()
    report = client.get('/admin/api/channel-links/report',params={'from':day,'to':day}).json()
    assert {row['platform']:row['entries'] for row in report['platforms']} == {'pikabu':1,'youtube':1}
    assert {row['platform']:row['entries'] for row in report['links']} == {'pikabu':1,'youtube':1}


def test_max_and_telegram_entries_with_same_numeric_id_remain_distinct(entry):
    client, engine, app = entry
    app.dependency_overrides[get_settings] = lambda: Settings(database_url="sqlite://", telegram_test_bot_token=TOKEN, max_bot_token="max-token")
    row = create(client)
    assert parse_qs(urlsplit(row["max_url"]).query) == {"startapp": [row["code"]]}
    data = signed_data(token="max-token", entry_code=row["code"])
    response = client.post("/apps/channel-bridge/max/verify", json={"init_data":data})
    assert response.status_code == 200, response.text
    assert response.json()["destination"] == "https://max.ru/id230409966750_biz"
    assert response.json()["request_write_access"] is False
    assert client.post("/apps/channel-bridge/verify", json={"init_data":data}).status_code == 401
    assert client.post("/apps/channel-bridge/verify", json={"init_data":signed_data(entry_code=row["code"])}).status_code == 200
    with Session(engine) as db:
        openings = list(db.scalars(select(TelegramTrackingEvent).where(TelegramTrackingEvent.event_type == "channel_entry_open")))
        assert {e.metadata_json["messenger"] for e in openings} == {"telegram","max"}
        assert len({e.metadata_json["visit"] for e in openings}) == 2
    assert client.post("/apps/channel-bridge/max/event", json={"init_data":data,"event":"channel_permission_requested"}).status_code == 422
    assert client.post("/apps/channel-bridge/max/event", json={"init_data":data,"event":"channel_open_requested"}).status_code == 204
    assert client.post('/admin/api/channel-links', json={'name':'Bad','platform':'pikabu','max_destination':'https://max.ru/other'}).status_code == 422
