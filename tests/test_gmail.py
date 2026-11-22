from dataclasses import replace
from datetime import datetime, timezone
from email import message_from_bytes
import base64
import json
import sqlite3
from urllib.parse import urlparse, parse_qs

import httpx
import pytest

from rpa.classify import Classifier
from rpa.gmail import GmailReader
from rpa.gmail_campaign import prepare, send, summary, directory, load, raw_message
from rpa.runtime import RPAError


class FakeHTTP:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.urls = []

    def get(self, url, headers):
        self.urls.append(url)
        value = next(self.replies)
        if isinstance(value, Exception):
            raise value
        return httpx.Response(200, json=value)


def message(mid='a', subject='tag Solicitud', labels=None):
    return dict(id=mid, internalDate=str(int(datetime(2026, 11, 18, tzinfo=timezone.utc).timestamp()*1000)),
                labelIds=['INBOX'] if labels is None else labels, payload={'headers': [
                    {'name':'Subject','value':subject}, {'name':'From','value':'Test <sender@gmail.com>'}]})


def test_gmail_full_scan_history_and_metadata_only(settings):
    s = replace(settings, source='GMAIL', mailbox='receiver@gmail.com', gmail_campaign_tag='tag')
    http = FakeHTTP([{'historyId':'10'}, {'messages':[{'id':'a'}], 'nextPageToken':'next'}, message(),
                     {'messages':[{'id':'b'}]}, message('b', 'unrelated'),
                     {'history':[{'messagesAdded':[{'message':{'id':'c'}}]}], 'historyId':'20'}, message('c')])
    reader = GmailReader(s, http, 'test-token')
    first = reader.page()
    second = reader.page(first.cursor)
    third = reader.page(second.cursor)
    assert first.messages[0]['id']=='a' and first.phase=='NEXT'
    assert second.messages==[] and second.phase=='NEXT'
    assert third.phase=='DELTA' and json.loads(third.cursor)['history']=='20'
    assert third.messages[0]['id']=='c'
    for url in http.urls:
        query = parse_qs(urlparse(url).query)
        assert ('q' in query) == urlparse(url).path.endswith('/messages')
        if '/messages/' in url:
            assert query['format']==['metadata']
            assert 'body' not in query['fields'][0]


def test_gmail_expired_history_and_removals(settings):
    http = FakeHTTP([RPAError('HTTP_404')])
    with pytest.raises(RPAError, match='CURSOR_EXPIRED'):
        GmailReader(settings, http, 'token').page('{"mode":"history","history":"10"}')
    http = FakeHTTP([{'historyId':'20', 'history':[{'messagesDeleted':[{'message':{'id':'a'}}],
                      'labelsRemoved':[{'message':{'id':'b'}}]}]}, message('b', labels=[])])
    page = GmailReader(settings, http, 'token').page('{"mode":"history","history":"10"}')
    assert {m['id'] for m in page.messages if m['removed']}=={'a', 'b'}


def test_dataset_read_includes_spam_without_modifying_mailbox(settings):
    s=replace(settings,gmail_label='ALL',gmail_campaign_tag='tag')
    http=FakeHTTP([{'historyId':'1'},{'messages':[{'id':'spam'}]},message('spam',labels=['SPAM'])])
    page=GmailReader(s,http,'token').page()
    assert page.messages[0]['id']=='spam'
    params=parse_qs(urlparse(http.urls[1]).query)
    assert params['includeSpamTrash']==['true'] and 'labelIds' not in params
    assert 'subject:"tag"' in params['q'][0]


def test_prepare_500_and_mime(settings):
    campaign = prepare(settings, 'sender@gmail.com', 'receiver@gmail.com')
    classifier = Classifier(settings.root / 'config/reglas.json')
    assert len(campaign['messages'])==500
    assert len({m['message_id'] for m in campaign['messages']})==500
    assert campaign['expected']=={'Solicitud':84,'Consulta':84,'Reclamo':83,'Urgente':83,'Información':83,'Otros':83}
    assert all(classifier.classify(m['subject'])[0]==m['expected'] for m in campaign['messages'])
    msg = message_from_bytes(base64.urlsafe_b64decode(raw_message(campaign, campaign['messages'][0])))
    assert msg['To']=='receiver@gmail.com' and msg['From']=='sender@gmail.com'
    assert summary(settings, campaign['id'])['states']=={'PENDING':500}


def test_sender_recipient_and_manifest_guard(settings):
    campaign = prepare(settings, 'sender@gmail.com', 'receiver@gmail.com', 1)
    with pytest.raises(RPAError, match='ACCOUNT_MISMATCH'):
        send(settings, campaign['id'], 'other@gmail.com', 'receiver@gmail.com')
    path = directory(settings, campaign['id']) / 'mensajes.json'
    path.write_bytes(path.read_bytes()+b' ')
    with pytest.raises(RPAError, match='CAMPAIGN_MODIFIED'):
        load(settings, campaign['id'])


def test_accepted_never_resent(settings):
    campaign = prepare(settings, 'sender@gmail.com', 'receiver@gmail.com', 3)
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, json={'id':str(len(calls))})
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        for _ in range(2):
            result = send(settings, campaign['id'], campaign['sender'], campaign['recipient'], client, 'token', interval=0, execute=True)
            assert result['all_accepted']
    assert len(calls)==3


@pytest.mark.parametrize('failure', ['timeout', '500', '429', '403', 'invalid_success'])
def test_failed_send_stops_and_never_retries_unknown(settings, failure):
    campaign = prepare(settings, 'sender@gmail.com', 'receiver@gmail.com', 3)
    calls = []
    def handle(request):
        calls.append(request)
        if failure=='timeout':
            raise httpx.ReadTimeout('private detail', request=request)
        return httpx.Response(200 if failure=='invalid_success' else int(failure), json={})
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        result = send(settings, campaign['id'], campaign['sender'], campaign['recipient'], client, 'token', interval=0, execute=True)
        assert not result['all_accepted'] and result['accepted']==0
        assert result['states']['PENDING']==2
        with pytest.raises(RPAError, match='CAMPAIGN_REVIEW_REQUIRED'):
            send(settings, campaign['id'], campaign['sender'], campaign['recipient'], client, 'token', interval=0, execute=True)
    assert len(calls)==1


def test_crash_before_persisting_does_not_resend(settings):
    campaign = prepare(settings, 'sender@gmail.com', 'receiver@gmail.com', 1)
    with sqlite3.connect(directory(settings, campaign['id']) / 'campaign.sqlite3') as db:
        db.execute("UPDATE deliveries SET state='IN_FLIGHT',attempts=1")
    with pytest.raises(RPAError, match='CAMPAIGN_REVIEW_REQUIRED'):
        send(settings, campaign['id'], campaign['sender'], campaign['recipient'], execute=True)
    assert summary(settings, campaign['id'])['states']=={'UNCERTAIN':1}


def test_campaign_analysis_incremental_500_without_sending(settings, monkeypatch):
    from rpa.gmail_campaign import analyze
    from rpa.holidays import Holidays
    from rpa.mail_read import Page
    import rpa.orchestrator as orchestrator
    campaign = prepare(settings, 'sender@gmail.com', 'receiver@gmail.com')
    original_load = Holidays._load
    monkeypatch.setattr(Holidays, '_load', lambda self, year:
        original_load(Holidays(replace(self.s, holiday_mode='FIXTURE'), None), year))
    monkeypatch.setattr(orchestrator, 'authenticate_gmail', lambda *args: 'test-token')
    class Reader:
        queries = 0
        def __init__(self, *args):
            pass
        def page(self, cursor=None):
            # La segunda consulta incorpora los otros 250 correos del mismo lote.
            first = 250 if cursor else 0
            rows = [dict(id=str(item['sequence']), subject=item['subject'], sender='anon-'+__import__('hashlib').sha256(campaign['sender'].encode()).hexdigest()[:12], rfc_message_id=item['message_id'] if item['sequence']%2 else '<rewritten-by-provider>',
                         received=campaign['created'], modified='v1')
                    for item in campaign['messages'][first:first+250]]
            return Page(rows, 'second', 'DELTA')
    monkeypatch.setattr(orchestrator, 'GmailReader', Reader)
    first = analyze(settings, campaign['id'])
    second = analyze(settings, campaign['id'])
    assert first['received_unique']==250 and not first['complete']
    assert second['received_unique']==500 and second['correct']==500 and second['complete']
    assert second['categories']==campaign['expected']
    assert summary(settings, campaign['id'])['states']=={'PENDING':500}
    assert len((directory(settings, campaign['id'])/'analisis_acumulado.csv').read_text().splitlines())==501
    from rpa.campaign_report import export_campaign
    from rpa.excel import verify_report
    from pathlib import Path
    exported = export_campaign(settings,campaign['id'])
    assert verify_report(Path(exported['path']),exported['execution_id'],500)['sha256']==exported['sha256']
    assert export_campaign(settings,campaign['id'])['reused']
