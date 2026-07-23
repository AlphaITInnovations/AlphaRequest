"""Feld-genaue Sichtbarkeit der Beschreibung (backend/services/ticket_visibility.py)."""

import json
from types import SimpleNamespace

import pytest

from backend.models.models import TicketType
from backend.services import ticket_visibility as tv


# ── Fixtures / Helfer ────────────────────────────────────────────────────────────

GROUPS = [
    {"id": "g-it", "name": "IT"},
    {"id": "g-fuhrpark", "name": "Fuhrpark"},
    {"id": "g-hr", "name": "Personalabteilung"},
    {"id": "g-backoffice", "name": "Sekretariat GL"},
]

DESC = {
    "personal": {
        "first_name": "Anna", "last_name": "Muster", "title": "Frau",
        "start_date": "2026-01-01", "location": "Berlin", "contract_company": "Alpha",
        "department": "IT", "department_other": "",
        "personal_number": "12345", "cost_center": "CC-1", "private_street": "Weg 1",
    },
    "it": {"appearance_company": "Alpha", "software": {"datev": True}},
    "fuhrpark": {"car": "Ja", "car_class": "M"},
    "_next_assignee": {"id": "u-next", "name": "Next"},
}


def _ticket(owner_id="owner-1", phases=None):
    wf = {"phases": phases if phases is not None else [
        {"key": "erstellung", "type": "creation"},
        {"key": "backoffice", "type": "assignment",
         "responsibility": {"kind": "group", "id": "g-backoffice", "name": "Sekretariat GL"}},
        {"key": "durchfuehrung", "type": "department_review",
         "departments": {"g-it": {"name": "IT", "required": True, "status": "open"},
                         "g-fuhrpark": {"name": "Fuhrpark", "required": True, "status": "open"},
                         "g-hr": {"name": "Personalabteilung", "required": True, "status": "open"}}},
    ]}
    return SimpleNamespace(
        ticket_type=TicketType.zugang_beantragen,
        owner_id=owner_id,
        description=json.dumps(DESC),
        workflow_state_parsed=wf,
    )


@pytest.fixture(autouse=True)
def _mock_groups(monkeypatch):
    monkeypatch.setattr(tv, "get_groups", lambda: GROUPS)
    # user-id -> gruppen
    members = {
        "it-user": ["g-it"],
        "hr-user": ["g-hr"],
        "backoffice-user": ["g-backoffice"],
        "stranger": ["g-other"],
        "owner-1": [],
    }
    monkeypatch.setattr(tv, "get_group_ids_for_user", lambda uid: members.get(uid, []))


def _user(uid, perms=None):
    return {"id": uid, "permissions": perms or []}


# ── is_full_view ──────────────────────────────────────────────────────────────────

def test_full_view_for_oversight():
    assert tv.is_full_view(_ticket(), _user("x", ["view"])) is True
    assert tv.is_full_view(_ticket(), _user("x", ["manage"])) is True
    assert tv.is_full_view(_ticket(), _user("x", ["admin"])) is True


def test_full_view_for_owner():
    assert tv.is_full_view(_ticket(owner_id="owner-1"), _user("owner-1")) is True


def test_full_view_for_assignment_group():
    # Mitglied der BackOffice-Gruppe = verarbeitende Assignment-Phase → voll
    assert tv.is_full_view(_ticket(), _user("backoffice-user")) is True


def test_restricted_for_department_member():
    assert tv.is_full_view(_ticket(), _user("it-user")) is False


# ── filter_description ──────────────────────────────────────────────────────────────

def test_it_member_sees_base_plus_it_only():
    out = tv.filter_description(_ticket(), _user("it-user"), DESC)
    # Basisfelder
    assert out["personal"]["first_name"] == "Anna"
    assert out["personal"]["location"] == "Berlin"
    # IT-Abschnitt komplett
    assert out["it"]["software"]["datev"] is True
    # NICHT sichtbar:
    assert "personal_number" not in out["personal"]
    assert "cost_center" not in out["personal"]
    assert "private_street" not in out["personal"]
    assert "fuhrpark" not in out
    assert "_next_assignee" not in out


def test_hr_member_sees_full_personal_but_not_it():
    out = tv.filter_description(_ticket(), _user("hr-user"), DESC)
    assert out["personal"]["personal_number"] == "12345"
    assert out["personal"]["cost_center"] == "CC-1"
    assert "it" not in out
    assert "fuhrpark" not in out


def test_stranger_sees_only_base():
    out = tv.filter_description(_ticket(), _user("stranger"), DESC)
    assert set(out.keys()) == {"personal"}
    assert "personal_number" not in out["personal"]


def test_oversight_and_owner_see_everything():
    assert tv.filter_description(_ticket(), _user("x", ["view"]), DESC) == DESC
    assert tv.filter_description(_ticket(owner_id="owner-1"), _user("owner-1"), DESC) == DESC


def test_unknown_type_is_passthrough():
    t = _ticket()
    t.ticket_type = TicketType.hardware   # kein VISIBILITY-Eintrag
    assert tv.filter_description(t, _user("it-user"), DESC) == DESC


def test_no_user_is_passthrough():
    assert tv.filter_description(_ticket(), None, DESC) == DESC


def test_string_variant_filters_and_roundtrips():
    s = tv.filter_description_str(_ticket(), _user("it-user"), json.dumps(DESC))
    parsed = json.loads(s)
    assert "fuhrpark" not in parsed
    assert parsed["personal"]["first_name"] == "Anna"
    assert "personal_number" not in parsed["personal"]


def test_is_restricted_viewer():
    assert tv.is_restricted_viewer(_ticket(), _user("it-user")) is True
    assert tv.is_restricted_viewer(_ticket(), _user("x", ["admin"])) is False
    t = _ticket(); t.ticket_type = TicketType.hardware
    assert tv.is_restricted_viewer(t, _user("it-user")) is False


# ── filter_history ──────────────────────────────────────────────────────────────────

def _history():
    return [
        {"action": "ticket_created", "details": {"priority": "medium"}},
        {"action": "ticket_updated", "details": {"changes": {
            "priority": {"old": "low", "new": "high"},
            "description": {"old": DESC, "new": DESC},
        }}},
    ]


def test_history_redacted_for_restricted():
    out = tv.filter_history(_ticket(), _user("it-user"), _history())
    upd = out[1]["details"]["changes"]
    assert upd["priority"] == {"old": "low", "new": "high"}   # bleibt
    assert upd["description"] == {"redacted": True}            # Werte weg
    assert out[0] == _history()[0]                             # anderes Event unangetastet


def test_history_untouched_for_full_view():
    hist = _history()
    assert tv.filter_history(_ticket(), _user("x", ["admin"]), hist) == hist


def test_history_redacts_any_action_with_description():
    # auch admin_raw_edited (nicht nur ticket_updated) muss redigiert werden
    hist = [{"action": "admin_raw_edited", "details": {"changes": {
        "description": {"old": DESC, "new": DESC},
        "status": {"old": "in_progress", "new": "archived"},
    }}}]
    out = tv.filter_history(_ticket(), _user("it-user"), hist)
    assert out[0]["details"]["changes"]["description"] == {"redacted": True}
    assert out[0]["details"]["changes"]["status"] == {"old": "in_progress", "new": "archived"}
