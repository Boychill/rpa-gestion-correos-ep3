"""Prueba conjunta de la demo por tamaños, con Excel, logs y segunda ejecución sin cambios."""
from collections import Counter
from dataclasses import replace
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from openpyxl import load_workbook
from rpa.config import Settings
from rpa.demo_actions import DemoActions
from rpa.excel import verify_report, file_hash
from rpa.orchestrator import run
from rpa.store import Store, utcnow


def verify_groups(settings):
    evidence = dict(checked_at=utcnow(), source='FIXTURE', mail_sent=False, groups=[])
    for count in (100, 300, 500, 1000):
        started = time.monotonic()
        first = DemoActions(settings).simulation(count)
        assert first['status']=='COMPLETED' and first['send_state']=='DRY_RUN'
        assert first['metrics']['classified']==count and first['metrics']['failed']==0
        path = Path(first['report_path'])
        manifest = verify_report(path,first['execution_id'],count)
        book = load_workbook(path,read_only=True)
        try:
            categories = dict(Counter(row[4] for row in book['Correos'].iter_rows(min_row=2,values_only=True)))
            assert sum(categories.values())==count
            assert book['Referencia_API'].max_row>1
        finally:
            book.close()
        saved = first['logs']['file']
        assert file_hash(Path(saved['folder'])/saved['name'])==saved['sha256']
        assert first['logs']['supabase']['status']=='DISABLED'
        name = path.parent.parent.name
        configured = replace(settings,source='FIXTURE',fixture_count=count,mail_mode='DRY_RUN',
            holiday_mode='FIXTURE',supabase_enabled=False,require_excel=False,profile='presentation',
            runtime=settings.runtime/'presentacion'/name,output=path.parent.parent)
        second = run(configured)
        assert second['status']=='NO_CHANGES' and second['metrics']['processed']==0
        with Store(configured.runtime/'state.sqlite3',settings.root) as store:
            assert store.row('SELECT COUNT(*) FROM messages')[0]==count
            assert store.row("SELECT COUNT(*) FROM sends WHERE state!='DRY_RUN'")[0]==0
            assert store.row('SELECT COUNT(*) FROM sends')[0]==1
        row = dict(count=count,status='PASSED',classified=count,categories=categories,
            repeat_status=second['status'],duplicate_records=0,mail_sent=False,
            duration_seconds=round(time.monotonic()-started,3),
            report=path.relative_to(settings.root).as_posix(),sha256=manifest['sha256'],logs_verified=True)
        evidence['groups'].append(row)
        print(json.dumps(row,ensure_ascii=True),flush=True)
    evidence['status']='PASSED'
    (settings.root/'docs/evidence/pruebas_conjuntos.json').write_text(
        json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    return evidence


if __name__=='__main__':
    verify_groups(Settings.load(Path(__file__).resolve().parents[1]))
