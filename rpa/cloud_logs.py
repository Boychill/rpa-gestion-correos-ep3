"""Historial Supabase por REST. Cola local durable, upsert idempotente y tres intentos máximos.
Una invocación hace como máximo una petición por lote; Retry-After agenda la siguiente.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import time
import uuid
import httpx

from rpa.http import retry_delay
from rpa.runtime import RPAError, profile_lock
from rpa.store import encode, utcnow

LOG_COLUMNS = ("id", "installation_id", "execution_id", "source", "processed", "classified", "failed", "send_state",
               "kind", "step_id", "started", "finished", "duration_ms", "attempt", "retries", "status", "level", "code")
CONTEXT_COLUMNS = ('campaign_id', 'job_id', 'role', 'http_status', 'recovery')


def columns(settings):
    return LOG_COLUMNS + (CONTEXT_COLUMNS if settings.supabase_context_enabled else ())


def campaign_id(value):
    try: return str(uuid.UUID((value or '').removeprefix('RPA-TEST-')))
    except (ValueError, AttributeError): return None


def installation_id(store):
    store.execute("INSERT OR IGNORE INTO log_metadata VALUES('installation_id',?)", (str(uuid.uuid4()),))
    return store.row("SELECT value FROM log_metadata WHERE key='installation_id'")[0]


def log_records(store, execution_id=None, *, include_context=False):
    installation = installation_id(store)
    args = (execution_id,) if execution_id else ()
    condition = " AND id=?" if execution_id else ""
    records = []
    for run in store.rows("SELECT * FROM executions WHERE status!='RUNNING'"+condition+" ORDER BY started", args):
        metrics = json.loads(run["metrics"])
        send = store.row("SELECT state FROM sends WHERE execution_id=?", (run["id"],))
        failure = store.row("SELECT code FROM events WHERE execution_id=? AND result='FAILED' ORDER BY id DESC LIMIT 1", (run["id"],))
        status = {"COMPLETED": "COMPLETADO", "NO_CHANGES": "COMPLETADO", "PARTIAL": "FALLIDO", "REVIEW": "REVISION"}.get(run["status"], run["status"])
        base = dict(installation_id=installation, execution_id=run["id"], source=run["source"],
                    processed=int(metrics.get("processed", 0)), classified=int(metrics.get("classified", 0)),
                    failed=int(metrics.get("failed", 0)), send_state=send[0] if send else None)
        context_rows = store.rows('SELECT c.* FROM event_context c JOIN events e ON e.id=c.event_id WHERE e.execution_id=?', (run['id'],)) if include_context else []
        contexts = {row['event_id']:dict(row) for row in context_rows}
        cid = (campaign_id(run['signature']) if run['source'] in ('GMAIL_TEST_SEND','GMAIL_CONSOLIDATED') else None)
        cid = cid or next((campaign_id(r['dataset']) for r in context_rows if campaign_id(r['dataset'])), None)
        if include_context:
            last = contexts.get(store.row('SELECT id FROM events WHERE execution_id=? ORDER BY id DESC LIMIT 1',(run['id'],))[0], {}) if contexts else {}
            base.update(campaign_id=cid, job_id=run['id'], role=last.get('role'), http_status=last.get('http_status'), recovery=last.get('recovery','NONE'))
        records.append(dict(base, id=f"{installation}:execution:{run['id']}", kind="execution", step_id="execution",
            started=run["started"], finished=run["finished"],
            duration_ms=round(metrics.get("total_active_seconds", metrics.get("duration_seconds", 0))*1000, 3),
            attempt=1, retries=int(metrics.get("retries", 0)), status=status,
            level="INFO" if status == "COMPLETADO" else "ERROR",
            code=failure[0] if failure and status != "COMPLETADO" else "OK"))
        for event in store.rows("SELECT * FROM events WHERE execution_id=? ORDER BY id", (run["id"],)):
            # Incluir inicio evita colisiones si SQLite reutiliza un ID después de una purga.
            key = hashlib.sha256(f"{run['id']}:{event['id']}:{event['started']}".encode()).hexdigest()
            records.append(dict(base, id=f"{installation}:event:{key}", kind="event", step_id=event["step_id"],
                started=event["started"], finished=event["finished"], duration_ms=round(event["duration_ms"], 3),
                attempt=event["attempt"], retries=max(0, event["attempt"]-1),
                status="COMPLETADO" if event["result"] == "OK" else "FALLIDO", level=event["level"], code=event["code"],
                # Eventos son inmutables aunque cambie el resumen al reanudar.
                processed=0, classified=0, failed=0, send_state=None))
            if include_context:
                ctx = contexts.get(event['id'], {})
                records[-1].update(campaign_id=campaign_id(ctx.get('dataset')) or cid, job_id=ctx.get('job_id'),
                    role=ctx.get('role'), http_status=ctx.get('http_status'), recovery=ctx.get('recovery','NONE'))
    return records


def enqueue(store, records):
    now = utcnow()
    with store.db:
        for record in records:
            payload = encode(record)
            digest = hashlib.sha256(payload.encode()).hexdigest()
            old = store.row("SELECT * FROM log_outbox WHERE id=?", (record["id"],))
            if old and old["digest"] == digest:
                continue
            # Solo una revisión nueva de un registro ya sincronizado comienza otro contador.
            state = "PENDING" if not old or old["state"] == "SYNCED" else old["state"]
            attempts = 0 if not old or old["state"] == "SYNCED" else old["attempts"]
            due = now if not old or old["state"] == "SYNCED" else old["next_attempt"]
            store.db.execute("""INSERT INTO log_outbox VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                payload=excluded.payload,digest=excluded.digest,state=excluded.state,attempts=excluded.attempts,
                next_attempt=excluded.next_attempt,updated=excluded.updated""",
                (record["id"], record["execution_id"], payload, digest, state, attempts, due, "OK", now))


def queue_status(settings, store):
    counts = {row[0]: row[1] for row in store.rows("SELECT state,count(*) FROM log_outbox GROUP BY state")}
    return {"enabled": settings.supabase_enabled, "configured": bool(settings.supabase_url and settings.supabase_secret_key),
            "counts": counts, "max_attempts": settings.log_sync_max_attempts,
            "download_days": settings.log_download_days, "auto_clean_logs": settings.auto_clean_logs}


def headers(settings):
    # Las nuevas secret keys no son JWT; no colocarlas en Authorization: Bearer.
    return {"apikey": settings.supabase_secret_key, "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates,return=minimal"}


def sync_logs(settings, store, execution_id=None, client=None):
    settings.validate()
    with profile_lock(settings.runtime / "locks/cloud_logs.lock"):
        enqueue(store, log_records(store, execution_id, include_context=settings.supabase_context_enabled))
        if not settings.supabase_enabled:
            return dict(queue_status(settings, store), requests=0, status="DISABLED")
        own_client = client is None
        client = client or httpx.Client()
        requests, synced = 0, 0
        deadline = time.monotonic() + settings.log_sync_seconds
        try:
            # Un proceso pudo morir después del POST. Upsert con el mismo ID permite recuperarlo.
            store.execute("""UPDATE log_outbox SET state=CASE WHEN attempts>=? THEN 'REVIEW' ELSE 'PENDING' END,
                code='INTERRUPTED' WHERE state='IN_FLIGHT'""", (settings.log_sync_max_attempts,))
            store.execute("UPDATE log_outbox SET state='REVIEW' WHERE state='PENDING' AND attempts>=?",
                          (settings.log_sync_max_attempts,))
            for _ in range(settings.log_sync_max_batches):
                remaining = deadline-time.monotonic()
                if remaining <= 0:
                    break
                rows = store.rows("""SELECT * FROM log_outbox WHERE state='PENDING' AND attempts<?
                    AND next_attempt<=? ORDER BY updated,id LIMIT ?""",
                    (settings.log_sync_max_attempts, utcnow(), settings.log_sync_batch_size))
                if not rows:
                    break
                # Persistir antes de salir a la red, incluida la espera de recuperación.
                next_time = (datetime.now(timezone.utc)+timedelta(seconds=2)).isoformat()
                with store.db:
                    store.db.executemany("UPDATE log_outbox SET state='IN_FLIGHT',attempts=attempts+1,next_attempt=?,updated=? WHERE id=?",
                                         [(next_time, utcnow(), r["id"]) for r in rows])
                response = None
                requests += 1
                try:
                    response = client.post(settings.supabase_url.rstrip("/")+"/rest/v1/rpa_logs",
                        params={"on_conflict": "id"}, headers=headers(settings),
                        json=[json.loads(r["payload"]) for r in rows],
                        timeout=min(settings.http_timeout, remaining), follow_redirects=False)
                    code = "OK" if response.status_code in {200, 201, 204} else f"HTTP_{response.status_code}"
                    transient = response.status_code == 429 or response.status_code >= 500
                except httpx.TransportError:
                    code, transient = "NETWORK_ERROR", True
                if code == "OK":
                    with store.db:
                        store.db.executemany("UPDATE log_outbox SET state='SYNCED',code='OK',updated=? WHERE id=?",
                                             [(utcnow(), r["id"]) for r in rows])
                    synced += len(rows)
                    continue
                with store.db:
                    for row in rows:
                        attempt = row["attempts"]+1
                        state = ("REVIEW" if attempt >= settings.log_sync_max_attempts else "PENDING") if transient else "BLOCKED"
                        delay = retry_delay(response.headers.get("Retry-After") if response is not None else None, attempt)
                        # Fechas extremas: bloquear para revisión en vez de desbordar o consultar antes.
                        if not math.isfinite(delay) or delay > 365*86400:
                            state, delay = "REVIEW", 365*86400
                        due = (datetime.now(timezone.utc)+timedelta(seconds=max(1, delay))).isoformat()
                        store.db.execute("UPDATE log_outbox SET state=?,code=?,next_attempt=?,updated=? WHERE id=?",
                                         (state, code, due, utcnow(), row["id"]))
                # Un fallo detiene esta invocación; no castigar el servicio con otros lotes.
                break
        finally:
            if own_client:
                client.close()
        state = queue_status(settings, store)
        counts = state["counts"]
        status = next((s for s in ("BLOCKED", "REVIEW", "PENDING", "IN_FLIGHT") if counts.get(s)), "SYNCED")
        return dict(state, requests=requests, synced=synced, status=status)


def fetch_cloud_logs(settings, store, execution_id=None, client=None):
    """Descarga acotada por instalación. Un error no deja un archivo parcial presentado como completo."""
    settings.validate()
    if not settings.supabase_enabled:
        raise RPAError("SUPABASE_DISABLED")
    if execution_id and not store.row("SELECT id FROM executions WHERE id=?", (execution_id,)):
        raise RPAError("EXECUTION_NOT_FOUND")
    own_client = client is None
    client = client or httpx.Client()
    records, cursor = [], None
    installation = installation_id(store)
    deadline = time.monotonic()+settings.log_sync_seconds
    try:
        # Descarga manual finita: máximo 20 páginas, sin retries internos ni loops ilimitados.
        for _ in range(20):
            remaining = deadline-time.monotonic()
            if remaining <= 0:
                raise RPAError("DOWNLOAD_BUDGET_EXHAUSTED")
            params = {"installation_id": "eq."+installation, "order": "id.asc", "limit": "500",
                      "select": ",".join(columns(settings))}
            if cursor:
                params["id"] = "gt."+cursor
            if execution_id:
                params["execution_id"] = "eq."+execution_id
            response = client.get(settings.supabase_url.rstrip("/")+"/rest/v1/rpa_logs", params=params,
                                  headers=headers(settings), timeout=min(settings.http_timeout, remaining), follow_redirects=False)
            if response.status_code != 200:
                raise RPAError(f"DOWNLOAD_HTTP_{response.status_code}")
            try:
                batch = response.json()
                if not isinstance(batch, list) or len(batch) > 500:
                    raise ValueError()
                previous = cursor
                for item in batch:
                    if (not isinstance(item, dict) or not isinstance(item.get("id"), str)
                            or item.get("installation_id") != installation
                            or not set(columns(settings)).issubset(item)
                            or (execution_id and item.get("execution_id") != execution_id)
                            or (previous is not None and item["id"] <= previous)):
                        raise ValueError()
                    previous = item["id"]
            except (ValueError, TypeError) as exc:
                raise RPAError("DOWNLOAD_SCHEMA_INVALID") from exc
            records.extend({key: item[key] for key in columns(settings)} for item in batch)
            if len(batch) < 500:
                return records
            cursor = batch[-1]["id"]
        raise RPAError("DOWNLOAD_LIMIT_EXCEEDED_FILTER_EXECUTION")
    except httpx.TransportError as exc:
        raise RPAError("DOWNLOAD_NETWORK_ERROR") from exc
    finally:
        if own_client:
            client.close()
