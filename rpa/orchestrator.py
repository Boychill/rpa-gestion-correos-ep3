"""main → run → lectura/clasificación → API/Excel → outbox → auditoría/mantenimiento."""
from dataclasses import asdict
import json
import time
import uuid
import httpx

from rpa.classify import Classifier
from rpa.excel import build_report, desktop_excel, verify_report
from rpa.holidays import Holidays
from rpa.http import ReaderHTTP
from rpa.mail_read import FixtureReader, GraphReader, authenticate
from rpa.mail_send import render, send_report
from rpa.runtime import Audit, Budget, RPAError, profile_lock
from rpa.store import Store, encode, utcnow
from rpa.log_files import finish_logging
from rpa.gmail import GmailReader, authenticate_gmail


def read_pages(settings, store, execution_id, reader, audit, budget, resume, metrics, progress=None):
    checkpoint = store.row("SELECT * FROM checkpoints WHERE scope=?", (settings.scope,))
    if resume and metrics.get("reading_complete"):
        return
    cursor = checkpoint["cursor"] if checkpoint else None
    resynced = False
    while True:
        budget.remaining()
        with audit.step("read_page"):
            try:
                page = reader.page(cursor)
            except RPAError as exc:
                if exc.code == "CURSOR_EXPIRED" and not resynced:
                    cursor, resynced = None, True
                    continue
                raise
            counts = store.ingest(execution_id, settings.identity, settings.scope, page.messages, page.cursor, page.phase)
            for key, value in counts.items():
                metrics[key] = metrics.get(key, 0) + value
            metrics["reading_complete"] = page.phase == "DELTA"
            store.execute("UPDATE executions SET metrics=? WHERE id=?", (encode(metrics), execution_id))
            if progress:
                progress({'stage':'Lectura guardada', 'done':metrics.get('new',0)+metrics.get('updated',0), 'total':None})
        if page.phase == "DELTA":
            break
        cursor = page.cursor


def classify_pending(settings, store, execution_id, classifier, audit, budget):
    while True:
        budget.remaining()
        with audit.step("classify_batch"):
            timer = time.monotonic()
            count = store.classify_batch(execution_id, classifier, settings.batch_size, settings.max_attempts)
            if time.monotonic()-timer > settings.batch_seconds:
                raise RPAError("BATCH_BUDGET_EXHAUSTED")
        if not count:
            return


def run(settings, resume_id=None, reader_factory=None, maintenance=None, progress=None):
    settings.validate()
    settings.runtime.mkdir(parents=True, exist_ok=True)
    settings.output.mkdir(parents=True, exist_ok=True)
    with profile_lock(settings.runtime / "locks" / f"{settings.profile}.lock"), \
            profile_lock(settings.runtime / "locks" / "state.lock"), \
            Store(settings.runtime / "state.sqlite3", settings.root) as store:
        active = store.row("SELECT * FROM executions WHERE status IN ('RUNNING','PARTIAL') ORDER BY started LIMIT 1")
        if active and resume_id != active["id"]:
            raise RPAError("RESUME_REQUIRED:" + active["id"])
        execution_id = resume_id or str(uuid.uuid4())
        if resume_id:
            previous = store.row("SELECT * FROM executions WHERE id=?", (resume_id,))
            if not previous or previous["profile"] != settings.profile or previous["signature"] != settings.signature:
                raise RPAError("RESUME_CONFIG_MISMATCH")
            existing = store.row("SELECT state FROM sends WHERE execution_id=?", (execution_id,))
            if existing:
                state = existing[0]
                if state in {"PREPARADO", "EN_ENVIO"}:
                    state = "ENVIO_INCIERTO"
                    store.execute("UPDATE sends SET state=?,updated=? WHERE execution_id=?", (state, utcnow(), execution_id))
                store.execute("UPDATE executions SET status=?,finished=? WHERE id=?",
                              ("REVIEW" if state in {"ENVIO_INCIERTO", "ERROR", "PENDIENTE_CUOTA"} else "COMPLETED", utcnow(), execution_id))
                return dict(execution_id=execution_id, status=state, resumed_without_send=True,
                            logs=finish_logging(settings, store, execution_id))
            if previous["status"] in {"COMPLETED", "NO_CHANGES", "REVIEW"}:
                return dict(execution_id=execution_id, status=previous["status"], resumed_without_send=True,
                            logs=finish_logging(settings, store, execution_id))
            started, metrics = previous["started"], json.loads(previous["metrics"])
            store.execute("UPDATE executions SET status='RUNNING' WHERE id=?", (execution_id,))
        else:
            started, metrics = utcnow(), {}
            store.execute("INSERT INTO executions(id,profile,signature,started,status,source) VALUES(?,?,?,?,?,?)",
                          (execution_id, settings.profile, settings.signature, started, "RUNNING", settings.source))
        audit = Audit(store, execution_id, settings.runtime / "logs")
        prior_seconds = metrics.get("total_active_seconds", 0)
        budget, timer = Budget(max(.001, settings.execution_seconds-prior_seconds)), time.monotonic()
        status, error, send_state = "PARTIAL", None, None
        http = reader = None
        try:
            with httpx.Client() as client:
                http = ReaderHTTP(client, settings, store, execution_id, audit, budget)
                with audit.step("configure_authenticate"):
                    classifier = Classifier(settings.root / "config/reglas.json")
                    token = (authenticate(settings, budget) if settings.source == "GRAPH" else
                             authenticate_gmail(settings, budget) if settings.source == "GMAIL" else None)
                    reader = (reader_factory(settings) if reader_factory else
                              GraphReader(settings, http, token) if settings.source == "GRAPH" else
                              GmailReader(settings, http, token) if settings.source == "GMAIL" else FixtureReader(settings))
                read_pages(settings, store, execution_id, reader, audit, budget, bool(resume_id), metrics, progress)
                if progress:progress({'stage':'Clasificando y calculando plazos', 'done':0,'total':None})
                classify_pending(settings, store, execution_id, classifier, audit, budget)
                items = store.items(execution_id)
                metrics.update(processed=len(items), classified=sum("category" in m for m in items))
                metrics["failed"] = metrics["processed"]-metrics["classified"]
                if not items:
                    status = "NO_CHANGES"
                else:
                    with audit.step("holidays"):
                        calendar = Holidays(settings, http)
                        calendar.apply(items)
                    with audit.step("excel_generate_verify"):
                        budget.remaining()
                        path = build_report(settings, execution_id, items, list(calendar.loaded.values()),
                                            started, utcnow(), prior_seconds+time.monotonic()-timer)
                        if settings.require_excel:
                            desktop_excel(settings, path, min(settings.batch_seconds, budget.remaining()))
                            verify_report(path, execution_id, len(items))
                    if calendar.errors or metrics["failed"]:
                        raise RPAError("REPORT_PARTIAL_SEND_BLOCKED")
                    with audit.step("prepare_send") as outcome:
                        body = render(settings, execution_id, metrics, prior_seconds+time.monotonic()-timer)
                        send_state = send_report(settings, store, execution_id, path, body, client, token, budget)
                        if send_state in {"ENVIO_INCIERTO", "ERROR", "PENDIENTE_CUOTA"}:
                            outcome.update(result='FAILED', code='REPORT_'+send_state)
                            error = 'REPORT_'+send_state
                    status = "REVIEW" if send_state in {"ENVIO_INCIERTO", "ERROR", "PENDIENTE_CUOTA"} else "COMPLETED"
                    # Resultado durable antes del mantenimiento; su fallo no permite otro envío.
                    store.execute("UPDATE executions SET status=? WHERE id=?", (status, execution_id))
                try:
                    with audit.step("maintenance"):
                        if maintenance:
                            maintenance()
                        else:
                            store.db.execute("PRAGMA wal_checkpoint(PASSIVE)")
                except Exception:
                    metrics["maintenance_failed"] = True
        except Exception as exc:
            error = exc.code if isinstance(exc, RPAError) else type(exc).__name__
            audit.event("execution", started, (time.monotonic()-timer)*1000, result="FAILED", code=error)
        finally:
            metrics["duration_seconds"] = round(time.monotonic()-timer, 4)
            metrics["total_active_seconds"] = round(prior_seconds + metrics["duration_seconds"], 4)
            metrics["queries"] = metrics.get("queries", 0) + (reader.queries if reader else 0)
            metrics["http_queries"] = metrics.get("http_queries", 0) + (http.queries if http else 0)
            metrics["retries"] = metrics.get("retries", 0) + (http.retries if http else 0)
            metrics["messages_per_second"] = round(metrics.get("processed", 0)/max(metrics["total_active_seconds"], .001), 2)
            result = dict(execution_id=execution_id, status=status, send_state=send_state, error=error,
                          source=settings.source, holiday_mode=settings.holiday_mode, metrics=metrics)
            store.execute("UPDATE executions SET status=?,finished=?,metrics=? WHERE id=?",
                          (status, utcnow(), encode(metrics), execution_id))
            directory = settings.output / execution_id
            directory.mkdir(parents=True, exist_ok=True)
            audit.close()
            result["logs"] = finish_logging(settings, store, execution_id)
            (directory / "resultado.json").write_text(encode(result), encoding="utf-8")
        return result
