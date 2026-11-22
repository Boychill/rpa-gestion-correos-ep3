"""Acciones de la presentación local. Preparar y simular nunca envían correo."""
from dataclasses import replace
import uuid
import sqlite3
from rpa.runtime import RPAError, profile_lock
from rpa.store import Store
from rpa.gmail_campaign import prepare, load, send, analyze
from rpa.campaign_report import export_campaign
from rpa.orchestrator import run


class DemoActions:
    def __init__(self, settings):
        self.settings = settings

    def simulation(self, count, progress=None):
        from rpa.scenarios import ScenarioConfig
        if isinstance(count,ScenarioConfig):
            from rpa.scenario_runner import simulate
            return simulate(self.settings,count,progress)
        if not 1 <= count <= 1000:
            raise RPAError('DEMO_COUNT_INVALID')
        name = uuid.uuid4().hex
        settings = replace(self.settings, source='FIXTURE', fixture_count=count, mail_mode='DRY_RUN',
            holiday_mode='FIXTURE', supabase_enabled=False, require_excel=False, profile='presentation',
            runtime=self.settings.runtime/'presentacion'/name, output=self.settings.output/'presentacion'/name)
        result = run(settings)
        result['report_path'] = str(settings.output/result['execution_id']/'reporte.xlsx')
        result['simulation'] = True
        return result

    def prepare(self, count):
        s = self.settings
        from rpa.scenarios import ScenarioConfig
        if isinstance(count,ScenarioConfig):
            return prepare(s,s.gmail_sender_address,s.gmail_receiver_address,count.total,config=count)
        return prepare(s,s.gmail_sender_address,s.gmail_receiver_address,count)

    def process(self, campaign_id, *, execute=False, stop_event=None, limit=None, interval=None, progress=None):
        s = self.settings
        manifest = load(s,campaign_id)
        with profile_lock(s.runtime/'locks/demo_workflow.lock'):
            with Store(s.runtime/'state.sqlite3',s.root) as store:
                if store.row("SELECT id FROM executions WHERE status='RUNNING' LIMIT 1"):
                    raise RPAError('ANOTHER_EXECUTION_RUNNING')
                if execute and store.row("SELECT id FROM executions WHERE status='PARTIAL' LIMIT 1"):
                    raise RPAError('RESUME_ANALYSIS_FIRST')
            result = {}
            if execute:
                from rpa.gmail_auth import authorize
                from rpa.runtime import Budget
                authorize(s,Budget(60),'receptor')
                result['send'] = send(s,campaign_id,manifest['sender'],manifest['recipient'],
                                      execute=True,stop_event=stop_event,limit=limit,interval=interval,progress=progress)
                if result['send'].get('error') and not result['send']['accepted']:
                    return result
            result['analysis'] = analyze(s,campaign_id,progress=progress)
            if result['analysis']['complete']:
                result['report'] = export_campaign(s,campaign_id)
                result['report_path'] = result['report']['path']
            scenarios = result['analysis'].get('scenario_report',{})
            if scenarios.get('report_path'):result['report_path'] = scenarios['report_path']
            return result

    def connections(self):
        from rpa.gmail_auth import local_authorization_status
        from rpa.gmail_campaign import sender_usage
        s = self.settings
        status = {'oauth':[local_authorization_status(s,role) for role in ('remitente','receptor')],
                  'supabase':{'enabled':s.supabase_enabled,'configured':bool(s.supabase_url and s.supabase_secret_key),
                              'remote_checked':False,'queue':{}},
                  'usage':sender_usage(s,s.gmail_sender_address)}
        path = s.runtime/'state.sqlite3'
        if path.exists():
            with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=1) as db:
                status['supabase']['queue'] = dict(db.execute('SELECT state,COUNT(*) FROM log_outbox GROUP BY state'))
                last = db.execute("SELECT updated FROM log_outbox WHERE state='SYNCED' ORDER BY updated DESC LIMIT 1").fetchone()
                status['supabase']['last_sync'] = last[0] if last else None
        return status

    def sync_logs(self):
        from rpa.cloud_logs import sync_logs
        s = self.settings
        with profile_lock(s.runtime/'locks/state.lock'),Store(s.runtime/'state.sqlite3',s.root) as store:
            return {'supabase_sync':sync_logs(s,store)}
