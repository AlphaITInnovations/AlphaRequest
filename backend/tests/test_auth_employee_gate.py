"""Hard Gate „ohne Directus-Datensatz kein Arbeiten" (core/dependencies.enforce_employee_link).

Testet die Gate-Entscheidung isoliert (ohne echte Session/Request): Treffer hängt
den Datensatz an, kein Datensatz blockt 403, Directus-Ausfall blockt normale User
503 – aber Admins und die ENV-Bootstrap-Allowlist kommen als Break-Glass rein.
"""
import pytest
from fastapi import HTTPException

from backend.core import dependencies as dep
from backend.services import directus_employee
from backend.database.users import PERM_ADMIN, PERM_VIEW


@pytest.fixture
def cfg(monkeypatch):
    monkeypatch.setattr(dep.config, "AUTH_REQUIRE_DIRECTUS_EMPLOYEE", True)
    monkeypatch.setattr(dep.config, "AUTH_BOOTSTRAP_EMAILS", set())
    return monkeypatch


def _user(**kw):
    u = {"id": "oid1", "email": "user@x.de", "permissions": [PERM_VIEW]}
    u.update(kw)
    return u


def _patch_lookup(monkeypatch, *, rec=None, error=False):
    def fake(email):
        if error:
            raise directus_employee.EmployeeLookupError("down")
        return rec
    monkeypatch.setattr(dep.directus_employee, "lookup_employee", fake)


def test_treffer_haengt_datensatz_an(cfg):
    _patch_lookup(cfg, rec={"id": 5, "vorgesetzter": "Chef"})
    u = _user()
    dep.enforce_employee_link(u)
    assert u["employee"] == {"id": 5, "vorgesetzter": "Chef"}


def test_kein_datensatz_blockt_hart_403(cfg):
    _patch_lookup(cfg, rec=None)
    with pytest.raises(HTTPException) as ei:
        dep.enforce_employee_link(_user())
    assert ei.value.status_code == 403
    assert ei.value.detail["code"] == "NO_DIRECTUS_RECORD"


def test_kein_datensatz_bootstrap_darf_rein(cfg):
    cfg.setattr(dep.config, "AUTH_BOOTSTRAP_EMAILS", {"user@x.de"})
    _patch_lookup(cfg, rec=None)
    u = _user()
    dep.enforce_employee_link(u)          # kein Raise
    assert u["employee"] is None


def test_directus_down_blockt_normale_user_503(cfg):
    _patch_lookup(cfg, error=True)
    with pytest.raises(HTTPException) as ei:
        dep.enforce_employee_link(_user())
    assert ei.value.status_code == 503
    assert ei.value.detail["code"] == "DIRECTUS_UNAVAILABLE"


def test_directus_down_admin_breakglass(cfg):
    _patch_lookup(cfg, error=True)
    u = _user(permissions=[PERM_VIEW, PERM_ADMIN])
    dep.enforce_employee_link(u)          # kein Raise
    assert u["employee"] is None


def test_directus_down_bootstrap_breakglass(cfg):
    cfg.setattr(dep.config, "AUTH_BOOTSTRAP_EMAILS", {"user@x.de"})
    _patch_lookup(cfg, error=True)
    dep.enforce_employee_link(_user())    # kein Raise


def test_gate_aus_haengt_best_effort_an_ohne_blockade(cfg):
    cfg.setattr(dep.config, "AUTH_REQUIRE_DIRECTUS_EMPLOYEE", False)
    _patch_lookup(cfg, rec=None)
    u = _user()
    dep.enforce_employee_link(u)          # kein Raise trotz kein Datensatz
    assert u["employee"] is None


def test_gate_aus_directus_down_kein_raise(cfg):
    cfg.setattr(dep.config, "AUTH_REQUIRE_DIRECTUS_EMPLOYEE", False)
    _patch_lookup(cfg, error=True)
    u = _user()
    dep.enforce_employee_link(u)
    assert u["employee"] is None


# ── Login-Audit: Directus-Zuordnung sichtbar machen (auth._employee_link_audit) ──

def _patch_auth_lookup(monkeypatch, *, rec=None, error=False):
    from backend.api.v1 import auth
    def fake(email):
        if error:
            raise directus_employee.EmployeeLookupError("Directus nicht erreichbar")
        return rec
    monkeypatch.setattr(auth.directus_employee, "lookup_employee", fake)
    return auth


def test_login_audit_treffer_ohne_sonderhinweis(monkeypatch):
    auth = _patch_auth_lookup(monkeypatch, rec={"id": 5})
    summary, details = auth._employee_link_audit("user@x.de")
    assert summary is None
    assert details == {"directus_employee": "zugeordnet"}


def test_login_audit_kein_treffer_nennt_email(monkeypatch):
    auth = _patch_auth_lookup(monkeypatch, rec=None)
    summary, details = auth._employee_link_audit("Falsch@Alpha.org")
    assert summary and "Falsch@Alpha.org" in summary
    assert details["directus_employee"] == "kein_treffer"
    assert details["email"] == "Falsch@Alpha.org"


def test_login_audit_directus_fehler(monkeypatch):
    auth = _patch_auth_lookup(monkeypatch, error=True)
    summary, details = auth._employee_link_audit("user@x.de")
    assert summary and "nicht prüfbar" in summary
    assert details["directus_employee"] == "fehler"
    assert "Directus nicht erreichbar" in details["error"]


def test_login_audit_ohne_email():
    from backend.api.v1 import auth
    summary, details = auth._employee_link_audit("")
    assert summary and "ohne E-Mail" in summary
    assert details == {"directus_employee": "keine_email"}
