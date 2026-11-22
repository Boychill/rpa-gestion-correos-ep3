"""Exportación verificada y limpieza confirmada de logs gestionados; nunca borra SQLite."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import stat
import time
import uuid
import zipfile

from rpa.excel import file_hash
from rpa.runtime import RPAError, profile_lock
from rpa.store import encode, utcnow


def regular_file(path, base):
    if path.parent != base or path.is_symlink() or base.is_symlink():
        return False
    # También rechazar junctions/reparse points de Windows en todos los ancestros.
    for part in (path, *path.parents):
        if getattr(part.lstat(), "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024):
            return False
    return path.is_file() and path.resolve().parent == base.resolve()


def candidates(settings, store):
    base = settings.runtime / "logs"
    if not base.exists():
        return []
    result = []
    for path in base.iterdir():
        match = re.fullmatch(r"([0-9a-f-]{36})\.(DEBUG|INFO|ERROR)\.log(?:\.[1-3])?", path.name)
        if not match or not regular_file(path, base):
            continue
        run = store.row("SELECT status FROM executions WHERE id=?", (match[1],))
        if not run or run[0] in {"RUNNING", "PARTIAL", "REVIEW"}:
            continue
        days = getattr(settings, f"retention_{match[2].lower()}_days")
        age = (time.time()-path.stat().st_mtime)/86400
        if age >= days:
            result.append({"name": path.name, "size": path.stat().st_size, "sha256": file_hash(path),
                           "age_days": round(age, 2), "retention_days": days})
    return result


def export_logs(settings, store, selected):
    allowed = {item["name"]: item for item in candidates(settings, store)}
    if not selected or len(selected) != len(set(selected)) or any(name not in allowed for name in selected):
        raise RPAError("CLEANUP_SELECTION_INVALID")
    ident = str(uuid.uuid4())
    directory = settings.runtime / "exports"
    directory.mkdir(parents=True, exist_ok=True)
    manifest = {"id": ident, "created": utcnow(), "files": [allowed[name] for name in selected]}
    path = directory / f"{ident}.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for entry in manifest["files"]:
            archive.write(settings.runtime / "logs" / entry["name"], entry["name"])
        archive.writestr("manifest.json", encode(manifest))
    verify_archive(path, manifest)
    digest = file_hash(path)
    store.execute("INSERT INTO cleanups VALUES(?,?,?,?,?,NULL)", (ident, utcnow(), "EXPORTED", encode(manifest), digest))
    return {"id": ident, "sha256": digest, "manifest": manifest, "download": f"/api/archive/{ident}"}


def verify_archive(path, manifest):
    with zipfile.ZipFile(path) as archive:
        if archive.testzip() or json.loads(archive.read("manifest.json")) != manifest:
            raise RPAError("ARCHIVE_INVALID")
        for entry in manifest["files"]:
            if hashlib.sha256(archive.read(entry["name"])).hexdigest() != entry["sha256"]:
                raise RPAError("ARCHIVE_HASH_MISMATCH")


def clean_export(settings, store, ident, confirmation, saved_copy):
    if confirmation != f"ELIMINAR {ident}" or saved_copy is not True:
        raise RPAError("EXPLICIT_CONFIRMATION_REQUIRED")
    with profile_lock(settings.runtime / "locks/cleanup.lock"):
        row = store.row("SELECT * FROM cleanups WHERE id=?", (ident,))
        if not row or row["state"] != "EXPORTED":
            raise RPAError("CLEANUP_STATE_INVALID")
        path = settings.runtime / "exports" / f"{ident}.zip"
        if not regular_file(path, path.parent) or file_hash(path) != row["archive_hash"]:
            raise RPAError("ARCHIVE_HASH_MISMATCH")
        manifest = json.loads(row["manifest"])
        verify_archive(path, manifest)
        allowed = {item["name"]: item for item in candidates(settings, store)}
        for item in manifest["files"]:
            if item["name"] not in allowed or allowed[item["name"]]["sha256"] != item["sha256"]:
                raise RPAError("CLEANUP_SELECTION_CHANGED")
        deleted, failed = [], []
        # Marcar primero: un reinicio no vuelve a ejecutar ciegamente el borrado.
        store.execute("UPDATE cleanups SET state='DELETING' WHERE id=?", (ident,))
        for item in manifest["files"]:
            try:
                target = settings.runtime / "logs" / item["name"]
                if not regular_file(target, target.parent) or file_hash(target) != item["sha256"]:
                    raise OSError()
                target.unlink()
                deleted.append(item["name"])
            except OSError:
                failed.append(item["name"])
            store.execute("UPDATE cleanups SET result=? WHERE id=?", (encode(dict(deleted=deleted, failed=failed)), ident))
        store.execute("UPDATE cleanups SET state=? WHERE id=?", ("PARTIAL" if failed else "CLEANED", ident))
        return dict(deleted=deleted, failed=failed, database_preserved=True)
