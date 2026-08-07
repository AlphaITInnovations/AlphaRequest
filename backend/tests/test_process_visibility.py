"""Ebene-1: feldbezogene Sichtbarkeit + Schreibschutz (services/process_visibility)."""

from backend.schemas.process_definition import ProcessDefinition
from backend.services.process_visibility import (
    ViewerCtx, can_see_field, filter_values, editable_field_keys, apply_writes,
)

DEFN = ProcessDefinition.model_validate({
    "schemaVersion": 1, "key": "demo", "name": "Demo",
    "fields": [
        {"key": "base.name", "widget": "text"},                          # geteilt
        {"key": "it.host", "widget": "text",
         "visibility": {"visibleToGroups": ["g_it"]}},                    # gruppen-beschränkt
        {"key": "personal.salary", "widget": "textarea",
         "visibility": {"confidential": True, "visibleToGroups": ["g_sgl"]}},  # vertraulich
    ],
    "phases": [
        {"key": "start", "kind": "start", "responsibility": {"kind": "owner"},
         "fields": [{"ref": "base.name", "mode": "editable"}]},
        {"key": "review", "kind": "review",
         "responsibility": {"kind": "departments", "rule": [{"group": "g_it"}]},
         "fields": [{"ref": "base.name", "mode": "readonly"},
                    {"ref": "it.host", "mode": "editable"},
                    {"ref": "personal.salary", "mode": "editable"}]},
    ],
})
FIELDS = {f.key: f for f in DEFN.fields}
REVIEW = DEFN.phases[1]

FULL = ViewerCtx(full_view=True, is_admin=False, group_ids=set())
ADMIN = ViewerCtx(full_view=True, is_admin=True, group_ids=set())
IT = ViewerCtx(full_view=False, is_admin=False, group_ids={"g_it"})
SGL = ViewerCtx(full_view=False, is_admin=False, group_ids={"g_sgl"})
OUT = ViewerCtx(full_view=False, is_admin=False, group_ids=set())

VALUES = {"base.name": "Max", "it.host": "PC-1", "personal.salary": "50k"}


def test_shared_field_visible_to_all():
    for ctx in (FULL, ADMIN, IT, SGL, OUT):
        assert can_see_field(FIELDS["base.name"], ctx)


def test_group_restricted_field():
    assert can_see_field(FIELDS["it.host"], IT)
    assert can_see_field(FIELDS["it.host"], FULL)   # Vollsicht sieht nicht-vertrauliche
    assert not can_see_field(FIELDS["it.host"], OUT)
    assert not can_see_field(FIELDS["it.host"], SGL)


def test_confidential_hard_gate():
    # Vollsicht hilft NICHT bei vertraulich; nur Gruppe oder Admin-Fallback
    assert not can_see_field(FIELDS["personal.salary"], FULL)
    assert can_see_field(FIELDS["personal.salary"], SGL)
    assert can_see_field(FIELDS["personal.salary"], ADMIN)
    assert not can_see_field(FIELDS["personal.salary"], IT)


def test_filter_values_per_viewer():
    assert filter_values(DEFN, VALUES, ADMIN) == VALUES                       # Admin: alles
    assert filter_values(DEFN, VALUES, FULL) == {"base.name": "Max", "it.host": "PC-1"}  # kein salary
    assert filter_values(DEFN, VALUES, IT) == {"base.name": "Max", "it.host": "PC-1"}
    assert filter_values(DEFN, VALUES, SGL) == {"base.name": "Max", "personal.salary": "50k"}
    assert filter_values(DEFN, VALUES, OUT) == {"base.name": "Max"}


def test_filter_default_deny_without_defn():
    assert filter_values(None, VALUES, ADMIN) == {}


def test_regression_restricted_viewer_never_sees_confidential_or_foreign():
    # IT-Mitglied: darf salary (vertraulich, g_sgl) NIE sehen – unter keinem Key
    filtered = filter_values(DEFN, VALUES, IT)
    assert "personal.salary" not in filtered
    assert "50k" not in filtered.values()
    # Außenstehende sehen nur das geteilte Feld
    assert set(filter_values(DEFN, VALUES, OUT)) == {"base.name"}


def test_editable_field_keys_by_phase_and_visibility():
    # IT-Mitglied in review: it.host editierbar (sichtbar+editable); base.name readonly;
    # personal.salary nicht sichtbar → nicht editierbar
    assert editable_field_keys(DEFN, REVIEW, IT, VALUES) == {"it.host"}
    # Außenstehende: nichts
    assert editable_field_keys(DEFN, REVIEW, OUT, VALUES) == set()
    # SGL darf salary editieren (sichtbar+editable), it.host nicht (nicht sichtbar)
    assert editable_field_keys(DEFN, REVIEW, SGL, VALUES) == {"personal.salary"}


def test_apply_writes_discards_forbidden():
    stored = {"base.name": "Max", "it.host": "PC-1", "personal.salary": "50k"}
    submitted = {"it.host": "PC-2", "personal.salary": "hack", "base.name": "Evil"}
    merged = apply_writes(DEFN, REVIEW, stored, submitted, IT)
    assert merged["it.host"] == "PC-2"          # erlaubt
    assert merged["personal.salary"] == "50k"   # vertraulich → verworfen, Bestand bleibt
    assert merged["base.name"] == "Max"         # readonly → verworfen, Bestand bleibt
