"""Schutz der Pflicht-Fachabteilungen (/settings/groups) – Ebene-1, KEINE DB.

Nach dem Rückbau des Alt-Systems kommt dieser Schutz aus zwei NEUEN Quellen:
  * `services/seed_definitions.required_group_names()` – die Namen, über die die
    ausgelieferten Prozesse ihre Gruppen-Platzhalter auflösen, und
  * `process_definitions.groups_referenced_in_definitions()` – die IDs, die
    irgendeine (auch archivierte) Definition referenziert.

Beides muss greifen. Fällt eines weg, lässt sich nach dem Cutover eine
Fachabteilung löschen oder umbenennen, die ein veröffentlichter Prozess braucht:
die Zuständigkeit einer Phase zeigt dann ins Leere, und ein vertrauliches Feld
mit `visibility.visibleToGroups` wäre für NIEMANDEN mehr sichtbar.

Die API-Tests kürzen die Pflicht-Namensliste bewusst auf „IT" ein. So scheitert
eine Anfrage nachweislich an DEM Namen, um den es im Test geht, und nicht an
einem beliebigen anderen Pflichtnamen, der im Rumpf zufällig fehlt.
"""
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend.api.v1 import settings as settings_api
from backend.core.dependencies import get_current_user
from backend.database.users import PERM_ADMIN, PERM_VIEW
from backend.main import _install_error_handlers
from backend.services import seed_definitions as seed

ADMIN = {"id": "u_admin", "displayName": "Admin", "permissions": [PERM_VIEW, PERM_ADMIN]}

# „IT" ist ein Pflicht-Name; „Sonderprojekte" ist eine frei angelegte Gruppe, die
# aber von einer Definition referenziert wird; „Kantine" ist beides nicht.
GRUPPEN = [
    {"id": "g_it", "name": "IT", "members": ["u1"], "distributions": [], "hidden": False},
    {"id": "g_sonder", "name": "Sonderprojekte", "members": [], "distributions": [],
     "hidden": False},
    {"id": "g_kantine", "name": "Kantine", "members": [], "distributions": [], "hidden": False},
]

REFERENZIERT = {"g_sonder"}


@pytest.fixture
def store(monkeypatch):
    """Gruppen-Speicher, Definitions-Referenzen und Pflicht-Namen ohne DB."""
    zustand = {"groups": [dict(g) for g in GRUPPEN], "saved": None, "ref_calls": []}

    monkeypatch.setattr(settings_api, "get_groups",
                        lambda: [dict(g) for g in zustand["groups"]])

    def _save(neu):
        zustand["saved"] = [dict(g) for g in neu]
        zustand["groups"] = [dict(g) for g in neu]

    def _referenced(ids):
        zustand["ref_calls"].append(set(ids))
        return set(ids) & REFERENZIERT

    def _assert_unreferenced(ids):
        """Ersatz der DB-gestützten Prüfung – gleiche Wirkung (409)."""
        if set(ids or ()) & REFERENZIERT:
            raise HTTPException(409, "Diese Fachabteilung wird von einem Prozess verwendet.")

    monkeypatch.setattr(settings_api, "save_groups", _save)
    monkeypatch.setattr(settings_api, "_referenced_group_ids", _referenced)
    monkeypatch.setattr(settings_api, "_assert_groups_unreferenced", _assert_unreferenced)
    monkeypatch.setattr(settings_api, "record_audit", lambda **kw: None)
    # Pflicht-Namen auf genau einen kürzen (siehe Modul-Docstring). Greift für
    # BEIDE Leser, weil settings.py die Funktion je Aufruf frisch importiert.
    monkeypatch.setattr(seed, "required_group_names", lambda: ["IT"])
    return zustand


def _client(user: dict = ADMIN, *, user_cache=()) -> TestClient:
    app = FastAPI()
    _install_error_handlers(app)
    app.include_router(settings_api.router)
    app.dependency_overrides[get_current_user] = lambda: user
    app.state.user_cache = [{"id": u} for u in user_cache]
    return TestClient(app)


# ── Namensquelle ─────────────────────────────────────────────────────────────

def test_namensquelle_ist_seed_definitions():
    """Der Schutz darf nicht an einer eigenen Liste hängen, die auseinanderläuft.
    Ohne store-Fixture, also gegen die ECHTE Liste."""
    echt = {n.strip().lower() for n in seed.required_group_names()}
    assert settings_api._required_group_names() == echt
    assert "it" in echt and "personalabteilung" in echt


def test_pflichtname_wird_case_insensitiv_erkannt(store):
    """In der DB kann die Gruppe „IT" oder „it" heißen."""
    assert settings_api._is_required_group_name("IT")
    assert settings_api._is_required_group_name("  it ")
    assert not settings_api._is_required_group_name("Kantine")
    assert not settings_api._is_required_group_name("")


# ── Anzeige-Flag ─────────────────────────────────────────────────────────────

def test_required_flag_kommt_aus_beiden_quellen(store):
    daten = _client().get("/settings/groups").json()["data"]
    nach_id = {g["id"]: g for g in daten}
    assert nach_id["g_it"]["required"] is True          # Pflicht-NAME
    assert nach_id["g_sonder"]["required"] is True      # von einer Definition referenziert
    assert nach_id["g_kantine"]["required"] is False    # frei löschbar


def test_liste_fragt_die_referenzen_nur_einmal_ab(store):
    """Eine Abfrage pro Zeile wäre ein N+1 über alle Definitionen."""
    _client().get("/settings/groups")
    assert store["ref_calls"] == [{"g_it", "g_sonder", "g_kantine"}]


# ── Umbenennen ───────────────────────────────────────────────────────────────

def test_pflichtgruppe_laesst_sich_nicht_umbenennen(store):
    """Der Seeder löst die Gruppe über den NAMEN auf – nach einer Umbenennung legte
    der nächste Lauf eine zweite, leere Gruppe an."""
    r = _client(user_cache=["u1"]).put(
        "/settings/groups/g_it",
        json={"name": "IT-Abteilung", "members": ["u1"], "distributions": [], "hidden": False})
    assert r.status_code == 409
    assert store["saved"] is None                      # nichts geschrieben


def test_pflichtgruppe_bleibt_in_mitgliedern_editierbar(store):
    r = _client(user_cache=["u1", "u2"]).put(
        "/settings/groups/g_it",
        json={"name": "IT", "members": ["u1", "u2"], "distributions": [], "hidden": False})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["members"] == ["u1", "u2"]


def test_freie_gruppe_laesst_sich_umbenennen(store):
    r = _client().put("/settings/groups/g_kantine",
                      json={"name": "Betriebsrestaurant", "members": [],
                            "distributions": [], "hidden": False})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["name"] == "Betriebsrestaurant"


# ── Löschen ──────────────────────────────────────────────────────────────────

def test_pflichtgruppe_laesst_sich_nicht_loeschen(store):
    assert _client().delete("/settings/groups/g_it").status_code == 409
    assert store["saved"] is None


def test_von_einer_definition_referenzierte_gruppe_laesst_sich_nicht_loeschen(store):
    """Kein Pflicht-NAME, aber eine Definition zeigt auf die ID."""
    assert _client().delete("/settings/groups/g_sonder").status_code == 409
    assert store["saved"] is None


def test_unbeteiligte_gruppe_laesst_sich_loeschen(store):
    assert _client().delete("/settings/groups/g_kantine").status_code == 204
    assert [g["id"] for g in store["saved"]] == ["g_it", "g_sonder"]


# ── Bulk-Replace ─────────────────────────────────────────────────────────────

def test_bulk_darf_pflichtgruppe_nicht_weglassen(store):
    r = _client().put("/settings/groups",
                      json={"groups": [{"id": "g_kantine", "name": "Kantine"}]})
    assert r.status_code == 409 and "IT" in r.json()["error"]["message"]
    assert store["saved"] is None


def test_bulk_erkennt_umbenennung_einer_pflichtgruppe_als_verlust(store):
    """Umbenennen sieht im Bulk-Pfad aus wie „Name fehlt" – genau richtig."""
    r = _client(user_cache=["u1"]).put("/settings/groups", json={"groups": [
        {"id": "g_it", "name": "IT neu", "members": ["u1"]},
        {"id": "g_sonder", "name": "Sonderprojekte"},
        {"id": "g_kantine", "name": "Kantine"},
    ]})
    assert r.status_code == 409 and "IT" in r.json()["error"]["message"]
    assert store["saved"] is None


def test_bulk_darf_referenzierte_gruppe_nicht_entfernen(store):
    """Pflicht-Namen sind vollständig – es scheitert an der ID-Referenz."""
    r = _client(user_cache=["u1"]).put("/settings/groups", json={"groups": [
        {"id": "g_it", "name": "IT", "members": ["u1"]},
        {"id": "g_kantine", "name": "Kantine"},
    ]})
    assert r.status_code == 409
    assert "Prozess" in r.json()["error"]["message"]
    assert store["saved"] is None


def test_bulk_speichert_wenn_alles_erhalten_bleibt(store):
    r = _client(user_cache=["u1"]).put("/settings/groups", json={"groups": [
        {"id": "g_it", "name": "IT", "members": ["u1"]},
        {"id": "g_sonder", "name": "Sonderprojekte"},
    ]})
    assert r.status_code == 200, r.text
    assert [g["id"] for g in store["saved"]] == ["g_it", "g_sonder"]
