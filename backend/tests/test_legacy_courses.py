from datetime import datetime, timedelta, timezone
from decimal import Decimal
import pytest
from sqlalchemy import select, func

from test_masterclass_journey import setup, teardown_function
from app.app_service import require_user_resource, AppAccessError
from app.course_access_service import course_entry_unlocked
from app.legacy_upgrade_service import offer_payload, PACKAGE, PRICE_CODES
from app.masterclass_routes import course_context_for_member, create_offer_checkout_record
from app.models import Resource, UserAccess, UserEmail, User, UserOffer, PricingVersion, PriceEntry, UserCoursePolicy, Payment
from app.tilda_service import grant_payment_access


def legacy_setup(*, recipes=False):
    client, factory = setup()
    with factory() as db:
        user = db.scalar(select(User))
        access = db.scalar(select(UserAccess).join(Resource).where(Resource.code == "ACCESS_MASTERCLASS"))
        access.revoked_at = datetime.now(timezone.utc)
        resources = {row.code: row for row in db.scalars(select(Resource))}
        for code in ("ACCESS_MASTERCLASS_LEGACY", "ACCESS_CALORIES_LEGACY", "ACCESS_CALORIES", "dqs", "recipes", "metabolism"):
            resources[code] = Resource(code=code, name=code, status="active")
            db.add(resources[code])
        db.flush()
        for code in ("ACCESS_MASTERCLASS_LEGACY", "ACCESS_CALORIES_LEGACY", "dqs", "recipes") + (("ACCESS_RECIPES",) if recipes else ()):
            db.add(UserAccess(user_id=user.id, resource_id=resources[code].id, source="test", granted_at=datetime.now(timezone.utc)))
        db.add(UserCoursePolicy(user_id=user.id, resource_id=resources["ACCESS_MASTERCLASS_LEGACY"].id,
                                start_mode="open", unlock_mode="fully_unlocked", source="test"))
        version = PricingVersion(version_number=1, name="test", status="active", created_by="test")
        db.add(version); db.flush()
        for stage, amount in (("first",1990),("day",2500),("standard",2990)):
            db.add(PriceEntry(version_id=version.id, code=PRICE_CODES[stage], section="offer_stages", name="test",
                              sale_amount=Decimal(amount), enabled=True, resource_codes=list(PACKAGE)))
        db.commit()
    return client, factory


def test_old_course_uses_same_program_and_protects_locked_materials_even_with_full_open():
    client, factory = legacy_setup()
    asset = client.get('/assets/account-legacy-offer.js')
    assert asset.status_code == 200 and 'EdabalansLegacyOffer' in asset.text
    manifest = client.get('/api/masterclass/course/manifest',params={'email':'member@example.test'}).json()
    steps = {step['id']:step for day in manifest['days'] for step in day['steps']}
    assert manifest['accessEdition'] == 'non_updating'
    assert not steps['day-04-article-01'].get('locked')
    for ident in ('day-04-dqs','day-06-article-01','day-07-video-01','day-13-article-03'):
        assert steps[ident]['locked'] and not steps[ident]['required']
        assert 'contentAsset' not in steps[ident]
    assert not steps['day-15-article-02'].get('locked')
    for ident in ('day-04-article-01','day-07-video-01'):
        response = client.get('/api/account/resource-link',params={'target':'masterclass-21:'+ident})
        assert response.status_code == 200
        assert response.json()['action'] == ('open' if ident == 'day-04-article-01' else 'locked')
    response = client.get('/api/masterclass/course/materials',params={'email':'member@example.test','step_id':'day-07-video-01'})
    assert response.status_code == 200 and not response.json()['materials']
    assert client.post('/api/masterclass/course/days/4/open',json={'email':'member@example.test'}).status_code == 200
    index = next(i for i,s in enumerate(manifest['days'][3]['steps']) if s['id']=='day-04-dqs')
    assert client.post(f'/api/masterclass/course/days/4/steps/{index}/complete',json={'email':'member@example.test'}).status_code == 409
    with factory() as db:
        user = db.scalar(select(User))
        for app in ('dqs','recipes'):
            with pytest.raises(AppAccessError): require_user_resource(db,user,app)
        assert course_entry_unlocked(db,user.id,'ACCESS_CALORIES')
    account = client.get('/api/account-auth/account').json()
    assert next(c for c in account['courses'] if c['code']=='masterclass')['owned']
    assert next(c for c in account['courses'] if c['code']=='calories')['owned']


def test_separately_bought_recipes_survive_legacy_masterclass_and_future_steps_are_closed():
    _, factory = legacy_setup(recipes=True)
    from app.legacy_course_access import legacy_masterclass_manifest
    with factory() as db:
        user = db.scalar(select(User))
        context = course_context_for_member(db,user.id)
        steps = {s['id']:s for d in context.days.values() for s in d['steps']}
        assert not steps['day-07-video-01'].get('legacyLocked')
        require_user_resource(db,user,'recipes')
    base = {'days':[{'number':1,'steps':[{'id':'future-new-material','kind':'article'}]}]}
    protected = legacy_masterclass_manifest(base, {'ACCESS_MASTERCLASS_LEGACY'})
    assert protected['days'][0]['steps'][0]['locked']
    assert 'locked' not in base['days'][0]['steps'][0]


@pytest.mark.parametrize('legacy_calorie_start',[None,'auto','blocked'])
def test_one_persisted_window_changes_price_at_exact_boundaries_and_checkout_grants_package(legacy_calorie_start):
    client, factory = legacy_setup()
    if legacy_calorie_start:
        with factory() as db:
            user = db.scalar(select(User))
            resource = db.scalar(select(Resource).where(Resource.code=='ACCESS_CALORIES_LEGACY'))
            db.add(UserCoursePolicy(user_id=user.id,resource_id=resource.id,start_mode=legacy_calorie_start,unlock_mode='paced',source='test'))
            db.commit()
    shown = client.post('/api/account/legacy-offer/show').json()
    again = client.post('/api/account/legacy-offer/show').json()
    assert shown['started_at'] == again['started_at'] and shown['offers'][0]['price'] == 1990
    with factory() as db:
        user = db.scalar(select(User))
        window = db.scalar(select(UserOffer).where(UserOffer.stage_code=='legacy_upgrade'))
        start = window.started_at.replace(tzinfo=timezone.utc)
        for seconds, amount in ((599,1990),(600,2500),(86399,2500),(86400,2990)):
            payload = offer_payload(db,user,start=False,now=start+timedelta(seconds=seconds))
            assert payload['offers'][0]['price'] == amount
            assert payload['offers'][0]['items'] == list(PACKAGE)
        payload = offer_payload(db,user,start=False)
        checkout = create_offer_checkout_record(db,user,payload,payload['offers'][0])
        payment = Payment(user_id=user.id,source='robokassa',product_name_raw=checkout.title,payment_status='paid',currency='RUB',amount=1990)
        db.add(payment); db.flush()
        grant_payment_access(db,payment,checkout,datetime.now(timezone.utc)); db.flush()
        count = db.scalar(select(func.count(UserAccess.id)))
        grant_payment_access(db,payment,checkout,datetime.now(timezone.utc)); db.flush()
        assert db.scalar(select(func.count(UserAccess.id))) == count
        policy = db.scalar(select(UserCoursePolicy).join(Resource).where(Resource.code=='ACCESS_MASTERCLASS'))
        assert policy.unlock_mode == 'fully_unlocked' and policy.start_mode == 'open'
        assert course_entry_unlocked(db,user.id,'ACCESS_CALORIES') == (legacy_calorie_start != 'blocked'), 'Upgrade must preserve the legacy calories start'
        assert not offer_payload(db,user,start=False)['available']
        current = course_context_for_member(db,user.id)
        assert not current.manifest.get('accessEdition')
        assert db.scalar(select(func.count(UserOffer.id)).where(UserOffer.stage_code=='legacy_upgrade')) == 1


def test_unverified_or_revoked_old_right_does_not_start_discount_window():
    client, factory = legacy_setup()
    with factory() as db:
        user = db.scalar(select(User)); user.access_review_status='pending'; db.commit()
    assert not client.post('/api/account/legacy-offer/show').json()['available']

    with factory() as db:
        assert db.scalar(select(func.count(UserOffer.id))) == 0
        user = db.scalar(select(User)); user.access_review_status='completed'
        for row in db.scalars(select(UserAccess).join(Resource).where(Resource.code.like('%_LEGACY'))):
            row.paused_at=datetime.now(timezone.utc)
        db.commit()
    assert not client.post('/api/account/legacy-offer/show').json()['available']


def test_checkout_rejects_stale_displayed_price_before_creating_invoice():
    client, factory = legacy_setup()
    client.post('/api/account/legacy-offer/show')
    response = client.post('/api/payments/robokassa/account-offers/checkout',
                           json={'offer_code':'legacy-upgrade','expected_price':2500},headers={'Origin':'https://edabalans.ru'})
    assert response.status_code == 409
    from app.models import OfferCheckout
    with factory() as db:
        assert db.scalar(select(func.count(OfferCheckout.id))) == 0


def test_publish_prices_copies_existing_catalog_and_is_idempotent():
    client, factory = setup()
    from scripts.publish_legacy_upgrade_prices import publish
    with factory() as db:
        version = PricingVersion(version_number=1,name='Existing catalog',status='active',created_by='test')
        db.add(version); db.flush()
        db.add(PriceEntry(version_id=version.id,code='unchanged.product',section='base_products',name='Existing',sale_amount=Decimal(8800),enabled=True))
        db.commit()
        assert publish(db)['status'] == 'published'
        assert publish(db)['status'] == 'already_published'
        active = db.scalar(select(PricingVersion).where(PricingVersion.status=='active'))
        assert active.version_number == 2
        entries = {e.code:e for e in db.scalars(select(PriceEntry).where(PriceEntry.version_id==active.id))}
        assert entries['unchanged.product'].sale_amount == 8800
        assert set(PRICE_CODES.values()).issubset(entries)


def test_legacy_calories_real_course_and_metabolism_endpoints_without_modern_right():
    from test_calorie_course_journey import setup as calories_setup
    client, factory = calories_setup(masterclass_completed=False)
    with factory() as db:
        user = db.scalar(select(User).join(UserEmail).where(UserEmail.email_normalized=='calories@example.test'))
        modern = db.scalar(select(UserAccess).where(UserAccess.user_id==user.id))
        modern.revoked_at = datetime.now(timezone.utc)
        legacy = Resource(code='ACCESS_CALORIES_LEGACY',name='Old calories',status='active')
        db.add(legacy); db.flush()
        db.add(UserAccess(user_id=user.id,resource_id=legacy.id,source='test',granted_at=datetime.now(timezone.utc)))
        db.commit()
    course = client.get('/api/calories/course?email=calories@example.test')
    assert course.status_code == 200
    assert course.json()['stages'][0]['opened']
    assert not course.json()['stages'][1]['can_open']
    assert client.post('/api/calories/course/days/2/open',json={'email':'calories@example.test'}).status_code == 409
    assert client.get('/api/calories/course/manifest?email=calories@example.test').status_code == 200
    calculator = client.get('/api/apps/metabolism')
    assert calculator.status_code == 200 and calculator.json()['ok']
    account = client.get('/api/account-auth/account').json()
    assert next(row for row in account['applications'] if row['code']=='metabolism')['app']=='metabolism'
    with factory() as db:
        assert not db.scalar(select(UserAccess.id).join(Resource).where(Resource.code=='metabolism'))
        db.add(UserCoursePolicy(user_id=user.id,resource_id=legacy.id,start_mode='blocked',unlock_mode='paced',source='test'))
        db.commit()
    assert client.get('/api/calories/course?email=calories@example.test').status_code == 403
    assert not client.get('/api/apps/metabolism').json()['ok']


def test_upgrade_preserves_existing_modern_policy_and_progress_in_mixed_account():
    from app.models import CourseStageProgress
    client, factory = legacy_setup()
    with factory() as db:
        user = db.scalar(select(User))
        modern = db.scalar(select(Resource).where(Resource.code=='ACCESS_MASTERCLASS'))
        db.add(UserAccess(user_id=user.id,resource_id=modern.id,source='test',granted_at=datetime.now(timezone.utc)))
        existing = UserCoursePolicy(user_id=user.id,resource_id=modern.id,start_mode='blocked',unlock_mode='paced',source='manual_admin')
        db.add(existing)
        progress = CourseStageProgress(user_id=user.id,course_code='calories',stage_number=1,first_opened_at=datetime.now(timezone.utc))
        db.add(progress); db.flush()
        progress_id = progress.id
        payload = offer_payload(db,user,start=True)
        checkout = create_offer_checkout_record(db,user,payload,payload['offers'][0])
        payment = Payment(user_id=user.id,source='robokassa',product_name_raw=checkout.title,payment_status='paid',currency='RUB',amount=1990)
        db.add(payment); db.flush()
        grant_payment_access(db,payment,checkout,datetime.now(timezone.utc)); db.flush()
        db.expire(existing)
        assert existing.start_mode == 'blocked' and existing.unlock_mode == 'paced'
        assert db.get(CourseStageProgress,progress_id).first_opened_at == progress.first_opened_at
        assert db.scalar(select(func.count(CourseStageProgress.id))) == 1
