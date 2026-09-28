"""
Ebene-1: Freigabe per Mail-Link (kind=approval) – Token, Guard, Entscheidung,
Endpunkt und die beiden Mails. Kein echtes MariaDB: Stores sind Attrappen.

Drei Eigenschaften, die das Alt-System NICHT hatte und die hier scharf geprüft
werden, weil ihr Verlust unsichtbar wäre:
  * der GET verändert nichts (Mail-Clients laden Links vorab),
  * ein Link aus einem alten Durchlauf (Epoch) wirkt nicht mehr,
  * eine zweite Entscheidung wird abgewiesen statt erneut ausgeführt.
"""
import copy
import json
from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from itsdangerous import URLSafeTimedSerializer

from backend.api.v1 import process_approval as papi
from backend.database.process_tickets import ProcessTicketConflict
from backend.schemas.process_definition import ProcessDefinition
from backend.services import process_actions as pactions
from backend.services import process_approval as pa
from backend.services import process_engine as engine
from backend.services import process_events as pev
from backend.services import process_runtime as pr
from backend.utils.config import config


# ── Definition ────────────────────────────────────────────────────────────────

BASIS = {
    "schemaVersion": 1, "key": "einstellung", "name": "Einstellung",
    "fields": [
        {"key": "name", "widget": "text"},
        {"key": "freigabe.entscheidung", "widget": "text"},
        {"key": "freigabe.grund", "widget": "textarea"},
    ],
    "phases": [
        {"key": "erfassung", "kind": "start", "responsibility": {"kind": "owner"},
         "fields": [{"ref": "name", "required": True}]},
        {"key": "freigabe", "kind": "approval", "view": "approval",
         "responsibility": {"kind": "group", "group": "g_freigabe"},
         "approval": {"question": "Einstellung freigeben?",
                      "approveLabel": "Freigeben", "rejectLabel": "Ablehnen",
                      "decisionField": "freigabe.entscheidung",
                      "reasonField": "freigabe.grund"},
         "fields": [{"ref": "name", "mode": "readonly"},
                    {"ref": "freigabe.entscheidung", "mode": "readonly"},
                    {"ref": "freigabe.grund", "mode": "readonly"}]},
        {"key": "backoffice", "kind": "task",
         "responsibility": {"kind": "group", "group": "g_bo"},
         "fields": [{"ref": "name", "mode": "readonly"}]},
    ],
}

GROUPS = [{"id": "g_freigabe", "distributions": ["chef@example.org"]},
          {"id": "g_bo", "distributions": ["bo@example.org"]}]


def raw(**approval_patch) -> dict:
    """Definitions-Rohdaten mit angepasstem approval-Block."""
    d = copy.deepcopy(BASIS)
    d["phases"][1]["approval"].update(approval_patch)
    return d


def defn(**approval_patch) -> ProcessDefinition:
    return ProcessDefinition.model_validate(raw(**approval_patch))


DEFN = defn()


def ticket(d: ProcessDefinition = DEFN, *, phase_index: int = 1,
           values=None, status="in_progress") -> dict:
    values = values or {"name": "Max"}
    rt = pr.initial_runtime(d, "t0", values)
    for _ in range(phase_index):
        rt, status = pr.advance(d, rt, "t1", values)
    return {"id": 7, "process_key": "einstellung", "process_version": 1,
            "title": "Einstellung Max", "owner_id": "u_owner",
            "owner_name": "Antragsteller", "status": status, "priority": "normal",
            "values": dict(values), "runtime": rt, "rev": 0,
            "next_timer_due_at": None, "created_at": "t", "updated_at": "t"}


def token_fuer(row: dict, act: str = "approve", *, phase="freigabe", epoch=None) -> str:
    if epoch is None:
        epoch = int(row["runtime"].get("epoch", 0))
    return pa.make_token(row["id"], act, phase, epoch)


# ── Token ─────────────────────────────────────────────────────────────────────

def test_token_traegt_ticket_aktion_phase_und_epoch():
    t = pa.make_token(7, "approve", "freigabe", 3)
    payload, _issued = pa.require_token(t)
    assert payload == {"tid": 7, "act": "approve", "phase": "freigabe", "epoch": 3}


def test_token_kennt_nur_die_beiden_aktionen():
    with pytest.raises(ValueError):
        pa.make_token(7, "vielleicht", "freigabe", 0)


def test_manipuliertes_token_wird_abgewiesen():
    t = pa.make_token(7, "approve", "freigabe", 0)
    kaputt = ("X" if t[0] != "X" else "Y") + t[1:]
    assert pa.load_token(kaputt) is None
    with pytest.raises(pa.ApprovalError) as exc:
        pa.require_token(kaputt)
    assert exc.value.code == "invalid"


def test_token_des_altsystems_gilt_hier_nicht():
    """Gleicher SECRET_KEY, anderer Salt – die Wirkungsräume bleiben getrennt."""
    alt = URLSafeTimedSerializer(config.SECRET_KEY, salt="freigabe-v1")
    fremd = alt.dumps({"tid": 7, "act": "approve", "phase": "freigabe", "epoch": 0})
    assert pa.load_token(fremd) is None


def test_token_ohne_pflichtfelder_ist_ungueltig():
    eigen = URLSafeTimedSerializer(config.SECRET_KEY, salt=pa.SALT)
    assert pa.load_token(eigen.dumps({"tid": 7, "act": "approve"})) is None
    assert pa.load_token(eigen.dumps({"tid": "7", "act": "approve",
                                      "phase": "freigabe", "epoch": 0})) is None
    assert pa.load_token("") is None


def test_abgelaufenes_token():
    spec = DEFN.phases[1].approval          # linkMaxAge = P7D (Default)
    _payload, issued = pa.require_token(pa.make_token(7, "approve", "freigabe", 0))
    pa.assert_fresh(issued, spec, now=issued + timedelta(days=6, hours=23))
    with pytest.raises(pa.ApprovalError) as exc:
        pa.assert_fresh(issued, spec, now=issued + timedelta(days=7, seconds=1))
    assert exc.value.code == "expired"


def test_max_age_kommt_aus_der_definition():
    assert pa.max_age_seconds(DEFN.phases[1].approval) == 7 * 24 * 3600
    assert pa.max_age_seconds(defn(linkMaxAge="PT12H").phases[1].approval) == 12 * 3600


# ── Phasen-Guard ──────────────────────────────────────────────────────────────

def _guard(row, d=DEFN, **tok):
    payload, _ = pa.require_token(token_fuer(row, **tok))
    return pa.approval_context(row, d, payload)


def test_guard_laesst_die_richtige_phase_durch():
    idx, phase, spec = _guard(ticket())
    assert idx == 1 and phase.key == "freigabe" and spec.question == "Einstellung freigeben?"


def test_guard_weist_falschen_epoch_ab():
    """Nach einer Wiederaufnahme darf der alte Link nicht mehr wirken."""
    row = ticket()
    row["runtime"]["epoch"] = 1
    with pytest.raises(pa.ApprovalError) as exc:
        _guard(row, epoch=0)
    assert exc.value.code == "superseded"


def test_guard_weist_falsche_phase_ab():
    row = ticket(phase_index=2)             # steht im BackOffice
    with pytest.raises(pa.ApprovalError) as exc:
        _guard(row)
    assert exc.value.code == "closed"


def test_guard_weist_fremdes_ticket_ab():
    row = ticket()
    payload, _ = pa.require_token(pa.make_token(999, "approve", "freigabe", 0))
    with pytest.raises(pa.ApprovalError) as exc:
        pa.approval_context(row, DEFN, payload)
    assert exc.value.code == "invalid"


def test_guard_weist_abgelehnten_auftrag_ab():
    row = ticket()
    pr.reject(row["runtime"])
    with pytest.raises(pa.ApprovalError) as exc:
        _guard(row)
    assert exc.value.code == "closed"


def test_guard_weist_zweite_entscheidung_ab():
    row = ticket()
    pr.set_phase_decision(row["runtime"], 1, act="approve", by=None,
                          by_name="X", at="t2")
    with pytest.raises(pa.ApprovalError) as exc:
        _guard(row)
    assert exc.value.code == "already"


# ── Begründung ────────────────────────────────────────────────────────────────

def test_begruendung_ist_bei_ablehnung_pflicht():
    spec = DEFN.phases[1].approval          # requireReason = True (Default)
    with pytest.raises(pa.ApprovalError) as exc:
        pa.normalize_reason(spec, pa.REJECT, "   ")
    assert exc.value.code == "reason_required"
    # Für eine Zustimmung gilt die Pflicht nicht.
    assert pa.normalize_reason(spec, pa.APPROVE, "") is None
    assert pa.normalize_reason(spec, pa.REJECT, "  Budget fehlt ") == "Budget fehlt"


def test_begruendung_kann_abgeschaltet_werden():
    spec = defn(requireReason=False).phases[1].approval
    assert pa.normalize_reason(spec, pa.REJECT, "") is None


def test_zu_lange_begruendung():
    with pytest.raises(pa.ApprovalError) as exc:
        pa.normalize_reason(DEFN.phases[1].approval, pa.REJECT, "x" * 5001)
    assert exc.value.code == "reason_too_long"


# ── Entscheidung festschreiben ────────────────────────────────────────────────

def test_entscheidung_landet_im_runtime_und_in_den_feldern():
    row = ticket()
    spec = DEFN.phases[1].approval
    runtime, values = pa.apply_decision(row, spec, 1, act="reject",
                                        reason="Budget fehlt", now_iso="t5")
    d = pr.phase_decision(runtime, 1)
    assert d["act"] == "reject" and d["at"] == "t5" and d["by"] is None
    assert values["freigabe.entscheidung"] == "reject"
    assert values["freigabe.grund"] == "Budget fehlt"


def test_begruendung_steht_nicht_doppelt_im_runtime():
    """Der Runtime geht ungefiltert an jede Person mit Leserecht – ein Text, der
    laut Definition in ein Feld gehört, darf hier kein Zweitkanal sein."""
    row = ticket()
    runtime, _v = pa.apply_decision(row, DEFN.phases[1].approval, 1, act="reject",
                                    reason="Budget fehlt", now_iso="t5")
    d = pr.phase_decision(runtime, 1)
    assert d["reason"] is None and d["reason_in_field"] is True


def test_ohne_reasonfield_steht_die_begruendung_im_runtime():
    spec = defn(reasonField=None).phases[1].approval
    runtime, values = pa.apply_decision(ticket(), spec, 1, act="reject",
                                        reason="Budget fehlt", now_iso="t5")
    d = pr.phase_decision(runtime, 1)
    assert d["reason"] == "Budget fehlt" and d["reason_in_field"] is False
    assert values["freigabe.entscheidung"] == "reject"


def test_ohne_zielfelder_werden_keine_werte_geschrieben():
    spec = defn(decisionField=None, reasonField=None).phases[1].approval
    _runtime, values = pa.apply_decision(ticket(), spec, 1, act="approve",
                                         reason=None, now_iso="t5")
    assert values is None                    # nichts zu speichern


def test_zweite_entscheidung_wird_verweigert():
    row = ticket()
    pa.apply_decision(row, DEFN.phases[1].approval, 1, act="approve",
                      reason=None, now_iso="t5")
    with pytest.raises(ValueError):
        pa.apply_decision(row, DEFN.phases[1].approval, 1, act="reject",
                          reason="doch nicht", now_iso="t6")


def test_follow_up_liest_onreject():
    assert pa.follow_up(DEFN.phases[1].approval) == ("reject", None)
    assert pa.follow_up(defn(onReject="back_to:erfassung").phases[1].approval) \
        == ("send_back", "erfassung")


# ── Rücksprung (Runtime) ──────────────────────────────────────────────────────

def test_send_back_springt_zurueck_und_setzt_spaetere_phasen_zurueck():
    row = ticket(phase_index=2)              # BackOffice
    rt, status = pr.send_back(DEFN, row["runtime"], "t9", "erfassung", row["values"])
    assert rt["current_index"] == 0 and status == "in_progress"
    assert rt["phases"][0]["status"] == "open" and rt["phases"][0]["entered_at"] == "t9"
    assert rt["phases"][1]["status"] == "pending" and rt["phases"][1]["entered_at"] is None
    assert rt["phases"][2]["status"] == "pending"
    assert rt["rejected"] is False


def test_send_back_erhoeht_den_epoch_und_verwirft_die_entscheidung():
    """Sonst blieben die Fristen der Zielphase stumm UND der Link aus Runde 1
    wäre in Runde 2 wieder gültig."""
    row = ticket()
    pr.set_phase_decision(row["runtime"], 1, act="reject", by=None, by_name="X", at="t2")
    rt, _s = pr.send_back(DEFN, row["runtime"], "t9", "erfassung", row["values"])
    assert rt["epoch"] == 1
    assert pr.phase_decision(rt, 1) is None


def test_send_back_kennt_nur_frueher_liegende_phasen():
    row = ticket()
    with pytest.raises(ValueError):
        pr.send_back(DEFN, row["runtime"], "t9", "backoffice", row["values"])
    with pytest.raises(ValueError):
        pr.send_back(DEFN, row["runtime"], "t9", "gibtsnicht", row["values"])


def test_reopen_verwirft_die_entscheidung_ebenfalls():
    row = ticket(phase_index=3)              # durchgelaufen
    pr.set_phase_decision(row["runtime"], 1, act="approve", by=None, by_name="X", at="t2")
    rt, _s = pr.reopen(DEFN, row["runtime"], "t9", phase_key="freigabe")
    assert pr.phase_decision(rt, 1) is None


# ── Endpunkt ──────────────────────────────────────────────────────────────────

class FakeStore:
    ProcessTicketConflict = ProcessTicketConflict

    def __init__(self, row):
        self.rows = {row["id"]: copy.deepcopy(row)}

    def get(self, tid):
        r = self.rows.get(tid)
        return copy.deepcopy(r) if r else None

    def _guard(self, r, expected_rev):
        if expected_rev is not None and r["rev"] != expected_rev:
            raise ProcessTicketConflict(f"#{r['id']} geändert")

    def update_runtime(self, tid, *, runtime_json, status, next_timer_due_at=None,
                       expected_rev=None):
        r = self.rows[tid]
        self._guard(r, expected_rev)
        r["runtime"] = json.loads(runtime_json)
        r["status"] = status
        r["next_timer_due_at"] = next_timer_due_at
        r["rev"] += 1
        return copy.deepcopy(r)

    def update_values(self, tid, values_json, title=None, expected_rev=None):
        r = self.rows[tid]
        self._guard(r, expected_rev)
        r["values"] = json.loads(values_json)
        r["rev"] += 1
        return copy.deepcopy(r)

    def set_next_timer(self, tid, v, expected_rev=None):
        self.rows[tid]["next_timer_due_at"] = v

    def set_priority(self, tid, v, expected_rev=None):
        self.rows[tid]["priority"] = v

    def set_status(self, tid, v, expected_rev=None):
        self.rows[tid]["status"] = v


class FakeDefs:
    def __init__(self, definition_raw):
        self.raw = definition_raw

    def get_definition(self, key, ver):
        return {"version": ver, "definition": self.raw} if key == "einstellung" else None


class FakeFires:
    def fired_map(self, tid, pk, ep):
        return {}

    def claim(self, *a, **k):
        return True


class FakeEvents:
    def __init__(self):
        self.rows = []

    def add_event(self, **kw):
        ev = {"id": len(self.rows) + 1, "created_at": "t", **kw}
        ev["details"] = kw.get("details") or {}
        self.rows.append(ev)
        return dict(ev)


@pytest.fixture
def umgebung(monkeypatch):
    """Baut die Testumgebung; `bauen(**approval_patch)` liefert (client, store, mails)."""
    def bauen(**approval_patch):
        d_raw = raw(**approval_patch)
        d = ProcessDefinition.model_validate(d_raw)
        store = FakeStore(ticket(d))
        evstore = FakeEvents()
        mails: list = []

        monkeypatch.setattr(papi, "store", store)
        monkeypatch.setattr(papi, "defstore", FakeDefs(d_raw))
        monkeypatch.setattr(papi, "record_audit", lambda **kw: None)
        monkeypatch.setattr(engine, "store", store)
        monkeypatch.setattr(engine, "fires", FakeFires())
        monkeypatch.setattr(engine, "record_audit", lambda **kw: None)
        monkeypatch.setattr(pev, "store", evstore)
        monkeypatch.setattr(pev, "record_audit", lambda **kw: None)
        # Mails: nur festhalten, nicht versenden.
        monkeypatch.setattr(pactions, "notify_phase_entry", lambda *a, **k: [])
        monkeypatch.setattr(pactions, "notify_rejection",
                            lambda row, defn_, **kw: mails.append(("rejection", kw)) or [])
        monkeypatch.setattr(pactions, "notify_sent_back",
                            lambda row, defn_, phase, **kw: mails.append(("sent_back", kw)) or [])

        app = FastAPI()
        app.include_router(papi.router)
        return TestClient(app), store, evstore, mails
    return bauen


def test_get_zeigt_die_frage_und_aendert_nichts(umgebung):
    client, store, evstore, _m = umgebung()
    vorher = copy.deepcopy(store.rows)
    t = token_fuer(store.rows[7])
    r = client.get("/process-freigabe", params={"token": t})
    assert r.status_code == 200
    assert "Einstellung freigeben?" in r.text
    assert "Freigeben" in r.text and "Ablehnen" in r.text
    # Der eigentliche Punkt: KEIN Seiteneffekt (Scanner laden Links vorab).
    assert store.rows == vorher
    assert evstore.rows == []
    # Mehrfaches Vorladen ändert daran nichts.
    client.get("/process-freigabe", params={"token": t})
    assert store.rows == vorher


def test_get_mit_kaputtem_token_zeigt_eine_freundliche_seite(umgebung):
    client, *_ = umgebung()
    r = client.get("/process-freigabe", params={"token": "voellig-kaputt"})
    assert r.status_code == 200
    assert "ungültig" in r.text


def test_get_ohne_token(umgebung):
    client, *_ = umgebung()
    assert client.get("/process-freigabe").status_code == 200


def test_post_freigabe_schaltet_weiter(umgebung):
    client, store, evstore, _m = umgebung()
    t = token_fuer(store.rows[7])
    r = client.post("/process-freigabe", data={"token": t, "act": "approve"})
    assert r.status_code == 200 and "Freigegeben" in r.text
    row = store.rows[7]
    assert row["runtime"]["current_index"] == 2
    assert row["status"] == "in_progress"
    assert row["values"]["freigabe.entscheidung"] == "approve"
    entscheidung = pr.phase_decision(row["runtime"], 1)
    assert entscheidung["act"] == "approve" and entscheidung["by"] is None
    aktionen = [e["action"] for e in evstore.rows]
    assert pa.EVENT_DECIDED in aktionen and "advanced" in aktionen


def test_post_ablehnung_lehnt_den_auftrag_ab(umgebung):
    client, store, evstore, mails = umgebung()
    t = token_fuer(store.rows[7], "reject")
    r = client.post("/process-freigabe",
                    data={"token": t, "act": "reject", "reason": "Budget fehlt"})
    assert r.status_code == 200 and "Abgelehnt" in r.text
    row = store.rows[7]
    assert row["status"] == "rejected" and row["runtime"]["rejected"] is True
    assert row["values"]["freigabe.grund"] == "Budget fehlt"
    assert [k for k, _ in mails] == ["rejection"]
    assert mails[0][1]["reason"] == "Budget fehlt"


def test_post_ablehnung_ohne_grund_wird_nicht_ausgefuehrt(umgebung):
    client, store, evstore, _m = umgebung()
    vorher = copy.deepcopy(store.rows)
    t = token_fuer(store.rows[7], "reject")
    r = client.post("/process-freigabe", data={"token": t, "act": "reject", "reason": " "})
    assert r.status_code == 200
    assert "Bitte begründen" in r.text          # zurück auf die Bestätigungsseite
    assert store.rows == vorher and evstore.rows == []


def test_post_rueckgabe_zur_nachbesserung(umgebung):
    client, store, evstore, mails = umgebung(onReject="back_to:erfassung")
    t = token_fuer(store.rows[7], "reject")
    r = client.post("/process-freigabe",
                    data={"token": t, "act": "reject", "reason": "Bitte Gehalt ergänzen"})
    assert r.status_code == 200 and "Nachbesserung" in r.text
    row = store.rows[7]
    assert row["runtime"]["current_index"] == 0        # zurück in der Erfassung
    assert row["runtime"]["phases"][1]["status"] == "pending"
    assert row["runtime"]["rejected"] is False and row["status"] == "in_progress"
    assert row["runtime"]["epoch"] == 1                # alter Link ist damit tot
    assert pr.phase_decision(row["runtime"], 1) is None
    assert [k for k, _ in mails] == ["sent_back"]
    assert pa.EVENT_SENT_BACK in [e["action"] for e in evstore.rows]


def test_alter_link_wirkt_nach_der_rueckgabe_nicht_mehr(umgebung):
    client, store, _e, _m = umgebung(onReject="back_to:erfassung")
    alt = token_fuer(store.rows[7], "approve")
    client.post("/process-freigabe",
                data={"token": token_fuer(store.rows[7], "reject"), "act": "reject",
                      "reason": "Bitte nachbessern"})
    # Auftrag steht wieder in der Freigabe – aber im NÄCHSTEN Durchlauf.
    store.rows[7]["runtime"]["current_index"] = 1
    store.rows[7]["runtime"]["phases"][1]["status"] = "open"
    r = client.post("/process-freigabe", data={"token": alt, "act": "approve"})
    assert "nicht mehr aktuell" in r.text
    assert store.rows[7]["runtime"]["current_index"] == 1


def test_zweite_entscheidung_wird_abgewiesen(umgebung):
    client, store, _e, _m = umgebung()
    t = token_fuer(store.rows[7])
    assert client.post("/process-freigabe", data={"token": t, "act": "approve"}).status_code == 200
    nachher = copy.deepcopy(store.rows)
    r = client.post("/process-freigabe", data={"token": t, "act": "approve"})
    assert r.status_code == 200
    assert "Nichts mehr zu entscheiden" in r.text or "Bereits bearbeitet" in r.text
    assert store.rows == nachher                # wirklich nichts passiert


def test_post_mit_unbekannter_aktion(umgebung):
    client, store, _e, _m = umgebung()
    vorher = copy.deepcopy(store.rows)
    r = client.post("/process-freigabe",
                    data={"token": token_fuer(store.rows[7]), "act": "vielleicht"})
    assert r.status_code == 200 and store.rows == vorher


def test_abgelaufener_link_am_endpunkt(umgebung, monkeypatch):
    client, store, _e, _m = umgebung()

    def abgelaufen(*_a, **_k):
        raise pa.ApprovalError("expired", "Dieser Freigabe-Link ist abgelaufen")
    monkeypatch.setattr(pa, "assert_fresh", abgelaufen)
    r = client.get("/process-freigabe", params={"token": token_fuer(store.rows[7])})
    assert r.status_code == 200 and "abgelaufen" in r.text


# ── Mails ─────────────────────────────────────────────────────────────────────

def _capture():
    sent: list = []

    def sender(recips, subject, body, kind=None):
        sent.append({"to": recips, "subject": subject, "body": body, "kind": kind})
    return sent, sender


def test_freigabe_mail_enthaelt_beide_links(monkeypatch):
    monkeypatch.setattr(pactions, "watcher_emails", lambda tid: [])
    sent, sender = _capture()
    row = ticket()
    out = pactions.notify_phase_entry(row, DEFN, DEFN.phases[1], sender=sender,
                                      groups=GROUPS)
    assert out == ["chef@example.org"]
    assert len(sent) == 1 and sent[0]["kind"] == "approval_link"
    assert "Einstellung freigeben?" in sent[0]["body"]
    approve_url, reject_url = pactions.approval_links(row, DEFN.phases[1])
    assert approve_url in sent[0]["body"] and reject_url in sent[0]["body"]
    # ... und die Links tragen wirklich die beiden Richtungen.
    marke = "token="
    tokens = [teil.split("token=")[1].split('"')[0]
              for teil in sent[0]["body"].split("href=") if marke in teil]
    assert {pa.load_token(t)["act"] for t in tokens} == {"approve", "reject"}
    assert all(pa.load_token(t)["phase"] == "freigabe" for t in tokens)


def test_ohne_externallink_geht_die_normale_aufgaben_mail_raus(monkeypatch):
    monkeypatch.setattr(pactions, "watcher_emails", lambda tid: [])
    d = defn(externalLink=False)
    sent, sender = _capture()
    out = pactions.notify_phase_entry(ticket(d), d, d.phases[1], sender=sender,
                                      groups=GROUPS)
    assert out == ["chef@example.org"]
    assert sent[0]["kind"] == "phase_entry"
    assert "process-freigabe" not in sent[0]["body"]


def test_beobachter_bekommen_ueberhaupt_keine_mail(monkeypatch):
    """Beobachten heißt MITLESEN: der Auftrag steht in der Übersicht und zeigt dort
    den Stand. Eine Mail je Phasenwechsel würde die Mails unwichtig machen, die
    wirklich eine Aufgabe ankündigen – und ein Entscheidungs-Link an eine nur
    mitlesende Person wäre ohnehin falsch."""
    monkeypatch.setattr(pactions, "watcher_emails", lambda tid: ["beobachter@example.org"])
    sent, sender = _capture()
    empfaenger = pactions.notify_phase_entry(ticket(), DEFN, DEFN.phases[1],
                                             sender=sender, groups=GROUPS)
    assert "beobachter@example.org" not in empfaenger
    for m in sent:
        assert "beobachter@example.org" not in m["to"]


def test_fehlender_verteiler_bleibt_nicht_stumm(monkeypatch):
    """Ohne Empfänger:in wartet der Auftrag auf eine Entscheidung, die niemand
    angefordert bekommen hat – das muss im Audit UND im Verlauf auftauchen."""
    monkeypatch.setattr(pactions, "watcher_emails", lambda tid: [])
    monkeypatch.setattr(config, "TICKET_MAIL", "")
    audits: list = []
    verlauf: list = []
    import backend.database.audit_log as audit_mod
    monkeypatch.setattr(audit_mod, "record_audit", lambda **kw: audits.append(kw))
    monkeypatch.setattr(pev, "system", lambda row, action, **kw: verlauf.append(action))

    sent, sender = _capture()
    out = pactions.notify_phase_entry(ticket(), DEFN, DEFN.phases[1], sender=sender,
                                      groups=[{"id": "g_freigabe", "distributions": []}])
    assert out == [] and sent == []
    assert audits and audits[0]["action"] == "process_approval_no_recipient"
    assert verlauf == ["approval_no_recipient"]


def test_ersatzzustellung_an_die_zentraladresse_wird_gemeldet(monkeypatch):
    monkeypatch.setattr(pactions, "watcher_emails", lambda tid: [])
    monkeypatch.setattr(config, "TICKET_MAIL", "zentrale@example.org")
    audits: list = []
    import backend.database.audit_log as audit_mod
    monkeypatch.setattr(audit_mod, "record_audit", lambda **kw: audits.append(kw))
    monkeypatch.setattr(pev, "system", lambda *a, **k: None)

    sent, sender = _capture()
    out = pactions.notify_phase_entry(ticket(), DEFN, DEFN.phases[1], sender=sender,
                                      groups=[{"id": "g_freigabe", "distributions": []}])
    assert out == ["zentrale@example.org"]      # zugestellt, aber ersatzweise
    assert sent and sent[0]["kind"] == "approval_link"
    assert audits and audits[0]["action"] == "process_approval_no_recipient"


def test_ablehnungsmail_geht_an_die_erstellerin_mit_begruendung(monkeypatch):
    monkeypatch.setattr(pactions, "_user_email",
                        lambda uid: "owner@example.org" if uid == "u_owner" else None)
    sent, sender = _capture()
    out = pactions.notify_rejection(ticket(), DEFN, reason="Budget fehlt <b>",
                                    by_name=pa.ACTOR_NAME, sender=sender, groups=[])
    assert out == ["owner@example.org"]
    assert sent[0]["kind"] == "rejection"
    assert "Budget fehlt &lt;b&gt;" in sent[0]["body"]      # Freitext escapt
    assert "\n" not in sent[0]["subject"] and "\r" not in sent[0]["subject"]


def test_ablehnungsmail_bricht_nichts_ab(monkeypatch):
    monkeypatch.setattr(pactions, "_user_email", lambda uid: "owner@example.org")

    def boom(*a, **k):
        raise RuntimeError("Graph down")
    assert pactions.notify_rejection(ticket(), DEFN, reason="x", by_name="y",
                                     sender=boom, groups=[]) == []


def test_nachbesserungsmail_erreicht_die_erstellerin(monkeypatch):
    """Die Zielphase gehört der Ersteller:in – notify_phase_entry würde sie
    bewusst überspringen, hier muss sie erreicht werden."""
    monkeypatch.setattr(pactions, "_user_email",
                        lambda uid: "owner@example.org" if uid == "u_owner" else None)
    monkeypatch.setattr(pactions, "watcher_emails", lambda tid: [])
    sent, sender = _capture()
    row = ticket(phase_index=0)
    out = pactions.notify_sent_back(row, DEFN, DEFN.phases[0], reason="Gehalt fehlt",
                                    by_name=pa.ACTOR_NAME, sender=sender, groups=[])
    assert out == ["owner@example.org"]
    assert sent[0]["kind"] == "sent_back" and "Gehalt fehlt" in sent[0]["body"]


def test_betreff_kennt_keine_zeilenumbrueche(monkeypatch):
    """Header-Injection über den Auftragstitel."""
    monkeypatch.setattr(pactions, "watcher_emails", lambda tid: [])
    sent, sender = _capture()
    row = ticket()
    row["title"] = "Böse\r\nBcc: opfer@example.org"
    pactions.notify_phase_entry(row, DEFN, DEFN.phases[1], sender=sender, groups=GROUPS)
    assert "\r" not in sent[0]["subject"] and "\n" not in sent[0]["subject"]
