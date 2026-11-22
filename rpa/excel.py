"""Entrada: plantilla, filas y ejecución. Salida: XLSX cerrado/verificado. Errores: RPAError/OSError."""
from collections import Counter
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import json
import re
from openpyxl import Workbook, load_workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.styles import Font, PatternFill, Alignment

from rpa.classify import CATEGORIES
from rpa.runtime import RPAError

SHEETS = {"Resumen", "Correos", "Referencia_API", "Ejecuciones"}


def safe_text(value):
    if not isinstance(value, str):
        return value
    value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", value)
    if value.lstrip().startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n")):
        value = "'" + value
    return value[:32767]


def file_hash(path):
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def create_template(path):
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    book = Workbook()
    book.active.title = "Resumen"
    ws = book.active
    ws.append(["Categoría", "Cantidad"])
    for category in CATEGORIES:
        ws.append([category, 0])
    ws.append(["Total", "=SUM(B2:B7)"])
    chart = BarChart()
    chart.title = "Correos clasificados"
    chart.add_data(Reference(ws, min_col=2, min_row=1, max_row=7), titles_from_data=True)
    chart.set_categories(Reference(ws, min_col=1, min_row=2, max_row=7))
    ws.add_chart(chart, "D2")
    book.create_sheet("Correos").append(["ID seudónimo", "Remitente", "Asunto oculto", "Recepción UTC",
        "Categoría", "Regla", "Versión", "Plazo Santiago", "Resultado plazo"])
    book.create_sheet("Referencia_API").append(["Fecha", "Nombre", "Proveedor", "HTTP", "Consulta UTC", "Origen", "Nacional"])
    book.create_sheet("Ejecuciones").append(["Execution ID", "Inicio UTC", "Fin procesamiento UTC",
        "Duración segundos", "Origen", "Excel escritorio"])
    for sheet in book:
        sheet.freeze_panes = "A2"
        for cell in sheet[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="16324F")
            cell.alignment = Alignment(wrap_text=True)
        for col in "ABCDEFGHI":
            sheet.column_dimensions[col].width = 25
    book.save(path)
    book.close()


def assert_unlocked(path):
    if not path.exists():
        return
    if sys.platform == "win32":
        import win32file
        import win32con
        try:
            handle = win32file.CreateFile(str(path.resolve()), win32con.GENERIC_READ | win32con.GENERIC_WRITE,
                                         0, None, win32con.OPEN_EXISTING, 0, None)
            handle.Close()
        except Exception as exc:
            raise RPAError("WORKBOOK_LOCKED") from exc
    else:
        with path.open("r+b"):
            pass


def build_report(settings, execution_id, items, references, started, finished, duration):
    template = settings.root / "templates/reporte_base.xlsx"
    directory = settings.output / execution_id
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "reporte.xlsx"
    assert_unlocked(path)
    original_hash = file_hash(template)
    try:
        book = load_workbook(template)
        if set(book.sheetnames) != SHEETS or book["Resumen"]["B8"].value != "=SUM(B2:B7)" or not book["Resumen"]._charts:
            book.close()
            raise RPAError("TEMPLATE_INVALID")
    except RPAError:
        raise
    except Exception as exc:
        raise RPAError("TEMPLATE_INVALID") from exc
    try:
        counts = Counter(item.get("category", "Otros") for item in items)
        for i, category in enumerate(CATEGORIES, 2):
            book["Resumen"].cell(i, 2, counts[category])
        for item in items:
            # Evidencia académica redactada por defecto, incluso con origen real.
            values = [hashlib.sha256(item["id"].encode()).hexdigest()[:16], item["sender"], "[oculto]",
                      item["received"], item.get("category", "REVISIÓN"), item.get("rule", ""),
                      item.get("rules_version", ""), item.get("due"), item.get("due_result")]
            book["Correos"].append([safe_text(v) for v in values])
        for ref in references:
            for holiday in ref["data"]:
                book["Referencia_API"].append([safe_text(v) for v in [holiday["date"], holiday["localName"],
                    ref["provider"], ref["http_status"], ref["queried"], ref["origin"], holiday["global"]]])
        book["Ejecuciones"].append([execution_id, started, finished, round(duration, 3), settings.source, "NO_EJECUTADO"])
        for sheet in book:
            sheet.auto_filter.ref = sheet.dimensions
        temp = directory / "reporte.tmp.xlsx"
        book.save(temp)
        assert_unlocked(path)
        temp.replace(path)
    finally:
        book.close()
    if file_hash(template) != original_hash:
        raise RPAError("TEMPLATE_CHANGED")
    verify_report(path, execution_id, len(items))
    return path


def verify_report(path, execution_id, count=None):
    assert_unlocked(path)
    book = load_workbook(path)
    try:
        if set(book.sheetnames) != SHEETS or book["Ejecuciones"]["A2"].value != execution_id:
            raise RPAError("REPORT_ID_INVALID")
        if count is not None and book["Correos"].max_row != count+1:
            raise RPAError("REPORT_COUNT_INVALID")
        if book["Resumen"]["B8"].value != "=SUM(B2:B7)" or not book["Resumen"]._charts:
            raise RPAError("REPORT_STRUCTURE_INVALID")
    finally:
        book.close()
    return {"sha256": file_hash(path), "size": path.stat().st_size}


def desktop_excel(settings, path, timeout):
    if sys.platform != "win32":
        raise RPAError("EXCEL_WINDOWS_REQUIRED")
    evidence = path.parent / "excel_desktop.json"
    try:
        result = subprocess.run([sys.executable, str(settings.root / "scripts/office_worker.py"),
                                 "excel", str(path.resolve()), str(evidence.resolve())],
                                timeout=timeout, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired as exc:
        raise RPAError("EXCEL_TIMEOUT") from exc
    if result.returncode:
        raise RPAError("EXCEL_COM_UNAVAILABLE")
    return json.loads(evidence.read_text(encoding="utf-8"))
