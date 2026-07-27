"""Wiedereröffnungs-Logik (build_reopened_workflow in workflow_state.py)."""

import copy

import pytest

from backend.models.models import RequestStatus
from backend.services.workflow_state import build_reopened_workflow


def _archived_onboarding_wf() -> dict:
    """Archivierter Onboarding-Workflow: alle Phasen done, Index hinter dem Ende."""
    return {
        "current_phase_index": 5,
        "phases": [
            {"key": "erstellung", "label": "Erstellung", "type": "creation", "status": "done"},
            {"key": "freigabe", "label": "Freigabe", "type": "assignment", "status": "done",
             "responsibility": {"kind": "group", "id": "g-frei", "name": "Freigabe"}},
            {"key": "backoffice", "label": "BackOffice", "type": "assignment", "status": "done",
             "responsibility": {"kind": "group", "id": "g-bo", "name": "Sekretariat GL"}},
            {"key": "bearbeitung", "label": "Bearbeitung", "type": "assignment", "status": "done",
             "responsibility": {"kind": "user", "id": "u1", "name": "Chef"}},
            {"key": "durchfuehrung", "label": "Durchführung", "type": "department_review", "status": "done",
             "departments": {
                 "g-it": {"name": "IT", "required": True, "status": "done"},
                 "g-fp": {"name": "Fuhrpark", "required": True, "status": "done"},
             }},
        ],
    }


# ── Durchführung (department_review) ───────────────────────────────────────────

def test_reopen_into_department_review_single_department():
    wf = _archived_onboarding_wf()
    new_wf, new_status = build_reopened_workflow(
        wf, 4, departments={"g-it": "open", "g-fp": "done"},
    )
    assert new_status == RequestStatus.in_request.value
    assert new_wf["current_phase_index"] == 4
    # Phasen davor done, Ziel aktiv
    assert [p["status"] for p in new_wf["phases"][:4]] == ["done"] * 4
    assert new_wf["phases"][4]["status"] == "in_progress"
    # Genau IT wieder offen, Fuhrpark bleibt erledigt
    depts = new_wf["phases"][4]["departments"]
    assert depts["g-it"]["status"] == "open"
    assert depts["g-fp"]["status"] == "done"


def test_reopen_department_requires_at_least_one_open():
    wf = _archived_onboarding_wf()
    with pytest.raises(ValueError, match="mindestens eine|Mindestens eine"):
        build_reopened_workflow(wf, 4, departments={"g-it": "done", "g-fp": "done"})


def test_reopen_department_unspecified_stay_unchanged():
    wf = _archived_onboarding_wf()
    # Nur IT angeben → Fuhrpark behält seinen bisherigen Status (done)
    new_wf, _ = build_reopened_workflow(wf, 4, departments={"g-it": "open"})
    depts = new_wf["phases"][4]["departments"]
    assert depts["g-it"]["status"] == "open"
    assert depts["g-fp"]["status"] == "done"


def test_reopen_department_unknown_group_raises():
    wf = _archived_onboarding_wf()
    with pytest.raises(ValueError, match="nicht Teil"):
        build_reopened_workflow(wf, 4, departments={"g-unknown": "open"})


def test_reopen_department_invalid_status_raises():
    wf = _archived_onboarding_wf()
    with pytest.raises(ValueError, match="open.*done|'open' oder 'done'"):
        build_reopened_workflow(wf, 4, departments={"g-it": "skipped"})


# ── Bearbeitungsphase (assignment) ─────────────────────────────────────────────

def test_reopen_into_assignment_with_responsibility():
    wf = _archived_onboarding_wf()
    resp = {"kind": "user", "id": "u2", "name": "Neuer Chef"}
    new_wf, new_status = build_reopened_workflow(wf, 3, responsibility=resp)
    assert new_status == RequestStatus.in_progress.value
    assert new_wf["current_phase_index"] == 3
    assert [p["status"] for p in new_wf["phases"][:3]] == ["done"] * 3
    assert new_wf["phases"][3]["status"] == "in_progress"
    assert new_wf["phases"][4]["status"] == "pending"       # danach zurückgesetzt
    assert new_wf["phases"][3]["responsibility"] == resp


def test_reopen_into_assignment_respects_enter_status():
    # Phase mit erzwungenem Eintritts-Status (z.B. Einstellung 'vertragsruecklauf')
    # behält diesen auch beim Wiedereröffnen (nicht in_progress).
    wf = _archived_onboarding_wf()
    wf["phases"][3]["enter_status"] = "waiting_contract"
    _, new_status = build_reopened_workflow(wf, 3, responsibility={"kind": "group", "id": "g", "name": "SGL"})
    assert new_status == "waiting_contract"


def test_reopen_into_assignment_keeps_existing_responsibility_if_none_given():
    wf = _archived_onboarding_wf()
    new_wf, _ = build_reopened_workflow(wf, 1)   # Freigabe hat bereits eine Gruppe
    assert new_wf["phases"][1]["responsibility"]["id"] == "g-frei"


def test_reopen_into_assignment_without_any_responsibility_raises():
    wf = _archived_onboarding_wf()
    # Bearbeitung-Phase ohne Zuständigkeit vorbereiten
    wf["phases"][3].pop("responsibility")
    with pytest.raises(ValueError, match="Zuständigkeit"):
        build_reopened_workflow(wf, 3)


# ── Allgemein ──────────────────────────────────────────────────────────────────

def test_reopen_into_creation_phase_raises():
    wf = _archived_onboarding_wf()
    with pytest.raises(ValueError, match="nicht wiedereröffnet|Bearbeitungs"):
        build_reopened_workflow(wf, 0)   # Index 0 = Erstellung (creation)


def test_reopen_invalid_phase_index_raises():
    wf = _archived_onboarding_wf()
    with pytest.raises(ValueError, match="ungültig|Index"):
        build_reopened_workflow(wf, 99)


def test_reopen_clears_rejected_flag():
    wf = _archived_onboarding_wf()
    wf["rejected"] = {"phase_key": "freigabe", "message": "nope"}
    new_wf, _ = build_reopened_workflow(wf, 4, departments={"g-it": "open"})
    assert "rejected" not in new_wf


def test_reopen_does_not_mutate_input():
    wf = _archived_onboarding_wf()
    original = copy.deepcopy(wf)
    build_reopened_workflow(wf, 4, departments={"g-it": "open"})
    assert wf == original
