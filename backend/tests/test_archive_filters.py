"""Archiv-Filter (Ersteller, Zeitraum, Sortierung, erweiterte Suche).

Zwei Pfade: das persönliche Archiv filtert/sortiert in Python über den Scan
(hier direkt getestet), das globale Archiv delegiert an die SQL-Abfrage
`store.list_global_archive` (hier wird die Delegation + der Aufsichts-Gate
geprüft; die SQL-Semantik spiegelt die hier getestete Python-Logik)."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core.dependencies import get_current_user
from backend.main import _install_error_handlers
from backend.api.v1 import process_tickets as pt
from backend.services import process_access as acc
from backend.services import process_visibility as vis

ADMIN = {"id": "u_admin", "displayName": "Admin", "permissions": ["admin"]}


def _row(tid, title, owner, created, updated, status="in_progress"):
    return {"id": tid, "process_key": "demo", "process_version": 1, "title": title,
            "status": status, "priority": "normal", "owner_id": f"u{tid}",
            "owner_name": owner, "runtime": {}, "created_at": created, "updated_at": updated}


ROWS = [
    _row(1, "Alpha", "Anna Admin", "2026-01-10T09:00:00", "2026-03-01T09:00:00"),
    _row(2, "Beta", "Bob Bauer", "2026-02-15T09:00:00", "2026-02-20T09:00:00"),
    _row(3, "Gamma", "Anna Admin", "2026-03-20T09:00:00", "2026-03-25T09:00:00"),
]


class _Store:
    def __init__(self):
        self.global_calls: list = []

    def list_all_lightweight(self, limit=2000):
        # Wie der echte Store: neueste zuerst (updated_at DESC, id DESC).
        rows = sorted(ROWS, key=lambda r: (r["updated_at"], r["id"]), reverse=True)
        return [dict(r) for r in rows]

    def list_global_archive(self, **kw):
        # Attrappe: Aufruf-Parameter mitschreiben, Zeilen unverändert zurückgeben
        # (die echte SQL-Filterung braucht eine DB; die Logik spiegelt der mine-Pfad).
        self.global_calls.append(kw)
        return [dict(r) for r in ROWS], len(ROWS)


def _client(monkeypatch):
    store = _Store()
    monkeypatch.setattr(pt, "store", store)
    monkeypatch.setattr(acc, "has_oversight", lambda u: True)
    monkeypatch.setattr(acc, "archive_involved",
                        lambda defn, r, u, gids, is_watcher=False: True)
    monkeypatch.setattr(vis, "user_group_ids", lambda u: set())
    monkeypatch.setattr(pt.watchers, "ticket_ids_for_watcher", lambda uid: set())
    monkeypatch.setattr(pt, "_load_pinned_defn", lambda r, cache=None: None)
    app = FastAPI()
    _install_error_handlers(app)
    app.include_router(pt.router)
    app.dependency_overrides[get_current_user] = lambda: ADMIN
    return TestClient(app), store


def _ids(resp):
    return [r["id"] for r in resp.json()["data"]["items"]]


# ── Persönlicher Scan: Python-Filter/Sortierung (scope=mine) ──────────────────

def test_mine_default_sort_updated_desc(monkeypatch):
    c, _ = _client(monkeypatch)
    assert _ids(c.get("/process-tickets/archive")) == [3, 1, 2]


def test_mine_filter_created_by(monkeypatch):
    c, _ = _client(monkeypatch)
    assert _ids(c.get("/process-tickets/archive?created_by=anna")) == [3, 1]


def test_mine_q_matches_owner_and_id(monkeypatch):
    c, _ = _client(monkeypatch)
    assert _ids(c.get("/process-tickets/archive?q=bauer")) == [2]
    assert _ids(c.get("/process-tickets/archive?q=3")) == [3]


def test_mine_date_range_created(monkeypatch):
    c, _ = _client(monkeypatch)
    r = c.get("/process-tickets/archive?date_field=created&date_from=2026-02-01&date_to=2026-02-28")
    assert _ids(r) == [2]


def test_mine_date_range_updated(monkeypatch):
    c, _ = _client(monkeypatch)
    assert _ids(c.get("/process-tickets/archive?date_from=2026-03-10")) == [3]


def test_mine_sort_created_asc(monkeypatch):
    c, _ = _client(monkeypatch)
    assert _ids(c.get("/process-tickets/archive?sort=created_asc")) == [1, 2, 3]


def test_mine_owner_name_in_row(monkeypatch):
    c, _ = _client(monkeypatch)
    top = c.get("/process-tickets/archive").json()["data"]["items"][0]
    assert top["owner_name"] == "Anna Admin"


# ── Globales Archiv: Delegation an die SQL-Abfrage (scope=all) ────────────────

def test_global_delegates_to_sql_with_filters(monkeypatch):
    c, store = _client(monkeypatch)
    r = c.get("/process-tickets/archive?scope=all&created_by=anna&date_field=created"
              "&date_from=2026-02-01&date_to=2026-02-28&sort=created_asc&status=archived,rejected&q=x")
    assert r.status_code == 200
    kw = store.global_calls[-1]
    assert kw["created_by"] == "anna" and kw["q"] == "x"
    assert kw["date_field"] == "created"
    assert kw["date_from"] == "2026-02-01" and kw["date_to"] == "2026-02-28"
    assert kw["sort"] == "created_asc" and kw["status"] == ["archived", "rejected"]
    # SQL-gepagt → immer vollständig (nie truncated); owner_name wird durchgereicht.
    assert r.json()["data"]["truncated"] is False
    assert r.json()["data"]["items"][0]["owner_name"] in ("Anna Admin", "Bob Bauer")


def test_global_requires_oversight(monkeypatch):
    c, _ = _client(monkeypatch)
    monkeypatch.setattr(acc, "has_oversight", lambda u: False)
    assert c.get("/process-tickets/archive?scope=all").status_code == 403
