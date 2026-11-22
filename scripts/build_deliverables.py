"""Genera PDF/PPTX y ZIP de fuentes con lista permitida y manifiesto SHA256."""
from datetime import datetime, timezone
from html import escape
import hashlib
from io import BytesIO
import json
from pathlib import Path
import re
import shutil
import sys
import zipfile
import xml.etree.ElementTree as ET

from reportlab import rl_config
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Image, KeepTogether
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.util import Inches, Pt

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
EVIDENCE = ROOT / "docs/evidence"
NAVY, TEAL, LIGHT = "16324F", "0D7C86", "F0F5FA"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def font_setup():
    directory = Path("C:/Windows/Fonts")
    if (directory / "arial.ttf").exists():
        pdfmetrics.registerFont(TTFont("Body", str(directory / "arial.ttf")))
        pdfmetrics.registerFont(TTFont("BodyBold", str(directory / "arialbd.ttf")))
        pdfmetrics.registerFontFamily("Body", normal="Body", bold="BodyBold", italic="Body", boldItalic="BodyBold")
        return "Body", "BodyBold"
    return "Helvetica", "Helvetica-Bold"


def clean_inline(text):
    text = re.sub(r"\[([^]]+)\]\(([^)]+)\)", r"\1 (\2)", text)
    return escape(text.replace("`", "").replace("**", ""))


def table(rows, widths, styles):
    content = [[Paragraph(clean_inline(str(v)), styles["Small"]) for v in row] for row in rows]
    obj = Table(content, colWidths=widths, repeatRows=1, hAlign="LEFT")
    obj.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#DEEAF3")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), .4, colors.HexColor("#CDDAE7")),
        ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7)]))
    return obj


def markdown_story(path, styles, width):
    story, buffer, rows = [], [], []
    def flush():
        if buffer:
            story.extend([Paragraph(clean_inline(" ".join(buffer)), styles["Normal"]), Spacer(1, 7)])
            buffer.clear()
        if rows:
            count = len(rows[0])
            story.extend([table(rows, [width/count]*count, styles), Spacer(1, 12)])
            rows.clear()
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("|"):
            if buffer:
                flush()
            values = [v.strip() for v in line.strip("|").split("|")]
            if not all(re.fullmatch(r"[-: ]+", v) for v in values):
                rows.append(values)
        elif line.startswith("#"):
            flush()
            level = len(line)-len(line.lstrip("#"))
            story.append(Paragraph(clean_inline(line.lstrip("# ")), styles["Title" if level == 1 else "Heading2"]))
        elif not line.strip():
            flush()
        elif not line.startswith("```"):
            if rows:
                flush()
            buffer.append(line)
    flush()
    return story


def report(benchmark, checks, test_summary, font, bold):
    styles = getSampleStyleSheet()
    for style in styles.byName.values():
        style.fontName = font
    styles["Normal"].fontSize = 10
    styles["Normal"].leading = 15
    styles["Title"].fontName = bold
    styles["Title"].textColor = colors.HexColor("#"+NAVY)
    styles["Heading2"].fontName = bold
    styles["Heading2"].textColor = colors.HexColor("#"+TEAL)
    styles["Heading2"].spaceBefore = 16
    styles.add(ParagraphStyle("Small", parent=styles["Normal"], fontSize=8, leading=11))
    width = A4[0]-88
    story = [Paragraph("EVALUACIÓN PARCIAL 3 · ATY1102", styles["Heading2"]),
             Paragraph("Gestión inteligente<br/>de correos", styles["Title"]), Spacer(1, 14),
             Paragraph("Implementación Python · SQLite · Microsoft Graph · Excel · Auditoría local", styles["Normal"]),
             Spacer(1, 20), Paragraph("Estado de la entrega", styles["Heading2"])]
    summary = [["Componente", "Resultado verificado"], ["Pruebas automatizadas", test_summary],
        ["Capacidad", "100, 300, 500 y 1.000 mensajes sintéticos; sin envío real"],
        ["API real", "; ".join(f"Chile {a['year']}: {a['status']}" for a in checks["api"])],
        ["Escritorio", "Excel COM no disponible en el equipo inicial; acción real pendiente"],
        ["Correo real", "Buzón autorizado y envío pendientes"],
        ["Evaluación", "Matriz provisional; pauta oficial no proporcionada"]]
    story += [table(summary, [140, width-140], styles), Spacer(1, 20),
              Paragraph("Las métricas sintéticas no acreditan rendimiento de Graph ni interacción real con Office.", styles["Normal"]),
              PageBreak()]
    story += markdown_story(ROOT / "docs/INFORME.md", styles, width)
    story += [PageBreak(), Paragraph("Mediciones registradas", styles["Title"])]
    rows = [["Mensajes", "Total (s)", "Correos/s", "Páginas", "Pico Python (MiB)"]]
    for result in benchmark["results"]:
        rows.append([result["count"], result["seconds"], result["throughput"], result["metrics"]["queries"],
                     f"{result['python_peak_bytes']/1048576:.2f}"])
    story += [table(rows, [width/5]*5, styles), Spacer(1, 14),
              Paragraph(clean_inline(f"Equipo: {benchmark['platform']}. Python {benchmark['python']}. CPU: {benchmark['cpu']}. "
                                    f"Lote {benchmark['batch_size']}, página {benchmark['page_size']}. {benchmark['memory_note']}"), styles["Normal"]),
              Paragraph(clean_inline(f"Prueba: {benchmark['measured_at']}. Origen: FIXTURE. Resultados completos: docs/evidence/benchmark.json."), styles["Normal"])]
    for name in ("arquitectura", "flujo", "secuencia", "datos"):
        path = ROOT / f"docs/diagramas/{name}.png"
        if not path.exists():
            raise RuntimeError("Falta exportar diagramas; ejecute scripts/render_diagrams.ps1")
        image = ImageReader(str(path))
        iw, ih = image.getSize()
        scale = min(width/iw, 650/ih)
        story += [PageBreak(), Paragraph("Diagrama · "+name, styles["Title"]),
                  Image(str(path), width=iw*scale, height=ih*scale), Spacer(1, 10),
                  Paragraph(f"Fuente editable: docs/diagramas/{name}.mmd. SVG y PDF adjuntos permiten ampliar detalles.", styles["Small"])]
    for doc in ("PRUEBAS_GMAIL.md", "MATRIZ_EP3.md", "FUENTES.md"):
        story += [PageBreak()] + markdown_story(ROOT / "docs" / doc, styles, width)
    def footer(c, doc):
        c.setFont(font, 8)
        c.setFillColor(colors.HexColor("#"+NAVY))
        c.drawString(44, 25, "RPA EP3 | Evidencia sintética y real diferenciada")
        c.drawRightString(A4[0]-44, 25, str(doc.page))
    SimpleDocTemplate(str(DIST / "informe_tecnico.pdf"), pagesize=A4, leftMargin=44, rightMargin=44,
        topMargin=42, bottomMargin=42, title="Robot RPA EP3 · Informe técnico", author="Equipo EP3").build(
        story, onFirstPage=footer, onLaterPages=footer)
    SimpleDocTemplate(str(DIST / "guion_demo.pdf"), pagesize=A4, leftMargin=44, rightMargin=44,
        topMargin=42, bottomMargin=42).build(markdown_story(ROOT / "docs/GUION_DEMO.md", styles, width),
                                           onFirstPage=footer, onLaterPages=footer)


def slides_data(benchmark, test_summary):
    largest = benchmark["results"][-1]
    return [
        ("01 · CONTEXTO", "Un reporte, mil correos", ["Leer metadatos · clasificar · calcular plazos · consolidar",
          "Python + SQLite: flujo reproducible y recuperación persistente", "DRY_RUN por defecto; sin respuestas automáticas"], None),
        ("02 · DISEÑO", "Subprocesos con estado durable", ["main → orquestador → adaptadores → auditoría"], "arquitectura"),
        ("03 · CONTINUIDAD", "Reanudar sin perder mensajes", ["Cada página y su cursor se confirman juntos",
          "ID estable + fingerprint: duplicado o actualización", "429: Retry-After y tres intentos totales; 410: resincronizar",
          "Los pendientes sobreviven a una interrupción"], None),
        ("04 · REGLAS", "Seis categorías, prioridad visible", ["Urgente → Reclamo → Solicitud → Consulta → Información → Otros",
          "Tildes y mayúsculas normalizadas; palabras completas", "Asunto vacío o sin señal: Otros",
          "Categoría + regla ganadora + versión en SQLite y Excel"], None),
        ("05 · API", "Feriados que cambian el plazo", ["GET real Chile 2026 y 2027: evidencia guardada",
          "America/Santiago; recepción excluida, días hábiles nacionales", "Caché por año; carga al cruzar diciembre",
          "Sin cobertura: plazo nulo y envío bloqueado"], None),
        ("06 · REPORTE", "Excel verificable, escritorio pendiente", ["Resumen · Correos · Referencia_API · Ejecuciones",
          "Plantilla conservada, fórmulas y gráfico verificados", "COM: abrir → actualizar → recalcular → guardar → reabrir",
          "En este equipo: Excel COM no disponible"], None),
        ("07 · ENVÍO", "Un resultado incierto no se reenvía", ["PREPARADO persistente antes de llamar al proveedor",
          "ACEPTADO no confirma entrega", "ENVIO_INCIERTO requiere reconciliación separada",
          "Un destinatario permitido; hash y tamaño del adjunto"], None),
        ("08 · AUDITORÍA", "Exportar, verificar, confirmar", ["Panel local con filtros y descargas log / csv / json / zip",
          "ZIP + manifiesto + hashes antes de limpiar", "Confirmación explícita de copia y frase de eliminación",
          "Deduplicación, cursores, pendientes y envíos protegidos"], None),
        ("09 · MEDICIONES", "Capacidad demostrada con fixtures", [
          f"1.000 mensajes · {largest['seconds']:.2f} s · {largest['metrics']['queries']} páginas",
          f"{largest['throughput']:.2f} mensajes/s; pico Python {largest['python_peak_bytes']/1048576:.2f} MiB",
          test_summary, "Estas cifras no miden Gmail ni Office reales"], None),
        ("10 · IMPACTO", "Automatizar con revisión y trazabilidad", ["Reglas visibles y categoría Otros para ambigüedad",
          "Campos mínimos y evidencia redactada; SQLite privado", "Incrementalidad, caché y lotes reducen trabajo repetido",
          "Mejora: recuperación + auditoría descargable verificable"], None),
        ("11 · ACEPTACIÓN", "Lo que falta demostrar", ["Contrastar pauta oficial y validar herramienta requerida",
          "Ejecutar Excel real con evidencia antes/después", "Leer buzón autorizado y enviar un consolidado de prueba",
          "Supabase verificado; falta confirmar recepción del correo real"], None)]


def presentations(slides, font, bold):
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    prs.core_properties.title = "RPA EP3 · Gestión inteligente de correos"
    prs.core_properties.author = "Equipo EP3"
    prs.core_properties.created = datetime(2026, 11, 17, tzinfo=timezone.utc)
    prs.core_properties.modified = prs.core_properties.created
    pdf = canvas.Canvas(str(DIST / "presentacion.pdf"), pagesize=(960, 540), invariant=1)
    for number, (kicker, title, bullets, figure) in enumerate(slides, 1):
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        slide.background.fill.solid()
        slide.background.fill.fore_color.rgb = RGBColor.from_string(NAVY)
        def textbox(text, left, top, width, height, size, color="FFFFFF", weight=False):
            shape = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
            frame = shape.text_frame
            frame.word_wrap = True
            frame.margin_left = frame.margin_right = 0
            p = frame.paragraphs[0]
            p.text = text
            p.font.name = "Arial"
            p.font.size = Pt(size)
            p.font.bold = weight
            p.font.color.rgb = RGBColor.from_string(color)
        textbox(kicker, .65, .45, 12, .4, 14, "68D4CE")
        textbox(title, .65, 1.0, 12, 1.05, 32, weight=True)
        for i, bullet in enumerate(bullets):
            textbox(bullet, .8, 2.3+i*.85, 11.7, .8, 23)
        if figure:
            stages = [("ENTRADA", "Gmail / fixtures"), ("ESTADO", "SQLite / cursores"),
                      ("REGLAS", "Categoría / plazo"), ("REPORTE", "Excel / plantilla"), ("SALIDA", "Outbox / auditoría")]
            for index, (label, detail) in enumerate(stages):
                left = .65 + index*2.43
                shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(left), Inches(3.3), Inches(2.23), Inches(1.6))
                shape.fill.solid(); shape.fill.fore_color.rgb = RGBColor.from_string("E7F4F5")
                shape.line.fill.background()
                textbox(label, left+.12, 3.6, 2.0, .4, 16, NAVY, True)
                textbox(detail, left+.12, 4.15, 2.0, .5, 13, NAVY)
                if index < 4:
                    textbox("→", left+2.24, 3.9, .2, .4, 14, "68D4CE")
            textbox("Panel local: consultar, exportar y limpiar con confirmación", .8, 5.55, 11.7, .6, 21)
        textbox(f"EP3 · ATY1102    |    {number:02d} / {len(slides):02d}", .65, 7.05, 12, .3, 10, "B9CBDE")
        slide.notes_slide.notes_text_frame.text = "Guion: docs/GUION_DEMO.md. " + " ".join(bullets)
        pdf.setFillColor(colors.HexColor("#"+NAVY)); pdf.rect(0, 0, 960, 540, fill=1, stroke=0)
        pdf.setFillColor(colors.HexColor("#68D4CE")); pdf.setFont(bold, 13); pdf.drawString(47, 496, kicker)
        pdf.setFillColor(colors.white); pdf.setFont(bold, 30); pdf.drawString(47, 439, title)
        y = 352
        style = ParagraphStyle("slide", fontName=font, fontSize=21, leading=29, textColor=colors.white)
        for bullet in bullets:
            p = Paragraph(escape(bullet), style)
            _, height = p.wrap(850, 90)
            p.drawOn(pdf, 58, y-height)
            y -= max(61, height+10)
        if figure:
            for index, (label, detail) in enumerate(stages):
                left = 47 + index*178
                pdf.setFillColor(colors.HexColor("#E7F4F5")); pdf.roundRect(left, 185, 160, 115, 8, fill=1, stroke=0)
                pdf.setFillColor(colors.HexColor("#"+NAVY)); pdf.setFont(bold, 15); pdf.drawString(left+10, 260, label)
                pdf.setFont(font, 13); pdf.drawString(left+10, 221, detail)
                if index < 4:
                    pdf.setFillColor(colors.HexColor("#68D4CE")); pdf.drawString(left+162, 235, "→")
            pdf.setFillColor(colors.white); pdf.setFont(font, 21)
            pdf.drawString(58, 117, "Panel local: consultar, exportar y limpiar con confirmación")
        pdf.setFont(font, 10); pdf.setFillColor(colors.HexColor("#B9CBDE"))
        pdf.drawString(47, 24, f"EP3 · ATY1102    |    {number:02d} / {len(slides):02d}")
        pdf.showPage()
    pptx_path = DIST / "presentacion.pptx"
    prs.save(pptx_path)
    # Normalizar también las fechas del ZIP interno de PowerPoint.
    with zipfile.ZipFile(BytesIO(pptx_path.read_bytes())) as source:
        entries = {name: source.read(name) for name in source.namelist()}
    with zipfile.ZipFile(pptx_path, "w", zipfile.ZIP_DEFLATED) as target:
        for name in sorted(entries):
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            target.writestr(info, entries[name])
    pdf.save()


def package():
    paths = []
    top = ["main.py", "autenticar_gmail.py", "demo_presentacion.py", "Abrir_Demo.cmd", "README.md", "pyproject.toml", "requirements.txt", "requirements-dev.txt", "requirements-lock.txt",
           ".env.example", ".gitignore", "PROMPT_CODEX_EP3_RPA_GESTION_CORREOS.md", "PROMPT_CODEX_GOOGLE_CLOUD_GMAIL_EP3.md"]
    for name in top:
        paths.append((ROOT / name, name))
    for directory in ("rpa", "config", "migrations", "supabase", "templates", "tests", "scripts", "docs", "fixtures"):
        for path in sorted((ROOT / directory).rglob("*")):
            if (path.is_file() and "__pycache__" not in path.parts and path.suffix not in {".pyc", ".private", ".bin"}
                    and not (directory == "config" and path.relative_to(ROOT/'config').as_posix() != "reglas.json")
                    and not any(word in path.name.lower() for word in ("credentials", "client_secret", "token_"))):
                paths.append((path, path.relative_to(ROOT).as_posix()))
    for name in ("informe_tecnico.pdf", "presentacion.pptx", "presentacion.pdf", "guion_demo.pdf"):
        paths.append((DIST / name, "entregables/"+name))
    manifest = {name: digest(path) for path, name in sorted(paths, key=lambda p: p[1])}
    target = DIST / "RPA_EP3_entrega.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path, name in sorted(paths, key=lambda p: p[1]):
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, path.read_bytes())
        info = zipfile.ZipInfo("MANIFEST.sha256.json", date_time=(2026, 1, 1, 0, 0, 0))
        archive.writestr(info, json.dumps(manifest, sort_keys=True, indent=2).encode())
    with zipfile.ZipFile(target) as archive:
        assert archive.testzip() is None
        for name, expected in manifest.items():
            assert hashlib.sha256(archive.read(name)).hexdigest() == expected
        assert not any(name.startswith(("runtime/", "output/", ".venv/")) or name == ".env" for name in archive.namelist())
    (DIST / "RPA_EP3_entrega.sha256").write_text(digest(target)+"  RPA_EP3_entrega.zip\n", encoding="utf-8")
    return {"files": len(paths), "sha256": digest(target), "bytes": target.stat().st_size}


def main():
    DIST.mkdir(parents=True, exist_ok=True)
    rl_config.invariant = 1
    font, bold = font_setup()
    benchmark = json.loads((EVIDENCE / "benchmark.json").read_text(encoding="utf-8"))
    checks = json.loads((EVIDENCE / "real_checks.json").read_text(encoding="utf-8"))
    suites = ET.parse(EVIDENCE / "pytest.xml").getroot().findall("testsuite")
    total = sum(int(s.attrib["tests"]) for s in suites)
    failed = sum(int(s.attrib["failures"])+int(s.attrib["errors"]) for s in suites)
    test_summary = f"{total} pruebas; {failed} fallos en la corrida registrada"
    assert failed == 0, "Corregir pruebas antes de generar una entrega validada"
    report(benchmark, checks, test_summary, font, bold)
    presentations(slides_data(benchmark, test_summary), font, bold)
    print(json.dumps(package(), indent=2))


if __name__ == "__main__":
    main()
