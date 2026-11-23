"""Copias .log en runtime/logs/descargas y eliminación por antigüedad de archivos gestionados."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
import stat
import uuid

from rpa.cloud_logs import log_records
from rpa.excel import file_hash
from rpa.retention import candidates, regular_file
from rpa.runtime import RPAError, profile_lock
from rpa.store import encode, utcnow


def downloads_dir(settings):
    return settings.runtime / "logs/descargas"


def save_log(settings, store, records, source="LOCAL", execution_id=None):
    if source not in {"LOCAL", "SUPABASE"}:
        raise RPAError("LOG_SOURCE_INVALID")
    directory = downloads_dir(settings)
    # Validar antes de crear o escribir: no seguir junctions/enlaces hacia recursos ajenos.
    for part in (directory, *directory.parents):
        if part.is_symlink() or (part.exists() and getattr(part.lstat(), "st_file_attributes", 0)
                                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024)):
            raise RPAError("LOG_DIRECTORY_UNSAFE")
    directory.mkdir(parents=True, exist_ok=True)
    name = f"{source.lower()}-{uuid.uuid4()}.log"
    path = directory / name
    with profile_lock(settings.runtime / "locks/log_files.lock"):
        payload = "\n".join(encode(r) for r in records)+"\n"
        path.write_bytes(payload.encode("utf-8"))
        if not regular_file(path, directory):
            raise RPAError("LOG_DIRECTORY_UNSAFE")
        digest = hashlib.sha256(payload.encode()).hexdigest()
        if file_hash(path) != digest:
            raise RPAError("LOG_HASH_MISMATCH")
        created = utcnow()
        expires = (datetime.now(timezone.utc)+timedelta(days=settings.log_download_days)).isoformat()
        store.execute("INSERT INTO log_files VALUES(?,?,?,?,?,?,?)",
                      (name, execution_id, created, expires, digest, source, "ACTIVE"))
    return {"name": name, "folder": str(directory), "sha256": digest, "records": len(records),
            "created": created, "expires": expires, "download": f"/api/logs/files/{name}"}


def save_execution_log(settings, store, execution_id):
    records = log_records(store, execution_id, include_context=settings.supabase_context_enabled)
    if not records:
        raise RPAError("EXECUTION_LOG_NOT_READY")
    return save_log(settings, store, records, execution_id=execution_id)


def managed_download(settings, store, name):
    if not re.fullmatch(r"(?:local|supabase)-[0-9a-f-]{36}\.log", name):
        raise RPAError("LOG_NOT_FOUND")
    row = store.row("SELECT * FROM log_files WHERE name=? AND state='ACTIVE'", (name,))
    path = downloads_dir(settings) / name
    if not row or not path.exists() or not regular_file(path, path.parent) or file_hash(path) != row["sha256"]:
        raise RPAError("LOG_NOT_FOUND")
    return path


def auto_cleanup(settings, store):
    """Autorización: política explícita AUTO_CLEAN_LOGS. Nunca purga SQLite ni Supabase."""
    if not settings.auto_clean_logs:
        return {"enabled": False, "deleted": []}
    deleted, skipped = [], []
    with profile_lock(settings.runtime / "locks/cleanup.lock"), profile_lock(settings.runtime / "locks/log_files.lock"):
        for row in store.rows("SELECT * FROM log_files WHERE state='ACTIVE' AND expires<=?", (utcnow(),)):
            try:
                path = managed_download(settings, store, row["name"])
                path.unlink()
                store.execute("UPDATE log_files SET state='EXPIRED' WHERE name=?", (row["name"],))
                deleted.append("descargas/"+row["name"])
            except (OSError, RPAError):
                skipped.append(row["name"])
        # Logs rotativos originales: solo ejecuciones cerradas, edades por nivel y hash verificado.
        for entry in candidates(settings, store):
            path = settings.runtime / "logs" / entry["name"]
            try:
                if not regular_file(path, path.parent) or file_hash(path) != entry["sha256"]:
                    raise OSError()
                path.unlink()
                deleted.append(entry["name"])
            except OSError:
                skipped.append(entry["name"])
        if deleted or skipped:
            result = encode({"deleted": deleted, "skipped": skipped, "state_preserved": True})
            store.execute("INSERT INTO cleanups VALUES(?,?,?,?,?,?)", (str(uuid.uuid4()), utcnow(), "AUTO_RETENTION",
                encode({"download_days": settings.log_download_days, "policy": "AUTO_CLEAN_LOGS"}),
                hashlib.sha256(result.encode()).hexdigest(), result))
    return {"enabled": True, "deleted": deleted, "skipped": skipped}


def finish_logging(settings, store, execution_id):
    """Fallo del historial nunca cambia el resultado de correo ni permite un reenvío."""
    from rpa.cloud_logs import sync_logs
    result = {}
    for name, action in [("file", lambda: save_execution_log(settings, store, execution_id)),
                         ("supabase", lambda: sync_logs(settings, store, execution_id)),
                         ("retention", lambda: auto_cleanup(settings, store))]:
        try:
            result[name] = action()
        except Exception as exc:
            result[name] = {"status": "FAILED", "code": exc.code if isinstance(exc, RPAError) else type(exc).__name__}
    return result
