"""Selección, vista previa y envío explícito del reporte original con outbox existente."""
from dataclasses import replace
from pathlib import Path
import json
import sqlite3
import uuid

import httpx
from openpyxl import load_workbook

from rpa.excel import verify_report
from rpa.log_files import finish_logging
from rpa.mail_send import render, send_report
from rpa.runtime import Audit, Budget, RPAError, profile_lock
from rpa.store import Store, utcnow


def _location(settings, key):
    parts = Path(key).parts
    if not (len(parts) == 1 or len(parts) == 3 and parts[0] == 'presentacion'):
        raise RPAError('REPORT_SELECTION_INVALID')
    try:
        uuid.UUID(parts[-1])
        if len(parts) == 3: uuid.UUID(parts[1])
    except ValueError as exc:
        raise RPAError('REPORT_SELECTION_INVALID') from exc
    folder = (settings.output / key).resolve()
    runtime = (settings.runtime / Path(*parts[:-1])).resolve()
    if not folder.is_relative_to(settings.output.resolve()) or not runtime.is_relative_to(settings.runtime.resolve()):
        raise RPAError('REPORT_SELECTION_INVALID')
    return folder, runtime, parts[-1]


def available_reports(settings):
    reports = []
    for pattern in ('*/adjunto_manifest.json', 'presentacion/*/*/adjunto_manifest.json'):
        for path in settings.output.glob(pattern):
            key = path.parent.relative_to(settings.output).as_posix()
            reports.append({'key': key, 'execution_id': path.parent.name,
                            'label': ('Local · ' if key.startswith('presentacion/') else 'Operativa · ') + path.parent.name,
                            'modified': path.stat().st_mtime})
    return sorted(reports, key=lambda row: row['modified'], reverse=True)


def _read(settings, key):
    folder, runtime, eid = _location(settings, key)
    path = folder / 'reporte.xlsx'
    if not path.is_file() or not path.resolve().is_relative_to(folder):
        raise RPAError('REPORT_FILE_MISSING')
    dbpath = runtime / 'state.sqlite3'
    if not dbpath.is_file(): raise RPAError('REPORT_STATE_MISSING')
    with sqlite3.connect(dbpath.as_uri()+'?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        run = db.execute('SELECT * FROM executions WHERE id=?', (eid,)).fetchone()
        sent = db.execute('SELECT * FROM sends WHERE execution_id=?', (eid,)).fetchone()
        if not run or not sent: raise RPAError('REPORT_STATE_MISSING')
        run, sent = dict(run), dict(sent)
    verified = verify_report(path, eid)
    manifest = json.loads((folder/'adjunto_manifest.json').read_text(encoding='utf-8'))
    if (manifest.get('execution_id') != eid or any(verified[k] != sent[k] or verified[k] != manifest.get(k)
                                                for k in ('sha256', 'size'))):
        raise RPAError('ATTACHMENT_CHANGED')
    return folder, runtime, eid, path, run, sent, verified


def preview_report(settings, key, recipient):
    folder, runtime, eid, path, run, sent, verified = _read(settings, key)
    recipient = recipient.strip().lower()
    campaign = run['signature'] if run['source'] == 'GMAIL_CONSOLIDATED' else None
    # El correo no lee el buzón: evitar heredar un filtro ALL sin dataset.
    configured = replace(settings, runtime=runtime, output=folder.parent, source='GMAIL',
        mailbox=settings.gmail_receiver_address or settings.mailbox, gmail_label='INBOX', gmail_campaign_tag='',
        mail_mode='SEND', mail_adapter='GMAIL', holiday_mode='LIVE', recipient=recipient, send_authorized=True)
    reason = None
    if run['source'] not in ('GMAIL', 'GMAIL_CONSOLIDATED'):
        reason = 'REPORT_LOCAL_ONLY'
    elif run['status'] not in ('COMPLETED', 'NO_CHANGES'):
        reason = 'REPORT_EXECUTION_REVIEW'
    elif sent['state'] != 'DRY_RUN':
        reason = 'REPORT_'+sent['state']
    elif verified['size'] >= 3_000_000:
        reason = 'ATTACHMENT_TOO_LARGE'
    try: configured.validate()
    except ValueError: reason = reason or 'REPORT_RECIPIENT_NOT_ALLOWED'
    book = load_workbook(path, read_only=True)
    try:
        origins = {row[5] for row in book['Referencia_API'].iter_rows(min_row=2, values_only=True)}
        if not origins or not origins.issubset({'real', 'cache'}): reason = reason or 'REPORT_REAL_CALENDAR_REQUIRED'
        count = book['Correos'].max_row-1
    finally: book.close()
    metrics = json.loads(run['metrics'])
    body = render(replace(configured, source=run['source'], holiday_mode='LIVE' if origins <= {'real', 'cache'} else 'FIXTURE'),
                  eid, {'processed':count, 'classified':metrics.get('classified', count), 'failed':metrics.get('failed', 0)},
                  metrics.get('total_active_seconds', metrics.get('duration_seconds', 0)))
    original_body = folder/'correo_reporte.html'
    if original_body.is_file() and original_body.resolve().is_relative_to(folder):
        body = original_body.read_text(encoding='utf-8')
    return {'key':key, 'execution_id':eid, 'campaign_id':campaign, 'path':str(path), 'filename':path.name,
            'sender':settings.gmail_sender_address, 'recipient':recipient, 'subject':f'[RPA-EP3] Reporte {eid}',
            'body':body, 'count':count, 'state':sent['state'], 'can_send':reason is None, 'reason':reason, **verified}


def deliver_report(settings, preview, *, execute=False):
    """Volver a validar bajo lock antes del único POST; nunca promover simulaciones."""
    if not execute: return preview_report(settings, preview['key'], preview['recipient'])
    folder, runtime, eid = _location(settings, preview['key'])
    with profile_lock(runtime/'locks/state.lock'):
        current = preview_report(settings, preview['key'], preview['recipient'])
        if current['sha256'] != preview['sha256'] or current['sender'] != preview['sender']:
            raise RPAError('REPORT_PREVIEW_CHANGED')
        if current['state'] in ('ACEPTADO', 'ENTREGA_CONFIRMADA', 'ENVIO_INCIERTO', 'ERROR', 'PENDIENTE_CUOTA'):
            return {'execution_id':eid, 'send_state':current['state'], 'reused':True}
        if not current['can_send']: raise RPAError(current['reason'])
        configured = replace(settings, runtime=runtime, output=folder.parent, source='GMAIL',
            mailbox=settings.gmail_receiver_address or settings.mailbox, gmail_label='INBOX', gmail_campaign_tag='',
            mail_mode='SEND', mail_adapter='GMAIL', holiday_mode='LIVE', recipient=current['recipient'], send_authorized=True)
        with Store(runtime/'state.sqlite3', settings.root) as store, httpx.Client(follow_redirects=False) as client:
            audit = Audit(store, eid, runtime/'logs')
            try:
                with audit.step('gmail_consolidated_send', context={'role':'remitente', 'dataset':current['campaign_id'], 'job_id':eid}) as outcome:
                    state = send_report(configured, store, eid, Path(current['path']), preview['body'], client, None,
                                        Budget(120), promote_dry_run=True)
                    if state not in ('ACEPTADO', 'ENTREGA_CONFIRMADA'):
                        outcome.update(result='FAILED', code='REPORT_'+state)
                store.execute('UPDATE executions SET status=?,finished=? WHERE id=?',
                    ('COMPLETED' if state in ('ACEPTADO', 'ENTREGA_CONFIRMADA') else 'REVIEW', utcnow(), eid))
            except Exception:
                store.execute("UPDATE executions SET status='REVIEW',finished=? WHERE id=?", (utcnow(), eid))
                raise
            finally:
                audit.close()
                logs = finish_logging(configured, store, eid)
    return {'execution_id':eid, 'send_state':state, 'logs':logs, 'report_path':current['path']}
