"""GET /auth/profile: volle Profil-Anzeige (Konto + Azure-Profil + Directus-Employee)."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.v1 import auth as auth_api
from backend.core.dependencies import get_current_user
from backend.main import _install_error_handlers


def _client(user: dict) -> TestClient:
    app = FastAPI()
    _install_error_handlers(app)
    app.include_router(auth_api.router)
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def _user(**kw):
    u = {
        "id": "oid1", "displayName": "Helmut Popp", "email": "helmut.popp@x.org",
        "permissions": ["view"], "phone": "+4991121646622", "mobile": "+491607703602",
        "company": "AC", "position": "Niederlassungsleiter", "address": {"city": "Nürnberg"},
        "groups": ["g1", "g2"],
        "employee": {"first_name": "Helmut", "last_name": "Popp",
                     "job_title": "Niederlassungsleiter", "location": "Nürnberg"},
    }
    u.update(kw)
    return u


def test_profile_liefert_konto_azure_und_employee():
    r = _client(_user()).get("/auth/profile")
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["displayName"] == "Helmut Popp"
    assert d["mail"] == "helmut.popp@x.org"          # Fallback email→mail
    assert d["position"] == "Niederlassungsleiter"
    assert d["phone"] == "+4991121646622"
    assert d["groups"] == ["g1", "g2"]
    assert d["employee"]["last_name"] == "Popp"
    assert d["employee"]["location"] == "Nürnberg"


def test_profile_ohne_employee_ist_null():
    r = _client(_user(employee=None)).get("/auth/profile")
    assert r.status_code == 200
    assert r.json()["data"]["employee"] is None
