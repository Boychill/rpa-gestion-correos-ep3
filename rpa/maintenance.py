"""Respaldo consistente y purga analítica explícita. Nunca borra el estado operativo."""
from datetime import datetime, timedelta, timezone
import json
import sqlite3
import uuid

from rpa.excel import file_hash
from rpa.retention import regular_file
from rpa.runtime import RPAError
from rpa.store import utcnow


def backup(settings, store):
    directory = settings.runtime / "backups"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{uuid.uuid4()}.sqlite3"
    with sqlite3.connect(path) as target:
        store.db.backup(target)
        if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RPAError("BACKUP_INVALID")
    manifest = {"file": path.name, "sha256": file_hash(path), "created": utcnow(), "integrity": "ok"}
    path.with_suffix(".json").write_text(json.dumps(manifest), encoding="utf-8")
    return path, manifest


def preview(settings, store):
    cutoff = (datetime.now(timezone.utc)-timedelta(days=settings.analytics_retention_days)).isoformat()
    # Auditoría técnica informativa de ejecuciones sin envío real; conservar finales y errores.
    rows = store.rows("""SELECT v.id FROM events v JOIN executions e ON e.id=v.execution_id
        LEFT JOIN sends s ON s.execution_id=e.id
        WHERE v.started<? AND v.level IN ('INFO','DEBUG') AND e.status IN ('COMPLETED','NO_CHANGES')
        AND (s.state='DRY_RUN' OR s.state IS NULL)
        AND v.step_id IN ('http_get','read_page','classify_batch','holidays','configure_authenticate')""", (cutoff,))
    exports = []
    export_cutoff = (datetime.now(timezone.utc)-timedelta(days=settings.retention_export_days)).isoformat()
    for row in store.rows("SELECT id,archive_hash FROM cleanups WHERE created<? AND state IN ('EXPORTED','CLEANED')", (export_cutoff,)):
        path = settings.runtime / "exports" / f"{row['id']}.zip"
        if path.exists() and regular_file(path, path.parent) and file_hash(path) == row["archive_hash"]:
            exports.append(row["id"])
    return {"event_ids": [r[0] for r in rows], "export_ids": exports, "cutoff": cutoff}


def purge_events(settings, store, confirmation):
    if confirmation != "PURGAR_EVENTOS_NO_PROTEGIDOS":
        raise RPAError("EXPLICIT_CONFIRMATION_REQUIRED")
    selection = preview(settings, store)
    path, manifest = backup(settings, store)
    if file_hash(path) != manifest["sha256"]:
        raise RPAError("BACKUP_INVALID")
    ident = str(uuid.uuid4())
    with store.db:
        store.db.executemany("DELETE FROM events WHERE id=?", [(i,) for i in selection["event_ids"]])
        store.db.execute("INSERT INTO cleanups VALUES(?,?,?,?,?,?)", (ident, utcnow(), "ANALYTICS_PURGED",
            json.dumps({"backup": manifest, "events": selection["event_ids"]}), manifest["sha256"],
            json.dumps({"deleted": len(selection["event_ids"]), "operational_state_preserved": True})))
    return {"deleted_events": len(selection["event_ids"]), "backup": str(path), "sha256": manifest["sha256"]}


def expire_exports(settings, store, confirmation):
    if confirmation != "ELIMINAR_EXPORTACIONES_VENCIDAS":
        raise RPAError("EXPLICIT_CONFIRMATION_REQUIRED")
    deleted = []
    for ident in preview(settings, store)["export_ids"]:
        row = store.row("SELECT archive_hash FROM cleanups WHERE id=?", (ident,))
        path = settings.runtime / "exports" / f"{ident}.zip"
        if regular_file(path, path.parent) and file_hash(path) == row[0]:
            path.unlink()
            store.execute("UPDATE cleanups SET state='ARCHIVE_EXPIRED' WHERE id=?", (ident,))
            deleted.append(ident)
    return {"deleted_exports": deleted}
