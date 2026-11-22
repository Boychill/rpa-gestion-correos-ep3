"""Entrada: reporte verificado + destinatario autorizado. Salida: outbox durable.
No repetir un POST/Send ante resultado ambiguo ni tras una caída del proceso.
"""
import base64
from html import escape
import json
from string import Template
import subprocess
import sys
import hashlib
import time
from email.message import EmailMessage
from email.policy import SMTP

from rpa.excel import verify_report
from rpa.runtime import Audit, RPAError
from rpa.store import utcnow


def render(settings, execution_id, metrics, duration):
    values = dict(execution_id=execution_id, date=utcnow(),
                  period=f"{settings.period_start} — {settings.period_end}",
                  processed=metrics["processed"], classified=metrics["classified"], failed=metrics["failed"],
                  duration=f"{duration:.3f}", attachment="reporte.xlsx", source=settings.source,
                  holidays=settings.holiday_mode)
    try:
        body = Template((settings.root / "templates/correo_reporte.html").read_text(encoding="utf-8")).substitute(
            {key: escape(str(value), quote=True) for key, value in values.items()})
    except (ValueError, KeyError) as exc:
        raise RPAError("MAIL_TEMPLATE_INVALID") from exc
    if "${" in body:
        raise RPAError("MAIL_TEMPLATE_INVALID")
    return body


def send_report(settings, store, execution_id, path, body, client, token, budget, adapter=None, promote_dry_run=False):
    """Auditar también los resultados fallidos que no lanzan una excepción."""
    audit = Audit(store, execution_id, settings.runtime / 'logs')
    started, timer = utcnow(), time.monotonic()
    previous = store.row('SELECT state FROM sends WHERE execution_id=?', (execution_id,))
    try:
        state = _send_report(settings, store, execution_id, path, body, client, token, budget,
                             adapter, promote_dry_run, audit)
        row = store.row('SELECT reconciliation FROM sends WHERE execution_id=?', (execution_id,))
        details = json.loads(row[0]) if row and row[0] and row[0].startswith('{') else {}
        failed = state in {'ENVIO_INCIERTO', 'ERROR', 'PENDIENTE_CUOTA'}
        recovery = ('REVIEW_NO_RESEND' if state in {'ENVIO_INCIERTO', 'ERROR'} else
                    'WAIT_QUOTA' if state == 'PENDIENTE_CUOTA' else 'NONE')
        audit.event('report_delivery', started, (time.monotonic()-timer)*1000,
            result='FAILED' if failed else 'OK', code='REPORT_'+state,
            context={'role':'remitente', 'job_id':execution_id,
                     'http_status':details.get('http_status'),
                     'recovery':recovery if failed else 'NO_REPEAT' if previous else recovery})
        return state
    except Exception as exc:
        audit.event('report_delivery', started, (time.monotonic()-timer)*1000, result='FAILED',
                    code=exc.code if isinstance(exc, RPAError) else type(exc).__name__,
                    context={'role':'remitente', 'job_id':execution_id, 'recovery':'REVIEW_NO_RESEND'})
        raise
    finally:
        audit.close()


def _send_report(settings, store, execution_id, path, body, client, token, budget,
                 adapter=None, promote_dry_run=False, audit=None):
    old = store.row("SELECT * FROM sends WHERE execution_id=?", (execution_id,))
    promote = bool(old and old['state']=='DRY_RUN' and promote_dry_run and settings.mail_mode=='SEND')
    if old and not promote:
        if old["state"] in {"PREPARADO", "EN_ENVIO"}:
            store.execute("UPDATE sends SET state='ENVIO_INCIERTO',updated=? WHERE execution_id=?", (utcnow(), execution_id))
            return "ENVIO_INCIERTO"
        return old["state"]
    settings.validate()
    manifest = verify_report(path, execution_id)
    if promote and (manifest['sha256'] != old['sha256'] or manifest['size'] != old['size']):
        raise RPAError('ATTACHMENT_CHANGED')
    if manifest["size"] >= 3_000_000 and settings.mail_mode == "SEND":
        raise RPAError("ATTACHMENT_TOO_LARGE")
    subject = f"[RPA-EP3] Reporte {execution_id}"
    (path.parent / "correo_reporte.html").write_text(body, encoding="utf-8")
    (path.parent / "adjunto_manifest.json").write_text(json.dumps(dict(manifest, execution_id=execution_id)), encoding="utf-8")
    budget.remaining()
    gmail_raw = None
    if settings.mail_adapter == 'GMAIL':
        message = EmailMessage(policy=SMTP)
        message['From'], message['To'] = settings.gmail_sender_address, settings.recipient
        message['Subject'] = subject
        message['Message-ID'] = f'<rpa.report.{execution_id}@gmail.com>'
        message['X-RPA-Execution-ID'] = execution_id
        message.set_content('Reporte consolidado de gestión de correos. Consulta el archivo Excel adjunto.')
        message.add_alternative(body, subtype='html')
        attachment = path.read_bytes()
        if hashlib.sha256(attachment).hexdigest() != manifest['sha256']:
            raise RPAError('ATTACHMENT_CHANGED')
        message.add_attachment(attachment, maintype='application',
            subtype='vnd.openxmlformats-officedocument.spreadsheetml.sheet', filename='reporte.xlsx')
        gmail_raw = base64.urlsafe_b64encode(message.as_bytes()).decode('ascii')
        if settings.mail_mode == 'SEND' and not adapter:
            from rpa.gmail_auth import authorize
            token = authorize(settings, budget, 'remitente').token
    store.execute("INSERT OR REPLACE INTO sends VALUES(?,?,?,?,?,?,?,NULL)",
        (execution_id, "PREPARADO", manifest["sha256"], manifest["size"], utcnow(), utcnow(), settings.mail_adapter))
    audit.event('report_prepared', utcnow(), 0, code='REPORT_PREPARADO', context={'role':'remitente','job_id':execution_id})
    # La escritura anterior ocurre antes de cualquier efecto externo.
    state = "DRY_RUN"
    if settings.mail_mode == "SEND":
        try:
            store.execute("UPDATE sends SET state='EN_ENVIO',updated=? WHERE execution_id=?", (utcnow(), execution_id))
            audit.event('report_attempted', utcnow(), 0, code='REPORT_INTENTADO', context={'role':'remitente','job_id':execution_id})
            if adapter:
                adapter()
            elif settings.mail_adapter == 'GMAIL':
                from rpa.gmail_errors import error_code
                response = client.post('https://gmail.googleapis.com/gmail/v1/users/me/messages/send',
                    headers={'Authorization':'Bearer '+token}, json={'raw':gmail_raw},
                    timeout=min(settings.http_timeout, budget.remaining()))
                code = error_code(response)
                if response.status_code == 200 and response.json().get('id'):
                    store.execute('UPDATE sends SET reconciliation=? WHERE execution_id=?',
                        (json.dumps({'gmail_id':response.json()['id'], 'send_job_id':execution_id, 'http_status':response.status_code}), execution_id))
                else:
                    state = ('PENDIENTE_CUOTA' if code == 'GMAIL_DAILY_QUOTA' else
                             'ERROR' if response.status_code in (400, 401, 403, 404) else 'ENVIO_INCIERTO')
                    store.execute('UPDATE sends SET state=?,updated=?,reconciliation=? WHERE execution_id=?',
                        (state, utcnow(), json.dumps({'code':code,'send_job_id':execution_id,'http_status':response.status_code}), execution_id))
                    return state
            elif settings.mail_adapter == "GRAPH":
                response = client.post("https://graph.microsoft.com/v1.0/me/sendMail",
                    headers={"Authorization": "Bearer " + token}, timeout=min(settings.http_timeout, budget.remaining()),
                    json={"message": {"subject": subject, "body": {"contentType": "HTML", "content": body},
                        "toRecipients": [{"emailAddress": {"address": settings.recipient}}],
                        "internetMessageHeaders": [{"name": "x-rpa-execution-id", "value": execution_id}],
                        "attachments": [{"@odata.type": "#microsoft.graph.fileAttachment", "name": "reporte.xlsx",
                           "contentBytes": base64.b64encode(path.read_bytes()).decode()}]}, "saveToSentItems": True})
                if response.status_code != 202:
                    raise RPAError("SEND_NOT_ACCEPTED")
                store.execute('UPDATE sends SET reconciliation=? WHERE execution_id=?',
                              (json.dumps({'http_status':202}), execution_id))
            else:
                payload = path.parent / "outlook_request.private.json"
                try:
                    payload.write_text(json.dumps({"mailbox": settings.mailbox, "recipient": settings.recipient,
                        "subject": subject, "html": body, "attachment": str(path.resolve())}), encoding="utf-8")
                    result = subprocess.run([sys.executable, str(settings.root / "scripts/office_worker.py"),
                        "outlook", str(payload.resolve()), str((path.parent / "outlook_evidence.json").resolve())],
                        capture_output=True, timeout=budget.remaining(), creationflags=subprocess.CREATE_NO_WINDOW)
                    if result.returncode:
                        raise RPAError("OUTLOOK_SEND_UNKNOWN")
                finally:
                    payload.unlink(missing_ok=True)
            state = "ACEPTADO"
        except Exception:
            state = "ENVIO_INCIERTO"
    store.execute("UPDATE sends SET state=?,updated=? WHERE execution_id=?", (state, utcnow(), execution_id))
    return state


def reconcile(store, execution_id, state, evidence_path):
    if state not in {"ACEPTADO", "ENTREGA_CONFIRMADA"}:
        raise RPAError("RECONCILIATION_STATE_INVALID")
    old = store.row("SELECT state FROM sends WHERE execution_id=?", (execution_id,))
    if not old or old[0] not in {"ENVIO_INCIERTO", "PREPARADO", "ACEPTADO"}:
        raise RPAError("RECONCILIATION_NOT_APPLICABLE")
    from rpa.excel import file_hash
    if not evidence_path.is_file() or evidence_path.stat().st_size == 0:
        raise RPAError("RECONCILIATION_EVIDENCE_REQUIRED")
    # El operador verifica la evidencia; un HTTP 202 jamás confirma entrega.
    store.execute("UPDATE sends SET state=?,updated=?,reconciliation=? WHERE execution_id=?",
                  (state, utcnow(), file_hash(evidence_path), execution_id))
