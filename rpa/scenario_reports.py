"""Resultados de pruebas sin asuntos ni direcciones; conserva las cuatro hojas Excel."""
import csv
import json
from pathlib import Path
import shutil
from collections import Counter

from openpyxl import load_workbook
from rpa.excel import create_template, safe_text, verify_report
from rpa.store import utcnow


def summarize(rows, *, mode, prepared, accepted=0, received=0, classified=0,
              duration=0, retries=0, provider_failures=0, duplicates=0):
    results = Counter(row['validation'] for row in rows)
    specials = [r for r in rows if r['special']]
    return dict(mode=mode, configured=len(rows), prepared=prepared, accepted=accepted,
        received=received, classified=classified, normal=len(rows)-len(specials), special=len(specials),
        special_validated=sum(r['validation']=='PASSED' for r in specials),
        special_pending=sum(r['validation']=='PENDING' for r in specials),
        passed=results['PASSED'], failed=results['FAILED'], pending=results['PENDING'],
        unexpected_errors=results['FAILED'], simulated_technical=sum(r['technical'] for r in rows),
        expected_errors=sum(r['technical'] and r['validation']=='PASSED' for r in rows), attempted=0, review=0,
        real_provider_failures=provider_failures, duplicates=duplicates, retries=retries,
        duration_seconds=round(duration, 4),
        average_seconds=round(duration/max(1, results['PASSED']+results['FAILED']), 6),
        checked_at=utcnow())


FIELDS = ('scenario_id','sequence','type','special','technical','expected_category',
          'expected_result','actual_category','actual_result','validation','failure_reason')


def export_results(folder, summary, rows, *, base_report=None, execution_id=None):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    public_rows = [{key:r.get(key) for key in FIELDS} for r in rows]
    document = {'summary':summary, 'scenarios':public_rows}
    json_path, csv_path = folder/'pruebas.json', folder/'pruebas.csv'
    json_path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding='utf-8')
    with csv_path.open('w', encoding='utf-8-sig', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(public_rows)
    result = {'summary':summary, 'json_path':str(json_path), 'csv_path':str(csv_path)}
    if execution_id:
        # Copia separada: nunca alterar un adjunto preparado, aceptado o incierto.
        path = folder/'reporte_pruebas.xlsx'
        if base_report and Path(base_report).is_file():
            shutil.copyfile(base_report, path)
        else:
            create_template(path)
        book = load_workbook(path)
        try:
            if book['Ejecuciones'].max_row == 1:
                book['Ejecuciones'].append([execution_id, summary['checked_at'], summary['checked_at'],
                                           summary['duration_seconds'], summary['mode'], 'NO_EJECUTADO'])
            sheet = book['Resumen']
            sheet.cell(20, 1, 'Resultados de escenarios de prueba')
            for i, (key, value) in enumerate(summary.items(), 21):
                sheet.cell(i, 1, key)
                sheet.cell(i, 2, safe_text(value))
            first = 24+len(summary)
            for j, key in enumerate(FIELDS, 1):
                sheet.cell(first, j, key)
            for i, row in enumerate(public_rows, first+1):
                for j, key in enumerate(FIELDS, 1):
                    sheet.cell(i, j, safe_text(row[key]))
            book.save(path)
        finally:
            book.close()
        result.update(report_path=str(path), report=verify_report(path, execution_id))
    return result
