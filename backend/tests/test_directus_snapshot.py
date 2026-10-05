"""Ebene-1: server-seitiger Directus-Snapshot (services/directus_snapshot) – ohne Netz."""
from backend.schemas.process_definition import ProcessDefinition
from backend.services import directus_client as dc
from backend.services import directus_snapshot as ds


def _defn():
    return ProcessDefinition.model_validate({
        "schemaVersion": 1, "key": "k", "name": "N",
        "fields": [
            {"key": "kst", "widget": "directus", "directusSource": "kostenstelle",
             "directusFieldMap": [{"source": "firma.name", "target": "firma"},
                                  {"source": "nummer", "target": "kstnum"}]},
            {"key": "firma", "widget": "text"},
            {"key": "kstnum", "widget": "number"}],
        "phases": [{"key": "start", "kind": "start", "responsibility": {"kind": "owner"},
                    "fields": [{"ref": "kst"}, {"ref": "firma", "mode": "readonly"},
                               {"ref": "kstnum", "mode": "readonly"}]}],
    })


SRC = {"key": "kostenstelle", "label": "KST", "collection": "kst", "valueField": "nummer",
       "labelTemplate": "{{nummer}}", "fields": ["firma.name"], "filter": None, "sort": [], "limit": 200}


def test_fills_targets_on_new_value():
    calls = {}

    def query(coll, **kw):
        calls.update(coll=coll, kw=kw)
        return [{"nummer": 4711, "firma": {"name": "Alpha"}}]

    out = ds.apply_snapshots(_defn(), {"kst": "4711"}, {}, get_source=lambda k: SRC, query=query)
    assert out["firma"] == "Alpha"            # String-Ziel
    assert out["kstnum"] == 4711              # Zahl-Ziel korrekt gecoerct
    assert calls["coll"] == "kst"
    assert calls["kw"]["filter"] == {"nummer": {"_in": ["4711"]}}
    assert "firma.name" in calls["kw"]["fields"]


def test_frozen_when_value_unchanged():
    called = []

    def query(coll, **kw):
        called.append(1)
        return [{"nummer": 4711, "firma": {"name": "X"}}]

    out = ds.apply_snapshots(_defn(), {"kst": "4711", "firma": "Alt"},
                             {"kst": "4711", "firma": "Alt"}, get_source=lambda k: SRC, query=query)
    assert called == []                       # kein Directus-Aufruf – eingefroren
    assert out["firma"] == "Alt"


def test_clears_targets_when_emptied():
    out = ds.apply_snapshots(_defn(), {"kst": ""},
                             {"kst": "4711", "firma": "Alpha", "kstnum": 4711},
                             get_source=lambda k: SRC, query=lambda *a, **k: [])
    assert out["firma"] is None and out["kstnum"] is None


def test_directus_error_leaves_targets():
    def query(coll, **kw):
        raise dc.DirectusError("down")

    out = ds.apply_snapshots(_defn(), {"kst": "4711", "firma": "Alt"},
                             {"kst": "4700", "firma": "Alt"}, get_source=lambda k: SRC, query=query)
    assert out["firma"] == "Alt"              # best-effort: unverändert


def test_missing_source_skips():
    def query(*a, **k):
        raise AssertionError("query darf nicht aufgerufen werden")

    out = ds.apply_snapshots(_defn(), {"kst": "4711"}, {}, get_source=lambda k: None, query=query)
    assert out.get("firma") is None


def test_no_record_leaves_targets():
    # Schlüssel gesetzt, aber Re-Fetch findet NICHTS (z. B. Typ-Mismatch beim
    # valueField): Zielfelder dürfen NICHT geleert werden (sonst leere Basisdaten
    # + Titel nach dem Anlegen).
    out = ds.apply_snapshots(_defn(), {"kst": "4711", "firma": "Alpha", "kstnum": 4711}, {},
                             get_source=lambda k: SRC, query=lambda *a, **k: [])
    assert out["firma"] == "Alpha" and out["kstnum"] == 4711


def test_seed_snapshot_targets_fills_only_empty():
    d = _defn()
    # Leere Ziele werden aus den (live gefüllten) Formularwerten vorbelegt …
    out = ds.seed_snapshot_targets(d, {"kst": "1"}, {"kst": "1", "firma": "Alpha", "kstnum": 42})
    assert out["firma"] == "Alpha" and out["kstnum"] == 42
    # … bestehende Ziele aber nicht überschrieben, und Nicht-Ziele ignoriert.
    out2 = ds.seed_snapshot_targets(d, {"firma": "Da"}, {"firma": "Neu", "fremd": "x"})
    assert out2["firma"] == "Da" and "fremd" not in out2


def test_source_filter_merged_into_lookup():
    calls = {}
    src = {**SRC, "filter": {"aktiv": {"_eq": True}}}

    def query(coll, **kw):
        calls.update(kw=kw)
        return [{"nummer": 1, "firma": {"name": "A"}}]

    ds.apply_snapshots(_defn(), {"kst": "1"}, {}, get_source=lambda k: src, query=query)
    assert calls["kw"]["filter"] == {"_and": [{"aktiv": {"_eq": True}}, {"nummer": {"_in": ["1"]}}]}


# ── Firmen-Feld (widget=company): Directus-Firmen-ID → System-Firmenname ──────

def _defn_company():
    return ProcessDefinition.model_validate({
        "schemaVersion": 1, "key": "k", "name": "N",
        "fields": [
            {"key": "ma", "widget": "directus", "directusSource": "mitarbeitende",
             "directusFieldMap": [{"source": "company", "target": "firma"}]},
            {"key": "firma", "widget": "company"}],
        "phases": [{"key": "start", "kind": "start", "responsibility": {"kind": "owner"},
                    "fields": [{"ref": "ma"}, {"ref": "firma", "mode": "readonly"}]}],
    })


_MA_SRC = {"key": "mitarbeitende", "label": "MA", "collection": "mitarbeitende",
           "valueField": "email", "labelTemplate": "{{email}}", "fields": [],
           "filter": None, "sort": [], "limit": 200}


def _companies_patch(monkeypatch):
    monkeypatch.setattr(ds, "get_companies_full", lambda: [
        {"name": "Alpha GmbH", "directus_firma_id": "42"},
        {"name": "Beta GmbH", "directus_firma_id": "7"}])


def test_company_target_scalar_id_resolves_to_name(monkeypatch):
    _companies_patch(monkeypatch)
    out = ds.apply_snapshots(_defn_company(), {"ma": "x@y.de"}, {},
                             get_source=lambda k: _MA_SRC,
                             query=lambda *a, **k: [{"email": "x@y.de", "company": 42}])
    assert out["firma"] == "Alpha GmbH"


def test_company_target_relation_object_resolves_to_name(monkeypatch):
    _companies_patch(monkeypatch)
    out = ds.apply_snapshots(_defn_company(), {"ma": "x@y.de"}, {},
                             get_source=lambda k: _MA_SRC,
                             query=lambda *a, **k: [{"email": "x@y.de",
                                                     "company": {"id": 7, "name": "egal"}}])
    assert out["firma"] == "Beta GmbH"


def test_company_target_unknown_id_becomes_none(monkeypatch):
    _companies_patch(monkeypatch)
    out = ds.apply_snapshots(_defn_company(), {"ma": "x@y.de"}, {},
                             get_source=lambda k: _MA_SRC,
                             query=lambda *a, **k: [{"email": "x@y.de", "company": 999}])
    assert out["firma"] is None


# ── Auswahl-Feld (widget=select): Directus-Wert case-insensitiv auf Option ────

def _defn_select():
    return ProcessDefinition.model_validate({
        "schemaVersion": 1, "key": "k", "name": "N",
        "fields": [
            {"key": "ma", "widget": "directus", "directusSource": "mitarbeitende",
             "directusFieldMap": [{"source": "salutation", "target": "anrede"}]},
            {"key": "anrede", "widget": "select",
             "options": [{"value": "Herr"}, {"value": "Frau"}, {"value": "Divers"}]}],
        "phases": [{"key": "start", "kind": "start", "responsibility": {"kind": "owner"},
                    "fields": [{"ref": "ma"}, {"ref": "anrede", "mode": "editable"}]}],
    })


def test_select_target_maps_case_insensitively():
    # Directus liefert „herr" (Kleinschreibung) → Option-Wert „Herr" (wie Prefill).
    out = ds.apply_snapshots(_defn_select(), {"ma": "x@y.de"}, {},
                             get_source=lambda k: _MA_SRC,
                             query=lambda *a, **k: [{"email": "x@y.de", "salutation": "herr"}])
    assert out["anrede"] == "Herr"


def test_select_target_unknown_value_becomes_none():
    # Kein passender Options-Wert und kein Freitext → Feld bleibt ungesetzt (None),
    # statt einen ungültigen Wert ins Dropdown zu schreiben.
    out = ds.apply_snapshots(_defn_select(), {"ma": "x@y.de"}, {},
                             get_source=lambda k: _MA_SRC,
                             query=lambda *a, **k: [{"email": "x@y.de", "salutation": "mx"}])
    assert out["anrede"] is None
