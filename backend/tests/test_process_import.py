"""Ebene-1: Manueller Import löst Gruppen-Platzhalter auf (kein DB-Zugriff).

Seit dem Wegfall des Seed-Dialogs ist /processes:import DER Weg, die
mitgelieferten JSONs (backend/seeds/processes/) einzuspielen. Sie enthalten
Platzhalter (HIER_GRUPPEN_ID_*), die je Installation gegen echte Gruppen-IDs
aufgelöst werden müssen – fail-closed: ein stehen gebliebener Platzhalter
würde still einen dauerhaft kaputten Prozess anlegen.
"""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.v1 import processes as papi
from backend.core.dependencies import get_current_user
from backend.main import _install_error_handlers

ADMIN = {"id": "u_admin", "displayName": "Admin", "permissions": ["admin"]}

GRUPPEN = [
    {"id": "gid-it", "name": "IT"},
    {"id": "gid-hr", "name": "Personalabteilung"},
    {"id": "gid-fp", "name": "Fuhrpark"},
    {"id": "gid-sgl", "name": "Sekretariat GL"},
    {"id": "gid-lutz", "name": "FreigabeHerrLutz"},
]


class FakeDb:
    """Nur create_process – mehr braucht der Import nicht."""

    def __init__(self):
        self.created: list[dict] = []

    def create_process(self, key, name, definition_json, user_id, user_name):
        row = {"id": 1, "key": key, "version": 1, "status": "draft", "name": name,
               "definition": json.loads(definition_json), "base_version": None,
               "created_by": user_id, "created_by_name": user_name,
               "created_at": None, "updated_at": None, "published_at": None,
               "etag": "e1"}
        self.created.append(row)
        return row


@pytest.fixture
def ctx(monkeypatch):
    from backend.database import groups as groups_db
    fake = FakeDb()
    monkeypatch.setattr(papi, "db", fake)
    monkeypatch.setattr(papi, "record_audit", lambda **kw: None)
    monkeypatch.setattr(groups_db, "get_groups", lambda: GRUPPEN)
    app = FastAPI()
    _install_error_handlers(app)
    app.include_router(papi.router)
    app.dependency_overrides[get_current_user] = lambda: ADMIN
    return {"client": TestClient(app), "db": fake, "groups_db": groups_db}


def _onboarding_roh() -> dict:
    """Minimal-Definition mit Gruppen-Platzhaltern (HIER_..._EINSETZEN) – bewusst
    INLINE (entkoppelt von den entfernten Fach-Seeds): geprüft wird nur die
    Platzhalter-Auflösung des Imports, nicht die Struktur eines konkreten Prozesses."""
    return {
        "schemaVersion": 1, "key": "zugang-beantragen", "name": "Onboarding",
        "fields": [
            {"key": "base.name", "widget": "text"},
            {"key": "personal.private_street", "widget": "text",
             "visibility": {"confidential": False,
                            "visibleToGroups": ["HIER_GRUPPEN_ID_PERSONALABTEILUNG_EINSETZEN"]}},
            {"key": "it.note", "widget": "text",
             "visibility": {"confidential": False,
                            "visibleToGroups": ["HIER_GRUPPEN_ID_IT_EINSETZEN"]}},
        ],
        "phases": [
            {"key": "start", "kind": "start", "responsibility": {"kind": "owner"},
             "fields": [{"ref": "base.name", "required": True}]},
            {"key": "freigabe", "kind": "review",
             "responsibility": {"kind": "group",
                                "group": "HIER_GRUPPEN_ID_FREIGABEHERRLUTZ_EINSETZEN"},
             "fields": [{"ref": "base.name", "mode": "readonly"}]},
            {"key": "arbeitsvertrag", "kind": "task",
             "responsibility": {"kind": "group",
                                "group": "HIER_GRUPPEN_ID_SEKRETARIAT_GL_EINSETZEN"},
             "fields": [{"ref": "base.name", "mode": "readonly"}]},
            {"key": "durchfuehrung", "kind": "review",
             "responsibility": {"kind": "departments", "rule": [
                 {"group": "HIER_GRUPPEN_ID_IT_EINSETZEN", "required": True},
                 {"group": "HIER_GRUPPEN_ID_PERSONALABTEILUNG_EINSETZEN", "required": True},
                 {"group": "HIER_GRUPPEN_ID_FUHRPARK_EINSETZEN", "required": False}]},
             "fields": [{"ref": "base.name", "mode": "readonly"}]},
        ],
    }


def test_import_loest_platzhalter_auf(ctx):
    r = ctx["client"].post("/processes:import",
                           json={"targetKey": "zugang-beantragen",
                                 "definition": _onboarding_roh()})
    assert r.status_code == 200, r.text
    defn = ctx["db"].created[0]["definition"]
    assert "HIER_" not in json.dumps(defn, ensure_ascii=False)
    # Stichproben: Zuständigkeit und Sichtbarkeit zeigen auf echte Gruppen.
    vertrag = next(p for p in defn["phases"] if p["key"] == "arbeitsvertrag")
    assert vertrag["responsibility"]["group"] == "gid-sgl"      # Sekretariat GL
    strasse = next(f for f in defn["fields"] if f["key"] == "personal.private_street")
    assert strasse["visibility"]["visibleToGroups"] == ["gid-hr"]


def test_import_faellt_geschlossen_wenn_gruppen_fehlen(ctx, monkeypatch):
    monkeypatch.setattr(ctx["groups_db"], "get_groups",
                        lambda: [{"id": "gid-it", "name": "IT"}])
    r = ctx["client"].post("/processes:import",
                           json={"targetKey": "zugang-beantragen",
                                 "definition": _onboarding_roh()})
    assert r.status_code == 422
    err = r.json()["error"]
    # Die Meldung nennt die FEHLENDEN Fachabteilungen beim Namen.
    assert "Personalabteilung" in err["message"]
    assert any(f["code"] == "UNRESOLVED_PLACEHOLDER" for f in err["fields"])
    assert ctx["db"].created == []


def test_import_erlaubt_unbekannte_echte_ids(ctx):
    """Export aus einer ANDEREN Installation: echte, hier unbekannte IDs sind
    erlaubt – der Import erzeugt einen Entwurf, dessen Fehler der Editor anzeigt
    und reparieren lässt (nur Platzhalter sind hart verboten)."""
    text = json.dumps(_onboarding_roh(), ensure_ascii=False)
    for ph, ersatz in {
        "HIER_GRUPPEN_ID_IT_EINSETZEN": "fremd-1",
        "HIER_GRUPPEN_ID_PERSONALABTEILUNG_EINSETZEN": "fremd-2",
        "HIER_GRUPPEN_ID_FUHRPARK_EINSETZEN": "fremd-3",
        "HIER_GRUPPEN_ID_SEKRETARIAT_GL_EINSETZEN": "fremd-4",
        "HIER_GRUPPEN_ID_FREIGABEHERRLUTZ_EINSETZEN": "fremd-5",
    }.items():
        text = text.replace(ph, ersatz)
    r = ctx["client"].post("/processes:import",
                           json={"targetKey": "zugang-beantragen",
                                 "definition": json.loads(text)})
    assert r.status_code == 200, r.text
