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


def test_server_generated_braucht_bekannten_nummernkreis():
    """Die Laufzeit setzt server_generated jetzt um. Abgelehnt wird nur noch, was
    sie NICHT ausführen kann – hier ein erfundener Nummernkreis."""
    _invalid(lambda d: d["fields"].append(
        {"key": "x", "widget": "server_generated",
         "assign": {"action": "assign_sequence", "counter": "gibtsnicht"}}))


def test_server_generated_braucht_phase_und_firmenfeld():
    """Ohne Phase bekäme das Feld nie eine Nummer (die Vergabe hängt am Abschluss
    der ersten Phase, die es führt); ohne Firmen-Bezug scheitert sie zur Laufzeit."""
    _invalid(lambda d: d["fields"].append(
        {"key": "x", "widget": "server_generated",
         "assign": {"action": "assign_sequence", "counter": "personalnummer"}}))


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


def _base(**over):
    d = {
        "schemaVersion": 1, "key": "k", "name": "N",
        "fields": [{"key": "a", "widget": "text"}, {"key": "b", "widget": "text"}],
        "phases": [{"key": "start", "kind": "start", "responsibility": {"kind": "owner"},
                    "fields": [{"ref": "a"}]}],
    }
    d.update(over)
    return d


def _reject(d):
    with pytest.raises(ValidationError):
        ProcessDefinition.model_validate(d)


def test_dsl_ref_must_exist_in_catalog():
    d = _base()
    d["phases"][0]["fields"] = [{"ref": "a", "requiredWhen": {"==": ["ghost", "x"]}}]
    _reject(d)


def test_computed_from_must_exist():
    _reject(_base(fields=[{"key": "a", "widget": "text", "computed": {"from": "ghost"}}]))


def test_non_overridable_computed_not_editable():
    d = _base(fields=[{"key": "a", "widget": "text"},
                      {"key": "c", "widget": "text", "computed": {"from": "a"}}])  # overridable default False
    d["phases"][0]["fields"] = [{"ref": "c", "mode": "editable"}]
    _reject(d)


def test_bad_regex_pattern_rejected():
    _reject(_base(fields=[{"key": "a", "widget": "text", "constraints": {"pattern": "["}}]))


def test_top_level_server_stamped_rejected():
    _reject(_base(fields=[{"key": "a", "widget": "server_stamped"}]))


def test_action_set_status_validated():
    d = _base()
    d["phases"][0]["automations"] = [{"id": "x", "trigger": {"type": "on_enter"},
                                      "action": {"type": "set_status", "value": "bogus"}}]
    _reject(d)


def test_action_notify_requires_to():
    d = _base()
    d["phases"][0]["automations"] = [{"id": "x", "trigger": {"type": "on_enter"},
                                      "action": {"type": "notify"}}]
    _reject(d)


def test_group_reference_detector():
    from backend.database.process_definitions import _refs_group
    d = {
        "fields": [{"key": "x", "visibility": {"visibleToGroups": ["g_sgl"]}}],
        "phases": [{"responsibility": {"kind": "departments", "rule": [{"group": "g_it"}]}},
                   {"responsibility": {"kind": "group", "group": "g_lead"}}],
    }
    assert _refs_group(d, "g_sgl") is True    # Feld-Sichtbarkeit
    assert _refs_group(d, "g_it") is True     # Abteilungs-Regel
    assert _refs_group(d, "g_lead") is True   # Gruppen-Zuständigkeit
    assert _refs_group(d, "g_unknown") is False


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


# ── computed.map + bedingte Layout-Notiz (Position → Fahrzeuggruppe) ──────────

def test_computed_map_accepted():
    """computed darf zusätzlich zu `from` ein Lookup-`map` tragen."""
    d = copy.deepcopy(VALID)
    d["fields"].append({"key": "gruppe", "widget": "text",
                        "computed": {"from": "fuhrpark.car", "map": {"Ja": "G1"}}})
    d["phases"][0]["fields"].append({"ref": "gruppe", "mode": "readonly"})
    defn = ProcessDefinition.model_validate(d)
    g = next(f for f in defn.fields if f.key == "gruppe")
    assert g.computed.map == {"Ja": "G1"}


def test_title_template_valid():
    d = copy.deepcopy(VALID)
    d["titleTemplate"] = "Demo – {{base.name}} ({{erstellt}})"
    ProcessDefinition.model_validate(d)   # {{erstellt}} + Katalog-Feld sind erlaubt


def test_title_template_unknown_ref_rejected():
    d = copy.deepcopy(VALID)
    d["titleTemplate"] = "{{gibtsnicht}}"
    with pytest.raises(ValidationError):
        ProcessDefinition.model_validate(d)


def test_title_template_reserved_id_rejected():
    d = copy.deepcopy(VALID)
    d["titleTemplate"] = "#{{id}} {{base.name}}"   # id ist beim Anlegen noch nicht vergeben
    with pytest.raises(ValidationError):
        ProcessDefinition.model_validate(d)


def test_title_template_collection_field_rejected():
    d = copy.deepcopy(VALID)
    d["titleTemplate"] = "{{eintraege}}"           # collection lässt sich nicht als Titel setzen
    with pytest.raises(ValidationError):
        ProcessDefinition.model_validate(d)


def _defn_with_document(bindings):
    d = copy.deepcopy(VALID)
    d["phases"].append({
        "key": "vertrag", "kind": "task", "view": "document",
        "responsibility": {"kind": "owner"},
        "document": {"title": "Vertrag", "filename": "Vertrag_{{base.name}}",
                     "bindings": bindings}})
    return d


def test_document_bindings_valid():
    ProcessDefinition.model_validate(_defn_with_document({"name": "base.name"}))


def test_document_bindings_unknown_field_rejected():
    with pytest.raises(ValidationError):
        ProcessDefinition.model_validate(_defn_with_document({"name": "gibtsnicht"}))


def test_document_bindings_collection_field_rejected():
    with pytest.raises(ValidationError):     # eintraege ist eine collection
        ProcessDefinition.model_validate(_defn_with_document({"eintr": "eintraege"}))


def test_document_binding_today_source_valid():
    # @today ist kein Katalog-Feld, aber als Sonderquelle erlaubt.
    ProcessDefinition.model_validate(_defn_with_document({"heute": {"field": "@today"}}))


def test_document_binding_offset_und_string_coercion():
    d = ProcessDefinition.model_validate(_defn_with_document(
        {"a": "base.name", "b": {"field": "base.name", "offset": -20}}))
    doc = next(p for p in d.phases if p.key == "vertrag").document
    assert doc.bindings["a"].field == "base.name" and doc.bindings["a"].offset is None
    assert doc.bindings["b"].field == "base.name" and doc.bindings["b"].offset == -20


def test_computed_map_on_number_source_rejected():
    """map arbeitet mit Zeichenketten-Schlüsseln – ein Zahlen-Quellfeld ist nicht
    unterstützt (Backend/Frontend würden sonst auseinanderlaufen)."""
    d = copy.deepcopy(VALID)
    d["fields"].append({"key": "stufe", "widget": "number"})
    d["fields"].append({"key": "label", "widget": "text",
                        "computed": {"from": "stufe", "map": {"1": "Junior"}}})
    d["phases"][0]["fields"] += [{"ref": "stufe"}, {"ref": "label", "mode": "readonly"}]
    with pytest.raises(ValidationError):
        ProcessDefinition.model_validate(d)


def _defn_with_note(visible_when):
    return {
        "schemaVersion": 1, "key": "k", "name": "N",
        "fields": [{"key": "base.name", "widget": "text"}],
        "phases": [{"key": "start", "kind": "start", "responsibility": {"kind": "owner"},
                    "fields": [{"ref": "base.name"}],
                    "layout": [{"type": "section", "title": "S", "items": [
                        {"type": "field", "ref": "base.name"},
                        {"type": "note", "text": "Hinweis", "visibleWhen": visible_when},
                    ]}]}],
    }


def test_layout_note_visible_when_valid():
    ProcessDefinition.model_validate(_defn_with_note({"truthy": "base.name"}))


def test_layout_note_visible_when_unknown_ref_rejected():
    with pytest.raises(ValidationError):    # Referenz nicht im Katalog
        ProcessDefinition.model_validate(_defn_with_note({"truthy": "gibtsnicht"}))


def test_layout_note_visible_when_malformed_rejected():
    with pytest.raises(ValidationError):    # kaputte DSL-Struktur
        ProcessDefinition.model_validate(_defn_with_note({"kaputt": 1}))
