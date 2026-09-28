"""Admin-Eingriff in eine Freigabe-Phase: genehmigen / ablehnen / Freigabe-Mail
erneut senden (alles protokolliert).

Angemeldeter, admin-only Zwilling der Freigabe per Mail-Link
(api/v1/process_approval): derselbe Weg (pa.apply_decision → Verlauf/Audit →
Wirkung), nur mit der handelnden Person im Protokoll (via=admin). Ebene 1 – Stores
sind In-Memory-Attrappen, die Engine läuft echt.
"""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core.dependencies import get_current_user
from backend.main import _install_error_handlers
from backend.api.v1 import process_tickets as pt
from backend.database.process_tickets import ProcessTicketConflict
from backend.schemas.process_definition import ProcessDefinition
from backend.services import process_events as pev
from backend.services import process_runtime as pr
from backend.services import process_visibility as vis

ADMIN = {"id": "u_admin", "displayName": "Chef", "permissions": ["admin"]}
OWNER = {"id": "u_owner", "displayName": "Antragsteller", "permissions": []}


def _defn(*, on_reject=None, require_reason=False):
    approval = {"question": "Freigeben?", "externalLink": True, "emailBody": "x"}
    if on_reject is not None:
        approval["onReject"] = on_reject
    if require_reason:
        approval["requireReason"] = True
    return {
        "schemaVersion": 1, "key": "app", "name": "Approval-Flow",
        "fields": [{"key": "base.name", "widget": "text"}],
        "phases": [
            {"key": "start", "kind": "start", "responsibility": {"kind": "owner"},
             "fields": [{"ref": "base.name", "required": True}]},
            {"key": "frei", "kind": "approval", "view": "approval",
             "responsibility": {"kind": "owner"}, "approval": approval,
             "fields": [{"ref": "base.name", "mode": "readonly"}]},
            {"key": "ende", "kind": "task", "responsibility": {"kind": "owner"},
             "fields": [{"ref": "base.name", "mode": "readonly"}]},
        ],
    }


#: Standard-Freigabe (Ablehnung ist terminal) und Rücksprung-Variante (+Pflichtgrund).
DEFN_APP = _defn()
DEFN_BACK = _defn(on_reject="back_to:start", require_reason=True)


class FakeStore:
    ProcessTicketConflict = ProcessTicketConflict

    def __init__(self):
        self.rows: dict[int, dict] = {}
        self.seq = 0

    def get(self, tid):
        r = self.rows.get(tid)
        return dict(r) if r else None

    def _guard(self, r, expected_rev):
        if expected_rev is not None and r["rev"] != expected_rev:
            raise ProcessTicketConflict(f"#{r['id']} geändert")

    def update_runtime(self, tid, *, runtime_json, status, next_timer_due_at=None,
                       expected_rev=None):
        r = self.rows[tid]
        self._guard(r, expected_rev)
        r["runtime_json"] = runtime_json
        r["runtime"] = json.loads(runtime_json)
        r["status"] = status
        r["next_timer_due_at"] = next_timer_due_at
        r["rev"] += 1
        return dict(r)

    def update_values(self, tid, values_json, title=None, expected_rev=None):
        r = self.rows[tid]
        self._guard(r, expected_rev)
        r["values_json"] = values_json
        r["values"] = json.loads(values_json)
        if title is not None:
            r["title"] = title
        r["rev"] += 1
        return dict(r)

    def set_next_timer(self, tid, v, expected_rev=None):
        self.rows[tid]["next_timer_due_at"] = v

    def set_status(self, tid, v, expected_rev=None):
        self.rows[tid]["status"] = v


class FakeDefs:
    _MAP = {"app": DEFN_APP, "back": DEFN_BACK}

    def is_disabled(self, key):
        return False

    def get_published(self, key):
        d = self._MAP.get(key)
        return {"version": 1, "definition": d} if d else None

    def get_definition(self, key, ver):
        d = self._MAP.get(key)
        return {"version": ver, "definition": d} if d else None


class FakeEventStore:
    def __init__(self):
        self.rows = []

    def add_event(self, **kw):
        ev = {"id": len(self.rows) + 1, "created_at": "t", **kw}
        ev["details"] = kw.get("details") or {}
        ev["internal"] = bool(kw.get("internal"))
        self.rows.append(ev)
        return dict(ev)

    def list_for_ticket(self, tid, *, limit=100, offset=0):
        mine = [dict(e) for e in self.rows if e["ticket_id"] == tid]
        return mine[offset:offset + limit], len(mine)


class FakeFires:
    def fired_map(self, tid, pk, ep):
        return {}

    def claim(self, *a, **k):
        return True


@pytest.fixture
def env(monkeypatch):
    from backend.services import process_engine as engine
    store, evstore = FakeStore(), FakeEventStore()
    audits: list = []            # pt.record_audit (die eigene Freigabe-Audit-Zeile)
    mails = {"phase_entry": [], "phase_entry_ret": [], "rejection": [], "sent_back": []}

    monkeypatch.setattr(pt, "store", store)
    monkeypatch.setattr(pt, "defstore", FakeDefs())
    monkeypatch.setattr(pt, "record_audit", lambda **kw: audits.append(kw))
    monkeypatch.setattr(pev, "store", evstore)
    monkeypatch.setattr(pev, "record_audit", lambda **kw: None)
    monkeypatch.setattr(engine, "store", store)
    monkeypatch.setattr(engine, "fires", FakeFires())
    monkeypatch.setattr(vis, "user_group_ids", lambda u: set())

    def _phase_entry(row, defn, phase, **k):
        mails["phase_entry"].append(phase.key if phase else None)
        return list(mails["phase_entry_ret"])

    def _rejection(row, defn, *, reason=None, by_name=None, **k):
        mails["rejection"].append({"reason": reason, "by_name": by_name})
        return []

    def _sent_back(row, defn, phase, *, reason=None, by_name=None, **k):
        mails["sent_back"].append({"to": phase.key if phase else None,
                                   "reason": reason, "by_name": by_name})
        return []

    monkeypatch.setattr(pt.pactions, "notify_phase_entry", _phase_entry)
    monkeypatch.setattr(pt.pactions, "notify_rejection", _rejection)
    monkeypatch.setattr(pt.pactions, "notify_sent_back", _sent_back)

    state = {"user": dict(ADMIN)}
    app = FastAPI()
    _install_error_handlers(app)
    app.include_router(pt.router)
    app.dependency_overrides[get_current_user] = lambda: state["user"]
    return TestClient(app), state, store, evstore, audits, mails


def _seed(store, *, key="app", defn_raw=DEFN_APP, phase_index=1, status="in_request"):
    """Einen Auftrag direkt in einer bestimmten Phase ablegen (ohne Create-Flow)."""
    defn = ProcessDefinition.model_validate(defn_raw)
    values = {"base.name": "Max"}
    rt = pr.initial_runtime(defn, "t0", values)
    for _ in range(phase_index):
        rt, _ = pr.advance(defn, rt, "t1", values)
    store.seq += 1
    tid = store.seq
    store.rows[tid] = {"id": tid, "process_key": key, "process_version": 1,
                       "title": f"Auftrag {tid}", "status": status, "priority": "normal",
                       "owner_id": "u_owner", "owner_name": "Owner", "values": values,
                       "runtime": rt, "rev": 0, "next_timer_due_at": None,
                       "created_at": "t", "updated_at": "t",
                       "values_json": json.dumps(values), "runtime_json": json.dumps(rt)}
    return tid


def _events(evstore, action):
    return [e for e in evstore.rows if e["action"] == action]


# ── Genehmigen ────────────────────────────────────────────────────────────────

def test_decide_approve_advances_and_audits(env):
    client, _state, store, evstore, audits, _m = env
    tid = _seed(store)
    r = client.post(f"/process-tickets/{tid}:decide", json={"act": "approve"})
    assert r.status_code == 200
    assert r.json()["data"]["current_phase"] == "ende"          # Engine hat weitergeschaltet
    # Verlauf: die Entscheidung mit der handelnden Person (nicht der Mail-Kanal).
    dec = _events(evstore, "approval_decided")
    assert dec and dec[0]["actor_id"] == "u_admin"
    assert dec[0]["details"] == {"act": "approve", "via": "in_app",
                                 "follow_up": "advance", "reason_in_field": False}
    # Eigene Audit-Zeile (via=in_app), zusätzlich zur Verlaufs-Audit-Zeile.
    a = [x for x in audits if x["action"] == "process_approval_decided"]
    assert a and a[0]["actor_id"] == "u_admin" and a[0]["details"]["act"] == "approve"


def test_decide_allows_responsible(env):
    # Die ZUSTÄNDIGE Stelle (hier der Owner der Freigabe-Phase) darf im Web direkt
    # entscheiden – kein Admin nötig; die Person steht im Verlauf.
    client, state, store, evstore, *_ = env
    tid = _seed(store)
    state["user"] = dict(OWNER)
    r = client.post(f"/process-tickets/{tid}:decide", json={"act": "approve"})
    assert r.status_code == 200
    assert r.json()["data"]["current_phase"] == "ende"
    dec = _events(evstore, "approval_decided")
    assert dec and dec[0]["actor_id"] == "u_owner"


def test_decide_denies_view_only(env):
    # Reine Aufsicht (view) darf lesen, aber nicht entscheiden → 403.
    client, state, store, *_ = env
    tid = _seed(store)
    state["user"] = {"id": "u_view", "displayName": "Aufsicht", "permissions": ["view"]}
    r = client.post(f"/process-tickets/{tid}:decide", json={"act": "approve"})
    assert r.status_code == 403


def test_decide_denies_stranger(env):
    # Wer den Auftrag gar nicht sehen darf, bekommt 404 (nicht verraten, dass es ihn gibt).
    client, state, store, *_ = env
    tid = _seed(store)
    state["user"] = {"id": "u_fremd", "displayName": "Fremd", "permissions": []}
    r = client.post(f"/process-tickets/{tid}:decide", json={"act": "approve"})
    assert r.status_code == 404


# ── Ablehnen (terminal) ─────────────────────────────────────────────────────

def test_decide_reject_terminates_and_mails(env):
    client, _state, store, evstore, audits, mails = env
    tid = _seed(store)
    r = client.post(f"/process-tickets/{tid}:decide", json={"act": "reject", "reason": "passt nicht"})
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "rejected"
    assert store.rows[tid]["runtime"]["rejected"] is True
    assert _events(evstore, "rejected")
    # Ablehnungs-Mail mit dem Admin als Absender-Name.
    assert mails["rejection"] == [{"reason": "passt nicht", "by_name": "Chef"}]
    a = [x for x in audits if x["action"] == "process_approval_decided"]
    assert a[0]["details"]["follow_up"] == "reject"


# ── Ablehnen mit Rücksprung (onReject: back_to:) ─────────────────────────────

def test_decide_reject_sends_back(env):
    client, _state, store, evstore, _a, mails = env
    tid = _seed(store, key="back", defn_raw=DEFN_BACK)
    r = client.post(f"/process-tickets/{tid}:decide", json={"act": "reject", "reason": "bitte nachbessern"})
    assert r.status_code == 200
    assert r.json()["data"]["current_phase"] == "start"         # zurück in die Startphase
    assert _events(evstore, "approval_sent_back")
    assert mails["sent_back"] and mails["sent_back"][0]["to"] == "start"
    assert mails["sent_back"][0]["by_name"] == "Chef"


def test_decide_reject_requires_reason_when_configured(env):
    client, _state, store, *_ = env
    tid = _seed(store, key="back", defn_raw=DEFN_BACK)
    r = client.post(f"/process-tickets/{tid}:decide", json={"act": "reject", "reason": "   "})
    assert r.status_code == 422
    assert r.json()["error"]["fields"][0]["path"] == "reason"


# ── Zustands-Wächter ─────────────────────────────────────────────────────────

def test_decide_invalid_action_422(env):
    client, _state, store, *_ = env
    tid = _seed(store)
    r = client.post(f"/process-tickets/{tid}:decide", json={"act": "vielleicht"})
    assert r.status_code == 422
    assert r.json()["error"]["fields"][0]["path"] == "act"


def test_decide_not_in_approval_phase_409(env):
    client, _state, store, *_ = env
    tid = _seed(store, phase_index=2, status="in_progress")     # steht in „ende" (task)
    r = client.post(f"/process-tickets/{tid}:decide", json={"act": "approve"})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "PROCESS_INVALID_STATE"


def test_decide_already_decided_409(env):
    client, _state, store, *_ = env
    tid = _seed(store)
    rt = store.rows[tid]["runtime"]
    idx = rt["current_index"]
    store.rows[tid]["runtime"] = pr.set_phase_decision(
        rt, idx, act="approve", by=None, by_name="x", at="t",
        reason=None, reason_in_field=False)
    r = client.post(f"/process-tickets/{tid}:decide", json={"act": "approve"})
    assert r.status_code == 409
    assert "entschieden" in r.json()["error"]["message"]


def test_decide_terminal_409(env):
    client, _state, store, *_ = env
    tid = _seed(store, status="archived")
    r = client.post(f"/process-tickets/{tid}:decide", json={"act": "approve"})
    assert r.status_code == 409


def test_decide_conflict_409(env, monkeypatch):
    client, _state, store, *_ = env
    tid = _seed(store)

    def _boom(*a, **k):
        raise ProcessTicketConflict("stale")
    monkeypatch.setattr(store, "update_runtime", _boom)
    r = client.post(f"/process-tickets/{tid}:decide", json={"act": "approve"})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "TICKET_CONFLICT"


# ── Freigabe-Mail erneut senden ──────────────────────────────────────────────

def test_resend_resends_and_audits(env):
    client, _state, store, evstore, _a, mails = env
    tid = _seed(store)
    mails["phase_entry_ret"] = ["freigeber@x.de"]
    r = client.post(f"/process-tickets/{tid}:resend-approval")
    assert r.status_code == 200
    ev = _events(evstore, "approval_mail_resent")
    assert ev and ev[0]["details"]["recipients"] == ["freigeber@x.de"]
    assert ev[0]["actor_id"] == "u_admin"
    assert mails["phase_entry"] == ["frei"]


def test_resend_requires_admin(env):
    client, state, store, *_ = env
    tid = _seed(store)
    state["user"] = dict(OWNER)
    assert client.post(f"/process-tickets/{tid}:resend-approval").status_code == 403


def test_resend_not_in_approval_phase_409(env):
    client, _state, store, *_ = env
    tid = _seed(store, phase_index=2, status="in_progress")
    r = client.post(f"/process-tickets/{tid}:resend-approval")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "PROCESS_INVALID_STATE"


# ── Ability-Flags (damit die Oberfläche nicht raten muss) ────────────────────

def test_abilities_expose_decide_and_resend(env):
    client, state, store, *_ = env
    tid = _seed(store)
    a = client.get(f"/process-tickets/{tid}").json()["data"]["abilities"]
    assert a["decide_approval"] is True and a["resend_approval"] is True   # Admin: beides
    # Zuständige Stelle (Owner): entscheiden JA, erneut senden (Admin-Werkzeug) NEIN.
    state["user"] = dict(OWNER)
    b = client.get(f"/process-tickets/{tid}").json()["data"]["abilities"]
    assert b["decide_approval"] is True and b["resend_approval"] is False
    # Reine Aufsicht (view): weder noch – nur lesen.
    state["user"] = {"id": "u_view", "displayName": "Aufsicht", "permissions": ["view"]}
    c = client.get(f"/process-tickets/{tid}").json()["data"]["abilities"]
    assert c["decide_approval"] is False and c["resend_approval"] is False


def test_abilities_false_outside_approval_phase(env):
    client, _state, store, *_ = env
    tid = _seed(store, phase_index=2, status="in_progress")     # „ende" (task)
    a = client.get(f"/process-tickets/{tid}").json()["data"]["abilities"]
    assert a["decide_approval"] is False and a["resend_approval"] is False


def test_abilities_decide_false_after_decision(env):
    client, _state, store, *_ = env
    tid = _seed(store)
    rt = store.rows[tid]["runtime"]
    store.rows[tid]["runtime"] = pr.set_phase_decision(
        rt, rt["current_index"], act="approve", by=None, by_name="x", at="t",
        reason=None, reason_in_field=False)
    a = client.get(f"/process-tickets/{tid}").json()["data"]["abilities"]
    # Entschieden, aber (künstlich) noch in der Phase: decide fällt weg, resend nicht.
    assert a["decide_approval"] is False and a["resend_approval"] is True
