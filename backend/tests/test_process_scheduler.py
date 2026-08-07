"""Ebene-1: Action-Ausführung + Scheduler-Sweep (Feuern, Idempotenz, Catch-up).

Kein echtes MariaDB/Mail: DB-Layer + Sender werden durch In-Memory-Fakes ersetzt.
"""
import json
from datetime import datetime, timezone

from backend.schemas.process_definition import ProcessDefinition
from backend.services import process_actions as pactions
from backend.services import process_scheduler as sched


DEFN_DICT = {
    "schemaVersion": 1, "key": "k", "name": "N",
    "fields": [{"key": "a", "widget": "text"}],
    "phases": [
        {"key": "start", "kind": "start", "responsibility": {"kind": "owner"}, "fields": [{"ref": "a"}]},
        {"key": "review", "kind": "review",
         "responsibility": {"kind": "group", "group": "g1"},
         "fields": [{"ref": "a", "mode": "readonly"}],
         "automations": [
             {"id": "rem", "trigger": {"type": "timer", "after": "P7D", "repeat": "P7D"},
              "action": {"type": "notify", "to": "group:g1"}},
             {"id": "esc", "trigger": {"type": "timer", "after": "P14D"},
              "action": {"type": "escalate", "to": "group:g1"}},
         ]},
    ],
}
DEFN = ProcessDefinition.model_validate(DEFN_DICT)
GROUPS = [{"id": "g1", "distributions": ["it@example.org"]}]
ENTERED = "2026-08-01T00:00:00+00:00"
NOW = datetime(2026, 8, 22, tzinfo=timezone.utc)   # 21 Tage nach Eintritt


# ── run_action (rein, Sender injiziert) ───────────────────────────────────────

def test_run_action_notify_resolves_group_distribution():
    calls = []
    sender = lambda r, s, b, kind=None: calls.append((r, kind))
    row = {"id": 1, "title": "T", "values": {}}
    ch = pactions.run_action(DEFN.phases[1].automations[0].action, row, DEFN, DEFN.phases[1],
                             sender=sender, groups=GROUPS)
    assert calls and calls[0][0] == ["it@example.org"]
    assert ch == {}   # notify ändert keinen Zustand


def test_run_action_escalate_sets_priority():
    ch = pactions.run_action(DEFN.phases[1].automations[1].action, {"id": 1, "title": "T", "values": {}},
                             DEFN, DEFN.phases[1], sender=lambda *a, **k: None, groups=GROUPS)
    assert ch.get("priority") == "high"


def test_resolve_recipients_fallback(monkeypatch):
    from backend.utils.config import config
    monkeypatch.setattr(config, "TICKET_MAIL", "fallback@example.org")
    # unbekanntes Ziel (owner) → Fallback
    assert pactions.resolve_recipients("owner", {"values": {}}, DEFN.phases[1], GROUPS) == ["fallback@example.org"]


# ── Scheduler-Fakes ────────────────────────────────────────────────────────────

class FakeStore:
    def __init__(self, rows):
        self.rows = {r["id"]: r for r in rows}

    def list_due(self, now_iso, limit=200):
        return [dict(r) for r in self.rows.values()
                if r.get("next_timer_due_at") and r["next_timer_due_at"] <= now_iso
                and r["status"] not in ("archived", "rejected")]

    def get(self, tid):
        return dict(self.rows[tid])

    def set_next_timer(self, tid, v):
        self.rows[tid]["next_timer_due_at"] = v

    def set_priority(self, tid, v):
        self.rows[tid]["priority"] = v

    def set_status(self, tid, v):
        self.rows[tid]["status"] = v

    def update_values(self, tid, vj, expected_rev=None):
        self.rows[tid]["values"] = json.loads(vj)

    def update_runtime(self, tid, *, runtime_json, status, next_timer_due_at=None, expected_rev=None):
        self.rows[tid]["runtime"] = json.loads(runtime_json)
        self.rows[tid]["status"] = status


class FakeFires:
    def __init__(self):
        self.records = []   # ((tid,pk,ep,aid,occ), suppressed)

    def claim(self, tid, pk, ep, aid, occ, suppressed=False):
        key = (tid, pk, ep, aid, occ)
        if any(k == key for k, _ in self.records):
            return False
        self.records.append((key, suppressed))
        return True

    def fired_map(self, tid, pk, ep):
        m = {}
        for (t, p, e, a, o), _ in self.records:
            if t == tid and p == pk and e == ep:
                m[a] = max(m.get(a, 0), o)
        return m


class FakeDefs:
    def get_definition(self, key, ver):
        return {"definition": DEFN_DICT}


def _ticket():
    runtime = {"current_index": 1, "epoch": 0, "rejected": False, "sla_paused_ms": 0,
               "phases": [{"key": "start", "status": "done", "entered_at": ENTERED},
                          {"key": "review", "status": "open", "entered_at": ENTERED}]}
    return {"id": 1, "process_key": "k", "process_version": 1, "title": "T", "status": "in_request",
            "priority": "normal", "values": {}, "runtime": runtime,
            "next_timer_due_at": "2026-08-08T00:00:00+00:00"}


def _wire(monkeypatch, store, fires):
    import backend.database.groups as gmod
    calls = []
    monkeypatch.setattr(sched, "store", store)
    monkeypatch.setattr(sched, "fires", fires)
    monkeypatch.setattr(sched, "defstore", FakeDefs())
    monkeypatch.setattr(sched, "record_audit", lambda **k: None)
    monkeypatch.setattr(sched, "SENDER", lambda r, s, b, kind=None: calls.append(kind))
    monkeypatch.setattr(gmod, "get_groups", lambda: GROUPS)   # Empfänger-Auflösung ohne DB
    return calls


def test_sweep_fires_due_timers_with_catchup(monkeypatch):
    store = FakeStore([_ticket()])
    fires = FakeFires()
    calls = _wire(monkeypatch, store, fires)

    sched.sweep_once(NOW)

    kinds = sorted(calls)
    assert kinds == ["escalate", "notify"]          # je genau einmal ausgelöst
    # rem (7d/7d, 21 Tage) → Occurrences 1,2 unterdrückt, 3 gefeuert
    rem = sorted((o, sup) for (t, p, e, a, o), sup in fires.records if a == "rem")
    assert rem == [(1, True), (2, True), (3, False)]
    # esc (14d one-shot) → Occurrence 1 gefeuert
    assert [(o, sup) for (t, p, e, a, o), sup in fires.records if a == "esc"] == [(1, False)]
    # Eskalation hat Priorität gesetzt
    assert store.rows[1]["priority"] == "high"
    # next_timer neu berechnet: rem-Occurrence 4 = entered + 7d + 3*7d = 28d = 2026-08-29
    assert store.rows[1]["next_timer_due_at"] == "2026-08-29T00:00:00+00:00"


def test_sweep_is_idempotent(monkeypatch):
    store = FakeStore([_ticket()])
    fires = FakeFires()
    calls = _wire(monkeypatch, store, fires)

    sched.sweep_once(NOW)
    n_after_first = len(calls)
    # Timer künstlich wieder fällig machen und erneut sweepen – der Ledger verhindert Neu-Feuern
    store.set_next_timer(1, "2026-08-08T00:00:00+00:00")
    sched.sweep_once(NOW)
    assert len(calls) == n_after_first          # kein erneutes Feuern
