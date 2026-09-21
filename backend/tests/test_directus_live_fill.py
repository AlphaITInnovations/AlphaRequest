"""_live_fill_fields: welche directusFieldMap-Quellfelder die Options-Route
zusätzlich lädt, damit Snapshot-Ziele LIVE (bei der Auswahl) füllen.

Sicherheit: serverseitig aus der veröffentlichten Definition hergeleitet (nicht
vom Client bestimmbar) und auf in der Phase SICHTBARE, nicht-vertrauliche Ziele
beschränkt – verdeckte Ziele (z. B. Privatadresse) dürfen NICHT in die Options-
Liste gelangen."""
import backend.api.v1.directus as directus

DEFN = {
    "fields": [
        {"key": "base.mitarbeiter", "widget": "directus", "directusSource": "mitarbeitende",
         "directusFieldMap": [
             {"source": "first_name", "target": "base.vorname"},
             {"source": "location.name", "target": "base.niederlassung"},
             {"source": "private_street", "target": "base.privat_strasse"},  # hidden → raus
             {"source": "salary", "target": "base.gehalt"},                   # confidential → raus
         ]},
        {"key": "base.vorname", "widget": "text"},
        {"key": "base.niederlassung", "widget": "text"},
        {"key": "base.privat_strasse", "widget": "text"},
        {"key": "base.gehalt", "widget": "text",
         "visibility": {"confidential": True, "visibleToGroups": ["g"]}},
    ],
    "phases": [
        {"key": "antrag", "fields": [
            {"ref": "base.mitarbeiter", "mode": "editable"},
            {"ref": "base.vorname", "mode": "readonly"},
            {"ref": "base.niederlassung", "mode": "readonly"},
            {"ref": "base.privat_strasse", "mode": "hidden"},
            {"ref": "base.gehalt", "mode": "readonly"},
        ]},
    ],
}


def _patch(monkeypatch, defn=DEFN):
    monkeypatch.setattr(directus.defs_db, "get_published", lambda key: {"definition": defn})


def test_nur_sichtbare_nicht_vertrauliche_ziele(monkeypatch):
    _patch(monkeypatch)
    got = directus._live_fill_fields("mitarbeitende", "p", "base.mitarbeiter", "antrag")
    assert got == ["first_name", "location.name"]      # Reihenfolge wie im fieldMap
    assert "private_street" not in got                  # hidden-Ziel
    assert "salary" not in got                          # confidential-Ziel


def test_ohne_kontext_leer(monkeypatch):
    _patch(monkeypatch)
    assert directus._live_fill_fields("mitarbeitende", None, None, None) == []
    assert directus._live_fill_fields("mitarbeitende", "p", "base.mitarbeiter", None) == []


def test_feld_mit_anderer_quelle_leer(monkeypatch):
    """Kein beliebiges Feld abfragbar: passt directusSource nicht, gibt es nichts."""
    _patch(monkeypatch)
    assert directus._live_fill_fields("andere_quelle", "p", "base.mitarbeiter", "antrag") == []


def test_unbekannter_prozess_leer(monkeypatch):
    monkeypatch.setattr(directus.defs_db, "get_published", lambda key: None)
    assert directus._live_fill_fields("mitarbeitende", "p", "base.mitarbeiter", "antrag") == []
