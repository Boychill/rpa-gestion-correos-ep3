import json
import os
import re
import time
import uuid
import pytest
from fastapi.testclient import TestClient

from rpa.panel import create_app
from rpa.retention import candidates, clean_export, export_logs
from rpa.runtime import RPAError
from rpa.store import utcnow


def old_log(settings, store, status="COMPLETED"):
    ident = str(uuid.uuid4())
    store.execute("INSERT INTO executions(id,profile,signature,started,status,source) VALUES(?,?,?,?,?,?)",
                  (ident, "demo", "sig", utcnow(), status, "FIXTURE"))
    path = settings.runtime / "logs" / f"{ident}.INFO.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("redacted audit\n", encoding="utf-8")
    old = time.time()-40*86400
    os.utime(path, (old, old))
    return path


def test_export_clean_preserves_database(settings, store):
    path = old_log(settings, store)
    active = old_log(settings, store, "RUNNING")
    assert [c["name"] for c in candidates(settings, store)] == [path.name]
    data = export_logs(settings, store, [path.name])
    assert path.exists()
    with pytest.raises(RPAError, match="EXPLICIT_CONFIRMATION_REQUIRED"):
        clean_export(settings, store, data["id"], "yes", True)
    result = clean_export(settings, store, data["id"], "ELIMINAR " + data["id"], True)
    assert result["database_preserved"] and not path.exists() and active.exists()
    assert store.row("SELECT COUNT(*) FROM executions")[0] == 3


def test_tampered_export_and_arbitrary_paths(settings, store):
    path = old_log(settings, store)
    with pytest.raises(RPAError):
        export_logs(settings, store, ["../state.sqlite3"])
    data = export_logs(settings, store, [path.name])
    (settings.runtime / "exports" / f"{data['id']}.zip").write_bytes(b"tamper")
    with pytest.raises(RPAError, match="ARCHIVE_HASH_MISMATCH"):
        clean_export(settings, store, data["id"], "ELIMINAR " + data["id"], True)
    assert path.exists()


def test_changed_file_blocked(settings, store):
    path = old_log(settings, store)
    data = export_logs(settings, store, [path.name])
    path.write_text("new content", encoding="utf-8")
    with pytest.raises(RPAError, match="CLEANUP_SELECTION_CHANGED"):
        clean_export(settings, store, data["id"], "ELIMINAR " + data["id"], True)
    assert path.exists()


def test_panel_filters_downloads_csrf(settings, store):
    path = old_log(settings, store)
    with TestClient(create_app(settings)) as client:
        html = client.get("/").text
        token = re.search("const token='([^']+)'", html)[1]
        assert client.get("/api/executions").status_code == 200
        assert client.get("/api/events?execution_id=none").json() == []
        for fmt in ("json", "log", "csv", "zip"):
            assert client.get(f"/api/download/{fmt}").status_code == 200
        assert client.post("/api/export", json={"names": [path.name]}).status_code == 403
        assert client.post("/api/export", json={"names": [path.name]},
            headers={"x-csrf-token": token, "Origin": "https://evil.example"}).status_code == 403
        response = client.post("/api/export", json={"names": [path.name]}, headers={"x-csrf-token": token})
        assert response.status_code == 200
        assert client.get(response.json()["download"]).status_code == 200
        assert client.get("/", headers={"Host": "evil.example"}).status_code == 400
