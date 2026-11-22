import sqlite3
import pytest
from rpa.maintenance import backup, preview, purge_events
from rpa.runtime import RPAError


def test_verified_backup_and_separate_purge(settings, store):
    store.execute("UPDATE executions SET status='COMPLETED' WHERE id='test'")
    for step, level in [("read_page", "INFO"), ("read_page", "ERROR"), ("prepare_send", "INFO")]:
        store.execute("INSERT INTO events VALUES(NULL,?,?,?,?,?,?,?,?,?,?,?)",
            ("test", step, "redacted", "2020-01-01T00:00:00+00:00", "2020-01-01T00:00:01+00:00", 1, 1, level, "OK", "OK", "OK"))
    store.execute("INSERT INTO checkpoints VALUES('protected','opaque','NEXT')")
    assert len(preview(settings, store)["event_ids"]) == 1
    with pytest.raises(RPAError):
        purge_events(settings, store, "yes")
    result = purge_events(settings, store, "PURGAR_EVENTOS_NO_PROTEGIDOS")
    assert result["deleted_events"] == 1
    with sqlite3.connect(result["backup"]) as restored:
        assert restored.execute("SELECT count(*) FROM events").fetchone()[0] == 3
        assert restored.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert store.row("SELECT count(*) FROM events")[0] == 2
    assert store.row("SELECT cursor FROM checkpoints")[0] == "opaque"
