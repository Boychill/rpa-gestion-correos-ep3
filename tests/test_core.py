from dataclasses import replace
import json
from pathlib import Path
import pytest
from openpyxl import load_workbook

from rpa.classify import Classifier
from rpa.excel import build_report, safe_text, verify_report
from rpa.holidays import Holidays, validate_holidays
from rpa.mail_read import FixtureReader
from rpa.orchestrator import run
from rpa.runtime import RPAError, profile_lock
from rpa.store import Store


@pytest.mark.parametrize("subject,category", [("", "Otros"), ("URGÉNTE reclamo consulta", "Urgente"),
    ("Información de servicio", "Información"), ("consulta y reclamo", "Reclamo"),
    ("solicito certificado", "Solicitud"), ("consultante", "Otros")])
def test_rules(settings, subject, category):
    assert Classifier(settings.root / "config/reglas.json").classify(subject)[0] == category


def test_invalid_rules(settings, tmp_path):
    data = json.loads((settings.root / "config/reglas.json").read_text(encoding="utf-8"))
    data["rules"][1]["priority"] = data["rules"][0]["priority"]
    path = tmp_path / "rules.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        Classifier(path)


def test_atomic_ingest_and_genuine_update(settings, store):
    page = FixtureReader(settings).page()
    def crash():
        raise RuntimeError("power loss")
    with pytest.raises(RuntimeError):
        store.ingest("test", "mailbox", "scope", page.messages, page.cursor, page.phase, crash)
    assert store.row("SELECT COUNT(*) FROM messages")[0] == 0
    assert store.row("SELECT COUNT(*) FROM checkpoints")[0] == 0
    assert store.ingest("test", "mailbox", "scope", page.messages, page.cursor, page.phase)["new"] == 100
    assert store.ingest("test", "mailbox", "scope", page.messages, page.cursor, page.phase)["duplicates"] == 100
    page.messages[0]["subject"] = "Urgente actualización"
    counts = store.ingest("test", "mailbox", "scope", page.messages, page.cursor, page.phase)
    assert counts["updated"] == 1 and counts["duplicates"] == 99


def test_recover_interrupted_pagination(settings):
    settings = replace(settings, fixture_count=300)
    class Interrupt(FixtureReader):
        def page(self, cursor=None):
            if cursor:
                raise RPAError("SIMULATED_INTERRUPT")
            return super().page(cursor)
    first = run(settings, reader_factory=Interrupt)
    assert first["status"] == "PARTIAL"
    with pytest.raises(RPAError, match="RESUME_REQUIRED"):
        run(settings)
    recovered = run(settings, first["execution_id"])
    assert recovered["status"] == "COMPLETED"
    assert recovered["metrics"]["processed"] == 300
    assert run(settings)["status"] == "NO_CHANGES"
    with Store(settings.runtime / "state.sqlite3", settings.root) as db:
        assert db.row("SELECT COUNT(*) FROM messages")[0] == 300
        assert db.row("SELECT COUNT(*) FROM sends")[0] == 1


def test_tombstone(settings, store):
    msg = FixtureReader(settings).page().messages[0]
    store.ingest("test", "box", "scope", [msg], "a", "NEXT")
    store.ingest("test", "box", "scope", [{"id": msg["id"], "removed": True}], "b", "DELTA")
    assert not store.items("test")
    assert store.row("SELECT state FROM messages")[0] == "REMOVED"


def test_year_boundary_and_timezone(settings):
    calendar = Holidays(replace(settings, business_days=2), None)
    # 31 dic 2026 jueves; excluye viernes feriado 1 ene y fin de semana.
    assert calendar.due("2026-12-31T16:00:00Z") == ("2027-01-05", "OK")
    assert set(calendar.loaded) == {2027}
    assert calendar.due("2027-01-01T01:00:00Z")[0] == "2027-01-05"  # aún 31 dic en Chile


def test_missing_holiday_coverage(settings):
    class FailingHTTP:
        def get(self, *args):
            raise RPAError("HTTP_404")
    calendar = Holidays(replace(settings, holiday_mode="LIVE"), FailingHTTP())
    assert calendar.due("2026-12-31T16:00:00Z") == (None, "HTTP_404")
    with pytest.raises(RPAError):
        validate_holidays([{"date": "2027-01-01"}], 2026)


@pytest.mark.parametrize("value", ["=1+1", "+SUM(A1)", "-1", "@x", " \t=HYPERLINK(\"x\")"])
def test_formula_injection(value):
    assert safe_text(value).startswith("'")


def test_report_styles_formula_chart_and_hash(settings):
    result = run(settings)
    path = settings.output / result["execution_id"] / "reporte.xlsx"
    manifest = verify_report(path, result["execution_id"], 100)
    assert manifest["size"] > 1000
    book = load_workbook(path)
    assert book["Resumen"]["B8"].data_type == "f"
    assert book["Correos"]["A1"].font.bold
    assert book["Resumen"]._charts
    assert all(row[2].value == "[oculto]" for row in list(book["Correos"].rows)[1:])
    book.close()
    with pytest.raises(RPAError, match="REPORT_ID_INVALID"):
        verify_report(path, "wrong")


def test_corrupt_template(settings, tmp_path):
    root = tmp_path / "bad template"
    (root / "templates").mkdir(parents=True)
    (root / "templates/reporte_base.xlsx").write_bytes(b"not a workbook")
    with pytest.raises(RPAError, match="TEMPLATE_INVALID"):
        build_report(replace(settings, root=root), "test", [], [], "start", "end", 1)


def test_windows_locked_workbook(settings):
    import sys
    if sys.platform != "win32":
        pytest.skip("Prueba de bloqueo exclusivo Win32")
    import win32file
    import win32con
    from rpa.excel import assert_unlocked
    path = settings.output / "locked.xlsx"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"locked")
    handle = win32file.CreateFile(str(path), win32con.GENERIC_READ, 0, None, win32con.OPEN_EXISTING, 0, None)
    try:
        with pytest.raises(RPAError, match="WORKBOOK_LOCKED"):
            assert_unlocked(path)
    finally:
        handle.Close()
    assert_unlocked(path)


def test_profile_lock(settings):
    path = settings.runtime / "locks/test.lock"
    with profile_lock(path):
        with pytest.raises(RPAError, match="PROFILE_BUSY"):
            with profile_lock(path):
                pass


def test_maintenance_never_resends(settings):
    def fail():
        raise OSError("simulated")
    first = run(settings, maintenance=fail)
    assert first["status"] == "COMPLETED" and first["metrics"]["maintenance_failed"]
    again = run(settings, first["execution_id"])
    assert again["resumed_without_send"]


def test_attempts_survive_resume(settings, store):
    class BadRules:
        def classify(self, subject):
            raise ValueError()
    msg = FixtureReader(settings).page().messages[0]
    store.ingest("test", "box", "scope", [msg], "done", "DELTA")
    for _ in range(3):
        store.classify_batch("test", BadRules(), 100, 3)
    assert store.classify_batch("test", BadRules(), 100, 3) == 0
    assert tuple(store.row("SELECT state,attempts FROM messages")) == ("REVIEW", 3)


def test_launcher_from_another_directory(settings, tmp_path):
    import os
    import subprocess
    import sys
    env = dict(os.environ, SOURCE="FIXTURE", HOLIDAY_MODE="FIXTURE", MAIL_MODE="DRY_RUN",
               REQUIRE_EXCEL="false", RUNTIME_DIR=str(settings.runtime), OUTPUT_DIR=str(settings.output),
               SUPABASE_ENABLED="false", SUPABASE_URL="", SUPABASE_SECRET_KEY="")
    result = subprocess.run([sys.executable, str(settings.root / "main.py"), "run", "--count", "100"],
                            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr + result.stdout
    assert json.loads(result.stdout)["metrics"]["classified"] == 100


def test_resume_after_failure_before_new_delta_round(settings):
    first = run(settings)
    assert first["status"] == "COMPLETED"
    class BeforeRead(FixtureReader):
        def page(self, cursor=None):
            raise RPAError("INTERRUPTED_BEFORE_READ")
    failed = run(settings, reader_factory=BeforeRead)
    assert failed["status"] == "PARTIAL"
    calls = []
    class NextRound(FixtureReader):
        def page(self, cursor=None):
            calls.append(cursor)
            from rpa.mail_read import Page
            msg = FixtureReader(settings).page().messages[0]
            msg["id"] = "new-on-next-round"
            return Page([msg], "fixture:done", "DELTA")
    result = run(settings, failed["execution_id"], reader_factory=NextRound)
    assert result["metrics"]["processed"] == 1
    assert len(calls) == 1
