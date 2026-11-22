"""Consolidado de todos los mensajes de un dataset, aunque lleguen en varias ejecuciones."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
import time
import uuid
import httpx
from rpa.config import timestamp
from rpa.gmail_campaign import load
from rpa.excel import build_report, verify_report
from rpa.holidays import Holidays
from rpa.http import ReaderHTTP
from rpa.mail_send import render, send_report
from rpa.log_files import finish_logging
from rpa.runtime import Audit, Budget, RPAError, profile_lock
from rpa.store import Store, utcnow, encode


def export_campaign(settings, campaign_id):
    manifest = load(settings, campaign_id)
    expected = {item['subject']: item['expected'] for item in manifest['messages']}
    sender = 'anon-'+hashlib.sha256(manifest['sender'].encode()).hexdigest()[:12]
    configured = replace(settings, source='GMAIL', mailbox=manifest['recipient'],
        gmail_receiver_address=manifest['recipient'], gmail_campaign_tag=manifest['tag'],
        period_start=(timestamp(manifest['created'])-timedelta(days=1)).isoformat(),
        period_end=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat(),
        holiday_mode='LIVE', mail_adapter='GMAIL', mail_mode='DRY_RUN')
    execution_id = str(uuid.uuid5(uuid.UUID(campaign_id), 'consolidated-report-v1'))
    with profile_lock(settings.runtime/'locks/state.lock'), Store(settings.runtime/'state.sqlite3', settings.root) as store:
        old = store.row('SELECT status FROM executions WHERE id=?', (execution_id,))
        prior_send = store.row('SELECT state,sha256,size FROM sends WHERE execution_id=?', (execution_id,))
        path = settings.output/execution_id/'reporte.xlsx'
        if old and (old['status']=='COMPLETED' or prior_send and prior_send['state']!='DRY_RUN'):
            verified = verify_report(path,execution_id,len(expected))
            if prior_send and (verified['sha256']!=prior_send['sha256'] or verified['size']!=prior_send['size']):
                raise RPAError('ATTACHMENT_CHANGED')
            return dict(execution_id=execution_id, path=str(path), count=len(expected), reused=True,
                        **verified)
        items, seen = [], set()
        for row in store.rows("SELECT payload,category,rule,rules_version FROM messages WHERE mailbox=? AND state='CLASSIFIED'", (configured.identity,)):
            item = json.loads(row['payload'])
            subject = item['subject']
            if subject not in expected or item['sender']!=sender:
                continue
            if subject in seen or row['category']!=expected[subject]:
                raise RPAError('CAMPAIGN_CLASSIFICATION_REVIEW')
            seen.add(subject)
            items.append(dict(item, category=row['category'],rule=row['rule'],rules_version=row['rules_version']))
        if len(items)!=len(expected):
            raise RPAError('CAMPAIGN_RECEPTION_INCOMPLETE')
        started, timer = utcnow(), time.monotonic()
        store.execute('INSERT OR IGNORE INTO executions(id,profile,signature,started,status,source) VALUES(?,?,?,?,?,?)',
            (execution_id,'gmail-consolidated',campaign_id,started,'RUNNING','GMAIL_CONSOLIDATED'))
        audit = Audit(store,execution_id,settings.runtime/'logs')
        result, status = {}, 'REVIEW'
        try:
            with httpx.Client() as client:
                budget = Budget(300)
                http = ReaderHTTP(client,configured,store,execution_id,audit,budget)
                with audit.step('consolidated_report',context={'dataset':campaign_id,'role':'receptor'}):
                    calendar = Holidays(configured,http)
                    calendar.apply(items)
                    if calendar.errors:
                        raise RPAError('HOLIDAY_REFERENCE_REQUIRED')
                    path = build_report(configured,execution_id,items,list(calendar.loaded.values()),started,utcnow(),time.monotonic()-timer)
                    if configured.require_excel:
                        from rpa.excel import desktop_excel
                        desktop_excel(configured,path,min(configured.batch_seconds,budget.remaining()))
                    metrics = {'processed':len(items),'classified':len(items),'failed':0}
                    body = render(configured,execution_id,metrics,time.monotonic()-timer)
                    send_report(configured,store,execution_id,path,body,client,None,budget)
                    result = dict(execution_id=execution_id,path=str(path),count=len(items),mail_mode='DRY_RUN',
                                  **verify_report(path,execution_id,len(items)))
                    status = 'COMPLETED'
        finally:
            metrics = {'processed':len(items),'classified':len(items),'failed':int(status!='COMPLETED'),
                       'duration_seconds':round(time.monotonic()-timer,3)}
            store.execute('UPDATE executions SET status=?,finished=?,metrics=? WHERE id=?',
                          (status,utcnow(),encode(metrics),execution_id))
            audit.close()
            result['logs'] = finish_logging(settings,store,execution_id)
            (settings.runtime/'campaigns'/campaign_id/'reporte_consolidado.json').write_text(encode(result),encoding='utf-8')
        return result
