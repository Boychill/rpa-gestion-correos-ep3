"""Enviar una única copia del consolidado preparado; simulación por defecto."""
from pathlib import Path
from dataclasses import replace
import argparse
import json
import sys
import time
import httpx
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from rpa.config import Settings
from rpa.campaign_report import export_campaign
from rpa.gmail_campaign import load
from rpa.mail_send import render, send_report
from rpa.runtime import Audit, Budget, RPAError, profile_lock
from rpa.store import Store, utcnow
from rpa.log_files import finish_logging


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign',required=True)
    parser.add_argument('--recipient',required=True)
    parser.add_argument('--execute',action='store_true')
    args=parser.parse_args()
    settings=Settings.load(Path(__file__).resolve().parents[1])
    report=export_campaign(settings,args.campaign)
    if not args.execute:
        print(json.dumps(dict(report,mail_mode='DRY_RUN'),indent=2))
        return
    manifest=load(settings,args.campaign)
    s=replace(settings,source='GMAIL',mailbox=manifest['recipient'],mail_mode='SEND',mail_adapter='GMAIL',
              holiday_mode='LIVE',send_authorized=True,recipient=args.recipient)
    s.validate()  # El destinatario debe estar en ALLOWED_RECIPIENTS de la configuración local.
    eid=report['execution_id']
    with profile_lock(s.runtime/'locks/state.lock'), Store(s.runtime/'state.sqlite3',s.root) as store, httpx.Client() as client:
        audit=Audit(store,eid,s.runtime/'logs')
        try:
            metrics={'processed':report['count'],'classified':report['count'],'failed':0}
            body=render(s,eid,metrics,0)
            with audit.step('gmail_consolidated_send',context={'role':'remitente','dataset':args.campaign,'job_id':eid}):
                state=send_report(s,store,eid,Path(report['path']),body,client,None,Budget(120),promote_dry_run=True)
                if state not in ('ACEPTADO','ENTREGA_CONFIRMADA'):
                    store.execute("UPDATE executions SET status='REVIEW',finished=? WHERE id=?",(utcnow(),eid))
                    raise RPAError('REPORT_'+state)
            store.execute('UPDATE executions SET status=?,finished=? WHERE id=?',
                ('COMPLETED' if state in ('ACEPTADO','ENTREGA_CONFIRMADA') else 'REVIEW',utcnow(),eid))
        finally:
            audit.close()
            logs=finish_logging(s,store,eid)
    print(json.dumps({'execution_id':eid,'send_state':state,'logs':logs},indent=2))


if __name__=='__main__':
    try:
        main()
    except (RPAError,ValueError) as exc:
        print(exc.code if isinstance(exc,RPAError) else 'CONFIG_INVALID')
        raise SystemExit(1)
