"""Ebene-1: ISO-Dauer-Parser + Timer-/Occurrence-Mathematik (rein)."""

from datetime import datetime, timezone, timedelta

import pytest

from backend.schemas.process_definition import ProcessDefinition
from backend.services.iso_duration import parse_duration
from backend.services import process_automations as pa


# ── ISO-Dauer ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("txt,secs", [
    ("P7D", 7 * 86400), ("P14D", 14 * 86400), ("PT12H", 12 * 3600),
    ("P1W", 604800), ("PT30M", 1800), ("P1DT6H", 86400 + 6 * 3600), ("PT45S", 45),
])
def test_parse_duration_ok(txt, secs):
    assert parse_duration(txt) == secs


@pytest.mark.parametrize("bad", ["", "7D", "P", "PT", "abc", "P1M1D", None])
def test_parse_duration_bad(bad):
    with pytest.raises(ValueError):
        parse_duration(bad)


# ── Occurrence-Mathematik ─────────────────────────────────────────────────────

def test_max_due_occurrence_oneshot():
    assert pa.max_due_occurrence(7 * 86400, 0, 6 * 86400) == 0     # noch nicht fällig
    assert pa.max_due_occurrence(7 * 86400, 0, 7 * 86400) == 1     # genau fällig
    assert pa.max_due_occurrence(7 * 86400, 0, 100 * 86400) == 1   # bleibt 1 (one-shot)


def test_max_due_occurrence_repeat():
    d = 86400
    # after=7d, repeat=7d
    assert pa.max_due_occurrence(7 * d, 7 * d, 6 * d) == 0
    assert pa.max_due_occurrence(7 * d, 7 * d, 7 * d) == 1
    assert pa.max_due_occurrence(7 * d, 7 * d, 13 * d) == 1
    assert pa.max_due_occurrence(7 * d, 7 * d, 14 * d) == 2
    assert pa.max_due_occurrence(7 * d, 7 * d, 30 * d) == 4        # floor((30-7)/7)+1


def test_pause_shifts_due():
    d = 86400
    entered = "2026-08-01T00:00:00+00:00"
    now = datetime(2026, 8, 8, tzinfo=timezone.utc)   # 7 Tage später
    # ohne Pause: fällig; mit 3 Tagen Pause: elapsed=4d < 7d → nicht fällig
    assert pa._elapsed_seconds(entered, now, 0) == 7 * d
    assert pa.max_due_occurrence(7 * d, 0, pa._elapsed_seconds(entered, now, 3 * d * 1000)) == 0


def test_next_due_at():
    entered = "2026-08-01T00:00:00+00:00"
    base = datetime(2026, 8, 1, tzinfo=timezone.utc)
    # one-shot, nichts gefeuert → entered + 7d
    assert pa.next_due_at(entered, 7 * 86400, 0, 0, 0) == base + timedelta(days=7)
    # one-shot, gefeuert → keine weitere
    assert pa.next_due_at(entered, 7 * 86400, 0, 0, 1) is None
    # repeat, occurrence 1 gefeuert → entered + 7d + 1*7d = +14d
    assert pa.next_due_at(entered, 7 * 86400, 7 * 86400, 0, 1) == base + timedelta(days=14)


# ── Phasen-Timer über eine echte Definition ───────────────────────────────────

DEFN = ProcessDefinition.model_validate({
    "schemaVersion": 1, "key": "k", "name": "N",
    "fields": [{"key": "a", "widget": "text"}],
    "phases": [{"key": "start", "kind": "start", "responsibility": {"kind": "owner"},
                "fields": [{"ref": "a"}]},
               {"key": "review", "kind": "review",
                "responsibility": {"kind": "group", "group": "g_it"},
                "fields": [{"ref": "a", "mode": "readonly"}],
                "automations": [
                    {"id": "rem", "trigger": {"type": "timer", "after": "P7D", "repeat": "P7D"},
                     "action": {"type": "notify", "to": "responsible"}},
                    {"id": "esc", "trigger": {"type": "timer", "after": "P14D"},
                     "action": {"type": "escalate", "to": "owner"}},
                ]}],
})
REVIEW = DEFN.phases[1]
ENTERED = "2026-08-01T00:00:00+00:00"


def test_compute_next_timer_due_is_earliest():
    nd = pa.compute_next_timer_due(REVIEW, ENTERED, 0, {})
    assert nd == datetime(2026, 8, 8, tzinfo=timezone.utc)   # rem nach 7d ist am frühesten


def test_due_timers_catch_up():
    now = datetime(2026, 8, 22, tzinfo=timezone.utc)   # 21 Tage
    due = dict((a.id, occs) for a, occs in pa.due_timers(REVIEW, ENTERED, now, 0, {}))
    # rem (7d/7d): max occ = floor((21-7)/7)+1 = 3 → [1,2,3]; esc (14d one-shot) → [1]
    assert due["rem"] == [1, 2, 3]
    assert due["esc"] == [1]


def test_due_timers_respects_fired_map():
    now = datetime(2026, 8, 22, tzinfo=timezone.utc)
    due = dict((a.id, occs) for a, occs in pa.due_timers(REVIEW, ENTERED, now, 0, {"rem": 2, "esc": 1}))
    assert due["rem"] == [3]        # 1,2 schon gefeuert
    assert "esc" not in due          # schon gefeuert
