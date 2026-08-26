"""Ebene-1: Condition-DSL-Auswertung, Zwei-Pass-Validierung, Phasen-Runtime."""

import copy

from backend.schemas.process_definition import ProcessDefinition
from backend.services.condition_dsl import evaluate
from backend.services import process_validation as pv
from backend.services import process_runtime as pr


DEFN_DICT = {
    "schemaVersion": 1, "key": "demo", "name": "Demo",
    "fields": [
        {"key": "base.name", "widget": "text", "constraints": {"maxLength": 5}},
        {"key": "base.age", "widget": "number", "constraints": {"min": 18}},
        {"key": "fuhrpark.car", "widget": "select", "options": [{"value": "Ja"}, {"value": "Nein"}]},
        {"key": "extra.note", "widget": "textarea"},
    ],
    "phases": [
        {"key": "start", "kind": "start", "responsibility": {"kind": "owner"},
         "fields": [
             {"ref": "base.name", "required": True},
             {"ref": "extra.note", "requiredWhen": {"==": ["fuhrpark.car", "Ja"]}},
         ],
         "constraints": [{"when": {"truthy": "base.name"}, "message": "Name nötig"}]},
        {"key": "review", "kind": "review",
         "responsibility": {"kind": "departments",
                            "rule": [{"group": "g_it"},
                                     {"group": "g_fp", "when": {"==": ["fuhrpark.car", "Ja"]}}]},
         "fields": [{"ref": "base.name", "mode": "readonly"}]},
    ],
}


def _defn():
    return ProcessDefinition.model_validate(copy.deepcopy(DEFN_DICT))


# ── DSL ─────────────────────────────────────────────────────────────────────

def test_dsl_basics():
    v = {"fuhrpark.car": "Ja", "it.datev": True}
    assert evaluate({"==": ["fuhrpark.car", "Ja"]}, v) is True
    assert evaluate({"!=": ["fuhrpark.car", "Nein"]}, v) is True
    assert evaluate({"truthy": "it.datev"}, v) is True
    assert evaluate({"truthy": "missing"}, v) is False
    assert evaluate({"in": ["fuhrpark.car", ["Ja", "Vielleicht"]]}, v) is True
    assert evaluate({"and": [{"truthy": "it.datev"}, {"==": ["fuhrpark.car", "Ja"]}]}, v) is True
    assert evaluate({"or": [{"truthy": "missing"}, {"==": ["fuhrpark.car", "Nein"]}]}, v) is False
    assert evaluate({"not": {"truthy": "missing"}}, v) is True


# ── Pass 1 ──────────────────────────────────────────────────────────────────

def test_pass1_unknown_field_rejected():
    errs = pv.validate_values(_defn(), {"nope.field": "x"})
    assert errs and errs[0]["code"] == "UNKNOWN_FIELD"


def test_pass1_type_and_constraints():
    d = _defn()
    assert any(e["code"] == "TYPE" for e in pv.validate_values(d, {"base.age": "not-a-number"}))
    assert any(e["code"] == "MAX_LENGTH" for e in pv.validate_values(d, {"base.name": "toolong"}))
    assert any(e["code"] == "MIN" for e in pv.validate_values(d, {"base.age": 12}))
    assert any(e["code"] == "OPTION" for e in pv.validate_values(d, {"fuhrpark.car": "Vielleicht"}))
    assert pv.validate_values(d, {"base.name": "ok", "base.age": 30, "fuhrpark.car": "Ja"}) == []


def test_pass1_none_allowed():
    assert pv.validate_values(_defn(), {"base.name": None}) == []


# ── Pass 2 ──────────────────────────────────────────────────────────────────

def test_pass2_required_and_conditional():
    d = _defn()
    start = d.phases[0]
    # base.name fehlt → required-Fehler; extra.note nur pflicht, wenn car==Ja
    errs = pv.validate_phase_completion(d, start, {"fuhrpark.car": "Ja"})
    codes = {(e["path"], e["code"]) for e in errs}
    assert ("base.name", "REQUIRED") in codes
    assert ("extra.note", "REQUIRED") in codes
    # car != Ja → extra.note nicht pflicht
    errs2 = pv.validate_phase_completion(d, start, {"base.name": "ok", "fuhrpark.car": "Nein"})
    assert errs2 == []


def test_pass2_phase_constraint():
    d = _defn()
    errs = pv.validate_phase_completion(d, d.phases[0], {"fuhrpark.car": "Nein"})
    # base.name leer → sowohl REQUIRED als auch die CONSTRAINT (truthy base.name) schlagen an
    assert any(e["code"] == "CONSTRAINT" for e in errs)


# ── Runtime ─────────────────────────────────────────────────────────────────

def test_initial_runtime():
    rt = pr.initial_runtime(_defn(), "2026-08-07T10:00:00+00:00")
    assert rt["current_index"] == 0
    assert rt["phases"][0]["status"] == "open"
    assert rt["phases"][0]["entered_at"] == "2026-08-07T10:00:00+00:00"
    assert rt["phases"][1]["status"] == "pending"
    assert rt["epoch"] == 0 and rt["rejected"] is False


def test_advance_through_and_archive():
    d = _defn()
    rt = pr.initial_runtime(d, "t0")
    rt, status = pr.advance(d, rt, "t1")
    assert rt["current_index"] == 1
    assert rt["phases"][0]["status"] == "done"
    assert rt["phases"][1]["status"] == "open" and rt["phases"][1]["entered_at"] == "t1"
    assert status == "in_request"       # review-Phase
    rt, status = pr.advance(d, rt, "t2")
    assert status == "archived" and pr.is_terminal(rt)


def test_resolve_responsibility_conditional_departments():
    d = _defn()
    review = d.phases[1]
    r_yes = pr.resolve_responsibility(review, {"fuhrpark.car": "Ja"})
    groups_yes = {x["group"] for x in r_yes["departments"]}
    assert groups_yes == {"g_it", "g_fp"}
    r_no = pr.resolve_responsibility(review, {"fuhrpark.car": "Nein"})
    groups_no = {x["group"] for x in r_no["departments"]}
    assert groups_no == {"g_it"}


def test_enter_status_default_and_override():
    d = _defn()
    assert pr.enter_status_for(d.phases[1]) == "in_request"   # review
    assert pr.enter_status_for(d.phases[0]) == "in_progress"  # start/kein Override


# ── on_department_done: blockierende vs. nicht-blockierende directus_write ────

def _dept_defn(on_error):
    return ProcessDefinition.model_validate({
        "schemaVersion": 1, "key": "d", "name": "D",
        "fields": [{"key": "a", "widget": "text"}, {"key": "mid", "widget": "text"}],
        "phases": [
            {"key": "start", "kind": "start", "responsibility": {"kind": "owner"},
             "fields": [{"ref": "a"}]},
            {"key": "rev", "kind": "review",
             "responsibility": {"kind": "departments", "rule": [{"group": "g_it"}]},
             "fields": [{"ref": "a", "mode": "readonly"}],
             "automations": [{"id": "anlegen",
                "trigger": {"type": "on_department_done", "group": "g_it"},
                "action": {"type": "directus_write", "directus": {
                    "operation": "create", "collection": "m", "idField": "mid",
                    "onError": on_error,
                    "fieldMap": [{"source": "a", "target": "name"}]}}}]},
        ],
    })


def test_run_department_done_blocking_propagates(monkeypatch):
    import pytest
    from backend.services import process_engine as engine
    from backend.services import directus_client as dc
    defn = _dept_defn("block")
    row = {"id": 1, "values": {}, "runtime": {}}
    monkeypatch.setattr(engine, "_audit_fired", lambda *a, **k: None)

    def boom(action, r, d, p, sender=None):
        raise dc.DirectusError("down")

    monkeypatch.setattr(engine.actions, "run_action", boom)
    with pytest.raises(dc.DirectusError):
        engine.run_department_done_blocking(row, defn, defn.phases[1], "g_it")


def test_run_department_done_blocking_returns_changes(monkeypatch):
    from backend.services import process_engine as engine
    defn = _dept_defn("block")
    row = {"id": 1, "values": {}, "runtime": {}}
    monkeypatch.setattr(engine, "_audit_fired", lambda *a, **k: None)
    monkeypatch.setattr(engine.actions, "run_action",
                        lambda action, r, d, p, sender=None: {"values": {"mid": "42"}})
    assert engine.run_department_done_blocking(
        row, defn, defn.phases[1], "g_it") == {"values": {"mid": "42"}}


def test_run_department_done_skips_blocking(monkeypatch):
    # Die NICHT-blockierende Runde darf die blockierende Automation NICHT feuern
    # (die lief bereits im synchronen Blockier-Pfad).
    from backend.services import process_engine as engine
    defn = _dept_defn("block")
    row = {"id": 1, "values": {}, "runtime": {}}
    fired = []
    monkeypatch.setattr(engine, "fire",
                        lambda a, r, d, p, occurrence=None: fired.append(a.id) or False)
    engine.run_department_done(row, defn, defn.phases[1], "g_it")
    assert fired == []


def test_run_department_done_fires_nonblocking(monkeypatch):
    from backend.services import process_engine as engine
    defn = _dept_defn("continue")     # nicht blockierend → normale Runde feuert
    row = {"id": 1, "values": {}, "runtime": {}}
    fired = []
    monkeypatch.setattr(engine, "fire",
                        lambda a, r, d, p, occurrence=None: fired.append(a.id) or False)
    engine.run_department_done(row, defn, defn.phases[1], "g_it")
    assert fired == ["anlegen"]
