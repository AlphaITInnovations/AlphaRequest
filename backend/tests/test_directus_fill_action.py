"""Ebene-1: Automations-Aktion `directus_fill` (services/directus_fill_action).

Lädt Stammdaten aus Directus bei Phaseneintritt NACH – ohne Netz (Directus-
Zugriff injiziert). Deckt Happy-Path, Firmen-Auflösung (id→Name) und die
Best-effort-Pfade (kein Schlüssel / Quelle fehlt / Directus down / kein
Datensatz) ab sowie die Schema-Validierung des neuen Action-Typs.
"""
import pytest

from backend.schemas.process_definition import ProcessDefinition
from backend.services import directus_client as dc
from backend.services import directus_fill_action as dfa


# ── Definition mit directus_fill-Automation in Phase 2 ────────────────────────

def _defn():
    return ProcessDefinition.model_validate({
        "schemaVersion": 1, "key": "off", "name": "N",
        "fields": [
            {"key": "base.ma", "widget": "directus", "directusSource": "mitarbeitende",
             "directusFieldMap": [{"source": "first_name", "target": "base.vorname"}]},
            {"key": "base.vorname", "widget": "text"},
            {"key": "base.strasse", "widget": "text"},
            {"key": "base.plz", "widget": "text"},
            {"key": "base.firma", "widget": "company"}],
        "phases": [
            {"key": "start", "kind": "start", "responsibility": {"kind": "owner"},
             "fields": [{"ref": "base.ma"}]},
            {"key": "kuendigung", "kind": "task", "responsibility": {"kind": "owner"},
             "fields": [{"ref": "base.strasse", "mode": "readonly"},
                        {"ref": "base.plz", "mode": "readonly"},
                        {"ref": "base.firma", "mode": "readonly"}],
             "automations": [
                 {"id": "fill", "trigger": {"type": "on_enter"},
                  "action": {"type": "directus_fill", "directusFill": {
                      "source": "mitarbeitende", "keyField": "base.ma",
                      "fieldMap": [
                          {"source": "personal_address", "target": "base.strasse"},
                          {"source": "personal_zip", "target": "base.plz"},
                          {"source": "company", "target": "base.firma"}]}}}]}],
    })


_SRC = {"key": "mitarbeitende", "label": "MA", "collection": "mitarbeitende",
        "valueField": "email", "labelTemplate": "{{email}}", "fields": [],
        "filter": None, "sort": [], "limit": 200}


def _action(defn):
    return defn.phases[1].automations[0].action


def _phase(defn):
    return defn.phases[1]


def _companies_patch(monkeypatch):
    import backend.database.settings as settings
    monkeypatch.setattr(settings, "get_companies_full", lambda: [
        {"name": "Alpha GmbH", "directus_firma_id": "42"},
        {"name": "Beta GmbH", "directus_firma_id": "7"}])


# ── Happy-Path ────────────────────────────────────────────────────────────────

def test_fills_private_fields_and_resolves_company(monkeypatch):
    _companies_patch(monkeypatch)
    defn = _defn()
    calls = {}

    def query(coll, **kw):
        calls.update(coll=coll, kw=kw)
        return [{"email": "a@b.de", "personal_address": "Hauptstr. 1",
                 "personal_zip": "12345", "company": 42}]

    row = {"id": 1, "values": {"base.ma": "a@b.de"}}
    changes = dfa.execute(_action(defn), row, defn, _phase(defn),
                          get_source=lambda k: _SRC, query=query)
    vals = changes["values"]
    assert vals["base.strasse"] == "Hauptstr. 1"
    assert vals["base.plz"] == "12345"
    assert vals["base.firma"] == "Alpha GmbH"          # id→Name aufgelöst
    # Schlüsselabgleich wie beim Snapshot: _in gegen das valueField.
    assert calls["coll"] == "mitarbeitende"
    assert calls["kw"]["filter"] == {"email": {"_in": ["a@b.de"]}}
    assert "personal_address" in calls["kw"]["fields"]


def test_company_relation_object_resolves(monkeypatch):
    _companies_patch(monkeypatch)
    defn = _defn()
    row = {"id": 1, "values": {"base.ma": "a@b.de"}}
    changes = dfa.execute(
        _action(defn), row, defn, _phase(defn), get_source=lambda k: _SRC,
        query=lambda *a, **k: [{"email": "a@b.de", "company": {"id": 7, "name": "egal"}}])
    assert changes["values"]["base.firma"] == "Beta GmbH"


# ── Best-effort: nichts anfassen, Phase läuft trotzdem ────────────────────────

def test_no_key_value_returns_empty():
    defn = _defn()

    def query(*a, **k):
        raise AssertionError("ohne Schlüssel darf nicht abgefragt werden")

    row = {"id": 1, "values": {}}                       # base.ma leer
    assert dfa.execute(_action(defn), row, defn, _phase(defn),
                       get_source=lambda k: _SRC, query=query) == {}


def test_missing_source_returns_empty():
    defn = _defn()

    def query(*a, **k):
        raise AssertionError("fehlende Quelle darf nicht abfragen")

    row = {"id": 1, "values": {"base.ma": "a@b.de"}}
    assert dfa.execute(_action(defn), row, defn, _phase(defn),
                       get_source=lambda k: None, query=query) == {}


def test_directus_error_returns_empty():
    defn = _defn()

    def query(*a, **k):
        raise dc.DirectusError("down")

    row = {"id": 1, "values": {"base.ma": "a@b.de"}}
    assert dfa.execute(_action(defn), row, defn, _phase(defn),
                       get_source=lambda k: _SRC, query=query) == {}


def test_no_record_returns_empty():
    defn = _defn()
    row = {"id": 1, "values": {"base.ma": "a@b.de"}}
    assert dfa.execute(_action(defn), row, defn, _phase(defn),
                       get_source=lambda k: _SRC, query=lambda *a, **k: []) == {}


def test_company_unreadable_still_fills_private(monkeypatch):
    """Scheitert das Firmen-Lesen, bleiben die (datenschutzkritischen) Adress-Ziele
    trotzdem gefüllt; nur das Firmen-Ziel bleibt leer."""
    import backend.database.settings as settings

    def boom():
        raise RuntimeError("keine Rechte")

    monkeypatch.setattr(settings, "get_companies_full", boom)
    defn = _defn()
    row = {"id": 1, "values": {"base.ma": "a@b.de"}}
    changes = dfa.execute(
        _action(defn), row, defn, _phase(defn), get_source=lambda k: _SRC,
        query=lambda *a, **k: [{"email": "a@b.de", "personal_address": "Weg 2",
                                "personal_zip": "9", "company": 42}])
    vals = changes["values"]
    assert vals["base.strasse"] == "Weg 2" and vals["base.plz"] == "9"
    assert vals["base.firma"] is None                   # Firma unauflösbar → leer


# ── Dispatch: run_action leitet directus_fill an den Service weiter ───────────

def test_run_action_dispatches_to_directus_fill(monkeypatch):
    from backend.services import process_actions as actions
    from backend.services import directus_fill_action as dfa_mod
    seen = {}

    def fake_execute(action, row, defn, phase):
        seen["args"] = (action.type.value, row["id"])
        return {"values": {"base.strasse": "X"}}

    monkeypatch.setattr(dfa_mod, "execute", fake_execute)
    defn = _defn()
    changes = actions.run_action(_action(defn), {"id": 7, "values": {"base.ma": "a@b.de"}},
                                 defn, _phase(defn))
    assert seen["args"] == ("directus_fill", 7)
    assert changes == {"values": {"base.strasse": "X"}}


# ── Schema-Validierung des Action-Typs ────────────────────────────────────────

def _defn_with_action(action_block):
    return {
        "schemaVersion": 1, "key": "k", "name": "N",
        "fields": [{"key": "base.ma", "widget": "directus", "directusSource": "mitarbeitende",
                    "directusFieldMap": []},
                   {"key": "base.strasse", "widget": "text"}],
        "phases": [{"key": "p", "kind": "start", "responsibility": {"kind": "owner"},
                    "fields": [{"ref": "base.ma"}, {"ref": "base.strasse", "mode": "readonly"}],
                    "automations": [{"id": "a", "trigger": {"type": "on_enter"},
                                     "action": action_block}]}],
    }


def test_valid_directus_fill_action_ok():
    ProcessDefinition.model_validate(_defn_with_action(
        {"type": "directus_fill", "directusFill": {
            "source": "mitarbeitende", "keyField": "base.ma",
            "fieldMap": [{"source": "personal_address", "target": "base.strasse"}]}}))


def test_directus_fill_requires_spec():
    with pytest.raises(ValueError):
        ProcessDefinition.model_validate(_defn_with_action({"type": "directus_fill"}))


def test_directusfill_only_on_directus_fill_action():
    with pytest.raises(ValueError):
        ProcessDefinition.model_validate(_defn_with_action(
            {"type": "auto_advance", "directusFill": {
                "source": "mitarbeitende", "keyField": "base.ma",
                "fieldMap": [{"source": "x", "target": "base.strasse"}]}}))


def test_directus_fill_empty_fieldmap_rejected():
    with pytest.raises(ValueError):
        ProcessDefinition.model_validate(_defn_with_action(
            {"type": "directus_fill", "directusFill": {
                "source": "mitarbeitende", "keyField": "base.ma", "fieldMap": []}}))


def test_directus_fill_unknown_keyfield_rejected():
    with pytest.raises(ValueError):
        ProcessDefinition.model_validate(_defn_with_action(
            {"type": "directus_fill", "directusFill": {
                "source": "mitarbeitende", "keyField": "base.fehlt",
                "fieldMap": [{"source": "personal_address", "target": "base.strasse"}]}}))


def test_directus_fill_unknown_target_rejected():
    with pytest.raises(ValueError):
        ProcessDefinition.model_validate(_defn_with_action(
            {"type": "directus_fill", "directusFill": {
                "source": "mitarbeitende", "keyField": "base.ma",
                "fieldMap": [{"source": "personal_address", "target": "base.fehlt"}]}}))


def test_directus_fill_target_equals_keyfield_rejected():
    # Ziel == Schlüsselfeld überschriebe den Suchwert → beim nächsten Eintritt kein
    # Treffer mehr; wie der Snapshot (b.target == f.key) ausgeschlossen.
    with pytest.raises(ValueError):
        ProcessDefinition.model_validate(_defn_with_action(
            {"type": "directus_fill", "directusFill": {
                "source": "mitarbeitende", "keyField": "base.ma",
                "fieldMap": [{"source": "email", "target": "base.ma"}]}}))


def test_directus_fill_attachment_keyfield_rejected():
    # Nicht-skalares Schlüsselfeld (Anhang) würde nie matchen → stiller No-op.
    defn = {
        "schemaVersion": 1, "key": "k", "name": "N",
        "fields": [{"key": "base.anhang", "widget": "attachment"},
                   {"key": "base.strasse", "widget": "text"}],
        "phases": [{"key": "p", "kind": "start", "responsibility": {"kind": "owner"},
                    "fields": [{"ref": "base.strasse", "mode": "readonly"}],
                    "automations": [{"id": "a", "trigger": {"type": "on_enter"},
                                     "action": {"type": "directus_fill", "directusFill": {
                                         "source": "mitarbeitende", "keyField": "base.anhang",
                                         "fieldMap": [{"source": "personal_address",
                                                       "target": "base.strasse"}]}}}]}],
    }
    with pytest.raises(ValueError):
        ProcessDefinition.model_validate(defn)
