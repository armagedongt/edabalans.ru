import hashlib
import hmac
import json
from uuid import uuid4
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import strength_delivery as delivery
from app.config import Settings, get_settings
from app.database import get_db
from app.models import ManualMessage, CrmUser
from test_messenger_routing import _session, _linked


@pytest.fixture
def setup(tmp_path,monkeypatch):
    session=_session(tmp_path)
    user=CrmUser(display_name='Fixture',status='active',data_origin='native');session.add(user);session.flush()
    settings=Settings(app_auth_secret='synthetic-secret')
    calls=[]
    def sender(_settings,platform):
        def send(recipient,message):calls.append((platform,recipient,message));return 'id-'+str(len(calls))
        return send
    monkeypatch.setattr(delivery,'plan_sender',sender)
    payload={'request_id':str(uuid4()),'user_id':user.id,'messages':['<b>План</b>\n1) 40 кг × 12']}
    yield session,user,settings,calls,payload
    session.close()


@pytest.mark.parametrize('platform',['telegram','max'])
def test_exact_preferred_route_only_and_idempotent_replay(setup,platform):
    session,user,settings,calls,payload=setup
    _linked(session,user_id=user.id,platform='max' if platform=='telegram' else 'telegram',platform_user_id='other',preferred=False)
    contact,_=_linked(session,user_id=user.id,platform=platform,platform_user_id='chosen',preferred=True);session.commit()
    body=delivery.PlanPayload(**payload)
    first=delivery.deliver_saved_plan(session,settings,body)
    assert first['platform']==platform and calls==[(platform,'chosen',payload['messages'][0])]
    assert delivery.deliver_saved_plan(session,settings,body)==first and len(calls)==1
    row=session.scalar(select(ManualMessage));assert row.contact_id==contact.id and row.status=='sent'


def test_missing_or_ambiguous_link_never_falls_back(setup):
    session,user,settings,calls,payload=setup
    for stage in range(2):
        if stage:
            _linked(session,user_id=user.id,platform='telegram',platform_user_id='t',preferred=False)
            _linked(session,user_id=user.id,platform='max',platform_user_id='m',preferred=False);session.commit()
        with pytest.raises(HTTPException) as err:delivery.deliver_saved_plan(session,settings,delivery.PlanPayload(**payload))
        assert err.value.status_code==409 and not calls


def test_unavailable_explicit_primary_never_falls_back_to_other_channel(setup):
    session,user,settings,calls,payload=setup
    _,primary=_linked(session,user_id=user.id,platform='telegram',platform_user_id='primary',preferred=True)
    _linked(session,user_id=user.id,platform='max',platform_user_id='other',preferred=False)
    primary.is_deliverable=False;session.commit()
    with pytest.raises(HTTPException) as err:delivery.deliver_saved_plan(session,settings,delivery.PlanPayload(**payload))
    assert err.value.status_code==409 and not calls


def test_partial_failure_is_not_success_or_automatic_retry(setup,monkeypatch):
    session,user,settings,calls,payload=setup
    _linked(session,user_id=user.id,platform='telegram',platform_user_id='chosen',preferred=True);session.commit()
    payload['messages']=['part1','part2']
    def factory(*args):
        def send(to,msg):
            calls.append(msg)
            if msg=='part2':raise RuntimeError('private-token-url')
            return 'first-id'
        return send
    monkeypatch.setattr(delivery,'plan_sender',factory)
    body=delivery.PlanPayload(**payload)
    with pytest.raises(HTTPException) as err:delivery.deliver_saved_plan(session,settings,body)
    assert err.value.status_code==502 and '1 из 2' in err.value.detail and 'private-token' not in err.value.detail
    with pytest.raises(HTTPException) as err:delivery.deliver_saved_plan(session,settings,body)
    assert err.value.status_code==409 and calls==['part1','part2']
    assert sorted(row.status for row in session.scalars(select(ManualMessage)))==['sent','unconfirmed']


def test_signed_endpoint_rejects_tampering_and_extra_recipient(setup):
    session,user,settings,calls,payload=setup
    _linked(session,user_id=user.id,platform='max',platform_user_id='chosen',preferred=True);session.commit()
    app=FastAPI();app.include_router(delivery.router)
    app.dependency_overrides[get_db]=lambda:session
    app.dependency_overrides[get_settings]=lambda:settings
    client=TestClient(app)
    raw=json.dumps(payload).encode()
    sign=hmac.new(settings.app_auth_secret.encode(),b'strength-plan\n'+raw,hashlib.sha256).hexdigest()
    headers={'X-Edabalans-Strength-Signature':sign,'Content-Type':'application/json'}
    assert client.post('/internal/strength-plan',content=raw).status_code==403
    assert client.post('/internal/strength-plan',content=raw+b' ',headers=headers).status_code==403
    assert not calls
    assert client.post('/internal/strength-plan',content=raw,headers=headers).json()['platform']=='max'
    assert len(calls)==1
    payload['chat_id']='other';raw=json.dumps(payload).encode()
    headers['X-Edabalans-Strength-Signature']=hmac.new(settings.app_auth_secret.encode(),b'strength-plan\n'+raw,hashlib.sha256).hexdigest()
    assert client.post('/internal/strength-plan',content=raw,headers=headers).status_code==422
    assert len(calls)==1


def test_changed_identity_or_body_cannot_reuse_receipt(setup):
    session,user,settings,calls,payload=setup
    _,account=_linked(session,user_id=user.id,platform='telegram',platform_user_id='first',preferred=True);session.commit()
    delivery.deliver_saved_plan(session,settings,delivery.PlanPayload(**payload))
    payload['messages']=['changed']
    with pytest.raises(HTTPException) as err:delivery.deliver_saved_plan(session,settings,delivery.PlanPayload(**payload))
    assert err.value.status_code==409 and len(calls)==1


def test_maintenance_is_not_bypassed(setup):
    session,user,settings,calls,payload=setup
    _linked(session,user_id=user.id,platform='telegram',platform_user_id='first',preferred=True);session.commit()
    settings.telegram_maintenance_mode=True
    with pytest.raises(HTTPException) as err:delivery.deliver_saved_plan(session,settings,delivery.PlanPayload(**payload))
    assert err.value.status_code==503 and not calls


def test_existing_platform_clients_use_their_own_configuration(monkeypatch):
    settings=Settings(max_bot_token='max-test',telegram_test_bot_token='tg-test',telegram_api_base_url='https://relay.example.test',telegram_gateway_token='relay-test')
    calls=[]
    def max_client(token,**kwargs):
        calls.append(('max',token,kwargs));return SimpleNamespace(send_html=lambda *args:'max-id')
    def telegram_client(token,**kwargs):
        calls.append(('telegram',token,kwargs));return SimpleNamespace(send_html_message=lambda *args:'tg-id')
    monkeypatch.setattr(delivery,'MaxClient',max_client);monkeypatch.setattr(delivery,'TelegramClient',telegram_client)
    assert delivery.plan_sender(settings,'max')('42','message')=='max-id'
    assert calls[0][0:2]==('max','max-test')
    assert delivery.plan_sender(settings,'telegram')('42','message')=='tg-id'
    assert calls[1][2]['api_base_url']=='https://relay.example.test' and calls[1][2]['gateway_token']=='relay-test'
    settings.telegram_test_bot_token=''
    assert delivery.plan_sender(settings,'max')('42','message')=='max-id','MAX does not require Telegram configuration'
    with pytest.raises(HTTPException):delivery.plan_sender(settings,'telegram')
