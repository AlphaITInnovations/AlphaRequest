"""Prozess-Anzeigereihenfolge: Speicher-Helfer + Katalog-Sortierung."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.database.settings as settings_db
import backend.api.v1.processes as papi
from backend.core.dependencies import get_current_user

ADMIN = {"id": "a", "displayName": "Admin", "permissions": ["admin"]}


# ── Speicher-Helfer (settings_get/set gemockt, kein DB-Zugriff) ───────────────

def _mock_settings(monkeypatch):
    store: dict = {}
    monkeypatch.setattr(settings_db, "settings_get",
                        lambda k, default=None: store.get(k, default))
    monkeypatch.setattr(settings_db, "settings_set",
                        lambda k, v: store.__setitem__(k, v))
    return store


def test_set_get_process_order_normalizes(monkeypatch):
    _mock_settings(monkeypatch)
    saved = settings_db.set_process_order(["b", " a ", "b", "", "c"])
    assert saved == ["b", "a", "c"]              # dedupe + trim + Leere raus
    assert settings_db.get_process_order() == ["b", "a", "c"]


def test_get_process_order_default_empty(monkeypatch):
    _mock_settings(monkeypatch)
    assert settings_db.get_process_order() == []


def test_get_process_order_ignores_non_list(monkeypatch):
    store = _mock_settings(monkeypatch)
    store["PROCESS_ORDER"] = "kaputt"
    assert settings_db.get_process_order() == []


# ── Katalog wendet die Reihenfolge an (GET /processes) ────────────────────────

class _FakeCatalog:
    def __init__(self, rows):
        self._rows = rows

    def list_published_catalog(self, include_definition=False):
        return self._rows

    def disabled_keys(self):
        return set()


def _row(key: str) -> dict:
    return {"id": 1, "key": key, "version": 1, "status": "published",
            "name": key.upper(), "definition": {"key": key, "name": key.upper()}}


def _catalog_client(monkeypatch, rows, order):
    monkeypatch.setattr(papi, "db", _FakeCatalog(rows))
    monkeypatch.setattr(papi, "get_process_order", lambda: order)
    monkeypatch.setattr(papi, "get_group_ids_for_user", lambda uid: [])
    monkeypatch.setattr(papi.perms, "may_create", lambda defn, u, gids: True)
    app = FastAPI()
    app.include_router(papi.router)
    app.dependency_overrides[get_current_user] = lambda: ADMIN
    return TestClient(app)


def _keys(resp):
    return [p["key"] for p in resp.json()["data"]]


def test_catalog_applies_order(monkeypatch):
    client = _catalog_client(monkeypatch, [_row("c"), _row("a"), _row("b")], ["b", "a", "c"])
    assert _keys(client.get("/processes")) == ["b", "a", "c"]


def test_catalog_no_order_keeps_default(monkeypatch):
    client = _catalog_client(monkeypatch, [_row("c"), _row("a"), _row("b")], [])
    assert _keys(client.get("/processes")) == ["c", "a", "b"]


def test_catalog_unlisted_go_last_stable(monkeypatch):
    # Nur "b" gelistet → b zuerst, der Rest in Eingangsreihenfolge dahinter.
    client = _catalog_client(monkeypatch, [_row("c"), _row("a"), _row("b"), _row("d")], ["b"])
    assert _keys(client.get("/processes")) == ["b", "c", "a", "d"]
