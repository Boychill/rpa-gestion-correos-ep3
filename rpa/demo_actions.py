"""Acciones de la presentación local. Preparar y simular nunca envían correo."""
from dataclasses import replace
import uuid
from rpa.runtime import RPAError, profile_lock
from rpa.store import Store
from rpa.gmail_campaign import prepare, load, send, analyze
from rpa.campaign_report import export_campaign
from rpa.orchestrator import run


class DemoActions:
    def __init__(self, settings):
        self.settings = settings

    def simulation(self, count):
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
        return prepare(s,s.gmail_sender_address,s.gmail_receiver_address,count)

    def process(self, campaign_id, *, execute=False, stop_event=None):
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
                                      execute=True,stop_event=stop_event)
                if result['send'].get('error'):
                    return result
            result['analysis'] = analyze(s,campaign_id)
            if result['analysis']['complete']:
                result['report'] = export_campaign(s,campaign_id)
                result['report_path'] = result['report']['path']
            return result
