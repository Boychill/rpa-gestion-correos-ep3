"""Pruebas negativas con transportes simulados; ningún tráfico de red real."""
from dataclasses import replace
import time
import uuid

import httpx

from rpa.cloud_logs import sync_logs
from rpa.holidays import Holidays
from rpa.http import ReaderHTTP
from rpa.mail_read import Page
from rpa.orchestrator import run
from rpa.runtime import Audit, Budget, RPAError
from rpa.scenarios import generate
from rpa.scenario_reports import summarize, export_results
from rpa.store import Store, utcnow, encode


class SimulatedBudget(Budget):
    """Avanza la espera de fallos ficticios sin dormir ni modificar el reloj global."""
    def sleep(self, seconds):
        if seconds >= self.remaining():
            raise RPAError('RETRY_EXCEEDS_BUDGET')
        self.deadline -= seconds


def technical_check(settings, store, execution_id, audit, row):
    kind, ident = row['type'], row['scenario_id']
    message = dict(id=ident, subject='Consulta sintética', sender='anon-fixture',
                   received='2026-06-01T12:00:00+00:00', modified='scenario-v1')
    try:
        if kind in ('missing_id','invalid_date','incomplete_metadata','duplicate_id'):
            if kind == 'missing_id': message.pop('id')
            elif kind == 'invalid_date': message['received'] = 'invalid'
            elif kind == 'incomplete_metadata': message.pop('subject')
            store.ingest(execution_id, 'synthetic-negative', ident, [message], 'done', 'DELTA')
            if kind == 'duplicate_id':
                counts = store.ingest(execution_id, 'synthetic-negative', ident, [message], 'done', 'DELTA')
                return ('DUPLICATE_DETECTED' if counts['duplicates']==1 else 'DUPLICATE_MISSED'), 0, counts['duplicates']
            return 'INVALID_MESSAGE_ACCEPTED', 0, 0

        def handle(request):
            if kind == 'timeout':
                raise httpx.ReadTimeout('simulated', request=request)
            status = 401 if kind == 'authentication' else 429 if kind == 'http_429' else 500
            return httpx.Response(status, headers={'Retry-After':'0'}, json={'error':{'code':status}})

        with httpx.Client(transport=httpx.MockTransport(handle)) as client:
            if kind == 'supabase_failure':
                simulated = replace(settings, supabase_enabled=True,
                                    supabase_url='https://supabase.invalid', supabase_secret_key='sb_secret_simulated')
                before = store.row('SELECT COUNT(*) FROM messages')[0]
                result = sync_logs(simulated, store, execution_id, client=client)
                preserved = store.row('SELECT COUNT(*) FROM messages')[0] == before
                queued = store.row("SELECT COUNT(*) FROM log_outbox WHERE state='PENDING' AND execution_id=?",(execution_id,))[0]
                return ('LOCAL_QUEUE_PRESERVED' if preserved and queued and result['synced']==0 else 'QUEUE_CHECK_FAILED'), 0, 0
            http = ReaderHTTP(client, settings, store, execution_id, audit, SimulatedBudget(60))
            try:
                if kind == 'holidays_unavailable':
                    calendar = Holidays(replace(settings, holiday_mode='LIVE', runtime=settings.runtime/ident), http)
                    _, code = calendar.due(message['received'])
                    return code, http.retries, 0
                http.get('https://gmail.googleapis.com/simulated/'+ident)
            except RPAError as exc:
                return exc.code, http.retries, 0
            return 'UNEXPECTED_HTTP_SUCCESS', http.retries, 0
    except RPAError as exc:
        return exc.code, 0, 0


def simulate(settings, config, progress=None):
    config.validate()
    if config.mode != 'SIMULATION':
        raise RPAError('SIMULATION_MODE_REQUIRED')
    timer = time.monotonic()
    rows = generate(config)
    content = [r for r in rows if not r['technical']]
    name = uuid.uuid4().hex
    s = replace(settings, source='FIXTURE', fixture_count=len(content), holiday_mode='FIXTURE',
                mail_mode='DRY_RUN', mail_adapter='GMAIL', supabase_enabled=False, require_excel=False,
                profile='presentation', runtime=settings.runtime/'presentacion'/name,
                output=settings.output/'presentacion'/name)

    def emit(stage, done, total):
        if progress: progress({'stage':stage, 'done':done, 'total':total})

    class Reader:
        queries = 0
        def __init__(self, configured):
            self.s = configured
        def page(self, cursor=None):
            self.queries += 1
            start = int(cursor or 0)
            batch = content[start:start+self.s.batch_size]
            end = start+len(batch)
            messages = [dict(id=r['scenario_id'], subject=r['subject'], sender='anon-fixture',
                            received=self.s.period_start, modified='scenario-v1') for r in batch]
            emit('Lectura de datos sintéticos', end, len(content))
            return Page(messages, str(end), 'DELTA' if end==len(content) else 'NEXT')

    result = run(s, reader_factory=Reader)
    execution_id = result['execution_id']
    total_retries, duplicate_count = 0, 0
    with Store(s.runtime/'state.sqlite3', s.root) as store:
        categories = {r['id']:r['category'] for r in store.rows('SELECT id,category FROM messages')}
        # Los fallos esperados tienen ejecuciones separadas del resultado productivo.
        for index, row in enumerate(rows, 1):
            emit('Comprobación de escenarios', index, len(rows))
            if row['technical']:
                eid = str(uuid.uuid4())
                store.execute('INSERT INTO executions(id,profile,signature,started,status,source) VALUES(?,?,?,?,?,?)',
                              (eid,'scenario-test',row['scenario_id'],utcnow(),'COMPLETED','SIMULATED_TEST'))
                audit = Audit(store,eid,s.runtime/'logs')
                try:
                    audit.event('simulated_case',utcnow(),0,code='SIMULATED_TECHNICAL_CASE')
                    actual, retries, duplicates = technical_check(s,store,eid,audit,row)
                    row['actual_result'] = actual
                    total_retries += retries
                    duplicate_count += duplicates
                except Exception as exc:
                    row['actual_result'] = 'UNEXPECTED_'+type(exc).__name__
                finally:
                    audit.close()
                store.execute('UPDATE executions SET finished=? WHERE id=?', (utcnow(),eid))
            else:
                row['actual_category'] = categories.get(row['scenario_id'])
                row['actual_result'] = 'CLASSIFIED' if row['actual_category'] else 'NOT_CLASSIFIED'
            passed = (row['actual_result'] == row['expected_result'] and
                      row['actual_category'] == row['expected_category'])
            row['validation'] = 'PASSED' if passed else 'FAILED'
            row['failure_reason'] = None if passed else 'EXPECTED_RESULT_MISMATCH'
            if progress:
                progress({'stage':'Escenario '+row['type']+' · '+row['validation'], 'done':index, 'total':len(rows),
                          'expected':row['expected_category'] or row['expected_result'],
                          'actual':row['actual_category'] or row['actual_result']})
        summary = summarize(rows, mode='SIMULATION', prepared=len(rows), classified=len(categories),
                            duration=time.monotonic()-timer, retries=total_retries, duplicates=duplicate_count)
        result['metrics'].update({k:summary[k] for k in ('normal','special','special_validated',
            'unexpected_errors','simulated_technical','real_provider_failures')})
        store.execute('UPDATE executions SET metrics=? WHERE id=?', (encode(result['metrics']),execution_id))
        from rpa.log_files import finish_logging
        result['logs'] = finish_logging(s,store,execution_id)
    folder = s.output/execution_id
    exported = export_results(folder, summary, rows, base_report=folder/'reporte.xlsx', execution_id=execution_id)
    result.update(simulation=True, scenario_report=exported, report_path=exported['report_path'],
                  validation_status='PASSED' if not summary['failed'] else 'FAILED')
    (folder/'configuracion_prueba.json').write_text(encode(config.to_dict()), encoding='utf-8')
    (folder/'resultado.json').write_text(encode(result), encoding='utf-8')
    emit('Simulación terminada',len(rows),len(rows))
    return result
