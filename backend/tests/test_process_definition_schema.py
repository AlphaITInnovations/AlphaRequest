"""Ebene-1: Meta-Schema-Validierung der ProcessDefinition (kein DB-Zugriff)."""

import copy

import pytest
from pydantic import ValidationError

from backend.schemas.process_definition import ProcessDefinition, validate_condition


VALID = {
    "schemaVersion": 1,
    "key": "demo-prozess",
    "name": "Demo-Prozess",
    "fields": [
        {"key": "base.name", "widget": "text", "constraints": {"maxLength": 50}},
        {"key": "fuhrpark.car", "widget": "select", "options": [{"value": "Ja"}, {"value": "Nein"}]},
        {"key": "personal.salary", "widget": "textarea",
         "visibility": {"confidential": True, "visibleToGroups": ["grp_sgl"]}},
        {"key": "eintraege", "widget": "collection", "mode": "append_only",
         "item": [{"key": "text", "widget": "textarea"},
                  {"key": "author", "widget": "server_stamped", "value": "actor"}]},
        {"key": "personal.personal_number", "widget": "server_generated",
         "assign": {"action": "assign_sequence", "counter": "per_company"}},
    ],
    "phases": [
        {"key": "start", "label": "Erstellung", "kind": "start",
         "responsibility": {"kind": "owner"}, "grantsFullView": True,
         "enterStatus": "in_progress",
         "fields": [
             {"ref": "base.name", "required": True},
             {"ref": "personal.salary", "requiredWhen": {"==": ["fuhrpark.car", "Ja"]}},
         ]},
        {"key": "durchfuehrung", "kind": "review", "view": "review",
         "responsibility": {"kind": "departments",
                            "rule": [{"group": "grp_it"},
                                     {"group": "grp_fp", "when": {"==": ["fuhrpark.car", "Ja"]}}]},
         "fields": [{"ref": "base.name", "mode": "readonly",
                     "visibleWhen": {"truthy": "fuhrpark.car"}}],
         "automations": [
             {"id": "rem7", "trigger": {"type": "timer", "after": "P7D", "repeat": "P7D"},
              "action": {"type": "notify", "to": "responsible"}},
         ]},
    ],
}


def test_valid_definition_parses():
    d = ProcessDefinition.model_validate(VALID)
    assert d.key == "demo-prozess"
    assert len(d.phases) == 2
    # `from`-Alias / by_alias-Dump bleibt rund
    assert d.model_dump(by_alias=True)["fields"][0]["key"] == "base.name"


def _invalid(mutate):
    bad = copy.deepcopy(VALID)
    mutate(bad)
    with pytest.raises(ValidationError):
        ProcessDefinition.model_validate(bad)


def test_duplicate_field_keys():
    _invalid(lambda d: d["fields"].append({"key": "base.name", "widget": "text"}))


def test_fieldref_must_exist_in_catalog():
    _invalid(lambda d: d["phases"][0]["fields"].append({"ref": "does.not.exist"}))


def test_exactly_one_start_phase():
    _invalid(lambda d: d["phases"][1].__setitem__("kind", "start"))


def test_start_phase_must_be_first():
    def mut(d):
        d["phases"][0]["kind"] = "task"
        d["phases"][1]["kind"] = "start"
    _invalid(mut)


def test_bad_key_slug():
    _invalid(lambda d: d.__setitem__("key", "Nicht Erlaubt!"))


def test_server_generated_needs_assign():
    _invalid(lambda d: d["fields"].append({"key": "x", "widget": "server_generated"}))


def test_collection_needs_item():
    _invalid(lambda d: d["fields"].append({"key": "liste", "widget": "collection"}))


def test_confidential_needs_groups():
    _invalid(lambda d: d["fields"][2]["visibility"].__setitem__("visibleToGroups", []))


def test_unknown_top_level_key_rejected():
    _invalid(lambda d: d.__setitem__("bogus", 123))


def test_unsupported_schema_version():
    _invalid(lambda d: d.__setitem__("schemaVersion", 99))


def test_malformed_dsl_in_fieldref():
    _invalid(lambda d: d["phases"][0]["fields"][0].__setitem__("requiredWhen", {"==": ["only-one"]}))


# ── DSL direkt ────────────────────────────────────────────────────────────────

def test_validate_condition_accepts_wellformed():
    validate_condition({"==": ["a.b", "x"]})
    validate_condition({"truthy": "a.b"})
    validate_condition({"in": ["a.b", ["x", "y"]]})
    validate_condition({"and": [{"truthy": "a"}, {"not": {"==": ["b", 1]}}]})


@pytest.mark.parametrize("bad", [
    {"==": ["a"]},                 # falsche Arität
    {"in": ["a", "notalist"]},     # in braucht Liste
    {"truthy": 5},                 # ref muss String sein
    {"and": []},                   # leere Liste
    {"unknown": [1]},              # unbekannter Operator
    {"==": ["a", 1], "or": []},    # zwei Operatoren
    "notadict",
])
def test_validate_condition_rejects_malformed(bad):
    with pytest.raises(ValueError):
        validate_condition(bad)
