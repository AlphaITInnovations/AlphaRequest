"""Session-Cookie bleibt schlank und frei von Personendaten.

Das Starlette-Session-Cookie ist nur SIGNIERT (nicht verschlüsselt), geht mit
jedem Request mit und darf 4 KB nicht überschreiten. Früher landeten dort bei
jeder Antwort der komplette Directus-Mitarbeiter-Datensatz (private Adresse,
Telefon …) und alle AD-Gruppen-GUIDs – bei vielen Gruppen kippte das Cookie
über nginx-Puffer bzw. Browser-Limit (502 / Abmeldung 15 min nach Login).
"""
import time
from types import SimpleNamespace

import pytest

from backend.api.v1 import auth
from backend.core import dependencies as deps
from backend.database.sessions import parse_login_profile


def test_login_cookie_traegt_nur_die_schlanke_identitaet():
    claims = {"name": "Max Muster", "groups": [f"g{i}" for i in range(80)]}
    infos = {"phone": "+49 1", "mobile": "+49 2", "company": "AC", "position": "Dev",
             "address": {"city": "Nürnberg", "street": "Privatweg 1"}}
    payload, profile = auth._split_login_identity(claims, infos, "max@x.org", "oid-1")
    assert set(payload) == {"id", "oid", "displayName", "email"}
    assert payload["id"] == "max@x.org" and payload["displayName"] == "Max Muster"
    assert len(profile["groups"]) == 80
    assert profile["address"]["street"] == "Privatweg 1" and profile["phone"] == "+49 1"


@pytest.fixture
def request_with_session(monkeypatch):
    stored = {"id": "max@x.org", "oid": "oid-1", "displayName": "Max", "email": "max@x.org"}
    session = {"sid": "s1", "user": stored, "boot_id": deps.SERVER_BOOT_ID,
               "last_activity": int(time.time())}
    row = {"sid": "s1", "user_id": "max@x.org", "age_seconds": 0,
           "login_profile": {"groups": ["g-ad-1"], "phone": "+49 1",
                             "address": {"street": "Privatweg 1"}}}
    monkeypatch.setattr(deps.session_store, "get_session", lambda sid: row)
    monkeypatch.setattr(deps, "get_user_permissions", lambda uid: ["view"])
    monkeypatch.setattr(deps.directus_employee, "lookup_employee",
                        lambda mail: {"id": 7, "private_mail": "privat@x.org"})
    req = SimpleNamespace(session=session, cookies={}, client=SimpleNamespace(host="10.0.0.1"))
    return req, session, stored


def test_get_current_user_reichert_nur_die_kopie_an(request_with_session):
    req, session, stored = request_with_session
    user = deps.get_current_user(req)
    # Der Request bekommt alles …
    assert user["permissions"] == ["view"]
    assert user["employee"]["private_mail"] == "privat@x.org"
    assert user["groups"] == ["g-ad-1"] and user["phone"] == "+49 1"
    # … das Session-Dict (= Cookie-Inhalt) bleibt unverändert schlank.
    assert session["user"] is stored
    assert set(session["user"]) == {"id", "oid", "displayName", "email"}


def test_ohne_session_zeile_keine_ad_gruppen(request_with_session, monkeypatch):
    """Fail-open bei DB-Fehler: der Request läuft, aber ohne AD-Gruppen
    (Rechte, die NUR an einer AD-Gruppe hängen, greifen dann nicht)."""
    req, session, _ = request_with_session

    def boom(sid):
        raise RuntimeError("DB weg")
    monkeypatch.setattr(deps.session_store, "get_session", boom)
    user = deps.get_current_user(req)
    assert user["groups"] == []
    assert "groups" not in session["user"]


def test_parse_login_profile_ist_robust():
    assert parse_login_profile(None) == {}
    assert parse_login_profile("") == {}
    assert parse_login_profile("kaputt{") == {}
    assert parse_login_profile("[1, 2]") == {}
    assert parse_login_profile('{"groups": ["a"]}') == {"groups": ["a"]}


# ── Hintergrund-Abfragen verlängern die Session nicht ─────────────────────────

def test_hintergrund_abfrage_verlaengert_die_session_nicht(request_with_session):
    req, session, _ = request_with_session
    alt = int(time.time()) - 120                 # > SAFE_UPDATE_INTERVAL, < Timeout
    session["last_activity"] = alt
    req.headers = {"x-background-poll": "1"}
    deps.get_current_user(req)                   # authentifiziert normal …
    assert session["last_activity"] == alt       # … zählt aber nicht als Aktivität


def test_normale_abfrage_verlaengert_die_session(request_with_session):
    req, session, _ = request_with_session
    alt = int(time.time()) - 120
    session["last_activity"] = alt
    req.headers = {}
    deps.get_current_user(req)
    assert session["last_activity"] > alt


def test_hintergrund_abfrage_unterliegt_weiter_dem_timeout(request_with_session, monkeypatch):
    from fastapi import HTTPException
    req, session, _ = request_with_session
    monkeypatch.setattr(deps.session_store, "delete_session", lambda sid: None)
    session["last_activity"] = int(time.time()) - int(deps.config.SESSION_TIMEOUT) - 5
    req.headers = {"x-background-poll": "1"}
    with pytest.raises(HTTPException) as exc:
        deps.get_current_user(req)
    assert exc.value.status_code == 401
