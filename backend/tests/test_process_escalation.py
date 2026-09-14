"""Eskalation / Erinnerungen pro Phase (§6.1).

Der deklarative `escalation`-Block wird beim Planen in synthetische
Timer-Automationen expandiert; die vorhandene Timer-/Ledger-/Mail-Laufzeit feuert
sie unverändert. Zusätzlich neu: Mehrfach-Empfänger und der Ziel-Typ `user:<id>`
(einzelne Mitarbeiter:innen).
"""
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from backend.schemas.process_definition import (
    Action, ActionType, ESCALATION_AUTO_PREFIX, ProcessDefinition,
    escalation_automations, is_valid_recipient,
)
from backend.services import process_actions as pactions
from backend.services import process_automations as pa
from backend.services import process_runtime as pr


def _defn(escalation, phase_kind="task"):
    """Minimal-Prozess mit einer Phase, die den escalation-Block trägt."""
    return ProcessDefinition.model_validate({
        "key": "demo", "name": "Demo",
        "fields": [{"key": "a", "widget": "text"}],
        "phases": [
            {"key": "start", "kind": "start", "responsibility": {"kind": "owner"},
             "fields": [{"ref": "a"}]},
            {"key": "bearbeitung", "kind": phase_kind,
             "responsibility": {"kind": "group", "group": "g_it"},
             "escalation": escalation,
             "fields": [{"ref": "a", "mode": "readonly"}]},
            {"key": "ende", "kind": "end", "responsibility": {"kind": "owner"}},
        ],
    })


# ── Empfänger-Whitelist ───────────────────────────────────────────────────────

@pytest.mark.parametrize("tok,ok", [
    ("responsible", True), ("owner", True), ("watchers", True),
    ("group:g_it", True), ("user:u_chef", True),
    ("group:", False), ("user:", False), ("user: ", False),
    ("supervisor", False), ("", False), ("chef", False),
])
def test_is_valid_recipient(tok, ok):
    assert is_valid_recipient(tok) is ok


# ── Schema / Validierung ──────────────────────────────────────────────────────

def test_escalation_valid_parses():
    d = _defn({"enabled": True, "stages": [
        {"afterDays": 7, "repeatDays": 7, "recipients": ["responsible", "user:u_chef"]},
        {"afterDays": 14, "recipients": ["group:g_it"], "raisePriority": True, "message": "Dringend"},
    ]})
    esc = d.phases[1].escalation
    assert esc.enabled is True and len(esc.stages) == 2
    assert esc.stages[0].repeatDays == 7 and esc.stages[1].raisePriority is True


@pytest.mark.parametrize("stage", [
    {"afterDays": 0, "recipients": ["owner"]},          # afterDays muss > 0
    {"afterDays": -3, "recipients": ["owner"]},
    {"afterDays": 7, "repeatDays": 0, "recipients": ["owner"]},   # repeatDays muss > 0
    {"afterDays": 7, "recipients": []},                 # kein Empfänger
    {"afterDays": 7, "recipients": ["supervisor"]},     # unbekanntes Ziel
    {"afterDays": 99999, "recipients": ["owner"]},      # unrealistisch groß
])
def test_escalation_stage_invalid(stage):
    with pytest.raises(ValidationError):
        _defn({"enabled": True, "stages": [stage]})


def test_escalation_enabled_without_stages_rejected():
    with pytest.raises(ValidationError):
        _defn({"enabled": True, "stages": []})


def test_escalation_disabled_without_stages_ok():
    d = _defn({"enabled": False, "stages": []})
    assert d.phases[1].escalation.enabled is False


def test_escalation_forbidden_on_end_phase():
    # escalation direkt an der Endphase → abgelehnt
    with pytest.raises(ValidationError):
        ProcessDefinition.model_validate({
            "key": "d", "name": "D", "fields": [{"key": "a", "widget": "text"}],
            "phases": [
                {"key": "start", "kind": "start", "responsibility": {"kind": "owner"},
                 "fields": [{"ref": "a"}]},
                {"key": "ende", "kind": "end", "responsibility": {"kind": "owner"},
                 "escalation": {"enabled": True,
                                "stages": [{"afterDays": 7, "recipients": ["owner"]}]}},
            ],
        })


def test_reserved_automation_prefix_rejected():
    with pytest.raises(ValidationError):
        ProcessDefinition.model_validate({
            "key": "d", "name": "D", "fields": [{"key": "a", "widget": "text"}],
            "phases": [
                {"key": "start", "kind": "start", "responsibility": {"kind": "owner"},
                 "fields": [{"ref": "a"}],
                 "automations": [
                     {"id": f"{ESCALATION_AUTO_PREFIX}start__0",
                      "trigger": {"type": "timer", "after": "P7D"},
                      "action": {"type": "notify", "to": "owner"}}]},
            ],
        })


# ── Action: Mehrfach-Empfänger ────────────────────────────────────────────────

def test_action_recipients_list_valid():
    a = Action.model_validate({"type": "notify", "recipients": ["responsible", "user:u_x"]})
    assert a.recipients == ["responsible", "user:u_x"]


def test_action_notify_needs_a_target():
    with pytest.raises(ValidationError):        # weder to noch recipients
        Action.model_validate({"type": "notify"})


def test_action_recipients_only_for_notify_escalate():
    with pytest.raises(ValidationError):
        Action.model_validate({"type": "set_priority", "value": "high",
                               "recipients": ["owner"]})


def test_action_recipients_rejects_unknown_token():
    with pytest.raises(ValidationError):
        Action.model_validate({"type": "escalate", "recipients": ["supervisor"]})


# ── Expansion ─────────────────────────────────────────────────────────────────

def test_expansion_one_stage_one_timer():
    d = _defn({"enabled": True, "stages": [
        {"afterDays": 7, "repeatDays": 7, "recipients": ["responsible", "user:u_chef"]},
        {"afterDays": 14, "recipients": ["group:g_it"], "raisePriority": True, "message": "Dringend"},
    ]})
    autos = escalation_automations(d.phases[1])
    assert [a.id for a in autos] == [
        f"{ESCALATION_AUTO_PREFIX}bearbeitung__0", f"{ESCALATION_AUTO_PREFIX}bearbeitung__1"]
    a0, a1 = autos
    assert a0.trigger.after == "P7D" and a0.trigger.repeat == "P7D"
    assert a0.action.type == ActionType.notify           # kein raisePriority → notify
    assert a0.action.recipients == ["responsible", "user:u_chef"]
    assert a1.trigger.after == "P14D" and a1.trigger.repeat is None
    assert a1.action.type == ActionType.escalate         # raisePriority → escalate
    assert a1.action.template == "Dringend"


def test_expansion_disabled_is_empty():
    d = _defn({"enabled": False, "stages": [{"afterDays": 7, "recipients": ["owner"]}]})
    assert escalation_automations(d.phases[1]) == []


def test_expansion_no_block_is_empty():
    d = ProcessDefinition.model_validate({
        "key": "d", "name": "D", "fields": [{"key": "a", "widget": "text"}],
        "phases": [{"key": "start", "kind": "start", "responsibility": {"kind": "owner"},
                    "fields": [{"ref": "a"}]}],
    })
    assert escalation_automations(d.phases[0]) == []


# ── Timer-Laufzeit sieht die Eskalation (ohne explizite Automationen) ─────────

ENTERED = "2026-08-01T00:00:00+00:00"


def test_timer_math_picks_up_escalation():
    d = _defn({"enabled": True, "stages": [
        {"afterDays": 7, "repeatDays": 7, "recipients": ["responsible"]},
        {"afterDays": 14, "recipients": ["owner"]},
    ]})
    phase = d.phases[1]
    # frühester nächster Fälligkeitszeitpunkt = 7 Tage nach Eintritt
    nd = pa.compute_next_timer_due(phase, ENTERED, 0, {})
    assert nd == datetime(2026, 8, 8, tzinfo=timezone.utc)
    # nach 21 Tagen: Stufe 0 (7/7) → occ [1,2,3], Stufe 1 (14 one-shot) → [1]
    now = datetime(2026, 8, 22, tzinfo=timezone.utc)
    due = {a.id: occs for a, occs in pa.due_timers(phase, ENTERED, now, 0, {})}
    assert due[f"{ESCALATION_AUTO_PREFIX}bearbeitung__0"] == [1, 2, 3]
    assert due[f"{ESCALATION_AUTO_PREFIX}bearbeitung__1"] == [1]


def test_disabled_escalation_has_no_timer():
    d = _defn({"enabled": False, "stages": [{"afterDays": 7, "recipients": ["owner"]}]})
    assert pa.compute_next_timer_due(d.phases[1], ENTERED, 0, {}) is None


# ── Empfänger-Auflösung: user:<id> + Mehrfach ─────────────────────────────────

GROUPS = [{"id": "g_it", "distributions": ["it@example.org"]}]


def _ticket(defn):
    return {"id": 7, "title": "Testauftrag", "owner_id": "u_owner",
            "status": "in_progress", "values": {},
            "runtime": pr.initial_runtime(defn, "t0", {})}


def test_resolve_user_recipient(monkeypatch):
    monkeypatch.setattr(pactions, "_user_email",
                        lambda uid: "chef@example.org" if uid == "u_chef" else None)
    d = _defn({"enabled": False, "stages": []})
    out = pactions.resolve_recipients("user:u_chef", _ticket(d), d.phases[1], GROUPS)
    assert out == ["chef@example.org"]


def test_resolve_multi_unions_person_and_group(monkeypatch):
    monkeypatch.setattr(pactions, "_user_email",
                        lambda uid: "chef@example.org" if uid == "u_chef" else None)
    d = _defn({"enabled": False, "stages": []})
    t = _ticket(d)
    out = pactions.resolve_recipients_multi(
        ["user:u_chef", "responsible"], t, d.phases[1], GROUPS)
    # responsible = Gruppe g_it (Verteiler) + die Einzelperson
    assert set(out) == {"chef@example.org", "it@example.org"}


def test_resolve_multi_fallback_once(monkeypatch):
    """Kommt insgesamt niemand heraus, greift EINMAL der TICKET_MAIL-Fallback –
    nicht je Token."""
    monkeypatch.setattr(pactions, "_user_email", lambda uid: None)
    monkeypatch.setattr(pactions.config, "TICKET_MAIL", "zentrale@example.org")
    d = _defn({"enabled": False, "stages": []})
    out = pactions.resolve_recipients_multi(
        ["user:weg1", "user:weg2"], _ticket(d), d.phases[1], GROUPS)
    assert out == ["zentrale@example.org"]


def test_resolve_token_strips_id(monkeypatch):
    """Validator (is_valid_recipient) trimmt die ID – der Resolver muss dasselbe
    tun, sonst liefe ein „group: g_it" (Leerzeichen) stumm in den Fallback."""
    monkeypatch.setattr(pactions, "_user_email",
                        lambda uid: "chef@example.org" if uid == "u_chef" else None)
    d = _defn({"enabled": False, "stages": []})
    t = _ticket(d)
    assert pactions.resolve_recipients("group: g_it", t, d.phases[1], GROUPS) == ["it@example.org"]
    assert pactions.resolve_recipients("user: u_chef", t, d.phases[1], GROUPS) == ["chef@example.org"]


def test_resolve_multi_watchers_only_empty_ok(monkeypatch):
    monkeypatch.setattr(pactions, "watcher_emails", lambda tid: [])
    monkeypatch.setattr(pactions.config, "TICKET_MAIL", "zentrale@example.org")
    d = _defn({"enabled": False, "stages": []})
    out = pactions.resolve_recipients_multi(["watchers"], _ticket(d), d.phases[1], GROUPS)
    assert out == []        # niemand beobachtet → gültiges Leerergebnis, kein Fallback


# ── run_action: synthetische Eskalation feuert an alle + Priorität ────────────

def test_run_action_escalate_sends_to_all_and_bumps_priority(monkeypatch):
    monkeypatch.setattr(pactions, "_user_email",
                        lambda uid: "chef@example.org" if uid == "u_chef" else None)
    d = _defn({"enabled": True, "stages": [
        {"afterDays": 7, "recipients": ["responsible", "user:u_chef"], "raisePriority": True},
    ]})
    auto = escalation_automations(d.phases[1])[0]
    sent = []

    def sender(recips, subject, body, kind=None):
        sent.append({"to": recips, "kind": kind})

    changes = pactions.run_action(auto.action, _ticket(d), d, d.phases[1],
                                  sender=sender, groups=GROUPS)
    assert changes.get("priority") == "high"        # escalate stuft hoch
    assert set(sent[0]["to"]) == {"chef@example.org", "it@example.org"}
    assert sent[0]["kind"] == "escalate"


def test_run_action_notify_stage_does_not_bump_priority(monkeypatch):
    monkeypatch.setattr(pactions, "_user_email", lambda uid: None)
    d = _defn({"enabled": True, "stages": [
        {"afterDays": 7, "recipients": ["group:g_it"]},     # notify (kein raisePriority)
    ]})
    auto = escalation_automations(d.phases[1])[0]
    sent = []
    changes = pactions.run_action(
        auto.action, _ticket(d), d, d.phases[1],
        sender=lambda recips, subject, body, kind=None: sent.append(recips), groups=GROUPS)
    assert "priority" not in changes                # reine Erinnerung
    assert sent[0] == ["it@example.org"]
