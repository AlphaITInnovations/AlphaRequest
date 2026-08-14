"""Ebene-1: Fehler-Envelope-Normalisierung + Routen-Registrierung (kein DB-Zugriff).

Der Envelope-Handler wird an einer Mini-App getestet (env-unabhängig); die
Prozess-Routen werden direkt am Router geprüft.
"""

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel

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
        "/processes:import",
        # Ersetzt den Shell-Zugang (backend/scripts/seed_processes.py): ohne
        # diese Route ist eine frische Installation nur über den Server
        # bespielbar.
        "/processes:seed",
    }
    assert expected.issubset(paths), expected - paths
