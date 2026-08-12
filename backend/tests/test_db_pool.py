"""
Verbindungs-Pool (database/connection.py) – ohne echte DB.

Hintergrund: Ein Pool mit pre_ping=True, aber OHNE Dialekt, funktioniert beim
ersten Checkout und wirft erst beim WIEDERVERWENDEN einer Verbindung
"NotImplementedError: The ping feature requires that a dialect is passed to the
connection pool." Das ließ die App im Container beim Start scheitern (der zweite
ensure_table()-Aufruf in der Lifespan), war lokal aber unsichtbar, weil ohne DB
gar nicht verbunden wird.

Diese Tests prüfen den Pool daher mit einer Attrappe statt einer echten DB.
Sie sind deshalb von der Fail-Fast-Sperre in conftest ausgenommen (Marke
`echter_pool`) – sie WOLLEN echte Pool-Mechanik, nur ohne Server.
"""
import pytest

import backend.database.connection as conn_mod

pytestmark = pytest.mark.echter_pool


class FakeCursor:
    def __init__(self, conn):
        self._conn = conn
        self.rowcount = 1
        self.lastrowid = 42

    def execute(self, sql, params=()):
        self._conn.executed.append(sql)

    def fetchall(self):
        return []

    def fetchone(self):
        return None

    def close(self):
        pass


class FakeConnection:
    """Verhält sich wie eine pymysql-Verbindung (das erwartet der Pool)."""

    def __init__(self, registry):
        self.executed = []
        self.pings = 0
        self.commits = 0
        self.rollbacks = 0
        registry.append(self)

    def cursor(self):
        return FakeCursor(self)

    def begin(self):
        self.executed.append("BEGIN")

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def ping(self, reconnect=False):
        self.pings += 1
        return True

    def close(self):
        pass


def _use_fake_pool(monkeypatch):
    """Pool mit Attrappen-Verbindungen; gibt die Liste der erzeugten zurück."""
    created = []
    monkeypatch.setattr(conn_mod, "_connect_raw", lambda dsn: FakeConnection(created))
    monkeypatch.setattr(conn_mod, "_pool", None, raising=False)
    monkeypatch.setattr(conn_mod, "_pool_dsn", None, raising=False)
    monkeypatch.setenv("MARIADB_DSN", "mysql+pymysql://u:p@localhost/db")
    return created


def test_wiederholtes_ausleihen_funktioniert(monkeypatch):
    """Regression: der ZWEITE Checkout ist der, der ohne Dialekt geknallt hat."""
    _use_fake_pool(monkeypatch)
    for _ in range(5):
        conn = conn_mod.get_connection()
        conn_mod._exec(conn, "SELECT 1")
        conn.commit()
        conn.close()      # gibt an den Pool zurück (kein echtes Schließen)


def test_verbindung_wird_wiederverwendet(monkeypatch):
    """Der Pool soll nicht pro Aufruf neu verbinden – sonst wäre er sinnlos."""
    created = _use_fake_pool(monkeypatch)
    for _ in range(5):
        conn = conn_mod.get_connection()
        conn.close()
    assert len(created) == 1, f"erwartet 1 echte Verbindung, erzeugt: {len(created)}"


def test_pre_ping_wird_ausgefuehrt(monkeypatch):
    """Beim Wiederverwenden muss der Ping laufen (tote Verbindungen ersetzen)."""
    created = _use_fake_pool(monkeypatch)
    conn_mod.get_connection().close()          # erstmalig verbinden
    conn_mod.get_connection().close()          # wiederverwenden → Ping
    assert created[0].pings >= 1


def test_helfer_und_transaktionen_am_pool(monkeypatch):
    """_exec/_fetchall/_fetchone und begin/commit/rollback müssen am
    Pool-Proxy genauso funktionieren wie an einer rohen Verbindung."""
    created = _use_fake_pool(monkeypatch)
    conn = conn_mod.get_connection()
    conn.begin()
    cur = conn_mod._exec(conn, "INSERT INTO t VALUES (1)")
    assert cur.lastrowid == 42 and cur.rowcount == 1
    assert conn_mod._fetchall(conn, "SELECT 1") == []
    assert conn_mod._fetchone(conn, "SELECT 1") is None
    conn.rollback()
    conn.close()
    assert "BEGIN" in created[0].executed
    assert created[0].rollbacks >= 1
