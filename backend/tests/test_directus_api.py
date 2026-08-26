"""Ebene-1: Directus-API (api/v1/directus) – Router-App, Client/Store gemockt."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.v1 import directus as dapi
from backend.core.dependencies import get_current_user
from backend.main import _install_error_handlers

ADMIN = {"id": "a", "displayName": "Admin", "permissions": ["admin"]}
USER = {"id": "u", "displayName": "User", "permissions": []}

SRC = {"key": "kostenstelle", "label": "Kostenstelle", "collection": "kst",
       "valueField": "nummer", "labelTemplate": "{{nummer}} – {{firma.name}}",
       "fields": ["firma.name"], "filter": None, "sort": [], "limit": 200}


def _app(user, monkeypatch):
    monkeypatch.setattr(dapi, "record_audit", lambda **kw: None)
    app = FastAPI()
    _install_error_handlers(app)
    app.include_router(dapi.router)
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app, raise_server_exceptions=True)


# ── Auth ──────────────────────────────────────────────────────────────────────

def test_admin_endpoints_require_admin(monkeypatch):
    c = _app(USER, monkeypatch)
    assert c.get("/directus/status").status_code == 403
    assert c.get("/directus/collections").status_code == 403
    assert c.get("/directus/sources").status_code == 403
    assert c.put("/directus/sources", json={"sources": []}).status_code == 403


# ── Introspektion ───────────────────────────────────────────────────────────

def test_collections_ok_and_directus_error(monkeypatch):
    c = _app(ADMIN, monkeypatch)
    monkeypatch.setattr(dapi.dc, "list_collections", lambda: [{"collection": "kst"}])
    r = c.get("/directus/collections")
    assert r.status_code == 200 and r.json()["data"][0]["collection"] == "kst"

    def boom():
        raise dapi.dc.DirectusError("down", status=502)
    monkeypatch.setattr(dapi.dc, "list_collections", boom)
    r = c.get("/directus/collections")
    assert r.status_code == 502 and r.json()["error"]["code"] == "DIRECTUS_ERROR"


def test_fields_ok(monkeypatch):
    c = _app(ADMIN, monkeypatch)
    monkeypatch.setattr(dapi.dc, "list_fields", lambda col: [{"field": "nummer"}])
    r = c.get("/directus/collections/kst/fields")
    assert r.status_code == 200 and r.json()["data"][0]["field"] == "nummer"


def test_fields_falls_back_to_sample_on_schema_error(monkeypatch):
    c = _app(ADMIN, monkeypatch)

    def boom(col):
        raise dapi.dc.DirectusError("403 forbidden", status=403)
    monkeypatch.setattr(dapi.dc, "list_fields", boom)
    monkeypatch.setattr(dapi.dc, "sample_fields", lambda col: [{"field": "nummer"}])
    r = c.get("/directus/collections/kst/fields")
    assert r.status_code == 200 and r.json()["data"][0]["field"] == "nummer"


def test_fields_falls_back_to_sample_when_empty(monkeypatch):
    c = _app(ADMIN, monkeypatch)
    monkeypatch.setattr(dapi.dc, "list_fields", lambda col: [])
    monkeypatch.setattr(dapi.dc, "sample_fields", lambda col: [{"field": "x"}])
    r = c.get("/directus/collections/kst/fields")
    assert r.status_code == 200 and r.json()["data"][0]["field"] == "x"


# ── Quellen verwalten ─────────────────────────────────────────────────────────

def test_put_sources_saves_and_audits(monkeypatch):
    c = _app(ADMIN, monkeypatch)
    captured = {}
    monkeypatch.setattr(dapi.store, "set_all", lambda lst: captured.setdefault("in", lst) or lst)
    r = c.put("/directus/sources", json={"sources": [SRC]})
    assert r.status_code == 200
    assert r.json()["data"][0]["key"] == "kostenstelle"
    assert captured["in"][0]["collection"] == "kst"


def test_put_sources_invalid_is_422(monkeypatch):
    c = _app(ADMIN, monkeypatch)

    def boom(lst):
        raise dapi.store.SourceError("Doppelter Schlüssel „a“")
    monkeypatch.setattr(dapi.store, "set_all", boom)
    r = c.put("/directus/sources", json={"sources": [SRC]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_FAILED"


def test_preview_ok(monkeypatch):
    c = _app(ADMIN, monkeypatch)
    monkeypatch.setattr(dapi.dc, "query_items",
                        lambda col, **kw: [{"nummer": "10", "firma": {"name": "Alpha"}}])
    r = c.post("/directus/sources:preview", json=SRC)
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["options"][0]["label"] == "10 – Alpha"
    assert "firma.name" in data["fields"]


# ── Optionen (Formular, auch Nicht-Admin) ─────────────────────────────────────

def test_options_ok_for_normal_user(monkeypatch):
    c = _app(USER, monkeypatch)
    monkeypatch.setattr(dapi.store, "get", lambda k: dict(SRC))
    monkeypatch.setattr(dapi.dc, "is_configured", lambda: True)
    monkeypatch.setattr(dapi.dc, "query_items",
                        lambda col, **kw: [{"nummer": "10", "firma": {"name": "Alpha"}}])
    r = c.get("/directus/sources/kostenstelle/options?search=10")
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["error"] is None and d["options"][0]["value"] == "10"


def test_options_unknown_source_404(monkeypatch):
    c = _app(USER, monkeypatch)
    monkeypatch.setattr(dapi.store, "get", lambda k: None)
    assert c.get("/directus/sources/ghost/options").status_code == 404


def test_options_failsoft_when_unconfigured(monkeypatch):
    c = _app(USER, monkeypatch)
    monkeypatch.setattr(dapi.store, "get", lambda k: dict(SRC))
    monkeypatch.setattr(dapi.dc, "is_configured", lambda: False)
    r = c.get("/directus/sources/kostenstelle/options")
    assert r.status_code == 200 and r.json()["data"]["options"] == []
    assert "nicht konfiguriert" in r.json()["data"]["error"]


def test_options_failsoft_on_directus_error(monkeypatch):
    c = _app(USER, monkeypatch)
    monkeypatch.setattr(dapi.store, "get", lambda k: dict(SRC))
    monkeypatch.setattr(dapi.dc, "is_configured", lambda: True)

    def boom(col, **kw):
        raise dapi.dc.DirectusError("timeout")
    monkeypatch.setattr(dapi.dc, "query_items", boom)
    r = c.get("/directus/sources/kostenstelle/options")
    assert r.status_code == 200 and r.json()["data"]["options"] == []
    # Nach außen eine neutrale Meldung – die rohe Directus-Fehlermeldung leakt nicht.
    assert "nicht erreichbar" in r.json()["data"]["error"]
    assert "timeout" not in r.json()["data"]["error"]
