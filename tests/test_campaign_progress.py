import httpx
from rpa.gmail_campaign import prepare, send


def test_progress_keeps_counts_without_reloading_manifest_per_message(settings, monkeypatch):
    import rpa.gmail_campaign as campaign
    batch=prepare(settings,'sender@gmail.com','receiver@gmail.com',24)
    original=campaign.summary;reads=[];events=[]
    def counted(*args):
        reads.append(1);return original(*args)
    monkeypatch.setattr(campaign,'summary',counted)
    with httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'id':'mock'}))) as client:
        result=send(settings,batch['id'],batch['sender'],batch['recipient'],client,'mock',interval=0,execute=True,limit=12,progress=events.append)
        assert result['attempted']==12 and result['accepted']==12 and result['review']==0
        assert [e['accepted'] for e in events]==list(range(1,13))
        assert len(reads)==1
        events.clear()
        result=send(settings,batch['id'],batch['sender'],batch['recipient'],client,'mock',interval=0,execute=True,progress=events.append)
        assert [e['accepted'] for e in events]==list(range(13,25))
        assert result['attempted']==24 and len(reads)==2
