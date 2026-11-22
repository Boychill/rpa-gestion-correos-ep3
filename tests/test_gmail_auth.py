from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace
from unittest.mock import Mock

from google.auth.exceptions import RefreshError, TransportError
from google.oauth2.credentials import Credentials
import httpx
import pytest

from rpa.gmail_auth import authorize, atomic_private, save_token, read_token, refresh, SCOPES
from rpa.gmail_errors import error_code
from rpa.gmail_campaign import prepare, send
from rpa.runtime import Budget, RPAError


def configured(settings, tmp_path):
    path = tmp_path / 'private/client.json'
    client = {'installed':{'client_id':'test.apps.googleusercontent.com','client_secret':'test-secret',
                          'auth_uri':'https://accounts.google.com/o/oauth2/auth',
                          'token_uri':'https://oauth2.googleapis.com/token'}}
    atomic_private(path, json.dumps(client).encode())
    return replace(settings, gmail_client_file=str(path), gmail_sender_address='sender@gmail.com',
                   gmail_receiver_address='receiver@gmail.com',
                   gmail_sender_token_path=str(tmp_path/'private/sender.json'),
                   gmail_receiver_token_path=str(tmp_path/'private/receiver.json'))


def credential(role):
    return Credentials('test-access', refresh_token='test-refresh',
        token_uri='https://oauth2.googleapis.com/token', client_id='test.apps.googleusercontent.com',
        client_secret='test-secret', scopes=SCOPES[role], expiry=datetime.now(timezone.utc).replace(tzinfo=None)+timedelta(hours=1))


def test_no_browser_without_explicit_auth(settings, tmp_path, monkeypatch):
    s = configured(settings, tmp_path)
    browser = Mock(side_effect=AssertionError('Browser must never open'))
    monkeypatch.setattr('rpa.gmail_auth.InstalledAppFlow.from_client_config', browser)
    with pytest.raises(RPAError, match='AUTH_REQUIRED'):
        authorize(s, Budget(10), 'remitente')
    browser.assert_not_called()


def test_sender_only_never_calls_profile_and_tokens_separate(settings, tmp_path, monkeypatch):
    s = configured(settings, tmp_path)
    profile = Mock(side_effect=AssertionError('SEND cannot call getProfile'))
    monkeypatch.setattr('rpa.gmail_auth.receiver_profile', profile)
    path = tmp_path/'private/sender.json'
    save_token(path, credential('remitente'), 'remitente', s.gmail_sender_address)
    assert authorize(s, Budget(10), 'remitente').token=='test-access'
    profile.assert_not_called()
    assert not (tmp_path/'private/receiver.json').exists()
    assert 'test-refresh' not in path.read_text()  # DPAPI Windows
    assert read_token(path)['role']=='remitente'


def test_changed_scope_requires_explicit_reauthorization(settings, tmp_path):
    s = configured(settings, tmp_path)
    token = credential('receptor')
    save_token(tmp_path/'private/sender.json', token, 'remitente', s.gmail_sender_address)
    with pytest.raises(RPAError, match='AUTH_SCOPE_MISMATCH'):
        authorize(s, Budget(10), 'remitente')


def test_disabled_api_keeps_consent_but_never_bypasses_profile(settings, tmp_path, monkeypatch):
    s = configured(settings, tmp_path)
    flow = SimpleNamespace(run_local_server=lambda **kwargs: credential('receptor'))
    monkeypatch.setattr('rpa.gmail_auth.InstalledAppFlow.from_client_config', lambda *args, **kwargs: flow)
    profile = Mock(side_effect=RPAError('GMAIL_API_DISABLED'))
    monkeypatch.setattr('rpa.gmail_auth.receiver_profile', profile)
    with pytest.raises(RPAError, match='GMAIL_API_DISABLED'):
        authorize(s, Budget(10), 'receptor', interactive=True)
    assert (tmp_path/'private/receiver.json').exists()
    with pytest.raises(RPAError, match='GMAIL_API_DISABLED'):
        authorize(s, Budget(10), 'receptor')
    assert profile.call_count==2


@pytest.mark.parametrize('failure,code', [(RefreshError('invalid_grant'),'AUTH_REQUIRED'),
                                        (TransportError('network'),'AUTH_TRANSIENT')])
def test_refresh_failure_classification(settings, failure, code):
    credentials = SimpleNamespace(refresh=Mock(side_effect=failure))
    with pytest.raises(RPAError, match=code):
        refresh(credentials, settings, Budget(10))
    assert credentials.refresh.call_count==1


@pytest.mark.parametrize('reason,code', [('accessNotConfigured','GMAIL_API_DISABLED'),
    ('dailyLimitExceeded','GMAIL_DAILY_QUOTA'), ('userRateLimitExceeded','GMAIL_RATE_LIMIT'),
    ('insufficientPermissions','GMAIL_PERMISSION_DENIED')])
def test_distinct_403_reasons(reason, code):
    response = httpx.Response(403, json={'error':{'errors':[{'reason':reason}], 'message':'SECRET'}})
    assert error_code(response)==code


def test_generator_default_never_authenticates_or_sends(settings, monkeypatch):
    campaign = prepare(settings, 'sender@gmail.com','receiver@gmail.com', 3)
    monkeypatch.setattr('rpa.gmail_campaign.authenticate_gmail', Mock(side_effect=AssertionError()))
    result = send(settings, campaign['id'], campaign['sender'], campaign['recipient'])
    assert result['dry_run'] and result['states']=={'PENDING':3}


def test_limit_then_resume_skips_accepted(settings):
    campaign = prepare(settings, 'sender@gmail.com','receiver@gmail.com', 3)
    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(200, json={'id':str(len(requests))})
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        args = (settings,campaign['id'],campaign['sender'],campaign['recipient'])
        first = send(*args,client=client,token='fake',interval=0,execute=True,limit=1)
        second = send(*args,client=client,token='fake',interval=0,execute=True)
    assert first['accepted']==1 and first['attempted_this_invocation']==1
    assert second['accepted']==3 and second['attempted_this_invocation']==2 and len(requests)==3
    assert first['processed']==1 and second['processed']==2


def test_daily_quota_stops_with_due_time_and_no_repeat(settings):
    campaign = prepare(settings, 'sender@gmail.com','receiver@gmail.com', 3)
    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(403, json={'error':{'errors':[{'reason':'dailyLimitExceeded'}]}})
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        args = (settings,campaign['id'],campaign['sender'],campaign['recipient'])
        first = send(*args,client=client,token='fake',interval=0,execute=True)
        second = send(*args,client=client,token='fake',interval=0,execute=True)
    assert first['states']=={'DEFERRED':1,'PENDING':2}
    assert second['error']=='CAMPAIGN_RETRY_NOT_DUE' and len(requests)==1


def test_report_gmail_mime_single_send_and_unknown_result(settings, monkeypatch):
    from email import message_from_bytes
    import base64
    from rpa.orchestrator import run
    from rpa.store import Store
    from rpa.mail_send import send_report
    first = run(settings)
    eid = first['execution_id']
    s = replace(settings, source='GMAIL', mailbox='receiver@gmail.com', gmail_sender_address='sender@gmail.com',
                holiday_mode='LIVE', mail_mode='SEND', mail_adapter='GMAIL', send_authorized=True,
                recipient='receiver@gmail.com', allowed_recipients='receiver@gmail.com')
    monkeypatch.setattr('rpa.gmail_auth.authorize', lambda *args, **kwargs: SimpleNamespace(token='fake'))
    requests = []
    def handle(request):
        requests.append(request)
        data = json.loads(request.content)
        message = message_from_bytes(base64.urlsafe_b64decode(data['raw']))
        assert message['To']=='receiver@gmail.com' and message['Subject'].startswith('[RPA-EP3]')
        assert any(part.get_filename()=='reporte.xlsx' for part in message.walk())
        raise httpx.ReadTimeout('ambiguous', request=request)
    with Store(settings.runtime/'state.sqlite3', settings.root) as store, httpx.Client(transport=httpx.MockTransport(handle)) as client:
        store.execute('DELETE FROM sends WHERE execution_id=?', (eid,))
        args = (s,store,eid,settings.output/eid/'reporte.xlsx','<p>Reporte</p>',client,None,Budget(30))
        assert send_report(*args)=='ENVIO_INCIERTO'
        assert send_report(*args)=='ENVIO_INCIERTO'
        assert len(requests)==1


def test_explicit_dry_report_promotion_only_sends_once(settings, monkeypatch):
    from rpa.orchestrator import run
    from rpa.store import Store
    from rpa.mail_send import send_report
    first = run(settings)
    eid = first['execution_id']
    s = replace(settings, source='GMAIL', mailbox='receiver@gmail.com', gmail_sender_address='sender@gmail.com',
                holiday_mode='LIVE', mail_mode='SEND', mail_adapter='GMAIL', send_authorized=True,
                recipient='receiver@gmail.com', allowed_recipients='receiver@gmail.com')
    monkeypatch.setattr('rpa.gmail_auth.authorize', lambda *args, **kwargs: SimpleNamespace(token='fake'))
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(200,json={'id':'accepted'})
    with Store(settings.runtime/'state.sqlite3', settings.root) as store, httpx.Client(transport=httpx.MockTransport(handle)) as client:
        args = (s,store,eid,settings.output/eid/'reporte.xlsx','<p>Reporte</p>',client,None,Budget(30))
        assert send_report(*args)=='DRY_RUN' and not calls
        assert send_report(*args,promote_dry_run=True)=='ACEPTADO'
        assert send_report(*args,promote_dry_run=True)=='ACEPTADO' and len(calls)==1
