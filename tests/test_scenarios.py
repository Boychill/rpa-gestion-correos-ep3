from collections import Counter
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import hashlib
import json
import sqlite3

import httpx
import pytest
from openpyxl import load_workbook

from rpa.classify import Classifier
from rpa.demo_actions import DemoActions
from rpa.gmail_campaign import prepare,send,load,summary,send_preview,directory,sender_usage
from rpa.runtime import RPAError, Budget
from rpa.scenarios import ScenarioConfig, CONTENT, TECHNICAL, generate, preset, save_config, load_config
from rpa.store import Store,utcnow,encode


@pytest.mark.parametrize('changes',[
    {'total':0},{'total':-1},{'normal':-1},{'special':25},{'normal':17},
    {'total':1001,'normal':995}, {'distribution':{'combined':5}},
    {'distribution':{'invented':6}}, {'distribution':{'combined':-1}},
    {'normal':True}, {'seed':'abc'}, {'interval':float('nan')}, {'interval':0}, {'limit':0},
])
def test_invalid_quantities_are_rejected_without_correction(changes):
    config=replace(ScenarioConfig(),**changes)
    with pytest.raises(RPAError):config.validate()


@pytest.mark.parametrize('name',['quick','real','load','stress'])
def test_presets_have_exact_distribution_and_reproducible_cases(name,settings):
    config=preset(name)
    rows=generate(config)
    assert rows==generate(config)
    assert len(rows)==config.total and sum(r['special'] for r in rows)==config.special
    assert Counter(r['type'] for r in rows if r['special'])==Counter({k:n for k,n in config.distribution.items() if n})
    assert len({r['scenario_id'] for r in rows})==config.total
    classifier=Classifier(settings.root/'config/reglas.json')
    for row in rows:
        if not row['technical']:assert classifier.classify(row['subject'])[0]==row['expected_category']
    if name=='real':
        repeated=[r for r in rows if r['type']=='shared_text']
        assert len(repeated)==2 and repeated[0]['subject']==repeated[1]['subject']


def test_gmail_refuses_technical_cases_and_preserves_unique_subjects(settings):
    config=ScenarioConfig(6,1,5,{k:1 for k in CONTENT},'GMAIL',42,1,2)
    manifest=prepare(settings,'sender@gmail.com','receiver@gmail.com',6,config=config)
    assert len({r['subject'] for r in manifest['messages']})==6
    assert all(manifest['tag'] in r['subject'] for r in manifest['messages'])
    assert manifest['test_config']['special']==5
    with pytest.raises(RPAError,match='LOCAL_ONLY'):
        replace(config,distribution={'missing_id':5}).validate()
    with pytest.raises(RPAError):replace(config,total=501,normal=496).validate()


def test_saved_configs_roundtrip_and_path_guard(settings):
    save_config(settings,'demo_12',preset('quick'))
    assert load_config(settings,'demo_12')==preset('quick')
    with pytest.raises(RPAError):save_config(settings,'../outside',preset('quick'))


@pytest.mark.parametrize('name',['quick','load','stress'])
def test_offline_full_flow_validates_exact_cases_and_preserves_excel(settings,monkeypatch,name):
    def forbidden(*args,**kwargs):raise AssertionError('Real network is forbidden')
    monkeypatch.setattr(httpx.HTTPTransport,'handle_request',forbidden)
    monkeypatch.setattr('rpa.gmail_auth.authorize',forbidden)
    config=preset(name)
    result=DemoActions(settings).simulation(config)
    report=result['scenario_report'];m=report['summary']
    assert m['configured']==config.total and m['special']==config.special
    assert m['passed']==config.total and m['failed']==0 and m['pending']==0
    assert m['special_validated']==config.special and m['accepted']==m['received']==0
    assert m['simulated_technical']==sum(config.distribution.get(k,0) for k in TECHNICAL)
    assert m['real_provider_failures']==m['unexpected_errors']==0
    assert result['logs']['supabase']['status']=='DISABLED'
    assert not (settings.runtime/'state.sqlite3').exists()
    assert not (settings.runtime/'campaigns').exists()
    rows=json.loads(Path(report['json_path']).read_text(encoding='utf-8'))['scenarios']
    assert all('subject' not in row and 'sender' not in row for row in rows)
    book=load_workbook(report['report_path'])
    assert set(book.sheetnames)=={'Resumen','Correos','Referencia_API','Ejecuciones'}
    assert book['Correos'].max_row==m['classified']+1
    assert book['Resumen']['B8'].value=='=SUM(B2:B7)' and book['Resumen']._charts
    assert book['Resumen'].max_row>=config.total
    book.close()


def test_all_technical_cases_and_page_validation_rollback(settings):
    with Store(settings.runtime/'state.sqlite3',settings.root) as db:
        db.execute('INSERT INTO executions(id,profile,signature,started,status,source) VALUES(?,?,?,?,?,?)',
                   ('test','test','test',utcnow(),'RUNNING','FIXTURE'))
        valid={'id':'one','subject':'Consulta','sender':'anon','received':utcnow()}
        with pytest.raises(RPAError,match='MESSAGE_ID_INVALID'):
            db.ingest('test','fixture','scope',[valid,{'subject':'invalid'}],'cursor','DELTA')
        assert db.row('SELECT COUNT(*) FROM messages')[0]==0
        assert db.row('SELECT COUNT(*) FROM checkpoints')[0]==0


def test_new_campaign_small_batches_resume_and_dry_run(settings):
    config=replace(preset('real'),total=6,normal=0,limit=2)
    manifest=prepare(settings,'sender@gmail.com','receiver@gmail.com',6,config=config)
    calls=[]
    def handle(request):calls.append(request);return httpx.Response(200,json={'id':str(len(calls))})
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        args=(settings,manifest['id'],manifest['sender'],manifest['recipient'])
        assert send(*args,client=client,token='mock',interval=0)['dry_run']
        assert not calls
        assert send(*args,client=client,token='mock',interval=0,execute=True)['accepted']==2
        assert send_preview(settings,manifest['id'])['to_attempt']==2
        assert send(*args,client=client,token='mock',interval=0,execute=True,limit=6)['accepted']==6
        assert send(*args,client=client,token='mock',interval=0,execute=True)['processed']==0
    assert len(calls)==6
    usage=sender_usage(settings,manifest['sender'])
    assert usage['accepted']==6 and usage['attempted']==6 and not usage['official_quota']
    assert sender_usage(settings,'another@gmail.com')['accepted']==0


def test_uncertain_campaign_cannot_bypass_preview_or_send(settings):
    m=prepare(settings,'sender@gmail.com','receiver@gmail.com',2)
    with httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(500))) as client:
        send(settings,m['id'],m['sender'],m['recipient'],client,'mock',interval=0,execute=True)
        assert send_preview(settings,m['id'])['to_attempt']==0
        with pytest.raises(RPAError,match='REVIEW_REQUIRED'):
            send(settings,m['id'],m['sender'],m['recipient'],client,'mock',interval=0,execute=True)


def test_old_manifest_and_database_stay_compatible(settings):
    m=prepare(settings,'sender@gmail.com','receiver@gmail.com',2)
    path=directory(settings,m['id'])/'mensajes.json';before=path.read_bytes()
    assert 'test_config' not in load(settings,m['id'])
    assert send_preview(settings,m['id'])['to_attempt']==2
    assert summary(settings,m['id'])['expected']==2
    assert before==path.read_bytes()


def test_report_failure_is_a_failed_audit_event(settings,monkeypatch):
    import rpa.orchestrator as orchestrator
    monkeypatch.setattr(orchestrator,'send_report',lambda *args,**kwargs:'ENVIO_INCIERTO')
    result=orchestrator.run(replace(settings,fixture_count=2))
    assert result['status']=='REVIEW' and result['error']=='REPORT_ENVIO_INCIERTO'
    with Store(settings.runtime/'state.sqlite3',settings.root) as db:
        row=db.row("SELECT result,code FROM events WHERE step_id='prepare_send'")
        assert tuple(row)==('FAILED','REPORT_ENVIO_INCIERTO')
        from rpa.cloud_logs import log_records
        record=next(r for r in log_records(db,result['execution_id']) if r['kind']=='execution')
        assert record['status']=='REVISION' and record['code']=='REPORT_ENVIO_INCIERTO'


def test_report_provider_status_logged_and_not_resent(settings,monkeypatch):
    from rpa.orchestrator import run
    from rpa.mail_send import send_report
    result=run(replace(settings,fixture_count=2));eid=result['execution_id']
    s=replace(settings,source='GMAIL',mailbox='receiver@gmail.com',gmail_sender_address='sender@gmail.com',
        gmail_receiver_address='receiver@gmail.com',mail_adapter='GMAIL',mail_mode='SEND',holiday_mode='LIVE',
        send_authorized=True,recipient='receiver@gmail.com',allowed_recipients='receiver@gmail.com')
    monkeypatch.setattr('rpa.gmail_auth.authorize',lambda *a,**k:SimpleNamespace(token='mock'))
    calls=[]
    def handle(request):calls.append(request);return httpx.Response(403,json={'error':{'errors':[{'reason':'forbidden'}]}})
    with Store(s.runtime/'state.sqlite3',s.root) as db,httpx.Client(transport=httpx.MockTransport(handle)) as client:
        for _ in range(2):
            assert send_report(s,db,eid,s.output/eid/'reporte.xlsx','<p>test</p>',client,'mock',Budget(60),promote_dry_run=True)=='ERROR'
        row=db.row("SELECT e.result,c.http_status,c.recovery FROM events e JOIN event_context c ON e.id=c.event_id WHERE e.step_id='report_delivery' ORDER BY e.id DESC LIMIT 1")
        assert tuple(row)==('FAILED',403,'REVIEW_NO_RESEND')
    assert len(calls)==1


def test_resumed_rate_uses_accumulated_time(settings):
    from rpa.orchestrator import run
    s=replace(settings,fixture_count=6)
    with Store(s.runtime/'state.sqlite3',s.root) as db:
        db.execute('INSERT INTO executions(id,profile,signature,started,status,source,metrics) VALUES(?,?,?,?,?,?,?)',
            ('resume',s.profile,s.signature,utcnow(),'PARTIAL','FIXTURE',encode({'total_active_seconds':20})))
    result=run(s,resume_id='resume');m=result['metrics']
    assert result['status']=='COMPLETED' and m['total_active_seconds']>=20
    assert m['messages_per_second']==round(6/m['total_active_seconds'],2)


def test_ui_requires_explicit_confirmation(settings,monkeypatch):
    import tkinter as tk
    import demo_presentacion as gui
    s=replace(settings,gmail_sender_address='sender@gmail.com',gmail_receiver_address='receiver@gmail.com')
    prepare(s,s.gmail_sender_address,s.gmail_receiver_address,2)
    root=tk.Tk();root.withdraw()
    try:
        window=gui.DemoWindow(root,s)
        calls=[]
        monkeypatch.setattr(gui.messagebox,'askyesno',lambda *a,**k:False)
        monkeypatch.setattr(window,'start',lambda *a,**k:calls.append(a))
        window.send();assert calls==[]
        monkeypatch.setattr(gui.messagebox,'askyesno',lambda *a,**k:True)
        window.send();assert len(calls)==1
        assert len(window.tabs.tabs())==7
        window.toggle_presentation();window.toggle_presentation();root.update_idletasks()
        root.after_cancel(window.after_id)
    finally:root.destroy()


def test_campaign_partial_reception_keeps_special_cases_pending(settings,monkeypatch):
    import rpa.orchestrator as orchestrator
    from rpa.gmail_campaign import analyze
    from rpa.holidays import Holidays
    from rpa.mail_read import Page
    config=replace(preset('real'),total=6,normal=0,limit=6)
    campaign=prepare(settings,'sender@gmail.com','receiver@gmail.com',6,config=config)
    with httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'id':'mock'}))) as client:
        send(settings,campaign['id'],campaign['sender'],campaign['recipient'],client,'mock',interval=0,execute=True)
    original=Holidays._load
    monkeypatch.setattr(Holidays,'_load',lambda self,year:original(Holidays(replace(self.s,holiday_mode='FIXTURE'),None),year))
    monkeypatch.setattr(orchestrator,'authenticate_gmail',lambda *args:'mock')
    class Reader:
        queries=0
        def __init__(self,*args):pass
        def page(self,cursor=None):
            items=campaign['messages'][2:] if cursor else campaign['messages'][:2]
            rows=[dict(id=str(m['sequence']),subject=m['subject'],received=campaign['created'],
                  sender='anon-'+hashlib.sha256(campaign['sender'].encode()).hexdigest()[:12],
                  rfc_message_id=m['message_id']) for m in items]
            return Page(rows,'next','DELTA')
    monkeypatch.setattr(orchestrator,'GmailReader',Reader)
    first=analyze(settings,campaign['id']);m=first['scenario_report']['summary']
    assert m['accepted']==6 and m['received']==2 and m['special_pending']==4
    assert m['special_validated']==2 and m['failed']==0 and not first['complete']
    second=analyze(settings,campaign['id']);n=second['scenario_report']['summary']
    assert n['received']==n['special_validated']==6 and n['special_pending']==0 and second['complete']
    assert n['duration_seconds']>=m['duration_seconds']


def test_local_auth_status_does_not_refresh_or_write(settings,monkeypatch,tmp_path):
    import rpa.gmail_auth as auth
    def forbidden(*a,**k):raise AssertionError('No refresh or token write allowed')
    monkeypatch.setattr(auth,'refresh',forbidden);monkeypatch.setattr(auth,'save_token',forbidden)
    monkeypatch.setattr(auth,'client_config',lambda s:{'installed':{'client_id':'client'}})
    monkeypatch.setattr(auth,'read_token',lambda p:{'role':'remitente','declared_account':'sender@gmail.com',
        'credentials':{'client_id':'client','scopes':auth.SCOPES['remitente']}})
    monkeypatch.setattr(auth.Credentials,'from_authorized_user_info',lambda *a,**k:SimpleNamespace(valid=True,refresh_token='mock'))
    result=auth.local_authorization_status(replace(settings,gmail_sender_address='sender@gmail.com'),'remitente')
    assert result['status']=='LOCAL_VALID' and not result['remote_checked']


def test_only_technical_simulation_still_exports_four_sheets(settings):
    config=ScenarioConfig(10,0,10,{k:1 for k in TECHNICAL},'SIMULATION',42,1,10)
    result=DemoActions(settings).simulation(config)
    assert result['status']=='NO_CHANGES' and result['validation_status']=='PASSED'
    assert result['scenario_report']['summary']['passed']==10
    book=load_workbook(result['report_path'])
    assert len(book.sheetnames)==4 and book['Correos'].max_row==1
    book.close()
