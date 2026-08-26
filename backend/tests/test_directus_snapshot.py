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
    assert calls["kw"]["filter"] == {"nummer": {"_eq": "4711"}}
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


def test_source_filter_merged_into_lookup():
    calls = {}
    src = {**SRC, "filter": {"aktiv": {"_eq": True}}}

    def query(coll, **kw):
        calls.update(kw=kw)
        return [{"nummer": 1, "firma": {"name": "A"}}]

    ds.apply_snapshots(_defn(), {"kst": "1"}, {}, get_source=lambda k: src, query=query)
    assert calls["kw"]["filter"] == {"_and": [{"aktiv": {"_eq": True}}, {"nummer": {"_eq": "1"}}]}
