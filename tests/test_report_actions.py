from dataclasses import replace
from types import SimpleNamespace
import base64
from email import message_from_bytes
import json
import tkinter as tk

import httpx
import pytest

from rpa.config import Settings
from rpa.excel import build_report
from rpa.mail_send import send_report, reconcile
from rpa.report_actions import available_reports, preview_report, deliver_report
from rpa.runtime import Budget, RPAError
from rpa.store import Store, utcnow


@pytest.fixture
def prepared(settings, monkeypatch):
    """Reporte de Gmail sintético con referencias controladas; sin OAuth/red real."""
    import uuid
    s=replace(settings, source='GMAIL', mailbox='receiver@gmail.com', gmail_sender_address='sender@gmail.com',
        gmail_receiver_address='receiver@gmail.com', recipient='receiver@gmail.com', allowed_recipients='receiver@gmail.com',
        holiday_mode='LIVE', mail_adapter='GMAIL')
    eid=str(uuid.uuid4()); now=utcnow()
    with Store(s.runtime/'state.sqlite3',s.root) as db:
        db.execute('INSERT INTO executions(id,profile,signature,started,status,source,metrics) VALUES(?,?,?,?,?,?,?)',
                   (eid,'test','test',now,'COMPLETED','GMAIL',json.dumps({'classified':1})))
        path=build_report(s,eid,[{'id':'mock','sender':'anon-test','subject':'Consulta','received':now,'category':'Consulta'}],
            [{'provider':'Mock Calendar','http_status':200,'queried':now,'origin':'real',
              'data':[{'date':'2026-01-01','localName':'Mock holiday','global':True}]}],now,now,1)
        assert send_report(s,db,eid,path,'<p>Preview</p>',None,None,Budget(30))=='DRY_RUN'
    monkeypatch.setattr('rpa.gmail_auth.authorize',lambda *a,**k:SimpleNamespace(token='mock-token'))
    return s,eid,path


def transport(monkeypatch, handler):
    original=httpx.Client
    monkeypatch.setattr('rpa.report_actions.httpx.Client',lambda **kwargs:original(transport=httpx.MockTransport(handler),**kwargs))


def test_preview_and_dry_run_never_send(prepared, monkeypatch):
    s,eid,path=prepared
    transport(monkeypatch,lambda r:pytest.fail('Unexpected HTTP'))
    choices=available_reports(s);assert choices[0]['key']==eid
    preview=preview_report(s,eid,s.recipient)
    assert preview['can_send'] and preview['size']==path.stat().st_size
    assert deliver_report(s,preview)['state']=='DRY_RUN'
    assert '<' in preview['body'] and preview['recipient']==s.recipient


@pytest.mark.parametrize('case',['recipient','changed','missing','traversal','local','calendar','large'])
def test_invalid_report_cannot_be_sent(prepared,case,monkeypatch):
    s,eid,path=prepared
    preview=preview_report(s,eid,s.recipient)
    transport(monkeypatch,lambda r:pytest.fail('Must not call Gmail'))
    if case=='recipient':
        preview=preview_report(s,eid,'other@gmail.com')
        assert not preview['can_send']
    elif case=='changed':path.write_bytes(path.read_bytes()+b'changed')
    elif case=='missing':path.unlink()
    elif case=='traversal':preview['key']='../'+eid
    elif case=='local':
        with Store(s.runtime/'state.sqlite3',s.root) as db:db.execute("UPDATE executions SET source='FIXTURE'")
    elif case in ('calendar','large'):
        from openpyxl import load_workbook
        from rpa.excel import verify_report
        if case=='calendar':
            book=load_workbook(path);book['Referencia_API']['F2']='fixture';book.save(path);book.close()
        if case=='large':
            import zipfile
            with zipfile.ZipFile(path,'a',compression=zipfile.ZIP_STORED) as archive:archive.writestr('padding.txt',b' ' * 3_000_000)
        verified=verify_report(path,eid)
        (path.parent/'adjunto_manifest.json').write_text(json.dumps(dict(verified,execution_id=eid)),encoding='utf-8')
        with Store(s.runtime/'state.sqlite3',s.root) as db:db.execute('UPDATE sends SET sha256=?,size=?',(verified['sha256'],verified['size']))
        preview=preview_report(s,eid,s.recipient)
    with pytest.raises((RPAError,FileNotFoundError)):deliver_report(s,preview,execute=True)


@pytest.mark.parametrize('outcome',['accepted','timeout','quota','invalid_success','forbidden'])
def test_report_result_persisted_and_never_resent(prepared,monkeypatch,outcome):
    s,eid,path=prepared;calls=[]
    def handle(request):
        calls.append(request)
        if outcome=='timeout':raise httpx.ReadTimeout('private',request=request)
        if outcome=='quota':return httpx.Response(403,json={'error':{'errors':[{'reason':'dailyLimitExceeded'}]}})
        if outcome=='forbidden':return httpx.Response(403,json={})
        return httpx.Response(200,json={'id':'mock-id'} if outcome=='accepted' else {})
    transport(monkeypatch,handle)
    preview=preview_report(s,eid,s.recipient)
    first=deliver_report(s,preview,execute=True)
    expected={'accepted':'ACEPTADO','timeout':'ENVIO_INCIERTO','quota':'PENDIENTE_CUOTA',
              'invalid_success':'ENVIO_INCIERTO','forbidden':'ERROR'}[outcome]
    assert first['send_state']==expected
    assert deliver_report(s,preview,execute=True)['send_state']==expected and len(calls)==1
    mail=message_from_bytes(base64.urlsafe_b64decode(json.loads(calls[0].content)['raw']))
    assert mail['To']==s.recipient and mail['From']==s.gmail_sender_address
    assert any(p.get_filename()=='reporte.xlsx' and p.get_payload(decode=True)==path.read_bytes() for p in mail.walk())
    with Store(s.runtime/'state.sqlite3',s.root) as db:
        assert db.row('SELECT state FROM sends WHERE execution_id=?',(eid,))[0]==expected
        assert db.row("SELECT COUNT(*) FROM events WHERE step_id='report_attempted'")[0]==1


def test_supabase_failure_keeps_accepted_report(prepared,monkeypatch):
    s,eid,_=prepared;s=replace(s,supabase_enabled=True,supabase_url='https://mock.supabase.co',supabase_secret_key='sb_secret_MOCK')
    calls=[]
    def handle(request):
        if request.url.host=='gmail.googleapis.com':calls.append(1);return httpx.Response(200,json={'id':'mock'})
        return httpx.Response(503)
    transport(monkeypatch,handle)
    preview=preview_report(s,eid,s.recipient)
    result=deliver_report(s,preview,execute=True)
    assert result['send_state']=='ACEPTADO' and result['logs']['supabase']['status']=='PENDING'
    assert deliver_report(s,preview,execute=True)['send_state']=='ACEPTADO' and len(calls)==1


def test_confirmation_and_delivery_evidence(prepared,monkeypatch,tmp_path):
    import demo_presentacion as gui
    s,eid,_=prepared;root=tk.Tk();root.withdraw();app=gui.DemoWindow(root,s)
    try:
        preview=preview_report(s,eid,s.recipient);app.show_result({'report_preview':preview});calls=[]
        monkeypatch.setattr(app,'start',lambda *args,**kwargs:calls.append(args))
        monkeypatch.setattr(gui.messagebox,'askyesno',lambda *a,**k:False)
        app.send_excel();assert not calls
        monkeypatch.setattr(gui.messagebox,'askyesno',lambda *a,**k:True)
        app.send_excel();assert len(calls)==1
        assert app.report_preview is None
        # Evidencia es requisito; aceptación HTTP no marca recepción.
        with Store(s.runtime/'state.sqlite3',s.root) as db:
            db.execute("UPDATE sends SET state='ACEPTADO' WHERE execution_id=?",(eid,))
            with pytest.raises(RPAError):reconcile(db,eid,'ENTREGA_CONFIRMADA',tmp_path/'missing')
            proof=tmp_path/'proof.txt';proof.write_text('Mock operator receipt evidence')
            reconcile(db,eid,'ENTREGA_CONFIRMADA',proof)
        assert preview_report(s,eid,s.recipient)['state']=='ENTREGA_CONFIRMADA'
    finally:app.close()
