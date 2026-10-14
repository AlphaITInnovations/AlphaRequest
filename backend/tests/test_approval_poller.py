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


def _verify(k, *, clock_leeway=30, pickup_grace=0):
    return aj.make_verifier(k.public_key(), ISS, AUD,
                            clock_leeway=clock_leeway, pickup_grace=pickup_grace)


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
    ack, retry = ap.process_batch([d], _verify(key, clock_leeway=0), lambda c, dd: None,
                                  lambda dd, why: q.append(why))
    assert ack == [1] and retry == [] and q


def test_abgelaufen_blockiert_die_anderen_nicht(key):
    """F-03: ein (bei Collector-Toleranz noch angenommener) hier abgelaufener Eintrag
    darf die übrigen nicht aufhalten."""
    applied, q = [], []
    ack, retry = ap.process_batch([expired(key, 1, tid=1), decision(key, 2, tid=2)],
                                  _verify(key, clock_leeway=0),
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

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeApprove:
    """Minimale AlphaApprove-Attrappe: /pending liefert Unbestätigte, /ack konsumiert."""
    def __init__(self):
        self.q, self.consumed = [], set()
        self.ack_fails, self.ack_bad, self.bad_status = 0, 0, 0

    def add(self, d):
        self.q.append(d)

    def get(self, url, params=None, headers=None, timeout=None, allow_redirects=None):
        if self.bad_status:
            r = _Resp({"error": "overloaded"})      # 5xx MIT JSON-Körper (rutscht sonst durch)
            r.status_code = self.bad_status
            return r
        pend = [d for d in self.q if d["id"] not in self.consumed]
        return _Resp({"decisions": pend, "cursor": max([d["id"] for d in self.q], default=0)})

    def post(self, url, json=None, headers=None, timeout=None, allow_redirects=None):
        if self.ack_fails > 0:                       # Verbindung weg (Exception)
            self.ack_fails -= 1
            raise ConnectionError("ack weg")
        if self.ack_bad > 0:                         # 5xx-Status (kein Exception)
            self.ack_bad -= 1
            r = _Resp({"error": "overloaded"})
            r.status_code = 500
            return r
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


# ── B2/B3/B4: Cursor läuft weiter, wachsender Backoff, ACK-Status, Fehlerablage ─

class PagedApprove:
    """AlphaApprove-Attrappe MIT Cursor: /pending liefert höchstens `page` Einträge
    mit id > after. So lässt sich prüfen, dass eine blockierte erste Seite spätere
    Einträge nicht aufhält."""
    def __init__(self, page=2):
        self.items, self.consumed, self.page = [], set(), page

    def add(self, d):
        self.items.append(d)

    def get(self, url, params=None, headers=None, timeout=None, allow_redirects=None):
        after = (params or {}).get("after", 0)
        pend = [d for d in self.items if d["id"] > after and d["id"] not in self.consumed]
        page = pend[:self.page]
        cursor = page[-1]["id"] if page else after
        return _Resp({"decisions": page, "cursor": cursor})

    def post(self, url, json=None, headers=None, timeout=None, allow_redirects=None):
        for i in (json or {}).get("ids", []):
            self.consumed.add(i)
        return _Resp({})


class _Clock:
    """Virtuelle Uhr: sleep() rückt die Zeit vor, damit fällige Wiederholungen
    deterministisch (ohne echtes Warten) erreichbar werden."""
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


def test_run_cursor_laeuft_weiter_blockierte_seite_haelt_spaetere_nicht_auf(key):
    """B2: die volle erste Seite (1+2) schlägt dauerhaft fehl; Eintrag 3 dahinter muss
    trotzdem angewendet+bestätigt werden, 1+2 bleiben unbestätigt, ihre Abstände
    wachsen (1 s → 2 s → 4 s …)."""
    srv = PagedApprove(page=2)
    for i in (1, 2, 3):
        srv.add(decision(key, i, tid=i))
    clk = _Clock()
    attempts1 = []

    def apply(c, d):
        if c["tid"] == 1:
            attempts1.append(clk.t)
        if c["tid"] in (1, 2):
            raise ConnectionError("DB weg")           # vorübergehend gemeldet → Wiederholung

    ap.run(srv, "", "k", _verify(key), apply, lambda d, w: None,
           wait=5, backoff=1, should_stop=_cycles(60), sleep=clk.sleep, clock=clk)

    assert 3 in srv.consumed                           # hinter der blockierten Seite, trotzdem erledigt
    assert 1 not in srv.consumed and 2 not in srv.consumed
    gaps = [b - a for a, b in zip(attempts1, attempts1[1:])]
    assert len(gaps) >= 3 and all(y > x for x, y in zip(gaps, gaps[1:]))   # wachsend


def test_run_wachsende_wiederholung_bis_erfolg(key):
    """B2: 1+2 scheitern nur beim ERSTEN Versuch, 3 sofort ok → am Ende alle drei
    angewendet; 1+2 genau zweimal versucht."""
    srv = PagedApprove(page=2)
    for i in (1, 2, 3):
        srv.add(decision(key, i, tid=i))
    clk = _Clock()
    attempts = {}

    def apply(c, d):
        t = c["tid"]
        attempts[t] = attempts.get(t, 0) + 1
        if t in (1, 2) and attempts[t] == 1:
            raise ConnectionError("einmalig weg")

    ap.run(srv, "", "k", _verify(key), apply, lambda d, w: None,
           wait=5, backoff=1, should_stop=_cycles(60), sleep=clk.sleep, clock=clk)

    assert srv.consumed == {1, 2, 3}
    assert attempts[1] == 2 and attempts[2] == 2


def test_run_backoff_greift_auch_bei_ack_fehlschlag(key):
    """Fix: ein transient gescheiterter Eintrag wächst in den exponentiellen Backoff,
    auch wenn der /ack der erfolgreichen Einträge im selben Durchgang fehlschlägt."""
    srv = FakeApprove()
    srv.ack_fails = 999                       # /ack scheitert dauerhaft
    srv.add(decision(key, 1, tid=1))          # wird angewandt → ack (schlägt aber fehl)
    srv.add(decision(key, 2, tid=2))          # schlägt immer fehl → retry
    clk = _Clock()
    attempts2 = []

    def apply(c, d):
        if c["tid"] == 2:
            attempts2.append(clk.t)
            raise ConnectionError("B kaputt")

    ap.run(srv, "", "k", _verify(key), apply, lambda d, w: None,
           wait=5, backoff=1, should_stop=_cycles(60), sleep=clk.sleep, clock=clk)

    assert len(attempts2) >= 3
    assert attempts2 == sorted(attempts2)
    assert (attempts2[2] - attempts2[1]) > (attempts2[1] - attempts2[0])   # wachsend trotz ACK-Fehler


def test_run_ack_500_drosselt_und_bestaetigt_nach_erholung(key):
    """B3: /ack mit 5xx-Status gilt NICHT als gesendet → Backoff statt Hot-Loop, und
    nach Erholung wird idempotent bestätigt."""
    srv = FakeApprove()
    srv.ack_bad = 1                                    # der erste /ack liefert 500
    srv.add(decision(key, 1, tid=1))
    slept = []
    ap.run(srv, "", "k", _verify(key), lambda c, d: None, lambda d, w: None,
           wait=0, backoff=4, should_stop=_cycles(4), sleep=lambda s: slept.append(s))
    assert 4 in slept
    assert 1 in srv.consumed


def test_process_batch_fehlerablage_scheitert_landet_in_retry(key):
    """B4: scheitert die Fehlerablage (Audit kurz weg), darf der Eintrag NICHT bestätigt
    werden – er kommt in retry."""
    def boom(d, why):
        raise RuntimeError("Audit kurz weg")
    d = decision(key, 1)
    d["token"] = d["token"][:-3] + ("AAA" if d["token"][-3:] != "AAA" else "BBB")   # ungültig
    ack, retry = ap.process_batch([d], _verify(key, clock_leeway=0), lambda c, dd: None, boom)
    assert ack == [] and retry == [1]


def test_process_batch_permanent_mit_gescheiterter_fehlerablage_retry(key):
    """B4: auch ein dauerhaft unbrauchbarer Eintrag wird nur bestätigt, wenn die
    Fehlerablage geklappt hat – sonst retry statt spurlos verloren."""
    def boom(d, why):
        raise RuntimeError("Audit weg")

    def apply(c, d):
        raise ap.PermanentError("Auftrag zu")
    ack, retry = ap.process_batch([decision(key, 1)], _verify(key), apply, boom)
    assert ack == [] and retry == [1]


def test_live_verifier_folgt_der_rotation(key, monkeypatch):
    """Der Worker-Verifizierer löst den AKTUELLEN Public Key je Token auf (ohne App-
    Neustart). Hier ein reiner Cache-Tausch OHNE hinterlegten Vorgänger → der alte Token
    gilt nicht mehr, ein mit dem neuen Key signierter schon."""
    monkeypatch.setattr(aj.config, "APPROVAL_MAX_PICKUP_DELAY", 3600)
    v = ap._live_verifier()
    t_alt = aj.make_external_token(7, "approve", "freigabe", 0, ttl_seconds=3600)
    assert v(t_alt)["tid"] == 7
    # „Rotation" ohne Vorgänger: neuer Schlüssel nur im Cache, kein prev in der DB.
    monkeypatch.setattr(aj, "_private_key_cache", Ed25519PrivateKey.generate())
    with pytest.raises(aj.TokenInvalid):
        v(t_alt)                                     # mit altem Key signiert → ungültig
    t_neu = aj.make_external_token(8, "reject", "freigabe", 0, ttl_seconds=3600)
    assert v(t_neu)["tid"] == 8                       # mit neuem Key signiert → gültig


def test_live_verifier_akzeptiert_vorherigen_key_nach_rotation(monkeypatch):
    """Echte Rotation über regenerate_key(): ein mit dem ALTEN Key signierter, noch
    gültiger Link verifiziert weiter (über den aufbewahrten Vorgänger) – sonst ginge die
    angeklickte Entscheidung still verloren."""
    import backend.database.settings as dbsettings
    store: dict = {}
    monkeypatch.setattr(dbsettings, "settings_get", lambda k, d=None: store.get(k, d))
    monkeypatch.setattr(dbsettings, "settings_set", lambda k, v: store.__setitem__(k, v))
    monkeypatch.setattr(aj, "_private_key_cache", None)
    monkeypatch.setattr(aj.config, "APPROVAL_PRIVATE_KEY_PATH", "")
    monkeypatch.setattr(aj.config, "APPROVAL_ISSUER", ISS)
    monkeypatch.setattr(aj.config, "APPROVAL_AUDIENCE", AUD)
    monkeypatch.setattr(aj.config, "APPROVAL_MAX_PICKUP_DELAY", 3600)

    aj.public_key_b64()                                  # aktuellen Key in der DB anlegen
    t_alt = aj.make_external_token(7, "approve", "freigabe", 0, ttl_seconds=3600)   # alter Key
    aj.regenerate_key()                                  # alt → Vorgänger, neu → aktuell
    v = ap._live_verifier()
    assert v(t_alt)["tid"] == 7                           # über den Vorgänger verifiziert
    t_neu = aj.make_external_token(8, "reject", "freigabe", 0, ttl_seconds=3600)    # neuer Key
    assert v(t_neu)["tid"] == 8                           # aktueller Key gilt weiter


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
    # Fachabteilungs-Auflösung (DB) faken → deterministischer Actor-Name.
    monkeypatch.setattr(pactions, "responsible_department_name", lambda *a, **k: "FreigabeHerrLutz")
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


def test_apply_actor_name_ist_fachabteilung(umgebung):
    """„Freigegeben/Abgelehnt von" nennt die zuständige Fachabteilung, nicht den Kanal."""
    store, evstore = umgebung
    ap.apply_decision_entry(_claims(act="approve"), _dec(act="approve"))
    decided = [e for e in evstore.rows if e["action"] == "approval_decided"]
    assert decided and decided[0]["actor_name"] == "FreigabeHerrLutz"


def test_apply_actor_name_fallback_auf_kanal(umgebung, monkeypatch):
    """Lässt sich keine Abteilung auflösen (None), bleibt der Kanal-Name stehen."""
    monkeypatch.setattr(pactions, "responsible_department_name", lambda *a, **k: None)
    store, evstore = umgebung
    ap.apply_decision_entry(_claims(act="approve"), _dec(act="approve"))
    decided = [e for e in evstore.rows if e["action"] == "approval_decided"]
    assert decided and decided[0]["actor_name"] == ap.EXTERNAL_ACTOR


def test_apply_klick_metadaten_nur_im_audit_nicht_im_verlauf(umgebung, monkeypatch):
    """Die unverifizierten Klick-Metadaten (IP/Gerät/Host) gehören ins Audit (admin),
    NICHT in den für alle sichtbaren Ticket-Verlauf."""
    store, evstore = umgebung
    audits = []
    monkeypatch.setattr(approval_commit, "_record_audit", lambda **kw: audits.append(kw))
    ap.apply_decision_entry(_claims(act="approve"), _dec(act="approve"))  # _dec hat ip/ua/host
    ev = [e for e in evstore.rows if e["action"] == "approval_decided"][0]
    assert "klick_metadaten" not in (ev.get("details") or {})      # Verlauf: kein Leck
    aud = [a for a in audits if a.get("action") == "process_approval_decided"][0]
    assert "klick_metadaten" in (aud.get("details") or {})          # Audit: vorhanden


def test_apply_wirkung_gescheitert_wird_sichtbar_quarantaene(umgebung, monkeypatch):
    """Scheitert die Wirkung NACH dem Buchen (hier: engine.transition wirft), gilt die
    Entscheidung NICHT als angewandt: die Wiederzustellung wird sichtbar in die
    Quarantäne gemeldet (PermanentError) statt still ge-ackt."""
    store, evstore = umgebung

    def boom(*a, **k):
        raise RuntimeError("transition kaputt")
    monkeypatch.setattr(engine, "transition", boom)

    with pytest.raises(RuntimeError):                 # 1. Zustellung: gebucht, Wirkung scheitert
        ap.apply_decision_entry(_claims(act="approve"), _dec(act="approve"))
    with pytest.raises(ap.PermanentError):            # 2. Zustellung: nicht still ge-ackt
        ap.apply_decision_entry(_claims(act="approve"), _dec(act="approve"))


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


# ── Zuständige Fachabteilung als Actor-Name (für „Freigegeben/Abgelehnt von") ──

def test_responsible_department_name_eine_gruppe(monkeypatch):
    import backend.database.groups as groups
    monkeypatch.setattr(pactions.pr, "resolve_responsibility",
                        lambda phase, values: {"kind": "group", "group": "g1"})
    monkeypatch.setattr(groups, "get_group_name_from_id",
                        lambda gid: "FreigabeHerrLutz" if gid == "g1" else None)
    assert pactions.responsible_department_name(object(), {}) == "FreigabeHerrLutz"


def test_responsible_department_name_eine_abteilung(monkeypatch):
    import backend.database.groups as groups
    monkeypatch.setattr(pactions.pr, "resolve_responsibility",
                        lambda phase, values: {"kind": "departments",
                                               "departments": [{"group": "g9"}]})
    monkeypatch.setattr(groups, "get_group_name_from_id", lambda gid: "Sekretariat GL")
    assert pactions.responsible_department_name(object(), {}) == "Sekretariat GL"


def test_responsible_department_name_mehrdeutig_ist_none(monkeypatch):
    monkeypatch.setattr(pactions.pr, "resolve_responsibility",
                        lambda phase, values: {"kind": "departments",
                                               "departments": [{"group": "a"}, {"group": "b"}]})
    assert pactions.responsible_department_name(object(), {}) is None


def test_responsible_department_name_fehler_ist_none(monkeypatch):
    def boom(phase, values):
        raise RuntimeError("DB weg")
    monkeypatch.setattr(pactions.pr, "resolve_responsibility", boom)
    assert pactions.responsible_department_name(object(), {}) is None
