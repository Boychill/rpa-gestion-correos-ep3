"""Panel local: lecturas sanitizadas y limpieza con selección, archivo y confirmación."""
import csv
import asyncio
from contextlib import asynccontextmanager
from io import StringIO, BytesIO
import json
import secrets
import zipfile
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response, FileResponse
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from rpa.retention import candidates, export_logs, clean_export, regular_file
from rpa.runtime import RPAError, profile_lock
from rpa.store import Store
from rpa.cloud_logs import queue_status, sync_logs, fetch_cloud_logs, log_records
from rpa.log_files import save_log, auto_cleanup, managed_download


class Selection(BaseModel):
    names: list[str] = Field(max_length=500)


class Confirmation(BaseModel):
    confirmation: str
    saved_copy: bool


class LogDownload(BaseModel):
    source: str = "LOCAL"
    execution_id: str | None = None


def create_app(settings):
    def scheduled_cleanup():
        with Store(settings.runtime / "state.sqlite3", settings.root) as store:
            try:
                auto_cleanup(settings, store)
            except Exception as exc:
                store.execute("INSERT OR REPLACE INTO log_metadata VALUES('cleanup_error',?)", (type(exc).__name__,))

    @asynccontextmanager
    async def lifespan(app):
        await asyncio.to_thread(scheduled_cleanup)
        async def loop():
            while True:
                await asyncio.sleep(settings.log_cleanup_interval_seconds)
                await asyncio.to_thread(scheduled_cleanup)
        task = asyncio.create_task(loop())
        try:
            yield
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    app = FastAPI(title="RPA EP3 · Auditoría local", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])
    csrf = secrets.token_urlsafe(32)

    @app.middleware("http")
    async def local_guard(request, call_next):
        if request.headers.get("sec-fetch-site") == "cross-site":
            return Response(status_code=403)
        origin = request.headers.get("origin")
        if origin and origin != str(request.base_url).rstrip("/"):
            return Response(status_code=403)
        if request.method == "POST" and not secrets.compare_digest(request.headers.get("x-csrf-token", ""), csrf):
            return Response(status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'"
        return response

    def db():
        return Store(settings.runtime / "state.sqlite3", settings.root)

    @app.get("/", response_class=HTMLResponse)
    def index():
        return (settings.root / "templates/panel.html").read_text(encoding="utf-8").replace("__CSRF__", csrf)

    @app.get("/api/executions")
    def executions():
        with db() as store:
            return [dict(row) for row in store.rows("SELECT id,started,finished,status,source,metrics FROM executions ORDER BY started DESC LIMIT 500")]

    def query_events(execution_id=None, level=None, module=None, start=None, end=None):
        terms, args = [], []
        for column, op, value in [("execution_id", "=", execution_id), ("level", "=", level),
                                   ("step_id", "=", module), ("started", ">=", start), ("started", "<=", end)]:
            if value:
                terms.append(f"{column}{op}?")
                args.append(value)
        sql = "SELECT execution_id,step_id,started,finished,duration_ms,attempt,level,result,code FROM events"
        if terms:
            sql += " WHERE " + " AND ".join(terms)
        with db() as store:
            return [dict(row) for row in store.rows(sql+" ORDER BY id DESC LIMIT 10000", args)]

    @app.get("/api/events")
    def events(execution_id: str = "", level: str = "", module: str = "", start: str = "", end: str = ""):
        return query_events(execution_id, level, module, start, end)

    @app.get("/api/download/{fmt}")
    def download(fmt: str, execution_id: str = "", level: str = "", module: str = "", start: str = "", end: str = ""):
        rows = query_events(execution_id, level, module, start, end)
        if fmt == "json":
            data, media = json.dumps(rows, ensure_ascii=False).encode(), "application/json"
        elif fmt == "log":
            data, media = "\n".join(json.dumps(r, ensure_ascii=False) for r in rows).encode(), "text/plain"
        elif fmt == "csv":
            stream = StringIO(newline="")
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]) if rows else ["execution_id"])
            writer.writeheader()
            writer.writerows(rows)
            data, media = stream.getvalue().encode("utf-8-sig"), "text/csv"
        elif fmt == "zip":
            import hashlib
            stream = BytesIO()
            payload = json.dumps(rows, ensure_ascii=False).encode()
            with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("events.json", payload)
                archive.writestr("manifest.json", json.dumps({"events.json": hashlib.sha256(payload).hexdigest(),
                                                             "count": len(rows), "limit": 10000}))
            data, media = stream.getvalue(), "application/zip"
        else:
            raise HTTPException(404)
        return Response(data, media_type=media, headers={"Content-Disposition": f'attachment; filename="auditoria.{fmt}"'})

    @app.get("/api/storage")
    def storage():
        with db() as store:
            selection = candidates(settings, store)
        size = sum(p.stat().st_size for p in settings.runtime.rglob("*") if p.is_file() and not p.is_symlink())
        return dict(bytes=size, candidates=selection, retention={"DEBUG": settings.retention_debug_days,
            "INFO": settings.retention_info_days, "ERROR": settings.retention_error_days,
            "exports": settings.retention_export_days, "analytics": settings.analytics_retention_days},
            note=f"Limpieza automática de logs: {'activa' if settings.auto_clean_logs else 'inactiva'}. "
                 f"Copias .log: {settings.log_download_days} días. SQLite y Supabase se conservan. Descargas de auditoría: máximo 10000 eventos.")

    @app.get("/api/logs/status")
    def logs_status():
        with db() as store:
            return dict(queue_status(settings, store), files=[dict(r) for r in store.rows(
                "SELECT name,source,created,expires,sha256 FROM log_files WHERE state='ACTIVE' ORDER BY created DESC LIMIT 100")],
                folder="runtime/logs/descargas (dentro de RUNTIME_DIR)")

    @app.post("/api/logs/sync")
    def logs_sync():
        try:
            with profile_lock(settings.runtime / "locks/state.lock"), db() as store:
                return sync_logs(settings, store)
        except (RPAError, ValueError) as exc:
            raise HTTPException(400, exc.code if isinstance(exc, RPAError) else "SUPABASE_CONFIG_INVALID") from exc

    @app.post("/api/logs/save")
    def logs_save(selection: LogDownload):
        try:
            if selection.source not in {"LOCAL", "SUPABASE"}:
                raise RPAError("LOG_SOURCE_INVALID")
            with profile_lock(settings.runtime / "locks/state.lock"), db() as store:
                if selection.execution_id and not store.row("SELECT id FROM executions WHERE id=?", (selection.execution_id,)):
                    raise RPAError("EXECUTION_NOT_FOUND")
                records = (fetch_cloud_logs(settings, store, selection.execution_id) if selection.source == "SUPABASE"
                           else log_records(store, selection.execution_id))
                return save_log(settings, store, records, selection.source, selection.execution_id)
        except (RPAError, ValueError) as exc:
            raise HTTPException(400, exc.code if isinstance(exc, RPAError) else "LOG_CONFIG_INVALID") from exc

    @app.get("/api/logs/files/{name}")
    def logs_file(name: str):
        try:
            with db() as store:
                path = managed_download(settings, store, name)
            return FileResponse(path, filename=name, media_type="text/plain")
        except RPAError as exc:
            raise HTTPException(404, exc.code) from exc

    @app.post("/api/export")
    def export(selection: Selection):
        try:
            with db() as store:
                return export_logs(settings, store, selection.names)
        except RPAError as exc:
            raise HTTPException(400, exc.code) from exc

    @app.get("/api/archive/{ident}")
    def archive(ident: str):
        with db() as store:
            row = store.row("SELECT id FROM cleanups WHERE id=?", (ident,))
        if not row:
            raise HTTPException(404)
        path = settings.runtime / "exports" / f"{ident}.zip"
        if not path.exists() or not regular_file(path, path.parent):
            raise HTTPException(404)
        return FileResponse(path, filename=f"{ident}.zip")

    @app.post("/api/clean/{ident}")
    def clean(ident: str, confirmation: Confirmation):
        try:
            with db() as store:
                return clean_export(settings, store, ident, confirmation.confirmation, confirmation.saved_copy)
        except RPAError as exc:
            raise HTTPException(400, exc.code) from exc

    return app
