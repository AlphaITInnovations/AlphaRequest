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

# Neues Format: Basisdaten in eigenem 'base'-Block; personal nur noch HR-Felder.
DESC = {
    "base": {
        "salutation": "Frau", "first_name": "Anna", "last_name": "Muster",
        "contract_company": "Alpha", "location": "Berlin", "cost_center": "CC-1",
    },
    "personal": {
        "title": "Leiterin", "start_date": "2026-01-01",
        "personal_number": "12345", "private_street": "Weg 1",
        "department": "IT", "department_other": "",
    },
    "it": {"appearance_company": "Alpha", "software": {"datev": True}},
    "fuhrpark": {"car": "Ja", "car_class": "M"},
    "_next_assignee": {"id": "u-next", "name": "Next"},
}


def _ticket(owner_id="owner-1", phases=None, status="in_progress"):
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
        id=1,
        ticket_type=TicketType.zugang_beantragen,
        owner_id=owner_id,
        status=status,
        description=json.dumps(DESC),
        workflow_state_parsed=wf,
    )


@pytest.fixture(autouse=True)
def _mock_groups(monkeypatch):
    monkeypatch.setattr(tv, "get_groups", lambda: GROUPS)
    members = {
        "it-user": ["g-it"],
        "hr-user": ["g-hr"],
        "backoffice-user": ["g-backoffice"],
        "stranger": ["g-other"],
        "owner-1": [],
    }
    monkeypatch.setattr(tv, "get_group_ids_for_user", lambda uid: members.get(uid, []))
    monkeypatch.setattr(tv, "is_watcher", lambda tid, uid: False)


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
    assert tv.is_full_view(_ticket(), _user("backoffice-user")) is True


def test_restricted_for_department_member():
    assert tv.is_full_view(_ticket(), _user("it-user")) is False


# ── filter_description (neues base-Format) ─────────────────────────────────────────

def test_it_member_sees_base_plus_it_only():
    out = tv.filter_description(_ticket(), _user("it-user"), DESC)
    # Basisdaten-Block komplett
    assert out["base"]["first_name"] == "Anna"
    assert out["base"]["cost_center"] == "CC-1"
    assert out["base"]["salutation"] == "Frau"
    # IT-Abschnitt komplett
    assert out["it"]["software"]["datev"] is True
    # NICHT sichtbar:
    assert "personal" not in out          # HR-Block
    assert "fuhrpark" not in out
    assert "_next_assignee" not in out


def test_hr_member_sees_base_and_full_personal_but_not_it():
    out = tv.filter_description(_ticket(), _user("hr-user"), DESC)
    assert out["base"]["first_name"] == "Anna"
    assert out["personal"]["personal_number"] == "12345"
    assert out["personal"]["title"] == "Leiterin"
    assert "it" not in out
    assert "fuhrpark" not in out


def test_stranger_sees_only_base():
    out = tv.filter_description(_ticket(), _user("stranger"), DESC)
    assert set(out.keys()) == {"base"}


def test_oversight_and_owner_see_everything():
    assert tv.filter_description(_ticket(), _user("x", ["view"]), DESC) == DESC
    assert tv.filter_description(_ticket(owner_id="owner-1"), _user("owner-1"), DESC) == DESC


def test_force_scope_ignores_role():
    # Involviert-Kontext: Rolle/Voll-Sicht wird ignoriert, es zählt nur die Abteilung.
    admin_out = tv.filter_description(_ticket(), _user("x", ["admin"]), DESC, force_scope=True)
    assert set(admin_out.keys()) == {"base"}   # Admin ohne Fachabteilung → nur Basis
    owner_out = tv.filter_description(_ticket(owner_id="owner-1"), _user("owner-1"), DESC, force_scope=True)
    assert set(owner_out.keys()) == {"base"}   # Ersteller ohne Fachabteilung → nur Basis
    it_out = tv.filter_description(_ticket(), _user("it-user"), DESC, force_scope=True)
    assert "it" in it_out and "personal" not in it_out and "fuhrpark" not in it_out


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
    assert "personal" not in parsed
    assert parsed["base"]["first_name"] == "Anna"


def test_is_restricted_viewer():
    assert tv.is_restricted_viewer(_ticket(), _user("it-user")) is True
    assert tv.is_restricted_viewer(_ticket(), _user("x", ["admin"])) is False
    t = _ticket(); t.ticket_type = TicketType.hardware
    assert tv.is_restricted_viewer(t, _user("it-user")) is False


# ── history_visible / Beobachter / archiviert ────────────────────────────────────

def test_history_hidden_for_restricted():
    assert tv.history_visible(_ticket(), _user("it-user")) is False
    assert tv.history_visible(_ticket(), _user("stranger")) is False


def test_history_visible_for_oversight_and_owner():
    assert tv.history_visible(_ticket(), _user("x", ["admin"])) is True
    assert tv.history_visible(_ticket(owner_id="owner-1"), _user("owner-1")) is True
    assert tv.history_visible(_ticket(), None) is True   # interner Aufruf (Admin-Detail)


def test_watcher_has_full_view_and_history(monkeypatch):
    monkeypatch.setattr(tv, "is_watcher", lambda tid, uid: uid == "watch-user")
    assert tv.is_full_view(_ticket(), _user("watch-user")) is True
    assert tv.history_visible(_ticket(), _user("watch-user")) is True
    # sieht auch die volle Beschreibung
    assert tv.filter_description(_ticket(), _user("watch-user"), DESC) == DESC


def test_processor_full_view_only_while_active():
    # aktiv: BackOffice-Bearbeiter sieht alles
    assert tv.is_full_view(_ticket(status="in_progress"), _user("backoffice-user")) is True
    # archiviert/abgelehnt: Bearbeiter-Voll-Sicht fällt weg → eingeschränkt
    assert tv.is_full_view(_ticket(status="archived"), _user("backoffice-user")) is False
    assert tv.is_full_view(_ticket(status="rejected"), _user("backoffice-user")) is False
    # dann sieht der archivierte Bearbeiter nur noch Basis (keine Fachabteilung)
    out = tv.filter_description(_ticket(status="archived"), _user("backoffice-user"), DESC)
    assert set(out.keys()) == {"base"}


# ── Vertrauliche Felder (Einstellung P1): Gehalt/Konditionen nur Personalabteilung ──

DESC_EINSTELLUNG = {
    "base": {"first_name": "Max", "last_name": "Muster"},
    "personal": {"title": "Chef:in", "salary": "5000", "conditions": "30 Tage Urlaub"},
}


def _einstellung(owner_id="owner-1", status="in_progress"):
    return SimpleNamespace(
        id=2, ticket_type=TicketType.einstellung, owner_id=owner_id, status=status,
        description=json.dumps(DESC_EINSTELLUNG),
        workflow_state_parsed={"phases": [{"key": "erstellung", "type": "creation"}],
                               "current_phase_index": 0},
    )


def test_confidential_visible_to_personalabteilung():
    out = tv.filter_description(_einstellung(), _user("hr-user"), DESC_EINSTELLUNG)
    assert out["personal"]["salary"] == "5000"
    assert out["personal"]["conditions"] == "30 Tage Urlaub"


def test_confidential_hidden_from_owner_and_others():
    # Selbst Ersteller (Voll-Sicht) und fremde sehen Gehalt/Konditionen NICHT,
    # der Rest (Basis + Titel) bleibt sichtbar (kein normaler Spec für einstellung).
    for uid in ("owner-1", "stranger", "it-user"):
        out = tv.filter_description(_einstellung(), _user(uid), DESC_EINSTELLUNG)
        assert "salary" not in out["personal"]
        assert "conditions" not in out["personal"]
        assert out["personal"]["title"] == "Chef:in"
        assert out["base"]["first_name"] == "Max"


def test_confidential_visible_to_admin_and_internal():
    admin_out = tv.filter_description(_einstellung(), _user("x", ["admin"]), DESC_EINSTELLUNG)
    assert admin_out["personal"]["salary"] == "5000"
    internal = tv.filter_description(_einstellung(), None, DESC_EINSTELLUNG)   # z.B. Admin-Detail
    assert internal["personal"]["salary"] == "5000"


def test_confidential_string_variant_strips_for_non_hr():
    s = tv.filter_description_str(_einstellung(), _user("owner-1"), json.dumps(DESC_EINSTELLUNG))
    parsed = json.loads(s)
    assert "salary" not in parsed["personal"]
    assert parsed["personal"]["title"] == "Chef:in"


def test_preserve_confidential_on_write():
    old = {"personal": {"title": "Chef", "salary": "5000", "conditions": "X"}}
    new = {"personal": {"title": "Chef 2", "salary": "", "conditions": ""}}
    # Nicht-HR: Gehalt/Konditionen bleiben erhalten, Titel darf geändert werden.
    merged = tv.preserve_confidential(_einstellung(), _user("owner-1"), new, old)
    assert merged["personal"]["salary"] == "5000"
    assert merged["personal"]["conditions"] == "X"
    assert merged["personal"]["title"] == "Chef 2"
    # HR darf die vertraulichen Felder ändern.
    merged_hr = tv.preserve_confidential(_einstellung(), _user("hr-user"), new, old)
    assert merged_hr["personal"]["salary"] == ""
