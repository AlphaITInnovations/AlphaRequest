"""
Verlauf, Nachträge, Wiederaufnahme und Beobachter:innen der Prozess-Aufträge.

Vier Lücken gegenüber dem Alt-System, die hier geschlossen werden:
  * je Auftrag ein nachvollziehbarer Verlauf – aber REDIGIERT (der Verlauf darf
    kein Nebenkanal um die Feld-Sichtbarkeit herum sein),
  * Nachträge (auch nur-intern für die bearbeitende Seite),
  * Wiederaufnahme eines fertigen Auftrags MIT Epoch-Bump (sonst bleiben die
    Fristen im zweiten Durchlauf stumm),
  * Beobachter:innen als Weg zu Dauer-Einsicht ohne Zuständigkeit.

Ebene 1: kein echtes MariaDB, Stores sind In-Memory-Attrappen.
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
from backend.services import process_access as acc
from backend.services import process_actions as pactions
from backend.services import process_events as pev
from backend.services import process_runtime as pr
from backend.services import process_visibility as vis

# „gehalt" ist vertraulich (hartes Gate: nur g_hr), „notiz" nur für g_it sichtbar.
DEFN_RAW = {
    "schemaVersion": 1, "key": "demo", "name": "Demo",
    "fields": [
        {"key": "name", "widget": "text"},
        {"key": "gehalt", "widget": "text",
         "visibility": {"confidential": True, "visibleToGroups": ["g_hr"]}},
        {"key": "notiz", "widget": "text", "visibility": {"visibleToGroups": ["g_it"]}},
    ],
    "phases": [
        {"key": "start", "kind": "start", "responsibility": {"kind": "owner"},
         "fields": [{"ref": "name", "required": True}, {"ref": "gehalt"}]},
        {"key": "pruefung", "kind": "review",
         "responsibility": {"kind": "departments",
                            "rule": [{"group": "g_it"}, {"group": "g_fp", "required": False}]},
         "fields": [{"ref": "name", "mode": "readonly"}, {"ref": "notiz", "mode": "editable"}]},
    ],
}
DEFN = ProcessDefinition.model_validate(DEFN_RAW)

ADMIN = {"id": "u_admin", "displayName": "Admin", "permissions": ["admin"]}
OWNER = {"id": "u_owner", "displayName": "Antragsteller", "permissions": []}
ITLER = {"id": "u_it", "displayName": "IT-Mensch", "permissions": []}
FREMD = {"id": "u_x", "displayName": "Fremd", "permissions": []}


def _row(phase_index=0, values=None, status="in_progress"):
    values = values or {"name": "Max"}
    rt = pr.initial_runtime(DEFN, "t0", values)
    for _ in range(phase_index):
        rt, status = pr.advance(DEFN, rt, "t1", values)
    return {"id": 7, "process_key": "demo", "process_version": 1, "title": "Testauftrag",
            "owner_id": "u_owner", "status": status, "priority": "normal",
            "values": values, "runtime": rt, "rev": 0,
            "next_timer_due_at": None, "created_at": "t", "updated_at": "t"}


# ── Wiederaufnahme (reine Runtime-Logik) ─────────────────────────────────────

def test_reopen_erhoeht_den_epoch():
    """Ohne Epoch-Bump würde eine bereits gefeuerte Eskalation im zweiten
    Durchlauf nie wieder feuern – der Auftrag hätte stumme Fristen."""
    rt = _row(phase_index=2)["runtime"]          # durchgelaufen → archiviert
    assert rt["epoch"] == 0
    rt2, status = pr.reopen(DEFN, rt, "t9")
    assert rt2["epoch"] == 1
    assert status == "in_request"                # letzte betretene Phase = pruefung
    assert rt2["current_index"] == 1
    assert rt2["rejected"] is False


def test_reopen_setzt_entered_at_neu():
    """Die Frist läuft ab der Wiederaufnahme, nicht ab dem ersten Betreten."""
    rt = _row(phase_index=2)["runtime"]
    alt = rt["phases"][1]["entered_at"]
    rt2, _ = pr.reopen(DEFN, rt, "t9")
    assert alt == "t1" and rt2["phases"][1]["entered_at"] == "t9"


def test_reopen_auf_bestimmte_phase_setzt_spaetere_zurueck():
    rt = _row(phase_index=2)["runtime"]
    rt2, status = pr.reopen(DEFN, rt, "t9", phase_key="start", values={"name": "Max"})
    assert rt2["current_index"] == 0 and status == "in_progress"
    assert rt2["phases"][0]["status"] == "open"
    assert rt2["phases"][1]["status"] == "pending"
    assert rt2["phases"][1]["entered_at"] is None


def test_reopen_seedet_abteilungen_neu():
    rt = _row(phase_index=1)["runtime"]
    pr.set_department_status(rt, "g_it", "done", by="u", by_name="X", at="t2")
    rt, _ = pr.advance(DEFN, rt, "t3", {"name": "Max"})       # → archiviert
    rt2, _ = pr.reopen(DEFN, rt, "t9", phase_key="pruefung", values={"name": "Max"})
    stand = {d["group"]: d["status"] for d in pr.current_departments(rt2)}
    assert stand == {"g_it": "open", "g_fp": "open"}


def test_reopen_kennt_nur_echte_phasen():
    rt = _row(phase_index=2)["runtime"]
    with pytest.raises(ValueError):
        pr.reopen(DEFN, rt, "t9", phase_key="gibtsnicht")


def test_reopen_hebt_ablehnung_auf():
    rt = pr.reject(_row(phase_index=1)["runtime"])
    rt2, _ = pr.reopen(DEFN, rt, "t9")
    assert rt2["rejected"] is False and pr.is_terminal(rt2) is False


# ── Bearbeitende Seite (stabil über Phasen hinweg) ───────────────────────────

def test_staff_groups_ist_phasenunabhaengig():
    assert acc.staff_groups(DEFN) == {"g_it", "g_fp"}


def test_is_process_staff():
    assert acc.is_process_staff(DEFN, ITLER, ["g_it"]) is True
    assert acc.is_process_staff(DEFN, OWNER, []) is False
    # Aufsicht zählt auch ohne Gruppenmitgliedschaft.
    assert acc.is_process_staff(DEFN, {"id": "u_v", "permissions": ["view"]}, []) is True


# ── Redaktion des Verlaufs ───────────────────────────────────────────────────

def _ctx(user, group_ids=()):
    return vis.build_viewer_ctx(user, _row(), DEFN, group_ids=set(group_ids))


def _ev(**kw):
    base = {"id": 1, "action": "updated", "phase_key": "start", "epoch": 0,
            "actor_id": "u1", "actor_name": "X", "actor_type": "user",
            "internal": False, "body": None, "details": {}, "created_at": "t"}
    return {**base, **kw}


def test_interne_nachtraege_nur_fuer_bearbeitende_seite():
    evs = [_ev(action="comment", internal=True, body="intern"),
           _ev(id=2, action="comment", body="offen")]
    fuer_owner = pev.redact(evs, DEFN, _ctx(OWNER), staff=False)
    assert [e["body"] for e in fuer_owner] == ["offen"]
    fuer_it = pev.redact(evs, DEFN, _ctx(ITLER, ["g_it"]), staff=True)
    assert [e["body"] for e in fuer_it] == ["intern", "offen"]


def test_eintrag_ueber_unsichtbares_feld_entfaellt_ganz():
    """Auch „es wurde etwas geändert" ist Information über ein vertrauliches Feld."""
    evs = [_ev(details={"fields": ["gehalt"]})]
    assert pev.redact(evs, DEFN, _ctx(OWNER), staff=False) == []
    # HR darf – die Gruppe ist im harten Gate hinterlegt.
    hr = pev.redact(evs, DEFN, _ctx(FREMD, ["g_hr"]), staff=False)
    assert hr[0]["details"]["fields"] == ["gehalt"]


def test_teilweise_sichtbarer_eintrag_wird_gekuerzt_und_zaehlt_ehrlich():
    evs = [_ev(details={"fields": ["name", "gehalt"]})]
    out = pev.redact(evs, DEFN, _ctx(OWNER), staff=False)
    assert out[0]["details"]["fields"] == ["name"]
    assert out[0]["details"]["fields_hidden"] == 1


def test_einzelfeld_referenz_wird_geprueft():
    evs = [_ev(action="automation_fired", details={"field": "gehalt"})]
    assert pev.redact(evs, DEFN, _ctx(OWNER), staff=False) == []
    assert len(pev.redact(evs, DEFN, _ctx(ADMIN), staff=True)) == 1


def test_feldwerte_werden_defensiv_entfernt():
    """Werte gehören nicht in den Verlauf – falls doch, gehen sie nicht raus."""
    evs = [_ev(details={"values": {"gehalt": "100000"}, "fields": ["name"]})]
    out = pev.redact(evs, DEFN, _ctx(ADMIN), staff=True)
    assert "values" not in out[0]["details"]


def test_vollsicht_umgeht_vertraulich_NICHT():
    voll = vis.build_viewer_ctx({"id": "u_v", "permissions": ["view"]}, _row(), DEFN,
                                group_ids=set())
    evs = [_ev(details={"fields": ["gehalt"]})]
    assert pev.redact(evs, DEFN, voll, staff=True) == []


# ── Mail-Adressen (Regression) ───────────────────────────────────────────────

def test_user_email_versteht_die_appuser_dataclass():
    """`get_user` liefert eine Dataclass, kein dict. Mit `.get()` lief das in ein
    stilles None – jede persönliche Mail wäre auf die Zentraladresse gefallen."""
    from backend.database.users import AppUser
    u = AppUser(microsoft_id="u_it", display_name="IT", email="it@example.org",
                role="user", extra_permissions=[], created_at="t", last_login="t")
    import backend.database.users as users_mod
    orig = users_mod.get_user
    users_mod.get_user = lambda uid: u if uid == "u_it" else None
    try:
        assert pactions._user_email("u_it") == "it@example.org"
        assert pactions._user_email("u_nix") is None
    finally:
        users_mod.get_user = orig


# ── Nachtrags-Benachrichtigung ───────────────────────────────────────────────

def _capture():
    sent = []
    return sent, lambda to, subj, body, kind=None: sent.append({"to": to, "kind": kind,
                                                                "subject": subj})


def test_nachtrag_geht_an_zustaendige_ersteller_und_beobachter(monkeypatch):
    monkeypatch.setattr(pactions, "_user_email",
                        lambda uid: {"u_owner": "owner@x.de", "u_w": "watch@x.de"}.get(uid))
    monkeypatch.setattr(pactions, "watcher_emails", lambda tid: ["watch@x.de"])
    sent, sender = _capture()
    out = pactions.notify_comment(_row(phase_index=1), DEFN.phases[1],
                                  author_name="IT", body_text="Bitte prüfen",
                                  sender=sender,
                                  groups=[{"id": "g_it", "distributions": ["it@x.de"]},
                                          {"id": "g_fp", "distributions": ["fp@x.de"]}])
    assert set(out) == {"it@x.de", "fp@x.de", "owner@x.de", "watch@x.de"}
    assert sent[0]["kind"] == "comment"


def test_interner_nachtrag_geht_nicht_an_ersteller_oder_beobachter(monkeypatch):
    monkeypatch.setattr(pactions, "_user_email", lambda uid: "owner@x.de")
    monkeypatch.setattr(pactions, "watcher_emails", lambda tid: ["watch@x.de"])
    sent, sender = _capture()
    out = pactions.notify_comment(_row(phase_index=1), DEFN.phases[1], author_name="IT",
                                  body_text="intern", internal=True, sender=sender,
                                  groups=[{"id": "g_it", "distributions": ["it@x.de"]},
                                          {"id": "g_fp", "distributions": ["fp@x.de"]}])
    assert set(out) == {"it@x.de", "fp@x.de"}


def test_schreibende_person_bekommt_keine_eigene_mail(monkeypatch):
    monkeypatch.setattr(pactions, "watcher_emails", lambda tid: [])
    monkeypatch.setattr(pactions, "_user_email", lambda uid: None)
    sent, sender = _capture()
    out = pactions.notify_comment(_row(phase_index=1), DEFN.phases[1], author_name="IT",
                                  body_text="x", actor_email="it@x.de", sender=sender,
                                  groups=[{"id": "g_it", "distributions": ["it@x.de"]}])
    assert out == ["fp@x.de"] or out == []      # nur der Rest, nie die eigene Adresse
    assert "it@x.de" not in out


def test_ohne_beobachter_wird_nicht_die_zentraladresse_angeschrieben(monkeypatch):
    """„niemand beobachtet" ist ein gültiges leeres Ergebnis, kein Auflöse-Fehler."""
    monkeypatch.setattr(pactions, "watcher_emails", lambda tid: [])
    assert pactions.resolve_recipients("watchers", _row(), DEFN.phases[0], groups=[]) == []


# ── API ──────────────────────────────────────────────────────────────────────

class FakeStore:
    ProcessTicketConflict = ProcessTicketConflict

    def __init__(self, row):
        self.rows = {row["id"]: dict(row)}

    def get(self, tid):
        r = self.rows.get(tid)
        return dict(r) if r else None

    def update_runtime(self, tid, *, runtime_json, status, next_timer_due_at=None,
                       expected_rev=None):
        r = self.rows[tid]
        r["runtime"] = json.loads(runtime_json)
        r["runtime_json"] = runtime_json
        r["status"] = status
        r["rev"] += 1
        return dict(r)

    def set_next_timer(self, tid, v, expected_rev=None):
        self.rows[tid]["next_timer_due_at"] = v


class FakeDefs:
    def get_definition(self, key, ver):
        return {"version": ver, "definition": DEFN_RAW} if key == "demo" else None

    def get_published(self, key):
        return {"version": 1, "definition": DEFN_RAW} if key == "demo" else None


class FakeEventStore:
    def __init__(self):
        self.rows = []

    def add_event(self, **kw):
        # Wie der echte Store: `details` ist IMMER ein dict, nie None.
        ev = {"id": len(self.rows) + 1, "created_at": "t", **kw}
        ev["details"] = kw.get("details") or {}
        ev["internal"] = bool(kw.get("internal"))
        self.rows.append(ev)
        return dict(ev)

    def list_for_ticket(self, tid, *, limit=100, offset=0):
        mine = [dict(e) for e in self.rows if e["ticket_id"] == tid]
        return mine[offset:offset + limit], len(mine)


class FakeWatchers:
    def __init__(self):
        self.rows: dict[int, dict] = {}

    def watcher_ids(self, tid):
        return set(self.rows.get(tid, {}))

    def watcher_ids_for_tickets(self, tids):
        return {t: set(self.rows.get(t, {})) for t in tids}

    def list_watchers(self, tid):
        return [{"id": uid, "name": n, "added_by": None, "created_at": "t"}
                for uid, n in sorted(self.rows.get(tid, {}).items())]

    def add_watcher(self, tid, uid, name=None, added_by=None):
        neu = uid not in self.rows.setdefault(tid, {})
        self.rows[tid][uid] = name
        return neu

    def remove_watcher(self, tid, uid):
        return self.rows.get(tid, {}).pop(uid, "__nix__") != "__nix__"


@pytest.fixture
def setup(monkeypatch):
    """API mit Attrappen; `state['user']` bestimmt, wer angemeldet ist."""
    from backend.services import process_engine as engine
    row = _row(phase_index=1, values={"name": "Max", "gehalt": "100000"})
    row["status"] = "in_request"
    store, evstore, watch = FakeStore(row), FakeEventStore(), FakeWatchers()
    monkeypatch.setattr(pt, "store", store)
    monkeypatch.setattr(pt, "defstore", FakeDefs())
    monkeypatch.setattr(pt, "watchers", watch)
    monkeypatch.setattr(pev, "store", evstore)
    monkeypatch.setattr(pev, "record_audit", lambda **kw: None)
    monkeypatch.setattr(engine, "store", store)
    monkeypatch.setattr(pt.pactions, "notify_comment", lambda *a, **k: [])
    monkeypatch.setattr(pt.pactions, "notify_phase_entry", lambda *a, **k: [])
    # Gruppen-Mitgliedschaft kommt sonst aus der DB.
    monkeypatch.setattr(vis, "user_group_ids",
                        lambda u: {"g_it"} if u.get("id") == "u_it" else set())

    state = {"user": dict(ADMIN)}
    app = FastAPI()
    _install_error_handlers(app)
    app.include_router(pt.router)
    app.dependency_overrides[get_current_user] = lambda: state["user"]
    return TestClient(app), state, store, evstore, watch


def test_verlauf_ist_redigiert(setup):
    client, state, store, evstore, _w = setup
    evstore.add_event(ticket_id=7, action="updated", actor_id="u_it", actor_name="IT",
                      details={"fields": ["gehalt"]})
    evstore.add_event(ticket_id=7, action="updated", actor_id="u_it", actor_name="IT",
                      details={"fields": ["name"]})
    state["user"] = dict(ADMIN)
    assert len(client.get("/process-tickets/7/events").json()["data"]) == 2
    state["user"] = dict(OWNER)
    d = client.get("/process-tickets/7/events").json()["data"]
    assert [e["details"]["fields"] for e in d] == [["name"]]


def test_nachtrag_schreiben_und_lesen(setup):
    client, state, *_ = setup
    state["user"] = dict(OWNER)
    r = client.post("/process-tickets/7/comments", json={"body": "  Bitte eilig  "})
    assert r.status_code == 200
    assert r.json()["data"]["body"] == "Bitte eilig"        # getrimmt
    assert r.json()["data"]["action"] == "comment"
    d = client.get("/process-tickets/7/events").json()["data"]
    assert d[-1]["body"] == "Bitte eilig"


def test_leerer_nachtrag_wird_abgelehnt(setup):
    client, state, *_ = setup
    r = client.post("/process-tickets/7/comments", json={"body": "   "})
    assert r.status_code == 422
    assert r.json()["error"]["fields"][0]["path"] == "body"


def test_zu_langer_nachtrag_wird_abgelehnt(setup):
    client, state, *_ = setup
    r = client.post("/process-tickets/7/comments", json={"body": "x" * 5001})
    assert r.status_code == 422
    assert r.json()["error"]["fields"][0]["code"] == "TOO_LONG"


def test_interner_nachtrag_nur_fuer_bearbeitende_seite(setup):
    client, state, *_ = setup
    state["user"] = dict(OWNER)
    r = client.post("/process-tickets/7/comments", json={"body": "x", "internal": True})
    assert r.status_code == 403
    state["user"] = dict(ITLER)
    assert client.post("/process-tickets/7/comments",
                       json={"body": "x", "internal": True}).status_code == 200


def test_interner_nachtrag_ist_fuer_den_ersteller_unsichtbar(setup):
    client, state, *_ = setup
    state["user"] = dict(ITLER)
    client.post("/process-tickets/7/comments", json={"body": "intern!", "internal": True})
    state["user"] = dict(OWNER)
    d = client.get("/process-tickets/7/events").json()["data"]
    assert all(e["body"] != "intern!" for e in d)


def test_fremde_kommen_nicht_an_den_verlauf(setup):
    client, state, *_ = setup
    state["user"] = dict(FREMD)
    assert client.get("/process-tickets/7/events").status_code == 404
    assert client.post("/process-tickets/7/comments", json={"body": "x"}).status_code == 404


# ── Wiederaufnahme über die API ──────────────────────────────────────────────

def test_reopen_nur_fuer_admins(setup):
    client, state, store, *_ = setup
    store.rows[7]["status"] = "archived"
    state["user"] = dict(ITLER)
    r = client.post("/process-tickets/7:reopen", json={"reason": "Nacharbeit"})
    assert r.status_code == 403


def test_reopen_verlangt_einen_grund(setup):
    client, state, store, *_ = setup
    store.rows[7]["status"] = "archived"
    r = client.post("/process-tickets/7:reopen", json={"reason": "  "})
    assert r.status_code == 422
    assert r.json()["error"]["fields"][0]["path"] == "reason"


def test_reopen_geht_nicht_bei_aktivem_auftrag(setup):
    client, *_ = setup
    r = client.post("/process-tickets/7:reopen", json={"reason": "warum auch"})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "PROCESS_INVALID_STATE"


def test_reopen_setzt_auftrag_wieder_offen_und_schreibt_grund(setup):
    client, state, store, evstore, _w = setup
    store.rows[7]["status"] = "archived"
    store.rows[7]["runtime"]["current_index"] = 2       # hinter der letzten Phase
    r = client.post("/process-tickets/7:reopen", json={"reason": "Falsch abgeschlossen"})
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["status"] == "in_request" and d["current_phase"] == "pruefung"
    assert d["runtime"]["epoch"] == 1
    reopened = [e for e in evstore.rows if e["action"] == "reopened"]
    assert reopened and reopened[0]["body"] == "Falsch abgeschlossen"


def test_reopen_kennt_nur_echte_phasen_api(setup):
    client, state, store, *_ = setup
    store.rows[7]["status"] = "archived"
    r = client.post("/process-tickets/7:reopen", json={"reason": "x", "phase": "quatsch"})
    assert r.status_code == 422
    assert r.json()["error"]["fields"][0]["path"] == "phase"


# ── Erlaubte Aktionen (damit die Oberfläche nicht raten muss) ────────────────

def test_abilities_fuer_zustaendige_fachabteilung(setup):
    client, state, *_ = setup
    state["user"] = dict(ITLER)
    a = client.get("/process-tickets/7").json()["data"]["abilities"]
    assert a == {"edit": True, "internal_comment": True, "manage_watchers": True,
                 "reopen": False, "archive": False, "delete": False}


def test_abilities_fuer_den_ersteller(setup):
    """In der Prüfphase ist die Fachabteilung zuständig – der Ersteller liest nur."""
    client, state, *_ = setup
    state["user"] = dict(OWNER)
    a = client.get("/process-tickets/7").json()["data"]["abilities"]
    assert a["edit"] is False and a["internal_comment"] is False
    assert a["manage_watchers"] is False and a["reopen"] is False


def test_abilities_reopen_nur_bei_fertigem_auftrag(setup):
    client, state, store, *_ = setup
    assert client.get("/process-tickets/7").json()["data"]["abilities"]["reopen"] is False
    store.rows[7]["status"] = "archived"
    a = client.get("/process-tickets/7").json()["data"]["abilities"]
    assert a["reopen"] is True and a["edit"] is False


# ── Beobachter:innen ─────────────────────────────────────────────────────────

def test_sich_selbst_eintragen_und_wieder_austragen(setup):
    client, state, store, _e, watch = setup
    state["user"] = dict(ITLER)
    r = client.post("/process-tickets/7/watchers", json={})
    assert r.status_code == 200
    assert [w["id"] for w in r.json()["data"]] == ["u_it"]
    r2 = client.delete("/process-tickets/7/watchers/u_it")
    assert r2.status_code == 200 and r2.json()["data"] == []


def test_beobachten_gibt_leserecht(setup):
    """Der eigentliche Zweck: Einsicht ohne Zuständigkeit."""
    client, state, store, _e, watch = setup
    state["user"] = dict(FREMD)
    assert client.get("/process-tickets/7").status_code == 404
    watch.add_watcher(7, "u_x", "Fremd")
    assert client.get("/process-tickets/7").status_code == 200
    # ... aber nur auf die freigegebenen Felder.
    assert "gehalt" not in client.get("/process-tickets/7").json()["data"]["values"]


def test_fremde_eintragen_darf_nur_die_zustaendige_stelle(setup):
    client, state, store, _e, watch = setup
    watch.add_watcher(7, "u_x", "Fremd")          # damit u_x überhaupt lesen darf
    state["user"] = dict(FREMD)
    r = client.post("/process-tickets/7/watchers", json={"userId": "u_neu"})
    assert r.status_code == 403
    state["user"] = dict(ITLER)                   # zuständige Fachabteilung
    assert client.post("/process-tickets/7/watchers",
                       json={"userId": "u_neu"}).status_code == 200


def test_fremde_austragen_darf_nur_die_zustaendige_stelle(setup):
    client, state, store, _e, watch = setup
    watch.add_watcher(7, "u_x", "Fremd")
    watch.add_watcher(7, "u_andere", "Andere")
    state["user"] = dict(FREMD)
    assert client.delete("/process-tickets/7/watchers/u_andere").status_code == 403
    state["user"] = dict(ADMIN)
    assert client.delete("/process-tickets/7/watchers/u_andere").status_code == 200


def test_beobachter_eintragen_landet_im_verlauf(setup):
    client, state, store, evstore, _w = setup
    state["user"] = dict(ITLER)
    client.post("/process-tickets/7/watchers", json={})
    assert any(e["action"] == "watcher_added" for e in evstore.rows)
    # Zweimal eintragen erzeugt keinen zweiten Eintrag (idempotent).
    client.post("/process-tickets/7/watchers", json={})
    assert len([e for e in evstore.rows if e["action"] == "watcher_added"]) == 1


# ── Admin-Notfalleingriffe ───────────────────────────────────────────────────

def test_zwangsabschluss_nur_admin_und_mit_grund(setup):
    client, state, store, evstore, _w = setup
    state["user"] = dict(ITLER)
    assert client.post("/process-tickets/7:archive",
                       json={"reason": "hängt"}).status_code == 403
    state["user"] = dict(ADMIN)
    assert client.post("/process-tickets/7:archive", json={"reason": "  "}).status_code == 422
    r = client.post("/process-tickets/7:archive", json={"reason": "Gruppe aufgelöst"})
    assert r.status_code == 200 and r.json()["data"]["status"] == "archived"
    # Der Grund muss im Verlauf stehen, sonst ist der Abschluss unerklärlich.
    assert any(e.get("body") == "Gruppe aufgelöst" for e in evstore.rows)
    # Danach ist er terminal → kein zweiter Zwangsabschluss.
    assert client.post("/process-tickets/7:archive",
                       json={"reason": "nochmal"}).status_code == 409


def test_zwangsabschluss_ist_ueber_reopen_rueckholbar(setup):
    client, state, store, *_ = setup
    client.post("/process-tickets/7:archive", json={"reason": "Versehen"})
    r = client.post("/process-tickets/7:reopen", json={"reason": "doch noch nötig"})
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "in_request"


def test_loeschen_nur_admin_und_auditiert(setup, monkeypatch):
    client, state, store, *_ = setup
    geloescht = []
    monkeypatch.setattr(store, "delete", lambda tid: geloescht.append(tid) or True,
                        raising=False)
    audits = []
    monkeypatch.setattr(pt, "record_audit", lambda **kw: audits.append(kw))
    state["user"] = dict(ITLER)
    assert client.delete("/process-tickets/7").status_code == 403
    state["user"] = dict(ADMIN)
    assert client.delete("/process-tickets/7").status_code == 200
    assert geloescht == [7]
    # Auditiert VOR der Löschung – sonst wäre der Titel schon weg.
    assert audits and audits[0]["action"] == "process_ticket_deleted"
    assert "Testauftrag" in audits[0]["summary"]


def test_abilities_nennen_die_notfallaktionen(setup):
    client, state, store, *_ = setup
    a = client.get("/process-tickets/7").json()["data"]["abilities"]
    assert a["archive"] is True and a["delete"] is True
    state["user"] = dict(ITLER)
    b = client.get("/process-tickets/7").json()["data"]["abilities"]
    assert b["archive"] is False and b["delete"] is False
