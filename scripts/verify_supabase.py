"""Prueba real explícita: esquema, sincronización, upsert idempotente y descarga con hash.
No envía correos, no crea proyectos, no elimina filas y nunca imprime claves/respuestas privadas.
"""
from pathlib import Path
import hashlib
import json
import math
import sys
import time
import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rpa.config import Settings, timestamp
from rpa.cloud_logs import LOG_COLUMNS, headers, log_records, sync_logs, fetch_cloud_logs
from rpa.excel import file_hash
from rpa.log_files import save_log, managed_download
from rpa.runtime import RPAError, profile_lock
from rpa.store import Store, utcnow


def check(condition, code):
    if not condition:
        raise RPAError(code)


def verify():
    timer = time.monotonic()
    evidence = {"checked_at": utcnow(), "origin": "REAL_SUPABASE", "status": "FAILED",
                "mail_sent": False, "checks": {}, "http": []}
    def record(response):
        # Solo método/código; nunca URL, headers ni cuerpo.
        evidence["http"].append({"method": response.request.method, "status": response.status_code})
    try:
        settings = Settings.load(ROOT)
        check(settings.supabase_enabled, "SUPABASE_DISABLED")
        evidence["project_fingerprint"] = hashlib.sha256(settings.supabase_url.encode()).hexdigest()[:16]
        url = settings.supabase_url.rstrip("/")+"/rest/v1/rpa_logs"
        with profile_lock(settings.runtime / "locks/state.lock"), Store(settings.runtime / "state.sqlite3", ROOT) as store, \
                httpx.Client(timeout=min(15, settings.http_timeout), follow_redirects=False,
                             event_hooks={"response": [record]}) as client:
            response = client.get(url, headers=headers(settings), params={"select": ",".join(LOG_COLUMNS), "limit": "0"})
            check(response.status_code == 200, f"PREFLIGHT_HTTP_{response.status_code}")
            evidence["checks"]["schema_read"] = "PASSED"
            local = log_records(store)
            check(bool(local), "NO_LOCAL_LOGS_TO_VERIFY")
            first = sync_logs(settings, store, client=client)
            evidence["sync"] = first
            check(first["status"] == "SYNCED", "QUEUE_NOT_FULLY_SYNCED")
            remote = fetch_cloud_logs(settings, store, client=client)
            remote_by_id = {r["id"]: r for r in remote}
            check(len(remote_by_id) == len(remote), "REMOTE_DUPLICATES")
            for item in local:
                check(item["id"] in remote_by_id, "REMOTE_LOG_MISSING")
                found = remote_by_id[item["id"]]
                for key in LOG_COLUMNS:
                    if key in {"started", "finished"} and item[key] is not None:
                        check(timestamp(found[key]) == timestamp(item[key]), "REMOTE_TIMESTAMP_MISMATCH")
                    elif key == "duration_ms":
                        check(math.isclose(found[key], item[key], abs_tol=.001), "REMOTE_DURATION_MISMATCH")
                    else:
                        check(found[key] == item[key], "REMOTE_VALUE_MISMATCH")
            evidence["checks"]["persisted_values"] = "PASSED"
            evidence["local_records"] = len(local)
            evidence["remote_records"] = len(remote)
            # Reenviar el mismo ID de forma deliberada verifica la restricción remota, no solo la cola.
            response = client.post(url, headers=headers(settings), params={"on_conflict": "id"}, json=[local[0]])
            check(response.status_code in {200, 201, 204}, f"UPSERT_HTTP_{response.status_code}")
            after = fetch_cloud_logs(settings, store, client=client)
            check({r["id"] for r in after} == set(remote_by_id) and len(after) == len(remote), "UPSERT_CREATED_DUPLICATE")
            evidence["checks"]["remote_upsert_no_duplicates"] = "PASSED"
            second = sync_logs(settings, store, client=client)
            check(second["requests"] == 0, "UNCHANGED_LOGS_SENT_AGAIN")
            evidence["checks"]["second_sync_zero_requests"] = "PASSED"
            saved = save_log(settings, store, after, "SUPABASE")
            path = managed_download(settings, store, saved["name"])
            check(file_hash(path) == saved["sha256"], "DOWNLOAD_HASH_MISMATCH")
            loaded = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
            check(loaded == after, "DOWNLOAD_CONTENT_MISMATCH")
            evidence["checks"]["download_hash_and_content"] = "PASSED"
            evidence["download"] = {key: saved[key] for key in ("name", "sha256", "records", "created", "expires")}
            # Esto verifica el rechazo en la API sin clave; no sustituye una auditoría SQL de RLS.
            response = client.get(url, params={"select": "id", "limit": "0"})
            check(response.status_code in {401, 403}, "UNAUTHENTICATED_API_ACCESS")
            evidence["checks"]["unauthenticated_request_denied"] = "PASSED"
            evidence["max_attempts"] = settings.log_sync_max_attempts
            evidence["retention_days"] = settings.log_download_days
            evidence["status"] = "VERIFIED"
    except Exception as exc:
        evidence["error"] = exc.code if isinstance(exc, RPAError) else type(exc).__name__
    evidence["duration_seconds"] = round(time.monotonic()-timer, 3)
    target = ROOT / "docs/evidence/supabase_real_checks.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0 if evidence["status"] == "VERIFIED" else 2


if __name__ == "__main__":
    sys.exit(verify())
