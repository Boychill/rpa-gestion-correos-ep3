import threading
from dataclasses import replace
import httpx
from rpa.demo_actions import DemoActions
from rpa.gmail_campaign import prepare,send,summary


def test_presentation_simulation_does_not_use_gmail(settings,monkeypatch):
    def forbidden(*args,**kwargs):
        raise AssertionError('No network allowed in offline demo')
    monkeypatch.setattr(httpx.Client,'get',forbidden)
    monkeypatch.setattr(httpx.Client,'post',forbidden)
    result=DemoActions(settings).simulation(6)
    assert result['simulation'] and result['status']=='COMPLETED'
    assert result['metrics']['processed']==6 and result['send_state']=='DRY_RUN'
    assert result['logs']['supabase']['status']=='DISABLED'


def test_preparing_presentation_batch_never_sends(settings,monkeypatch):
    s=replace(settings,gmail_sender_address='sender@gmail.com',gmail_receiver_address='receiver@gmail.com')
    result=DemoActions(s).prepare(6)
    assert summary(s,result['id'])['states']=={'PENDING':6}


def test_stop_request_keeps_remaining_messages_for_resume(settings):
    campaign=prepare(settings,'sender@gmail.com','receiver@gmail.com',3)
    stopped=threading.Event()
    calls=[]
    def handle(request):
        calls.append(request);stopped.set()
        return httpx.Response(200,json={'id':'first'})
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        result=send(settings,campaign['id'],campaign['sender'],campaign['recipient'],client,'token',
                    interval=0,execute=True,stop_event=stopped)
    assert result['error']=='STOP_REQUESTED' and result['states']=={'ACCEPTED':1,'PENDING':2}
    assert len(calls)==1


def test_cli_returns_incomplete_when_delivery_is_not_confirmed(settings,monkeypatch):
    import sys
    import scripts.gmail_demo as cli
    monkeypatch.setattr(sys,'argv',['gmail_demo.py','run','--campaign','example','--sender','sender@gmail.com',
        '--recipient','receiver@gmail.com','--count','1','--execute'])
    monkeypatch.setattr(cli.Settings,'load',lambda _:settings)
    monkeypatch.setattr(cli,'load',lambda *args:{'count':1})
    monkeypatch.setattr(cli,'send',lambda *args,**kwargs:{'accepted':1,'all_accepted':True})
    monkeypatch.setattr(cli,'analyze',lambda *args:{'complete':False})
    monkeypatch.setattr('rpa.gmail.authenticate_gmail',lambda *args,**kwargs:'fake')
    assert cli.main()==1
