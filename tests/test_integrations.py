from dataclasses import replace
import json
import httpx
import pytest

from rpa.http import ReaderHTTP, retry_delay
from rpa.mail_read import GraphReader
from rpa.mail_send import send_report
from rpa.orchestrator import run
from rpa.runtime import Audit, Budget, RPAError
from rpa.store import Store


def make_http(settings, store, handler, seconds=60):
    audit = Audit(store, "test", settings.runtime / "logs")
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return ReaderHTTP(client, settings, store, "test", audit, Budget(seconds)), audit, client


def test_429_then_success(settings, store):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": "0"}) if len(calls) == 1 else httpx.Response(200, json={})
    http, audit, client = make_http(settings, store, handler)
    try:
        assert http.get("https://example.test").status_code == 200
        assert http.queries == 2 and http.retries == 1
        assert [r[0] for r in store.rows("SELECT result FROM events WHERE step_id='http_get' ORDER BY id")] == ["FAILED", "OK"]
        assert store.row("SELECT COUNT(*) FROM events WHERE step_id='retry_wait'")[0] == 1
    finally:
        audit.close()
        client.close()


def test_retry_budget_and_persisted_exhaustion(settings, store):
    calls = []
    def handler(request):
        calls.append(1)
        return httpx.Response(429, headers={"Retry-After": "0"})
    http, audit, client = make_http(settings, store, handler)
    try:
        with pytest.raises(RPAError, match="RETRIES_EXHAUSTED"):
            http.get("https://example.test")
        with pytest.raises(RPAError, match="RETRIES_EXHAUSTED"):
            http.get("https://example.test")
        assert len(calls) == 3
    finally:
        audit.close()
        client.close()


def test_retry_after_exceeds_budget(settings, store):
    http, audit, client = make_http(settings, store, lambda _: httpx.Response(429, headers={"Retry-After": "90"}), 1)
    try:
        with pytest.raises(RPAError, match="RETRY_EXCEEDS_BUDGET"):
            http.get("https://example.test")
        assert http.queries == 1
    finally:
        audit.close()
        client.close()


def test_permission_not_retried(settings, store):
    http, audit, client = make_http(settings, store, lambda _: httpx.Response(403))
    try:
        with pytest.raises(RPAError, match="HTTP_403"):
            http.get("https://example.test")
        assert http.queries == 1
    finally:
        audit.close()
        client.close()


def test_graph_opaque_links_immutable_and_local_filter(settings, store):
    requests = []
    link = "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages/delta?$skiptoken=opaque%2B123"
    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(200, json={"value": [
                {"id": "a", "subject": "Consulta", "receivedDateTime": "2026-05-01T12:00:00Z"},
                {"id": "b", "subject": "[RPA-EP3] Reporte", "receivedDateTime": "2026-05-01T12:00:00Z"},
                {"id": "c", "subject": "Fuera", "receivedDateTime": "2027-01-01T12:00:00Z"}], "@odata.nextLink": link})
        return httpx.Response(200, json={"value": [], "@odata.deltaLink": link.replace("skiptoken", "deltatoken")})
    http, audit, client = make_http(settings, store, handler)
    try:
        reader = GraphReader(settings, http, "dummy-token")
        first = reader.page()
        assert len(first.messages) == 1 and first.phase == "NEXT"
        assert reader.page(first.cursor).phase == "DELTA"
        assert str(requests[1].url) == link
        assert all(r.headers["Prefer"] == 'IdType="ImmutableId"' for r in requests)
        assert "body" not in requests[0].url.params["$select"]
    finally:
        audit.close()
        client.close()


def test_cursor_expiration_resync_deduplicates(settings):
    from rpa.mail_read import FixtureReader
    class Expired(FixtureReader):
        expired = False
        def page(self, cursor=None):
            if cursor and not self.expired:
                self.expired = True
                raise RPAError("CURSOR_EXPIRED")
            return super().page(cursor)
    result = run(replace(settings, fixture_count=300), reader_factory=Expired)
    assert result["status"] == "COMPLETED"
    assert result["metrics"]["duplicates"] == 100
    assert result["metrics"]["processed"] == 300


@pytest.mark.parametrize("recipient", ["evil@example.com", "a@example.com;b@example.com", "bad"])
def test_recipient_blocked(settings, recipient):
    with pytest.raises(ValueError, match="ENVIO_NO_AUTORIZADO"):
        replace(settings, source="GRAPH", client_id="id", tenant_id="id", mailbox="bot@example.com",
            holiday_mode="LIVE", require_excel=True, mail_mode="SEND", send_authorized=True,
            recipient=recipient, allowed_recipients="test@example.com").validate()


def test_uncertain_send_never_repeated(settings):
    first = run(settings)
    eid = first["execution_id"]
    settings_send = replace(settings, source="GRAPH", client_id="id", tenant_id="id", mailbox="bot@example.com",
        holiday_mode="LIVE", require_excel=True, mail_mode="SEND", send_authorized=True,
        recipient="test@example.com", allowed_recipients="test@example.com")
    calls = []
    def ambiguous():
        calls.append(1)
        raise TimeoutError()
    with Store(settings.runtime / "state.sqlite3", settings.root) as store:
        store.execute("DELETE FROM sends WHERE execution_id=?", (eid,))
        args = (settings_send, store, eid, settings.output / eid / "reporte.xlsx", "body", None, "token", Budget(30))
        assert send_report(*args, adapter=ambiguous) == "ENVIO_INCIERTO"
        assert send_report(*args, adapter=ambiguous) == "ENVIO_INCIERTO"
        assert calls == [1]
        store.execute("UPDATE sends SET state='PREPARADO' WHERE execution_id=?", (eid,))
        assert send_report(*args, adapter=ambiguous) == "ENVIO_INCIERTO"
        assert calls == [1]


def test_live_missing_year_blocks_report_send(settings, monkeypatch):
    def failed_get(self, *args, **kwargs):
        raise RPAError("HTTP_404")
    monkeypatch.setattr(ReaderHTTP, "get", failed_get)
    result = run(replace(settings, holiday_mode="LIVE"))
    assert result["status"] == "PARTIAL"
    assert result["error"] == "REPORT_PARTIAL_SEND_BLOCKED"
    assert (settings.output / result["execution_id"] / "reporte.xlsx").exists()
    with Store(settings.runtime / "state.sqlite3", settings.root) as store:
        assert store.row("SELECT COUNT(*) FROM sends")[0] == 0


def test_cache_expiry_and_schema(settings, store):
    from rpa.holidays import Holidays
    from rpa.store import utcnow
    live = replace(settings, holiday_mode="LIVE")
    valid = [{"date": "2026-01-01", "countryCode": "CL", "localName": "Año Nuevo", "global": True, "types": ["Public"]}]
    http, audit, client = make_http(settings, store, lambda _: httpx.Response(200, json=valid))
    try:
        assert Holidays(live, http).year(2026)["origin"] == "real"
        assert Holidays(live, http).year(2026)["origin"] == "cache"
        path = live.runtime / "cache/CL-2026.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["queried"] = "2020-01-01T00:00:00+00:00"
        path.write_text(json.dumps(data), encoding="utf-8")
        assert Holidays(live, http).year(2026)["origin"] == "real"
        assert http.queries == 2
    finally:
        audit.close()
        client.close()
