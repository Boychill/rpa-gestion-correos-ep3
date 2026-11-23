from pathlib import Path
import pytest
import socket
from rpa.config import Settings
from rpa.excel import create_template
from rpa.store import Store, utcnow


@pytest.fixture(autouse=True)
def no_external_network(monkeypatch):
    """La suite puede probar localhost, pero nunca Gmail/Supabase reales."""
    original = socket.socket.connect
    def guarded(sock, address):
        if isinstance(address, tuple) and address[0] not in ('127.0.0.1', '::1', 'localhost'):
            raise AssertionError('EXTERNAL_NETWORK_FORBIDDEN_IN_TESTS')
        return original(sock, address)
    monkeypatch.setattr(socket.socket, 'connect', guarded)


@pytest.fixture
def settings(tmp_path):
    root = Path(__file__).resolve().parents[1]
    create_template(root / "templates/reporte_base.xlsx")
    return Settings(root=root, runtime=tmp_path / "runtime con espacios", output=tmp_path / "output con espacios",
                    fixture_count=100, auto_clean_logs=False)


@pytest.fixture
def store(settings):
    with Store(settings.runtime / "state.sqlite3", settings.root) as db:
        db.execute("INSERT INTO executions(id,profile,signature,started,status,source) VALUES(?,?,?,?,?,?)",
                   ("test", "test", "signature", utcnow(), "RUNNING", "FIXTURE"))
        yield db
