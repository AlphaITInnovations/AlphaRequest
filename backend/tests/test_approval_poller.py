"""Ebene-1: externer Approval-Abhol-Worker – Stapelverarbeitung, Long-Poll-Schleife
(F-03: ein kaputter Eintrag blockiert die anderen nicht) und das reale Anwenden
über den geteilten Entscheidungs-Kern."""
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from backend.services import approval_commit
from backend.services import approval_jwt as aj
from backend.services import approval_poller as ap
from backend.services import process_engine as engine
from backend.services import process_events as pev
from backend.services import process_actions as pactions

ISS, AUD = "alpharequest-prod", "alphaapprove-prod"


@pytest.fixture
def key(monkeypatch):
    k = Ed25519PrivateKey.generate()
    monkeypatch.setattr(aj, "_private_key_cache", k)
    monkeypatch.setattr(aj.config, "APPROVAL_ISSUER", ISS)
    monkeypatch.setattr(aj.config, "APPROVAL_AUDIENCE", AUD)
    return k


def _verify(k, leeway=30):
    return aj.make_verifier(k.public_key(), ISS, AUD, leeway)


def decision(k, did, *, tid=1, act="approve", phase="freigabe", epoch=0, ttl=3600,
             env_act=None, **meta):
    token = aj.make_external_token(tid, act, phase, epoch, ttl_seconds=ttl)
    return {"id": did, "token": token, "tid": tid, "act": (env_act or act),
            "phase": phase, "epoch": epoch, **meta}


def expired(k, did, *, tid=1, act="approve", phase="freigabe", epoch=0):
    now = int(time.time())
    token = jwt.encode({"iss": ISS, "aud": AUD, "tid": tid, "act": act, "phase": phase,
                        "epoch": epoch, "iat": now - 4000, "exp": now - 100},
                       k, algorithm="EdDSA")
    return {"id": did, "token": token, "tid": tid, "act": act, "phase": phase, "epoch": epoch}


# ── process_batch ─────────────────────────────────────────────────────────────

def test_erfolg_wird_geackt(key):
    applied = []
    ack, retry = ap.process_batch([decision(key, 1, tid=9)], _verify(key),
                                  lambda c, d: applied.append(c["tid"]), lambda d, w: None)
    assert ack == [1] and retry == [] and applied == [9]


def test_huelle_weicht_vom_token_ab_quarantaene(key):
    q = []
    ack, retry = ap.process_batch([decision(key, 5, act="reject", env_act="approve")],
                                  _verify(key), lambda c, d: None, lambda d, why: q.append(why))
    assert ack == [5] and retry == [] and "Hülle" in q[0]


def test_dauerhafter_fehler_quarantaene(key):
    def apply(c, d):
        raise ap.PermanentError("Auftrag bereits in anderer Phase")
    ack, retry = ap.process_batch([decision(key, 1)], _verify(key), apply, lambda d, w: None)
    assert ack == [1] and retry == []


def test_voruebergehender_fehler_wird_nicht_geackt(key):
    def apply(c, d):
        raise ConnectionError("DB kurz weg")
    ack, retry = ap.process_batch([decision(key, 1)], _verify(key), apply, lambda d, w: None)
    assert ack == [] and retry == [1]


def test_ungueltiges_token_quarantaene(key):
    d = decision(key, 1)
    d["token"] = d["token"][:-3] + ("AAA" if d["token"][-3:] != "AAA" else "BBB")
    q = []
    ack, retry = ap.process_batch([d], _verify(key, leeway=0), lambda c, dd: None,
                                  lambda dd, why: q.append(why))
    assert ack == [1] and retry == [] and q


def test_abgelaufen_blockiert_die_anderen_nicht(key):
    """F-03: ein (bei Collector-Toleranz noch angenommener) hier abgelaufener Eintrag
    darf die übrigen nicht aufhalten."""
    applied, q = [], []
    ack, retry = ap.process_batch([expired(key, 1, tid=1), decision(key, 2, tid=2)],
                                  _verify(key, leeway=0),
                                  lambda c, d: applied.append(c["tid"]),
                                  lambda d, w: q.append(d["tid"]))
    assert applied == [2] and q == [1] and ack == [1, 2] and retry == []


# ── Long-Poll-Schleife ────────────────────────────────────────────────────────

class _Resp:
    status_code = 200

    def __init__(self, data):
        self._d = data

    def json(self):
        return self._d


class FakeApprove:
    """Minimale AlphaApprove-Attrappe: /pending liefert Unbestätigte, /ack konsumiert."""
    def __init__(self):
        self.q, self.consumed, self.ack_fails, self.bad_status = [], set(), 0, 0

    def add(self, d):
        self.q.append(d)

    def get(self, url, headers=None, timeout=None):
        if self.bad_status:
            r = _Resp({"error": "overloaded"})      # 5xx MIT JSON-Körper (rutscht sonst durch)
            r.status_code = self.bad_status
            return r
        pend = [d for d in self.q if d["id"] not in self.consumed]
        return _Resp({"decisions": pend, "cursor": max([d["id"] for d in self.q], default=0)})

    def post(self, url, json=None, headers=None, timeout=None):
        if self.ack_fails > 0:
            self.ack_fails -= 1
            raise ConnectionError("ack weg")
        for i in (json or {}).get("ids", []):
            self.consumed.add(i)
        return _Resp({})


def _cycles(n):
    c = {"n": 0}

    def stop():
        c["n"] += 1
        return c["n"] > n
    return stop


def test_run_verarbeitet_und_bestaetigt(key):
    srv = FakeApprove()
    srv.add(decision(key, 1, tid=1))
    srv.add(decision(key, 2, tid=2))
    applied = []
    ap.run(srv, "", "k", _verify(key), lambda c, d: applied.append(c["tid"]),
           lambda d, w: None, wait=0, backoff=0, should_stop=_cycles(2), sleep=lambda _: None)
    assert sorted(applied) == [1, 2]
    assert all(d["id"] in srv.consumed for d in srv.q)


def test_run_voruebergehender_eintrag_wird_bis_zum_erfolg_wiederholt(key):
    srv = FakeApprove()
    srv.add(decision(key, 1, tid=1))
    srv.add(decision(key, 2, tid=2))
    attempts, applied = {}, []

    def apply(c, d):
        t = c["tid"]
        attempts[t] = attempts.get(t, 0) + 1
        if t == 1 and attempts[1] == 1:
            raise ConnectionError("DB weg")
        applied.append(t)

    ap.run(srv, "", "k", _verify(key), apply, lambda d, w: None, wait=0, backoff=0,
           should_stop=_cycles(3), sleep=lambda _: None)
    assert sorted(applied) == [1, 2] and attempts[1] == 2
    assert all(d["id"] in srv.consumed for d in srv.q)


def test_run_drosselt_leere_antwort(key):
    srv = FakeApprove()                              # leere Queue
    slept = []
    ap.run(srv, "", "k", _verify(key), lambda c, d: None, lambda d, w: None,
           wait=0, backoff=7, should_stop=_cycles(1), sleep=lambda s: slept.append(s))
    assert 7 in slept                                # leere Antwort → sleep(backoff), kein Hot-Loop


def test_run_drosselt_fehlerstatus(key):
    srv = FakeApprove()
    srv.bad_status = 503                             # 5xx mit JSON-Körper
    slept = []
    ap.run(srv, "", "k", _verify(key), lambda c, d: None, lambda d, w: None,
           wait=0, backoff=3, should_stop=_cycles(1), sleep=lambda s: slept.append(s))
    assert 3 in slept                                # Status geprüft → Backoff statt Spin


def test_run_ack_fehlschlag_liefert_erneut(key):
    srv = FakeApprove()
    srv.ack_fails = 1                       # der erste /ack scheitert
    srv.add(decision(key, 1, tid=1))
    applied = []
    ap.run(srv, "", "k", _verify(key), lambda c, d: applied.append(c["tid"]),
           lambda d, w: None, wait=0, backoff=0, should_stop=_cycles(3), sleep=lambda _: None)
    # Trotz ACK-Fehlschlag am Ende konsumiert (wurde erneut geliefert + geackt).
    assert 1 in srv.consumed


# ── Reales Anwenden über den geteilten Kern ──────────────────────────────────

@pytest.fixture
def umgebung(key, monkeypatch):
    from backend.tests.test_process_approval import (
        FakeStore, FakeDefs, FakeEvents, FakeFires, ticket, raw,
    )
    d_raw = raw()
    store = FakeStore(ticket())
    evstore = FakeEvents()

    # Wie im Endpunkt-Test: den EVENTS-Store faken, damit sowohl commit_decision
    # (events.system) ALS AUCH die Engine (advanced) in denselben Fake schreiben.
    monkeypatch.setattr(ap, "store", store)
    monkeypatch.setattr(ap, "defstore", FakeDefs(d_raw))
    monkeypatch.setattr(approval_commit, "_store", store)
    monkeypatch.setattr(approval_commit, "_record_audit", lambda **kw: None)
    monkeypatch.setattr(engine, "store", store)
    monkeypatch.setattr(engine, "fires", FakeFires())
    monkeypatch.setattr(engine, "record_audit", lambda **kw: None)
    monkeypatch.setattr(pev, "store", evstore)
    monkeypatch.setattr(pev, "record_audit", lambda **kw: None)
    monkeypatch.setattr(pactions, "notify_phase_entry", lambda *a, **k: [])
    monkeypatch.setattr(pactions, "notify_rejection", lambda *a, **k: [])
    monkeypatch.setattr(pactions, "notify_sent_back", lambda *a, **k: [])
    return store, evstore


def _actions(evstore):
    return [e["action"] for e in evstore.rows]


def _claims(tid=7, act="approve", phase="freigabe", epoch=0):
    return {"tid": tid, "act": act, "phase": phase, "epoch": epoch}


def _dec(**claims_over):
    c = _claims(**claims_over)
    return {"id": 42, "token": "egal", "client_ip": "203.0.113.7",
            "user_agent": "Mobile", "hostname": "host.example", "lang": "de", **c}


def test_apply_approve_schaltet_weiter(umgebung):
    store, evstore = umgebung
    ap.apply_decision_entry(_claims(act="approve"), _dec(act="approve"))
    assert store.rows[7]["runtime"]["current_index"] == 2
    assert "approval_decided" in _actions(evstore) and "advanced" in _actions(evstore)


def test_apply_reject_lehnt_ab(umgebung):
    store, evstore = umgebung
    ap.apply_decision_entry(_claims(act="reject"), _dec(act="reject"))
    assert store.rows[7]["status"] == "rejected"


def test_apply_ist_idempotent_bei_gleicher_entscheidung(umgebung):
    store, evstore = umgebung
    ap.apply_decision_entry(_claims(act="approve"), _dec(act="approve"))
    before = store.rows[7]["rev"]
    # zweite Zustellung derselben Entscheidung → kein Fehler, kein zweiter Effekt
    ap.apply_decision_entry(_claims(act="approve"), _dec(act="approve"))
    assert store.rows[7]["rev"] == before


def test_apply_gegenentscheidung_ist_permanent(umgebung):
    store, ev = umgebung
    ap.apply_decision_entry(_claims(act="approve"), _dec(act="approve"))
    with pytest.raises(ap.PermanentError):
        ap.apply_decision_entry(_claims(act="reject"), _dec(act="reject"))


def test_apply_veraltete_epoch_ist_permanent(umgebung):
    store, ev = umgebung
    store.rows[7]["runtime"]["epoch"] = 5
    with pytest.raises(ap.PermanentError):
        ap.apply_decision_entry(_claims(epoch=0), _dec(epoch=0))


def test_apply_unbekannter_auftrag_ist_permanent(umgebung):
    with pytest.raises(ap.PermanentError):
        ap.apply_decision_entry(_claims(tid=999), _dec(tid=999))


def test_apply_kaputte_definition_ist_permanent(key, monkeypatch):
    """Eine gepinnte Definition, die nicht mehr validiert, ist DAUERHAFT (sonst
    würde der Eintrag ewig erneut abgeholt)."""
    from backend.tests.test_process_approval import FakeStore, ticket

    class BadDefs:
        def get_definition(self, k, v):
            return {"version": v, "definition": {"schemaVersion": 1, "key": "x"}}  # ungültig

    monkeypatch.setattr(ap, "store", FakeStore(ticket()))
    monkeypatch.setattr(ap, "defstore", BadDefs())
    with pytest.raises(ap.PermanentError):
        ap.apply_decision_entry(_claims(), _dec())
