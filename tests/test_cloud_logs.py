from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import re
import httpx
import pytest
from fastapi.testclient import TestClient

from rpa.cloud_logs import enqueue, fetch_cloud_logs, log_records, queue_status, sync_logs
from rpa.log_files import auto_cleanup, managed_download, save_execution_log, save_log
from rpa.panel import create_app
from rpa.runtime import Audit, RPAError
from rpa.store import Store, utcnow


@pytest.fixture
def cloud(settings, store):
    store.execute("UPDATE executions SET status='COMPLETED',finished=?,metrics=? WHERE id='test'",
                  (utcnow(), json.dumps({"duration_seconds": 1.25, "retries": 1, "processed": 100, "classified": 100})))
    audit = Audit(store, "test", settings.runtime / "logs")
    audit.event("http_get", utcnow(), 20, attempt=1, result="FAILED", code="HTTP_429")
    audit.event("http_get", utcnow(), 30, attempt=2)
    audit.close()
    return replace(settings, supabase_enabled=True, supabase_url="https://rpa-test.supabase.co",
                   supabase_secret_key="sb_secret_TEST_ONLY_NOT_REAL")


def test_supabase_upsert_idempotent_and_private_fields_excluded(cloud, store):
    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(201)
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        first = sync_logs(cloud, store, client=client)
        second = sync_logs(cloud, store, client=client)
    assert first["synced"] == 3 and second["requests"] == 0
    assert len(requests) == 1
    req = requests[0]
    assert req.headers["apikey"] == cloud.supabase_secret_key
    assert "authorization" not in req.headers
    assert req.url.params["on_conflict"] == "id"
    records = json.loads(req.content)
    assert {r["status"] for r in records} == {"FALLIDO", "COMPLETADO"}
    assert all(not {"host", "subject", "body", "sender", "cursor", "mailbox"} & set(r) for r in records)
    assert cloud.supabase_secret_key not in repr(cloud)
    summary = next(r for r in records if r["kind"] == "execution")
    assert summary["duration_ms"] == 1250 and summary["retries"] == 1
    assert summary["status"] == "COMPLETADO"  # 429 recuperado no convierte la ejecución en fallida.


def test_extended_context_is_opt_in_and_survives_download(cloud, store):
    import uuid
    cid=str(uuid.uuid4())
    audit=Audit(store,'test',cloud.runtime/'logs')
    audit.event('report_delivery',utcnow(),10,result='FAILED',code='REPORT_ENVIO_INCIERTO',
                context={'dataset':cid,'job_id':cid+':1','role':'remitente','http_status':503,'recovery':'REVIEW_NO_RESEND'})
    audit.close()
    legacy=log_records(store)
    assert all('campaign_id' not in row for row in legacy)
    s=replace(cloud,supabase_context_enabled=True);sent=[]
    def handler(request):
        if request.method=='POST':sent.extend(json.loads(request.content));return httpx.Response(201)
        assert 'campaign_id' in request.url.params['select']
        return httpx.Response(200,json=sorted(sent,key=lambda r:r['id']))
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert sync_logs(s,store,client=client)['status']=='SYNCED'
        records=fetch_cloud_logs(s,store,client=client)
    row=next(r for r in records if r['step_id']=='report_delivery')
    assert row['campaign_id']==cid and row['http_status']==503 and row['recovery']=='REVIEW_NO_RESEND'
    assert row['role']=='remitente' and row['job_id']==cid+':1'
    assert all(not {'body','subject','sender','token','host'} & set(r) for r in records)


def test_three_persistent_attempts_no_loop_or_restart_reset(cloud, store):
    calls = []
    def fail(request):
        calls.append(1)
        return httpx.Response(503, headers={"Retry-After": "0"})
    with httpx.Client(transport=httpx.MockTransport(fail)) as client:
        for _ in range(3):
            store.execute("UPDATE log_outbox SET next_attempt='2020-01-01T00:00:00+00:00'")
            assert sync_logs(cloud, store, client=client)["requests"] == 1
        assert sync_logs(cloud, store, client=client)["requests"] == 0
    with Store(cloud.runtime / "state.sqlite3", cloud.root) as reopened:
        with httpx.Client(transport=httpx.MockTransport(fail)) as client:
            assert sync_logs(cloud, reopened, client=client)["requests"] == 0
        assert reopened.row("SELECT min(attempts),max(attempts) FROM log_outbox")[:] == (3, 3)
        assert reopened.row("SELECT count(*) FROM log_outbox WHERE state='REVIEW'")[0] == 3
    assert len(calls) == 3


def test_429_schedules_retry_without_sleeping_or_busy_poll(cloud, store):
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(429, headers={"Retry-After": "3600"}))) as client:
        assert sync_logs(cloud, store, client=client)["requests"] == 1
        assert sync_logs(cloud, store, client=client)["requests"] == 0
    due = datetime.fromisoformat(store.row("SELECT next_attempt FROM log_outbox")[0])
    assert due > datetime.now(timezone.utc)+timedelta(minutes=59)
    assert store.row("SELECT state FROM log_outbox")[0] == "PENDING"


def test_permission_failure_is_blocked_and_not_retried(cloud, store):
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(403))) as client:
        assert sync_logs(cloud, store, client=client)["requests"] == 1
        assert sync_logs(cloud, store, client=client)["requests"] == 0
    assert store.row("SELECT count(*) FROM log_outbox WHERE state='BLOCKED'")[0] == 3


def test_uncertain_post_upserts_same_ids_after_restart(cloud, store):
    remote, calls = {}, []
    def transport(request):
        rows = json.loads(request.content)
        remote.update({row["id"]: row for row in rows})
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ReadTimeout("ambiguous")
        return httpx.Response(204)
    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        sync_logs(cloud, store, client=client)
        store.execute("UPDATE log_outbox SET next_attempt='2020-01-01T00:00:00+00:00'")
        assert sync_logs(cloud, store, client=client)["synced"] == 3
    assert len(remote) == 3 and len(calls) == 2


def test_inflight_recovery_preserves_attempts(cloud, store):
    enqueue(store, log_records(store))
    store.execute("UPDATE log_outbox SET state='IN_FLIGHT',attempts=3")
    with httpx.Client(transport=httpx.MockTransport(lambda _: pytest.fail("No debe consultar"))) as client:
        assert sync_logs(cloud, store, client=client)["requests"] == 0
    assert store.row("SELECT state FROM log_outbox")[0] == "REVIEW"


def test_download_remote_logs_saved_with_expiry(cloud, store):
    records = sorted(log_records(store), key=lambda r: r["id"])
    def transport(request):
        assert request.url.params["installation_id"].startswith("eq.")
        assert "subject" not in request.url.params["select"]
        return httpx.Response(200, json=[dict(r, unexpected="omit") for r in records])
    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        rows = fetch_cloud_logs(cloud, store, "test", client)
    assert all("unexpected" not in r for r in rows)
    saved = save_log(cloud, store, rows, "SUPABASE", "test")
    path = managed_download(cloud, store, saved["name"])
    assert path.parent == cloud.runtime / "logs/descargas"
    assert len(path.read_text(encoding="utf-8").splitlines()) == 3
    expiry = datetime.fromisoformat(saved["expires"])-datetime.fromisoformat(saved["created"])
    assert 14.99 <= expiry.total_seconds()/86400 <= 15.01


def test_remote_download_no_pagination_loop(cloud, store):
    record = log_records(store)[0]
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=[record]*500))) as client:
        with pytest.raises(RPAError, match="DOWNLOAD_SCHEMA_INVALID"):
            fetch_cloud_logs(cloud, store, client=client)


def test_retention_deletes_only_expired_managed_files(cloud, store):
    saved = save_execution_log(cloud, store, "test")
    current = save_execution_log(cloud, store, "test")
    alien = cloud.runtime / "logs/descargas/archivo-personal.log"
    alien.write_text("preservar", encoding="utf-8")
    store.execute("UPDATE log_files SET expires='2020-01-01T00:00:00+00:00' WHERE name=?", (saved["name"],))
    store.execute("INSERT INTO checkpoints VALUES('critical','opaque','NEXT')")
    result = auto_cleanup(replace(cloud, auto_clean_logs=True), store)
    assert result["deleted"] == ["descargas/"+saved["name"]]
    assert not (alien.parent / saved["name"]).exists()
    assert alien.exists() and (alien.parent / current["name"]).exists()
    assert store.row("SELECT cursor FROM checkpoints")[0] == "opaque"
    assert store.row("SELECT count(*) FROM events")[0] == 2
    assert store.row("SELECT state FROM cleanups")[0] == "AUTO_RETENTION"


def test_modified_log_and_unsafe_path_are_preserved(cloud, store):
    saved = save_execution_log(cloud, store, "test")
    path = cloud.runtime / "logs/descargas" / saved["name"]
    path.write_text("modificado", encoding="utf-8")
    store.execute("UPDATE log_files SET expires='2020-01-01T00:00:00+00:00'")
    assert not auto_cleanup(replace(cloud, auto_clean_logs=True), store)["deleted"]
    assert path.exists()
    with pytest.raises(RPAError):
        managed_download(cloud, store, "../state.sqlite3")


def test_log_panel_and_disabled_configuration(settings, store, cloud):
    with TestClient(create_app(settings)) as client:
        token = re.search("const token='([^']+)'", client.get("/").text)[1]
        auth = {"x-csrf-token": token}
        assert client.post("/api/logs/sync", json={}).status_code == 403
        response = client.post("/api/logs/sync", json={}, headers=auth)
        assert response.json()["status"] == "DISABLED"
        saved = client.post("/api/logs/save", json={"source": "LOCAL", "execution_id": "test"}, headers=auth)
        assert saved.status_code == 200
        assert client.get(saved.json()["download"]).status_code == 200
        assert "supabase_secret_key" not in client.get("/api/logs/status").text


def test_incomplete_config_and_secret_repr(settings):
    with pytest.raises(ValueError, match="SUPABASE_CONFIG_REQUIRED"):
        replace(settings, supabase_enabled=True).validate()
    with pytest.raises(ValueError, match="LOG_CONFIG_INVALID"):
        replace(settings, log_sync_max_attempts=4).validate()


def test_cloud_failure_does_not_fail_robot_or_repeat_report(settings, monkeypatch):
    from rpa.orchestrator import run
    live = replace(settings, supabase_enabled=True, supabase_url="https://rpa-test.supabase.co",
                   supabase_secret_key="sb_secret_TEST_ONLY_NOT_REAL")
    monkeypatch.setattr(httpx.Client, "post", lambda *args, **kwargs: httpx.Response(503))
    result = run(live)
    assert result["status"] == "COMPLETED" and result["send_state"] == "DRY_RUN"
    assert result["logs"]["file"]["records"] > 0
    assert result["logs"]["supabase"]["status"] == "PENDING"
    assert run(live, result["execution_id"])["resumed_without_send"]
    with Store(settings.runtime / "state.sqlite3", settings.root) as store:
        assert store.row("SELECT count(*) FROM sends")[0] == 1


def test_auto_cleanup_rotated_logs_preserves_active_runs(settings, store):
    import os
    import time
    import uuid
    paths = {}
    for status in ("COMPLETED", "RUNNING", "PARTIAL", "REVIEW"):
        eid = str(uuid.uuid4())
        store.execute("INSERT INTO executions(id,profile,signature,started,status,source) VALUES(?,?,?,?,?,?)",
                      (eid, "test", "sig", utcnow(), status, "FIXTURE"))
        path = settings.runtime / "logs" / f"{eid}.ERROR.log.1"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("audit", encoding="utf-8")
        os.utime(path, (time.time()-40*86400, time.time()-40*86400))
        paths[status] = path
    result = auto_cleanup(replace(settings, auto_clean_logs=True), store)
    assert result["deleted"] == [paths["COMPLETED"].name]
    assert all(paths[status].exists() for status in ("RUNNING", "PARTIAL", "REVIEW"))
