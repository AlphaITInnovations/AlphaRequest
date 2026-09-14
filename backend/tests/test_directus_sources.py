"""Ebene-1: reine Logik der Directus-Quellen (database/directus_sources) – DB-frei."""
import pytest

from backend.database import directus_sources as ds


def test_normalize_requires_collection_value_label():
    for bad in [
        {"key": "k"},
        {"key": "k", "collection": "c"},
        {"key": "k", "collection": "c", "valueField": "v"},
    ]:
        with pytest.raises(ds.SourceError):
            ds.normalize_source(bad)


def test_normalize_rejects_bad_slug():
    with pytest.raises(ds.SourceError):
        ds.normalize_source({"key": "Bad Key", "collection": "c",
                             "valueField": "v", "labelTemplate": "t"})


def test_normalize_defaults_and_limit_clamp():
    s = ds.normalize_source({"key": "kostenstelle", "collection": "kst",
                             "valueField": "nummer", "labelTemplate": "{{nummer}}",
                             "limit": 99999})
    assert s["label"] == "kostenstelle"       # Fallback: key
    assert s["filter"] is None and s["fields"] == [] and s["sort"] == []
    assert s["limit"] == 1000                  # geklemmt


def test_normalize_rejects_non_dict_filter():
    with pytest.raises(ds.SourceError):
        ds.normalize_source({"key": "k", "collection": "c", "valueField": "v",
                             "labelTemplate": "t", "filter": "nope"})


def test_resolve_path():
    rec = {"nummer": "10", "firma": {"name": "Alpha"}}
    assert ds.resolve_path(rec, "firma.name") == "Alpha"
    assert ds.resolve_path(rec, "firma.plz") is None
    assert ds.resolve_path(rec, "x.y") is None


def test_template_paths_and_render_label():
    tpl = "{{nummer}} – {{firma.name}}"
    assert ds.template_paths(tpl) == ["nummer", "firma.name"]
    assert ds.render_label(tpl, {"nummer": "10", "firma": {"name": "Alpha"}}) == "10 – Alpha"
    assert ds.render_label(tpl, {"nummer": "10"}) == "10 – "      # fehlend → leer


def test_query_fields_union_dedup():
    s = ds.normalize_source({"key": "k", "collection": "c", "valueField": "nummer",
                             "labelTemplate": "{{nummer}} {{firma.name}}",
                             "fields": ["adresse.plz", "nummer"]})
    assert ds.query_fields(s) == ["nummer", "firma.name", "adresse.plz"]


def test_build_option_value_label_record():
    s = ds.normalize_source({"key": "k", "collection": "c", "valueField": "nummer",
                             "labelTemplate": "{{nummer}} – {{firma.name}}"})
    o = ds.build_option({"nummer": "10", "firma": {"name": "Alpha"}}, s)
    assert o["value"] == "10"
    assert o["label"] == "10 – Alpha"
    assert o["record"]["firma"]["name"] == "Alpha"


def test_build_option_label_falls_back_to_value():
    s = ds.normalize_source({"key": "k", "collection": "c", "valueField": "nummer",
                             "labelTemplate": "{{leer}}"})
    assert ds.build_option({"nummer": "7"}, s)["label"] == "7"


def test_set_all_rejects_duplicate_keys(monkeypatch):
    monkeypatch.setattr(ds, "settings_set", lambda k, v: None)
    dup = {"key": "a", "collection": "c", "valueField": "v", "labelTemplate": "t"}
    with pytest.raises(ds.SourceError):
        ds.set_all([dup, dict(dup)])


def test_get_all_skips_invalid(monkeypatch):
    monkeypatch.setattr(ds, "settings_get", lambda k, d: [
        {"key": "ok", "collection": "c", "valueField": "v", "labelTemplate": "t"},
        {"key": "BAD KEY", "collection": "c", "valueField": "v", "labelTemplate": "t"},
    ])
    assert [s["key"] for s in ds.get_all()] == ["ok"]
