"""Lotes sintéticos Gmail: persistencia por mensaje, sin reenvío tras respuesta incierta."""
from collections import Counter
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.policy import SMTP
import base64
import csv
import hashlib
import json
import math
import re
import sqlite3
import time
import uuid

import httpx

from rpa.gmail import BASE, authenticate_gmail
from rpa.log_files import finish_logging
from rpa.runtime import Audit, Budget, RPAError, profile_lock
from rpa.store import Store, encode, utcnow

EXAMPLES = [
    ('Solicitud', 'Solicitud de acceso al entorno de laboratorio'),
    ('Consulta', 'Consulta sobre horario de la demostración'),
    ('Reclamo', 'Reclamo de prueba por retraso simulado'),
    ('Urgente', 'Urgente: incidente simulado de laboratorio'),
    ('Información', 'Información sobre actividad de laboratorio'),
    ('Otros', 'Saludos del equipo de laboratorio'),
]


def directory(settings, campaign_id):
    if str(uuid.UUID(campaign_id)) != campaign_id:
        raise RPAError('CAMPAIGN_ID_INVALID')
    return settings.runtime / 'campaigns' / campaign_id


def prepare(settings, sender, recipient, count=500, *, config=None):
    if type(count) is not int or not 1 <= count <= 500:
        raise RPAError('CAMPAIGN_COUNT_INVALID')
    for address in (sender, recipient):
        if not re.fullmatch(r'[A-Za-z0-9._%+-]+@gmail\.com', address):
            raise RPAError('CAMPAIGN_GMAIL_ADDRESS_REQUIRED')
    campaign_id, created = str(uuid.uuid4()), utcnow()
    tag = 'RPA-TEST-' + campaign_id
    scenarios = None
    if config is not None:
        from rpa.scenarios import generate
        config.validate()
        if config.mode != 'GMAIL' or config.total != count:
            raise RPAError('CAMPAIGN_CONFIG_MISMATCH')
        scenarios = generate(config)
    messages = []
    for i in range(count):
        category, subject = EXAMPLES[i % len(EXAMPLES)]
        if scenarios:
            category, subject = scenarios[i]['expected_category'], scenarios[i]['subject']
        messages.append(dict(sequence=i+1, expected=category,
            subject=f'[{tag}] {i+1:03d}/{count} {subject}',
            body=f'Mensaje sintético {i+1} de {count} para probar la clasificación RPA.\n'
                 f'Categoría esperada: {category}.\nNo representa una petición ni incidente real.\n'
                 f'Identificador del lote: {campaign_id}\n',
            message_id=f'<rpa.{campaign_id}.{i+1}@gmail.com>'))
        if scenarios:
            messages[-1]['scenario'] = scenarios[i]
    manifest = dict(id=campaign_id, created=created, sender=sender.lower(), recipient=recipient.lower(),
                    count=count, tag=tag, expected=dict(Counter(m['expected'] for m in messages)), messages=messages)
    if config is not None:
        manifest['test_config'] = config.to_dict()
    folder = directory(settings, campaign_id)
    folder.mkdir(parents=True)
    raw = encode(manifest).encode('utf-8')
    (folder / 'mensajes.json').write_bytes(raw)
    with sqlite3.connect(folder / 'campaign.sqlite3') as db:
        db.executescript('''CREATE TABLE manifest(sha256 TEXT NOT NULL);
            CREATE TABLE deliveries(sequence INTEGER PRIMARY KEY, state TEXT NOT NULL DEFAULT 'PENDING',
              attempts INTEGER NOT NULL DEFAULT 0, gmail_id TEXT, code TEXT, updated TEXT, due REAL NOT NULL DEFAULT 0);''')
        db.execute('INSERT INTO manifest VALUES(?)', (hashlib.sha256(raw).hexdigest(),))
        db.executemany('INSERT INTO deliveries(sequence) VALUES(?)', [(i+1,) for i in range(count)])
    return manifest


def load(settings, campaign_id):
    folder = directory(settings, campaign_id)
    raw = (folder / 'mensajes.json').read_bytes()
    with sqlite3.connect(folder / 'campaign.sqlite3') as db:
        if db.execute('SELECT sha256 FROM manifest').fetchone()[0] != hashlib.sha256(raw).hexdigest():
            raise RPAError('CAMPAIGN_MODIFIED')
    return json.loads(raw)


def summary(settings, campaign_id):
    manifest = load(settings, campaign_id)
    with sqlite3.connect(directory(settings, campaign_id) / 'campaign.sqlite3') as db:
        states = dict(db.execute('SELECT state,COUNT(*) FROM deliveries GROUP BY state'))
    accepted = states.get('ACCEPTED', 0) + states.get('RECEIVED', 0)
    return dict(campaign_id=campaign_id, expected=manifest['count'], states=states,
                accepted=accepted, received=states.get('RECEIVED', 0), all_accepted=accepted==manifest['count'])


def raw_message(manifest, item):
    message = EmailMessage(policy=SMTP)
    message['From'], message['To'] = manifest['sender'], manifest['recipient']
    message['Subject'], message['Message-ID'] = item['subject'], item['message_id']
    message['X-RPA-Campaign'] = manifest['id']
    message.set_content(item['body'])
    return base64.urlsafe_b64encode(message.as_bytes()).decode('ascii')


def send(settings, campaign_id, sender, recipient, client=None, token=None, interval=None, execute=False, limit=None, stop_event=None, progress=None):
    manifest = load(settings, campaign_id)
    if (sender.lower(), recipient.lower()) != (manifest['sender'], manifest['recipient']):
        raise RPAError('CAMPAIGN_ACCOUNT_MISMATCH')
    if ((settings.gmail_sender_address and sender.lower() != settings.gmail_sender_address.lower())
            or (settings.gmail_receiver_address and recipient.lower() != settings.gmail_receiver_address.lower())):
        raise RPAError('CAMPAIGN_ACCOUNT_NOT_ALLOWED')
    if not execute:
        return dict(summary(settings, campaign_id), dry_run=True)
    controls = manifest.get('test_config', {})
    interval = controls.get('interval', 1.0) if interval is None else interval
    limit = controls.get('limit') if limit is None else limit
    if not isinstance(interval, (int, float)) or not math.isfinite(interval) or not 0 <= interval <= 60:
        raise RPAError('CAMPAIGN_INTERVAL_INVALID')
    if interval < 1 and client is None:
        raise RPAError('CAMPAIGN_INTERVAL_INVALID')
    if limit is not None and (type(limit) is not int or not 1 <= limit <= manifest['count']):
        raise RPAError('CAMPAIGN_LIMIT_INVALID')
    folder = directory(settings, campaign_id)
    budget, started, timer = Budget(settings.execution_seconds), utcnow(), time.monotonic()
    execution_id = str(uuid.uuid4())
    own_client = client is None
    with profile_lock(folder / 'send.lock'), sqlite3.connect(folder / 'campaign.sqlite3') as db, \
            Store(settings.runtime / 'state.sqlite3', settings.root) as store:
        db.row_factory = sqlite3.Row
        # Un cierre entre el POST y su persistencia no debe producir otro POST.
        with db:
            db.execute("UPDATE deliveries SET state='UNCERTAIN',code='INTERRUPTED' WHERE state='IN_FLIGHT'")
        store.execute("UPDATE executions SET status='REVIEW',finished=? WHERE source='GMAIL_TEST_SEND' AND signature=? AND status='RUNNING'",
                      (utcnow(), campaign_id))
        if db.execute("SELECT 1 FROM deliveries WHERE state IN ('UNCERTAIN','BLOCKED')").fetchone():
            raise RPAError('CAMPAIGN_REVIEW_REQUIRED')
        store.execute('INSERT INTO executions(id,profile,signature,started,status,source) VALUES(?,?,?,?,?,?)',
                      (execution_id, 'gmail-test-send', campaign_id, started, 'RUNNING', 'GMAIL_TEST_SEND'))
        audit = Audit(store, execution_id, settings.runtime / 'logs')
        error = None
        attempted_now = 0
        retries_now = 0
        try:
            token = token or authenticate_gmail(replace(settings, mailbox=sender), budget, send=True)
            client = client or httpx.Client(follow_redirects=False)
            for item in manifest['messages']:
                budget.remaining()
                if stop_event is not None and stop_event.is_set():
                    error = 'STOP_REQUESTED'
                    break
                row = db.execute('SELECT * FROM deliveries WHERE sequence=?', (item['sequence'],)).fetchone()
                if row['state'] in ('ACCEPTED', 'RECEIVED'):
                    continue
                if limit is not None and attempted_now >= limit:
                    break
                if row['due'] > time.time():
                    error = 'CAMPAIGN_RETRY_NOT_DUE'
                    break
                if row['attempts'] >= 3:
                    error = 'CAMPAIGN_ATTEMPTS_EXHAUSTED'
                    break
                attempt = row['attempts']+1
                attempted_now += 1
                retries_now += int(attempt > 1)
                raw = raw_message(manifest, item)
                with db:
                    db.execute("UPDATE deliveries SET state='IN_FLIGHT',attempts=?,updated=? WHERE sequence=?",
                               (attempt, utcnow(), item['sequence']))
                msg_started, msg_timer = utcnow(), time.monotonic()
                state, code, gmail_id, due = 'UNCERTAIN', 'SEND_UNKNOWN', None, 0
                http_status = None
                try:
                    response = client.post(BASE+'/messages/send', headers={'Authorization': 'Bearer '+token},
                                           json={'raw': raw}, timeout=min(settings.http_timeout, budget.remaining()))
                    http_status = response.status_code
                    if response.status_code == 200:
                        gmail_id = response.json().get('id')
                        if isinstance(gmail_id, str) and gmail_id:
                            state, code = 'ACCEPTED', 'GMAIL_ACCEPTED'
                    elif response.status_code == 429:
                        # Detener el lote y revisar la recepción; no repetir automáticamente un envío.
                        state, code = 'UNCERTAIN', 'HTTP_429_REVIEW'
                    elif response.status_code in (400, 401, 403, 404):
                        from rpa.gmail_errors import error_code
                        state, code = 'BLOCKED', error_code(response)
                        if code in ('GMAIL_DAILY_QUOTA', 'GMAIL_RATE_LIMIT'):
                            from rpa.http import retry_delay
                            state = 'DEFERRED' if attempt < 3 else 'BLOCKED'
                            due = time.time()+max(86400 if code=='GMAIL_DAILY_QUOTA' else 60,
                                                retry_delay(response.headers.get('Retry-After'), attempt))
                    else:
                        code = 'HTTP_'+str(response.status_code)+'_UNKNOWN'
                except (httpx.TransportError, ValueError, RPAError):
                    pass
                with db:
                    db.execute('UPDATE deliveries SET state=?,gmail_id=?,code=?,updated=?,due=? WHERE sequence=?',
                               (state, gmail_id, code, utcnow(), due, item['sequence']))
                audit.event('gmail_send_'+str(item['sequence']), msg_started, (time.monotonic()-msg_timer)*1000,
                            attempt, 'OK' if state=='ACCEPTED' else 'FAILED', code,
                            context=dict(dataset=campaign_id, job_id=campaign_id+':'+str(item['sequence']),
                                         role='remitente', http_status=http_status,
                                         recovery='NONE' if state=='ACCEPTED' else 'WAIT_QUOTA' if state=='DEFERRED' else 'REVIEW_NO_RESEND'))
                if state != 'ACCEPTED':
                    error = code
                    break
                if progress:
                    progress({'stage':'Aceptado por Gmail', 'done':summary(settings,campaign_id)['accepted'],
                              'total':manifest['count'], 'accepted':summary(settings,campaign_id)['accepted']})
                if interval:
                    budget.sleep(max(1.0, interval))
        except Exception as exc:
            error = exc.code if isinstance(exc, RPAError) else type(exc).__name__
            audit.event('gmail_send', started, (time.monotonic()-timer)*1000, result='FAILED', code=error)
        finally:
            if own_client and client:
                client.close()
            result = summary(settings, campaign_id)
            result.update(execution_id=execution_id, error=error, duration_seconds=round(time.monotonic()-timer, 3))
            accepted_now = store.row("SELECT COUNT(*) FROM events WHERE execution_id=? AND step_id LIKE 'gmail_send_%' AND result='OK'",
                                     (execution_id,))[0]
            result.update(processed=accepted_now, failed=max(0, attempted_now-accepted_now), retries=retries_now)
            result['attempted_this_invocation'] = attempted_now
            state = 'COMPLETED' if result['all_accepted'] else 'REVIEW'
            store.execute('UPDATE executions SET status=?,finished=?,metrics=? WHERE id=?',
                          (state, utcnow(), encode(result), execution_id))
            audit.close()
            result['logs'] = finish_logging(settings, store, execution_id)
            (folder / 'envio_resultado.json').write_text(encode(result), encoding='utf-8')
        return result


def analyze(settings, campaign_id, progress=None):
    from rpa.orchestrator import run
    manifest = load(settings, campaign_id)
    start = datetime.fromisoformat(manifest['created']) - timedelta(days=1)
    end = datetime.now(timezone.utc) + timedelta(days=30)
    configured = replace(settings, source='GMAIL', mailbox=manifest['recipient'],
        gmail_campaign_tag=manifest['tag'], gmail_label=settings.gmail_label, profile='gmail-'+campaign_id[:8],
        period_start=start.isoformat(), period_end=end.isoformat(), holiday_mode='LIVE', mail_mode='DRY_RUN',
        require_excel=False, execution_seconds=1800)
    # Reanudar una ejecución parcial con exactamente su ventana inicial.
    folder = directory(settings, campaign_id)
    config_path = folder / 'analysis_window.json'
    if config_path.exists():
        window = json.loads(config_path.read_text(encoding='utf-8'))
        configured = replace(configured, **window)
    else:
        config_path.write_text(encode(dict(period_start=configured.period_start, period_end=configured.period_end)), encoding='utf-8')
    with Store(settings.runtime / 'state.sqlite3', settings.root) as store:
        active = store.row("SELECT id,signature FROM executions WHERE status IN ('RUNNING','PARTIAL') LIMIT 1")
        resume = active['id'] if active and active['signature']==configured.signature else None
    result = run(configured, resume_id=resume, progress=progress)
    expected = {item['subject']: item['expected'] for item in manifest['messages']}
    with Store(settings.runtime / 'state.sqlite3', settings.root) as store:
        rows = store.rows("SELECT payload,category FROM messages WHERE mailbox=? AND state='CLASSIFIED'",
                          (configured.identity,))
    actual = {}
    received_sequences = []
    expected_ids = {item['message_id']:item for item in manifest['messages']}
    expected_subjects = {item['subject']:item for item in manifest['messages']}
    sender_hash = 'anon-'+hashlib.sha256(manifest['sender'].encode()).hexdigest()[:12]
    duplicates = 0
    for row in rows:
        payload = json.loads(row['payload'])
        subject = payload['subject']
        # Gmail puede sustituir Message-ID: el asunto generado incluye UUID del dataset
        # y número individual. Esto correlaciona trabajos; ingest sigue deduplicando por ID Gmail.
        item = expected_ids.get(payload.get('rfc_message_id')) or expected_subjects.get(subject)
        if item and subject == item['subject'] and payload['sender'] == sender_hash:
            duplicates += int(subject in actual)
            actual[subject] = row['category']
            received_sequences.append(item['sequence'])
    # Correlación por identificador de prueba único y remitente, nunca por ID interno entre buzones.
    with profile_lock(folder / 'send.lock'), sqlite3.connect(folder / 'campaign.sqlite3') as db:
        with db:
            db.executemany("UPDATE deliveries SET state='RECEIVED',updated=? WHERE sequence=? AND state IN ('ACCEPTED','UNCERTAIN','IN_FLIGHT')",
                           [(utcnow(), sequence) for sequence in received_sequences])
    correct = sum(actual.get(subject)==category for subject, category in expected.items())
    check = dict(campaign_id=campaign_id, expected=len(expected), received_unique=len(actual),
                 correct=correct, duplicates=duplicates, missing=len(expected)-len(actual),
                 categories=dict(Counter(actual.values())), complete=correct==len(expected) and duplicates==0
                    and result['status'] in ('COMPLETED', 'NO_CHANGES'),
                 execution=result)
    with (folder / 'analisis_acumulado.csv').open('w', encoding='utf-8-sig', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(['Numero', 'Categoria esperada', 'Categoria recibida', 'Recibido', 'Coincide'])
        for item in manifest['messages']:
            category = actual.get(item['subject'])
            writer.writerow([item['sequence'], item['expected'], category or '',
                             category is not None, category == item['expected']])
    from rpa.scenario_reports import summarize, export_results
    scenarios = []
    for item in manifest['messages']:
        row = dict(item.get('scenario') or dict(scenario_id=item['message_id'], sequence=item['sequence'],
            type='normal', special=False, technical=False, expected_category=item['expected'], expected_result='CLASSIFIED'))
        category = actual.get(item['subject'])
        row.update(actual_category=category, actual_result='CLASSIFIED' if category else None,
                   validation='PENDING' if category is None else 'PASSED' if category==item['expected'] else 'FAILED',
                   failure_reason='CATEGORY_MISMATCH' if category is not None and category!=item['expected'] else None)
        scenarios.append(row)
    state = summary(settings,campaign_id)
    with sqlite3.connect(folder/'campaign.sqlite3') as db:
        retries = db.execute('SELECT COALESCE(SUM(MAX(0,attempts-1)),0) FROM deliveries').fetchone()[0]
    with Store(settings.runtime/'state.sqlite3',settings.root) as store:
        provider_failures = store.row("SELECT COUNT(*) FROM events e JOIN executions x ON e.execution_id=x.id WHERE x.signature=? AND x.source='GMAIL_TEST_SEND' AND e.result='FAILED' AND e.step_id GLOB 'gmail_send_[0-9]*'",(campaign_id,))[0]
        runs = store.rows("SELECT source,metrics FROM executions WHERE (source='GMAIL_TEST_SEND' AND signature=?) OR (source='GMAIL' AND profile=?)",
                          (campaign_id,configured.profile))
        elapsed = 0
        for row in runs:
            metrics = json.loads(row['metrics'])
            elapsed += metrics.get('total_active_seconds',metrics.get('duration_seconds',0))
            if row['source']=='GMAIL':retries += metrics.get('retries',0)
    totals = summarize(scenarios, mode='GMAIL', prepared=manifest['count'], accepted=state['accepted'],
        received=len(actual), classified=len(actual), duration=elapsed,
        retries=retries, provider_failures=provider_failures, duplicates=duplicates)
    report_folder = settings.output/result['execution_id']
    base_report = report_folder/'reporte.xlsx'
    check['scenario_report'] = export_results(folder,totals,scenarios)
    if base_report.is_file():
        check['scenario_report'] = export_results(report_folder,totals,scenarios,
            base_report=base_report,execution_id=result['execution_id'])
    (folder / 'analisis_resultado.json').write_text(encode(check), encoding='utf-8')
    return check


def send_preview(settings, campaign_id, *, limit=None, interval=None):
    manifest = load(settings,campaign_id)
    controls = manifest.get('test_config',{})
    limit = controls.get('limit',manifest['count']) if limit is None else limit
    interval = controls.get('interval',1.0) if interval is None else interval
    if type(limit) is not int or not 1 <= limit <= manifest['count'] or not math.isfinite(interval) or not 1 <= interval <= 60:
        raise RPAError('CAMPAIGN_SEND_CONTROLS_INVALID')
    with sqlite3.connect(directory(settings,campaign_id)/'campaign.sqlite3') as db:
        rows = db.execute('SELECT state,due,attempts FROM deliveries ORDER BY sequence').fetchall()
    blocked = any(state in ('UNCERTAIN','BLOCKED','IN_FLIGHT') for state,_,_ in rows)
    eligible = 0
    for state,due,attempts in rows:
        if state in ('ACCEPTED','RECEIVED'):continue
        if due > time.time() or attempts >= 3:break
        eligible += 1
    return dict(summary(settings,campaign_id), sender=manifest['sender'],recipient=manifest['recipient'],
                to_attempt=0 if blocked else min(limit,eligible), limit=limit, interval=interval,
                pending=sum(state not in ('ACCEPTED','RECEIVED') for state,_,_ in rows), review_required=blocked)


def sender_usage(settings, sender):
    """Estimación de campañas locales; no consulta ni representa cuota oficial."""
    ids = []
    for path in (settings.runtime/'campaigns').glob('*/mensajes.json'):
        try:
            manifest = load(settings,path.parent.name)
            if manifest['sender']==sender.lower():ids.append(manifest['id'])
        except (OSError,ValueError,RPAError,sqlite3.Error):continue
    accepted = attempted = 0
    state = settings.runtime/'state.sqlite3'
    if state.exists() and ids:
        with sqlite3.connect(state.resolve().as_uri()+'?mode=ro',uri=True) as db:
            rows = db.execute("SELECT x.signature,e.result FROM events e JOIN executions x ON e.execution_id=x.id WHERE x.source='GMAIL_TEST_SEND' AND e.step_id GLOB 'gmail_send_[0-9]*' AND e.started>=?",((datetime.now(timezone.utc)-timedelta(hours=24)).isoformat(),)).fetchall()
        for campaign,result in rows:
            if campaign in ids:
                attempted += 1; accepted += result=='OK'
    return {'window_hours':24,'attempted':attempted,'accepted':accepted,'official_quota':False,
            'includes_external_sends':False}
