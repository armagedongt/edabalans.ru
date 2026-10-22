import os
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://test:test@127.0.0.1:5432/test")
os.environ.setdefault("ADMIN_USERNAME", "admin@example.com")
os.environ.setdefault("ADMIN_PASSWORD", "test-admin-password")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import get_db
from app.main import app
from app.finance_facts import report
from app.models import (AttributionEvent, ManagedDocumentVersion, MessengerAccount, Payment,
                        PriceEntry, PricingVersion, Product, TelegramTrackingEvent, TelegramTrackingLink, User)
from app.payment_metrics import coaching_payment_summary


def dt(value):
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


@pytest.fixture
def db():
    engine = create_engine('sqlite://', connect_args={'check_same_thread':False}, poolclass=StaticPool)
    for model in (User, Product, MessengerAccount, PricingVersion, PriceEntry, Payment,
                  TelegramTrackingLink, TelegramTrackingEvent, AttributionEvent, ManagedDocumentVersion):
        model.__table__.create(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def user(db, name):
    row=User(display_name=name);db.add(row);db.flush();return row


def entry(db, who, at, *, platform='telegram', external=None, event='start_first', medium='organic', **details):
    row=TelegramTrackingEvent(user_id=who.id if who else None, telegram_user_id=external,
        event_type=event, occurred_at=dt(at), metadata_json={'messenger':platform,
        'max_delivery_status':'sent','raw_query':{'utm_source':'pikabu','utm_medium':medium},**details})
    db.add(row);db.flush();return row


def payment(db, who, at, amount, **extra):
    row=Payment(user_id=who.id if who else None, paid_at=dt(at) if at else None,
        amount=Decimal(str(amount)) if amount is not None else None,source='test_fixture',
        product_name_raw='Покупка',payment_status='paid',currency='RUB',**extra)
    db.add(row);db.flush();return row


def test_calendar_receipts_and_entry_cohorts_have_different_windows(db):
    a,b=user(db,'Первый'),user(db,'Второй')
    db.add_all([MessengerAccount(user_id=a.id,platform='telegram',platform_user_id='42',source='fixture'),
                MessengerAccount(user_id=a.id,platform='max',platform_user_id='99',source='fixture')]);db.flush()
    # Earliest channel join precedes a MAX start; both identities are one person.
    entry(db,None,'2026-08-31T21:00:00',external='42',event='channel_membership',
          medium='cpc',subscribed=True,joined=True)
    entry(db,a,'2026-09-05T00:00:00',platform='max',external='99')
    # The same numeric ID on a different platform must remain a separate lead.
    entry(db,None,'2026-09-03T00:00:00',platform='max',external='42')
    entry(db,b,'2026-09-30T21:00:00')
    payment(db,a,'2026-09-30T21:00:00',100) # exactly 30 days after entry: late
    payment(db,a,'2026-11-01T12:00:00',50) # repeat, not another first buyer
    payment(db,b,'2026-10-10T12:00:00',200)
    now=dt('2026-11-20T12:00:00')
    september=report(db,'2026-09',now)
    october=report(db,'2026-10',now)
    assert september['receipts']['revenue']==0
    assert september['cohort']['observed_entries']==2
    assert september['cohort']['early_buyers']==0
    assert september['cohort']['late_buyers']==1
    assert september['cohort']['total_rate']==50
    assert september['cohort']['groups']['paid']['late_buyers']==1
    assert october['receipts']['revenue']==300
    assert october['receipts']['buyers']==2
    assert october['cohort']['leads']==1
    assert october['cohort']['early_buyers']==1
    assert october['cohort']['total_rate']==100
    first=next(x for x in october['people'] if x['user_id']==str(a.id))
    assert first['period_revenue']==100
    assert first['observed_ltv']==150


@pytest.mark.parametrize('tracked_first', [False, True])
def test_same_join_keeps_tracking_source_regardless_of_observation_order(db, tracked_first):
    lead=user(db,'Вступление по рекламной ссылке')
    link=TelegramTrackingLink(platform='telegram',placement='cpc',name='Реклама',target_kind='channel',status='active')
    db.add(link);db.flush()
    for tracked in ([True,False] if tracked_first else [False,True]):
        event=entry(db,lead,'2026-09-03T00:00:00',event='channel_join' if tracked else 'channel_membership',
                    subscribed=True,joined=True)
        event.metadata_json={'subscribed':True,'joined':True,'attribution_basis':'unattributed'}
        if tracked:event.tracking_link_id=link.id
    payment(db,lead,'2026-09-04T00:00:00',100)
    result=report(db,'2026-09',dt('2026-10-20T00:00:00'))
    assert result['cohort']['leads']==1
    assert result['cohort']['groups']['paid']['early_buyers']==1
    assert result['cohort']['groups']['unknown']['leads']==0
    assert result['receipts']['buyer_sources']['paid']==1


def test_unlinked_and_uncertain_payments_are_not_silently_classified(db):
    a=user(db,'С неизвестной датой')
    entry(db,a,'2026-09-03T00:00:00')
    payment(db,a,None,100)
    payment(db,a,'2026-09-15T00:00:00',30)
    free=payment(db,None,'2026-09-05T00:00:00',75,price_entry_code='manual.payment')
    estimated=payment(db,a,'2026-09-06T00:00:00',50,amount_is_estimated=True)
    test=payment(db,a,'2026-09-07T00:00:00',999);test.payment_status='test_paid'
    result=report(db,'2026-09',dt('2026-10-20T00:00:00'))
    assert result['receipts']['revenue']==105
    assert result['receipts']['unlinked_payments']==1
    assert result['receipts']['uncertain_amounts']==1
    assert result['cohort']['unknown_first_purchase']==1
    assert result['cohort']['leads']==0
    assert result['cohort']['total_rate'] is None
    assert result['support']['payment_count']==0


def test_old_buyers_unconfirmed_max_and_subscription_checks_do_not_invent_new_conversions(db):
    old=user(db,'Покупал раньше')
    entry(db,old,'2026-09-02T00:00:00')
    payment(db,old,'2026-08-01T00:00:00',100)
    entry(db,None,'2026-09-03T00:00:00',platform='max',external='max-pending',max_delivery_status='pending')
    entry(db,None,'2026-09-03T00:00:00',external='check',event='subscription_check',subscribed=True)
    entry(db,None,'2026-09-03T00:00:00',external='request',event='channel_join_request')
    result=report(db,'2026-09',dt('2026-10-20T00:00:00'))
    assert result['cohort']['observed_entries']==1
    assert result['cohort']['already_buyers']==1
    assert result['cohort']['leads']==0


def test_versioned_tariff_snapshot_and_monthly_support_without_product_id(db):
    a=user(db,'Клиент')
    version=PricingVersion(version_number=1,name='Историческая',created_by='test');db.add(version);db.flush()
    db.add(PriceEntry(version_id=version.id,code='site.masterclass.basic',section='site_tariffs',
                      name='Минимальный',product_code='MASTERCLASS_BASIC',sale_amount=100))
    payment(db,a,'2026-09-01T12:00:00',100,pricing_version_id=version.id,price_entry_code='site.masterclass.basic')
    payment(db,a,'2026-09-02T12:00:00',200,price_entry_code='subscription.coaching.monthly')
    result=report(db,'2026-09',dt('2026-10-20T00:00:00'))
    assert {x['code'] for x in result['categories']}=={'MASTERCLASS_BASIC','COACHING'}
    assert result['support']['payment_count']==1
    assert result['support']['monthly_payments']==1


def test_merged_people_keep_earliest_entry_and_late_purchase_is_not_limited_to_year(db):
    root=user(db,'Общий человек');old=user(db,'Объединённый профиль')
    old.merged_into_user_id=root.id
    entry(db,old,'2026-09-01T12:00:00',medium='cpc')
    entry(db,root,'2026-09-05T12:00:00')
    payment(db,old,'2027-12-01T12:00:00',100)
    result=report(db,'2026-09',dt('2028-01-01T12:00:00'))
    assert result['cohort']['leads']==1
    assert result['cohort']['late_buyers']==1
    assert result['cohort']['total_rate']==100
    assert result['cohort']['groups']['paid']['late_buyers']==1


def test_coaching_counter_accepts_assigned_free_payment_and_excludes_pending_test():
    def p(status='paid',amount=100,price=None):
        return SimpleNamespace(payment_status=status,price_entry_code=price,currency='RUB',amount=Decimal(amount),amount_is_estimated=False)
    result=coaching_payment_summary([(p(price='subscription.coaching.monthly'),None),(p(),'COACHING'),
                                    (p(),'CONSULTATION'),(p('pending'),'COACHING'),(p('test_paid'),'COACHING'),
                                    (p(amount=0),'COACHING'),(p(amount=-100),'COACHING')])
    assert result=={'payment_count':2,'monthly_payments':1,'other_payments':1,'amount_rub':200,'unknown_amount_count':0}


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db]=lambda:db
    client=TestClient(app,base_url='https://admin.example.com')
    client.post('/admin/api/login',json={'username':'admin@example.com','password':'test-admin-password'})
    yield client
    app.dependency_overrides.pop(get_db,None)


def test_fact_and_expense_boundaries_and_explicit_zero(client,db):
    anonymous=TestClient(app,base_url='https://admin.example.com')
    assert anonymous.get('/admin/api/finance/facts').status_code==401
    assert anonymous.post('/admin/api/finance/expenses',json={'month':'2026-09','ads':0}).status_code==401
    assert client.get('/admin/api/finance/facts?month=2026-09').headers['cache-control']=='no-store'
    for invalid in ('2026-13','2026-8','2026-08','2099-01'):
        assert client.get('/admin/api/finance/facts',params={'month':invalid}).status_code==422
    url='/admin/api/finance/expenses'
    body={'month':'2026-09','ads':0,'opex':100}
    assert client.post(url,json=body).status_code==403
    assert client.post(url,json=body,headers={'X-Finance-Write':'1','Origin':'https://evil.example'}).status_code==403
    headers={'X-Finance-Write':'1'}
    assert client.post(url,json={**body,'ads':-1},headers=headers).status_code==422
    assert client.post(url,json=body,headers=headers).status_code==200
    report_sep=client.get('/admin/api/finance/facts?month=2026-09').json()
    assert report_sep['expenses']['ads']==0
    assert report_sep['expenses']['opex']==100
    assert client.post(url,json={**body,'opex':200},headers=headers).status_code==200
    assert client.get('/admin/api/finance/facts?month=2026-09').json()['expenses']['opex']==200
    # A missing month in the all-period report is unknown, not zero.
    if datetime.now(timezone.utc)>=dt('2026-10-01T00:00:00'):
        assert client.get('/admin/api/finance/facts').json()['expenses']['ads'] is None
