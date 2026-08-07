"""Regressionen zu den Funden des Backend-Reviews (Stufen 1–5).

Jeder Test hier steht für einen konkret gefundenen Defekt – nicht löschen, ohne
den zugehörigen Fix zu verstehen.
"""
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from backend.schemas.process_definition import ProcessDefinition
from backend.services import process_compute as compute
from backend.services import process_engine as engine
from backend.services import process_visibility as vis
from backend.utils.timeutil import to_db_datetime, utcnow_iso, as_aware_utc


# ── FATAL: tz-behaftete ISO-Strings in DATETIME-Spalten ───────────────────────

def test_db_datetime_never_carries_offset():
    """MariaDB kennt kein Offset-DATETIME-Literal – ein '+00:00' im Wert führt im
    Strict-Mode zu Fehler 1292 und hätte JEDEN Timer stumm lahmgelegt."""
    for value in (utcnow_iso(),
                  "2026-08-29T00:00:00+00:00",
                  "2026-08-29T02:00:00+02:00",
                  datetime(2026, 8, 29, tzinfo=timezone.utc)):
        out = to_db_datetime(value)
        assert "+" not in out and "Z" not in out and "T" not in out
        assert out == datetime.fromisoformat(out).strftime("%Y-%m-%d %H:%M:%S")
    assert to_db_datetime(None) is None


def test_db_datetime_normalises_to_utc():
    # 02:00 Berlin (+02:00) == 00:00 UTC
    assert to_db_datetime("2026-08-29T02:00:00+02:00") == "2026-08-29 00:00:00"


def test_as_aware_utc_treats_naive_as_utc():
    assert as_aware_utc("2026-08-29T00:00:00").tzinfo is not None


# ── Guard wurde validiert, aber nie ausgewertet ──────────────────────────────

def _defn_with_guard(guard):
    return ProcessDefinition.model_validate({
        "schemaVersion": 1, "key": "k", "name": "N",
        "fields": [{"key": "flag", "widget": "checkbox"}],
        "phases": [{"key": "start", "kind": "start", "responsibility": {"kind": "owner"},
                    "fields": [{"ref": "flag"}],
                    "automations": [{"id": "a1", "trigger": {"type": "on_enter"},
                                     "guard": guard,
                                     "action": {"type": "set_priority", "value": "high"}}]}],
    })


def test_guard_blocks_and_allows():
    d_true = _defn_with_guard({"truthy": "flag"})
    assert engine.guard_passes(d_true.phases[0].automations[0], {"values": {"flag": True}}) is True
    assert engine.guard_passes(d_true.phases[0].automations[0], {"values": {"flag": False}}) is False
    # ohne Guard: immer feuern
    d_none = _defn_with_guard(None)
    assert engine.guard_passes(d_none.phases[0].automations[0], {"values": {}}) is True


# ── append_only: Verlaufs-Log darf nicht überschrieben werden ────────────────

APPEND_DEFN = ProcessDefinition.model_validate({
    "schemaVersion": 1, "key": "k", "name": "N",
    "fields": [{"key": "log", "widget": "collection", "mode": "append_only",
                "item": [{"key": "text", "widget": "textarea"},
                         {"key": "author", "widget": "server_stamped", "value": "actor"},
                         {"key": "ts", "widget": "server_stamped", "value": "now"}]}],
    "phases": [{"key": "start", "kind": "start", "responsibility": {"kind": "owner"},
                "fields": [{"ref": "log", "mode": "append_only"}]}],
})
CTX = vis.ViewerCtx(full_view=True, is_admin=True, group_ids=set())


def test_append_only_allows_append():
    stored = {"log": [{"text": "eins"}]}
    merged = vis.apply_writes(APPEND_DEFN, APPEND_DEFN.phases[0], stored,
                              {"log": [{"text": "eins"}, {"text": "zwei"}]}, CTX)
    assert len(merged["log"]) == 2


@pytest.mark.parametrize("attack", [
    [],                                   # alles löschen
    [{"text": "manipuliert"}],            # Bestand ändern
    [{"text": "zwei"}, {"text": "eins"}],  # umsortieren
])
def test_append_only_rejects_destructive_writes(attack):
    stored = {"log": [{"text": "eins"}]}
    with pytest.raises(vis.AppendOnlyViolation):
        vis.apply_writes(APPEND_DEFN, APPEND_DEFN.phases[0], stored, {"log": attack}, CTX)


# ── server_stamped: Autor/Zeitstempel sind nicht fälschbar ───────────────────

def test_server_stamped_cannot_be_forged_on_new_entries():
    stored = {"log": [{"text": "alt", "author": "Alice", "ts": "2026-01-01T00:00:00+00:00"}]}
    submitted = {"log": [
        {"text": "alt", "author": "Alice", "ts": "2026-01-01T00:00:00+00:00"},
        {"text": "neu", "author": "Chef", "ts": "2001-01-01T00:00:00+00:00"},   # gefälscht
    ]}
    out = compute.stamp_server_fields(APPEND_DEFN, submitted, stored,
                                      actor="Bob", now_iso="2026-08-07T12:00:00+00:00")
    assert out["log"][0]["author"] == "Alice"                 # Bestand unverändert
    assert out["log"][0]["ts"] == "2026-01-01T00:00:00+00:00"
    assert out["log"][1]["author"] == "Bob"                   # Fälschung überschrieben
    assert out["log"][1]["ts"] == "2026-08-07T12:00:00+00:00"


# ── Ehrlichkeits-Regel: nicht implementierte Features werden abgelehnt ───────

def _base(**over):
    d = {"schemaVersion": 1, "key": "k", "name": "N",
         "fields": [{"key": "a", "widget": "text"}],
         "phases": [{"key": "start", "kind": "start", "responsibility": {"kind": "owner"},
                     "fields": [{"ref": "a"}]}]}
    d.update(over)
    return d


def _reject(d):
    with pytest.raises(ValidationError):
        ProcessDefinition.model_validate(d)


def test_terminal_enter_status_rejected():
    d = _base()
    d["phases"][0]["enterStatus"] = "archived"
    _reject(d)


def test_terminal_set_status_action_rejected():
    d = _base()
    d["phases"][0]["automations"] = [{"id": "x", "trigger": {"type": "on_enter"},
                                      "action": {"type": "set_status", "value": "rejected"}}]
    _reject(d)


@pytest.mark.parametrize("action", [
    {"type": "spawn_process", "process": "other"},
    {"type": "assign_sequence", "counter": "c"},
    {"type": "require_attachment", "field": "a"},
])
def test_unimplemented_actions_rejected(action):
    d = _base()
    d["phases"][0]["automations"] = [{"id": "x", "trigger": {"type": "on_enter"}, "action": action}]
    _reject(d)


def test_unknown_recipient_rejected():
    d = _base()
    d["phases"][0]["automations"] = [{"id": "x", "trigger": {"type": "on_enter"},
                                      "action": {"type": "notify", "to": "tippfehler"}}]
    _reject(d)
    # gültige Ziele gehen durch
    for to in ("responsible", "owner", "watchers", "group:abc"):
        ok = _base()
        ok["phases"][0]["automations"] = [{"id": "x", "trigger": {"type": "on_enter"},
                                           "action": {"type": "notify", "to": to}}]
        ProcessDefinition.model_validate(ok)


def test_approval_phase_kind_rejected_until_implemented():
    d = _base()
    d["phases"].append({"key": "frei", "kind": "approval", "view": "readonly",
                        "responsibility": {"kind": "group", "group": "g1"}, "fields": []})
    _reject(d)


@pytest.mark.parametrize("bad", ["P0D", "7D", "PT0S", "P1M"])
def test_bad_timer_duration_rejected_at_publish(bad):
    d = _base()
    d["phases"][0]["automations"] = [{"id": "x", "trigger": {"type": "timer", "after": bad},
                                      "action": {"type": "notify", "to": "owner"}}]
    _reject(d)


def test_catchup_is_capped():
    """Ohne Deckel wären es nach langem Ausfall tausende Ledger-Inserts."""
    from backend.services.process_automations import due_timers, MAX_CATCHUP
    d = _base()
    d["phases"][0]["automations"] = [{"id": "r", "trigger": {"type": "timer", "after": "PT5M",
                                                             "repeat": "PT5M"},
                                      "action": {"type": "notify", "to": "owner"}}]
    defn = ProcessDefinition.model_validate(d)
    now = datetime(2026, 8, 10, tzinfo=timezone.utc)          # 3 Tage = 864 Occurrences
    (_, occs), = due_timers(defn.phases[0], "2026-08-07T00:00:00+00:00", now, 0, {})
    assert len(occs) == MAX_CATCHUP
    assert occs[-1] == 864                                     # die aktuellste feuert
