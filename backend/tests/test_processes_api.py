"""Ebene-1: Fehler-Envelope-Normalisierung + Routen-Registrierung (kein DB-Zugriff).

Der Envelope-Handler wird an einer Mini-App getestet (env-unabhängig); die
Prozess-Routen werden direkt am Router geprüft.
"""

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel

from backend.api.v1 import processes as papi
from backend.core.dependencies import get_current_user
from backend.main import _install_error_handlers
from backend.schemas.responses import api_error, ErrorCode
from backend.api.v1.processes import router as processes_router


def _client() -> TestClient:
    app = FastAPI()
    _install_error_handlers(app)

    class Body(BaseModel):
        n: int

    @app.get("/plain401")
    def _plain():
        raise HTTPException(status_code=401)

    @app.get("/coded")
    def _coded():
        raise api_error(409, ErrorCode.PROCESS_KEY_EXISTS, "existiert")

    @app.get("/withfields")
    def _fields():
        raise api_error(422, ErrorCode.VALIDATION_FAILED, "schlecht",
                        fields=[{"path": "key", "code": "MISMATCH", "message": "x"}])

    @app.post("/echo")
    def _echo(body: Body):
        return {"ok": body.n}

    return TestClient(app, raise_server_exceptions=True)


def test_plain_http_exception_is_enveloped():
    r = _client().get("/plain401")
    assert r.status_code == 401
    body = r.json()
    assert "error" in body and body["error"]["code"] == "UNAUTHORIZED"
    assert "detail" not in body   # alte Form ist weg


def test_coded_api_error_envelope():
    r = _client().get("/coded")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "PROCESS_KEY_EXISTS"


def test_api_error_carries_fields():
    r = _client().get("/withfields")
    body = r.json()
    assert body["error"]["code"] == "VALIDATION_FAILED"
    assert body["error"]["fields"][0]["path"] == "key"


def test_request_validation_error_normalized():
    r = _client().post("/echo", json={"n": "not-an-int"})
    assert r.status_code == 422
    body = r.json()
    assert body["error"]["code"] == "VALIDATION_FAILED"
    assert any(f["path"] == "n" for f in body["error"]["fields"])


def test_process_routes_registered():
    paths = {r.path for r in processes_router.routes}
    expected = {
        "/processes",
        "/processes/{key}",
        "/processes/{key}/versions",
        "/processes/{key}/versions/{version:int}",
        "/processes/{key}/versions/{version:int}:publish",
        "/processes/{key}/versions/{version:int}:export",
        "/processes/{key}:duplicate",
        "/processes/{key}:set-active",
        "/processes:import",
        # Ersetzt den Shell-Zugang (backend/scripts/seed_processes.py): ohne
        # diese Route ist eine frische Installation nur über den Server
        # bespielbar.
        "/processes:seed",
    }
    assert expected.issubset(paths), expected - paths


# ── Prozess global (de)aktivieren ──────────────────────────────────────────────

class _FakeDefs:
    """Nur, was der set-active-Endpunkt anfasst."""

    def __init__(self):
        self.state: dict[str, bool] = {}

    def get_published(self, key):
        return {"id": 1, "key": key, "version": 1, "status": "published",
                "name": key, "definition": None} if key != "ghost" else None

    def set_disabled(self, key, disabled, by_id=None, by_name=None):
        self.state[key] = disabled
        return {"key": key, "disabled": disabled}

    def is_disabled(self, key):
        return self.state.get(key, False)


def _app(user, monkeypatch):
    fake = _FakeDefs()
    monkeypatch.setattr(papi, "db", fake)
    monkeypatch.setattr(papi, "record_audit", lambda **kw: None)
    app = FastAPI()
    _install_error_handlers(app)
    app.include_router(papi.router)
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app), fake


ADMIN = {"id": "a", "displayName": "Admin", "permissions": ["admin"]}
VIEWER = {"id": "v", "displayName": "Viewer", "permissions": ["view"]}


def test_set_active_admin_toggles(monkeypatch):
    client, fake = _app(ADMIN, monkeypatch)
    r = client.post("/processes/onboarding:set-active", json={"disabled": True})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["disabled"] is True
    assert fake.state["onboarding"] is True
    # Wieder freigeben.
    r = client.post("/processes/onboarding:set-active", json={"disabled": False})
    assert r.json()["data"]["disabled"] is False


def test_set_active_requires_admin(monkeypatch):
    client, _ = _app(VIEWER, monkeypatch)
    r = client.post("/processes/onboarding:set-active", json={"disabled": True})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "ADMIN_REQUIRED"


def test_set_active_blocks_system_process(monkeypatch):
    client, _ = _app(ADMIN, monkeypatch)
    # basis-ticket ist ein System-Prozess (seeds.SYSTEM_PROCESS_KEYS) – unantastbar.
    r = client.post("/processes/basis-ticket:set-active", json={"disabled": True})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "SYSTEM_PROCESS_READONLY"


def test_set_active_unknown_process(monkeypatch):
    client, _ = _app(ADMIN, monkeypatch)
    r = client.post("/processes/ghost:set-active", json={"disabled": True})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "PROCESS_NOT_FOUND"
