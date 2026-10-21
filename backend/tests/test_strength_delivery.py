import hashlib
import hmac
import io
import json
import re
from html import unescape
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select

from app import strength_delivery as delivery
from app.account_auth_routes import COOKIE_NAME, token_hash
from app.app_service import require_user_resource
from app.config import get_settings
from app.models import AccountCredential, AccountSession, AdminAppEdit, Resource, StrengthState, UserAccess
from test_admin_apps import make_client, add_user, login


def workout():
    return {"session_id": "selected", "session_number": 3, "workout_type": 2,
            "exercises": [{"exercise_id": "press", "exercise_name": "Жим <тест>", "sort_order": 1,
                           "note": "Пользователь & <текст>", "coach_note": "Тренер\nстрока2",
                           "sets": [{"plan_weight": 40, "plan_reps": 12, "fact_weight": 50, "fact_reps": 15}]}]}


def test_plan_format_ignores_fact_escapes_and_keeps_both_comment_categories():
    source = workout()
    before = deepcopy(source)
    rendered = "\n".join(delivery.plan_messages(source, "Верх <имя>", {}))
    assert "Верх &lt;имя&gt;" in rendered and "1️⃣ Жим &lt;тест&gt;" in rendered
    assert "1) 40 кг × 12" in rendered and "50 кг" not in rendered
    assert "<i>* Комментарий тренера: Тренер\nстрока2</i>" in rendered
    assert "Пользователь &amp; &lt;текст&gt;" in rendered
    assert source == before


def test_long_comments_split_without_broken_entities_or_lost_text():
    source = workout()
    source["exercises"][0]["coach_note"] = '<&🏋️' * 3000
    messages = delivery.plan_messages(source, "Верх", {})
    assert len(messages) > 1
    assert all(len(message.encode('utf-16-le')) // 2 <= 3800 for message in messages)
    assert all(message.count('<i>') == message.count('</i>') for message in messages)
    restored=''.join(unescape(part) for message in messages for part in re.findall(r'<i>\* Комментарий тренера: (.*?)</i>',message,re.S))
    assert restored == source['exercises'][0]['coach_note']
    empty = workout();empty['exercises'][0]['sets'] = [{'fact_weight': 60, 'fact_reps': 10}]
    with pytest.raises(ValueError):
        delivery.plan_messages(empty, "Верх", {})


@pytest.fixture
def api(monkeypatch):
    client, factory = make_client()
    with factory() as db:
        owner = add_user(db, "owner-plan@example.test", "Получатель")
        other = add_user(db, "other-plan@example.test", "Другой")
        db.add(Resource(code="strength", name="Силовые", status="active"));db.flush()
        resource = db.scalar(select(Resource).where(Resource.code == "strength"))
        db.add(UserAccess(user_id=owner.id, resource_id=resource.id, source="test", granted_at=datetime.now(timezone.utc)))
        db.add(AccountCredential(user_id=owner.id, password_hash="test", password_version=1, issued_via="test"))
        db.add(AccountSession(user_id=owner.id, token_hash=token_hash("synthetic-session"), password_version=1,
                              expires_at=datetime.now(timezone.utc)+timedelta(days=1)))
        for user in (owner, other):
            db.add(StrengthState(user_id=user.id, version=4, workout_types=[{"workout_type": 2, "title": "Верх"}],
                                 hidden_exercises=[], workouts=[workout()]))
        db.commit();uid, other_id = str(owner.id), str(other.id)
    # These tests exercise identity and product access; legal and course release have their own suites.
    monkeypatch.setattr(delivery, "require_user_resource", lambda db,u,r:require_user_resource(db,u,r,require_legal_acceptance=False))
    monkeypatch.setattr(delivery, "application_access_state", lambda *a:{"start_open":True})
    settings = get_settings();monkeypatch.setattr(settings,"app_auth_secret","synthetic-shared-secret")
    sent = []
    def send(request, timeout):
        assert request.full_url == settings.strength_delivery_endpoint
        expected = hmac.new(settings.app_auth_secret.encode(), b"strength-plan\n"+request.data,hashlib.sha256).hexdigest()
        assert request.get_header('X-edabalans-strength-signature') == expected
        sent.append(json.loads(request.data))
        return io.BytesIO(json.dumps({"ok":True,"platform":"max","message_ids":["message-1"]}).encode())
    monkeypatch.setattr(delivery.urllib.request,"urlopen",send)
    body = {"session_id":"selected","version":4,"request_id":str(uuid4())}
    return client,factory,uid,other_id,sent,body


def test_native_sends_only_own_saved_plan_without_accepting_a_recipient(api):
    client,factory,uid,other,sent,body=api
    client.cookies.set(COOKIE_NAME,"synthetic-session")
    response=client.post('/api/apps/strength/send-plan',json=body)
    assert response.status_code==200 and response.json()['platform']=='max'
    assert sent[0]['user_id']==uid and 'target_user_id' not in sent[0]
    assert '1) 40 кг × 12' in sent[0]['messages'][0]
    assert client.post('/api/apps/strength/send-plan',json={**body,'target_user_id':other}).status_code==401
    assert client.post('/api/apps/strength/send-plan',json={**body,'chat_id':'attacker'}).status_code==422
    assert len(sent)==1
    with factory() as db:
        assert all(state.version==4 and state.workouts==[workout()] for state in db.scalars(select(StrengthState)))


def test_admin_targets_profile_owner_and_audits_only_success(api):
    client,factory,uid,other,sent,body=api
    login(client)
    response=client.post('/api/apps/strength/send-plan',json={**body,'target_user_id':other})
    assert response.status_code==200 and sent[0]['user_id']==other
    with factory() as db:
        audit=db.scalar(select(AdminAppEdit).where(AdminAppEdit.action=='sendPlan'))
        assert str(audit.target_user_id)==other and audit.details['session_id']=='selected'


@pytest.mark.parametrize('change,status', [({},401),({'version':3},409),({'session_id':'missing'},404)])
def test_auth_version_and_missing_session_never_send(api,change,status):
    client,_,_,_,sent,body=api
    if change:client.cookies.set(COOKIE_NAME,'synthetic-session')
    assert client.post('/api/apps/strength/send-plan',json={**body,**change}).status_code==status
    assert not sent


def test_native_without_access_or_course_release_cannot_send(api,monkeypatch):
    client,factory,uid,_,sent,body=api
    client.cookies.set(COOKIE_NAME,'synthetic-session')
    monkeypatch.setattr(delivery,'application_access_state',lambda *a:{'start_open':False})
    assert client.post('/api/apps/strength/send-plan',json=body).status_code==403
    monkeypatch.setattr(delivery,'application_access_state',lambda *a:{'start_open':True})
    with factory() as db:
        db.query(UserAccess).delete();db.commit()
    assert client.post('/api/apps/strength/send-plan',json=body).status_code==403
    assert not sent


def test_delivery_failure_does_not_leak_secrets_or_record_success(api,monkeypatch):
    client,factory,uid,_,sent,body=api
    login(client)
    def fail(*args,**kwargs):raise OSError('synthetic-secret-token')
    monkeypatch.setattr(delivery.urllib.request,'urlopen',fail)
    response=client.post('/api/apps/strength/send-plan',json={**body,'target_user_id':uid})
    assert response.status_code==502 and 'synthetic-secret-token' not in response.text
    with factory() as db:
        assert db.scalar(select(AdminAppEdit).where(AdminAppEdit.action=='sendPlan')) is None


def test_partial_confirmation_cannot_be_reported_as_success(api):
    _,_,_,_,_,_=api
    with pytest.raises(delivery.HTTPException) as error:
        delivery.deliver_plan(get_settings(),{'messages':['part1','part2']})
    assert error.value.status_code==502
