"""Ebene-1: Ticket-Runtime-API (create/patch/advance/reject) mit In-Memory-Store.

Kein echtes MariaDB: der DB-Layer wird durch einen In-Memory-Fake ersetzt, die
Auth-Dependency überschrieben. Getestet wird die Endpunkt-Logik: Zwei-Pass-
Validierung, Pinning der Definition, Phasen-Fortschritt, Terminal-Sperre.
"""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core.dependencies import get_current_user
from backend.main import _install_error_handlers
from backend.api.v1 import process_tickets as pt
from backend.database.process_tickets import ProcessTicketConflict


DEFN = {
    "schemaVersion": 1, "key": "demo", "name": "Demo-Prozess",
    "fields": [
        {"key": "base.name", "widget": "text"},
        {"key": "base.age", "widget": "number"},
    ],
    "phases": [
        {"key": "start", "kind": "start", "responsibility": {"kind": "owner"},
         "fields": [{"ref": "base.name", "required": True},
                    {"ref": "base.age", "mode": "editable"}]},
        {"key": "review", "kind": "review",
         "responsibility": {"kind": "departments", "rule": [{"group": "g_it"}]},
         "fields": [{"ref": "base.name", "mode": "readonly"}]},
    ],
}


class FakeStore:
    ProcessTicketConflict = ProcessTicketConflict   # damit `store.ProcessTicketConflict` im Endpunkt greift

    def __init__(self):
        self.rows: dict[int, dict] = {}
        self.seq = 0

    def create(self, **kw):
        self.seq += 1
        row = {"id": self.seq, "rev": 0, "next_timer_due_at": None,
               "created_at": "t", "updated_at": "t", **kw}
        row["values"] = json.loads(kw["values_json"])
        row["runtime"] = json.loads(kw["runtime_json"])
        self.rows[self.seq] = row
        return dict(row)

    def get(self, tid):
        r = self.rows.get(tid)
        return dict(r) if r else None

    def _guard(self, r, expected_rev):
        if expected_rev is not None and r["rev"] != expected_rev:
            raise ProcessTicketConflict(f"#{r['id']} geändert")

    def update_values(self, tid, values_json, title=None, expected_rev=None):
        r = self.rows[tid]
        self._guard(r, expected_rev)
        r["values_json"] = values_json
        r["values"] = json.loads(values_json)
        if title is not None:
            r["title"] = title
        r["rev"] += 1
        return dict(r)

    def update_runtime(self, tid, *, runtime_json, status, next_timer_due_at=None, expected_rev=None):
        r = self.rows[tid]
        self._guard(r, expected_rev)
        r["runtime_json"] = runtime_json
        r["runtime"] = json.loads(runtime_json)
        r["status"] = status
        r["next_timer_due_at"] = next_timer_due_at
        r["rev"] += 1
        return dict(r)

    def set_next_timer(self, tid, v, expected_rev=None):
        self.rows[tid]["next_timer_due_at"] = v

    def set_priority(self, tid, v, expected_rev=None):
        self.rows[tid]["priority"] = v

    def set_status(self, tid, v, expected_rev=None):
        self.rows[tid]["status"] = v

    def list_tickets(self, **kw):
        rows = [dict(r) for r in self.rows.values()]
        return rows, len(rows)


#: Wie DEFN, aber mit festem Titel (titleEditable=false – wie das Basis-Ticket).
DEFN_FIXED = {**DEFN, "key": "fix", "titleEditable": False}

#: Start-Phase mit on_enter-auto_advance – zum Prüfen von autoStart (Onboarding:
#: erst Anhänge hochladen, dann selbst :advance, damit die Freigabe-Mail sie mitnimmt).
DEFN_FLOW = {
    "schemaVersion": 1, "key": "flow", "name": "Auto-Flow",
    "titleTemplate": "Neuer Auftrag – {{base.name}}",
    "fields": [{"key": "base.name", "widget": "text"}],
    "phases": [
        {"key": "start", "kind": "start", "responsibility": {"kind": "owner"},
         "fields": [{"ref": "base.name", "required": True}],
         "automations": [{"id": "go", "trigger": {"type": "on_enter"},
                          "action": {"type": "auto_advance"}}]},
        {"key": "work", "kind": "task", "responsibility": {"kind": "owner"},
         "fields": [{"ref": "base.name", "mode": "readonly"}]},
    ],
}


class FakeDefs:
    def __init__(self):
        self.definition_loads = 0
        self.disabled: set[str] = set()

    def is_disabled(self, key):
        return key in self.disabled

    def get_published(self, key):
        if key == "demo":
            return {"version": 1, "definition": DEFN}
        if key == "fix":
            return {"version": 1, "definition": DEFN_FIXED}
        if key == "flow":
            return {"version": 1, "definition": DEFN_FLOW}
        return None

    def get_definition(self, key, ver):
        self.definition_loads += 1
        if key == "demo":
            return {"version": ver, "definition": DEFN}
        if key == "fix":
            return {"version": ver, "definition": DEFN_FIXED}
        if key == "flow":
            return {"version": ver, "definition": DEFN_FLOW}
        return None


class FakeFires:
    """Leerer Ledger – reicht für die API-Tests (keine Timer in DEFN)."""

    def fired_map(self, tid, pk, ep):
        return {}

    def claim(self, *a, **k):
        return True


@pytest.fixture
def defs():
    return FakeDefs()


@pytest.fixture
def client(monkeypatch, defs):
    from backend.services import process_engine as engine
    fake_store = FakeStore()
    monkeypatch.setattr(pt, "store", fake_store)
    monkeypatch.setattr(pt, "defstore", defs)
    # Die Engine hält eigene Modul-Aliasse (store/fires) – in Tests mitziehen.
    monkeypatch.setattr(engine, "store", fake_store)
    monkeypatch.setattr(engine, "fires", FakeFires())
    app = FastAPI()
    _install_error_handlers(app)
    app.include_router(pt.router)
    app.dependency_overrides[get_current_user] = lambda: {
        "id": "u1", "displayName": "Admin", "permissions": ["admin"]}
    return TestClient(app)


def test_create_rejects_bad_value(client):
    r = client.post("/process-tickets", json={"processKey": "demo", "values": {"base.age": "NaN"}})
    assert r.status_code == 422
    body = r.json()
    assert body["error"]["code"] == "VALIDATION_FAILED"
    assert any(f["path"] == "base.age" for f in body["error"]["fields"])


def test_create_rejects_unknown_process(client):
    r = client.post("/process-tickets", json={"processKey": "ghost"})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "PROCESS_NOT_FOUND"


def test_create_blocked_when_process_disabled(client, defs):
    """Ein global deaktivierter Prozess lässt kein Anlegen zu – auch nicht für
    Admins mit Erstellrecht (die Sperre gilt bis zur Freigabe)."""
    defs.disabled.add("demo")
    r = client.post("/process-tickets", json={"processKey": "demo", "values": {"base.name": "Max"}})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "PROCESS_DISABLED"
    # Nach Freigabe geht es wieder.
    defs.disabled.discard("demo")
    assert client.post("/process-tickets",
                       json={"processKey": "demo", "values": {"base.name": "Max"}}).status_code == 200


def test_create_ok(client):
    r = client.post("/process-tickets", json={"processKey": "demo", "values": {"base.name": "Max"}})
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["status"] == "in_progress"
    assert d["current_phase"] == "start"
    assert d["process_version"] == 1
    assert d["values"] == {"base.name": "Max"}


def test_create_auto_start_schaltet_direkt_weiter(client):
    """Standard: eine Start-Phase mit on_enter-auto_advance schaltet beim Anlegen
    sofort weiter (unverändertes Verhalten)."""
    r = client.post("/process-tickets", json={"processKey": "flow", "values": {"base.name": "Max"}})
    assert r.status_code == 200
    assert r.json()["data"]["current_phase"] == "work"


def test_create_rendert_titel_aus_vorlage(client):
    """Ist eine titleTemplate gesetzt, wird der Titel beim Anlegen daraus erzeugt
    (aus den Startphasen-Werten) statt aus dem manuell gesendeten Titel."""
    r = client.post("/process-tickets", json={"processKey": "flow",
                    "title": "wird ignoriert", "values": {"base.name": "Max Mustermann"}})
    assert r.status_code == 200
    assert r.json()["data"]["title"] == "Neuer Auftrag – Max Mustermann"


def test_create_defer_start_bleibt_in_startphase(client):
    """autoStart=false unterdrückt das sofortige Weiterschalten: der Auftrag bleibt
    in der Start-Phase, damit der Client zuerst Datei-Anhänge hochladen und dann
    selbst :advance rufen kann (so landen sie in der Freigabe-Mail)."""
    r = client.post("/process-tickets",
                    json={"processKey": "flow", "values": {"base.name": "Max"}, "autoStart": False})
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["current_phase"] == "start"
    # Der nachgelagerte :advance schaltet dann regulär weiter.
    adv = client.post(f"/process-tickets/{d['id']}:advance")
    assert adv.status_code == 200
    assert adv.json()["data"]["current_phase"] == "work"


def test_patch_merges_values(client):
    tid = client.post("/process-tickets", json={"processKey": "demo", "values": {"base.name": "Max"}}).json()["data"]["id"]
    r = client.patch(f"/process-tickets/{tid}", json={"values": {"base.age": 30}})
    assert r.status_code == 200
    assert r.json()["data"]["values"] == {"base.name": "Max", "base.age": 30}


def test_titel_bleibt_aenderbar_wenn_die_definition_nichts_sagt(client):
    tid = client.post("/process-tickets", json={"processKey": "demo",
                                                "values": {"base.name": "Max"}}).json()["data"]["id"]
    r = client.patch(f"/process-tickets/{tid}", json={"title": "Neuer Titel"})
    assert r.status_code == 200
    assert r.json()["data"]["title"] == "Neuer Titel"


def test_fester_titel_wird_serverseitig_abgewiesen(client):
    """titleEditable=false (Basis-Ticket): der Titel wird beim Anlegen festgelegt
    und ist danach für ALLE nur lesbar – auch für Admins, sonst wäre die
    Prozess-Einstellung nur Deko."""
    tid = client.post("/process-tickets", json={"processKey": "fix", "title": "So bleibt es",
                                                "values": {"base.name": "Max"}}).json()["data"]["id"]
    r = client.patch(f"/process-tickets/{tid}", json={"title": "Umbenannt"})
    assert r.status_code == 422
    assert r.json()["error"]["fields"][0]["path"] == "title"
    assert r.json()["error"]["fields"][0]["code"] == "TITLE_LOCKED"
    assert client.get(f"/process-tickets/{tid}").json()["data"]["title"] == "So bleibt es"
    # Der UNVERÄNDERTE Titel darf im Body mitkommen (kein Fehl-422 für Clients,
    # die immer den ganzen Zustand senden).
    r = client.patch(f"/process-tickets/{tid}", json={"title": "So bleibt es",
                                                      "values": {"base.age": 1}})
    assert r.status_code == 200


def test_advance_blocked_when_required_missing(client):
    tid = client.post("/process-tickets", json={"processKey": "demo"}).json()["data"]["id"]
    r = client.post(f"/process-tickets/{tid}:advance")
    assert r.status_code == 422
    assert any(f["path"] == "base.name" and f["code"] == "REQUIRED"
               for f in r.json()["error"]["fields"])


def test_full_lifecycle_advance_and_archive(client):
    tid = client.post("/process-tickets", json={"processKey": "demo", "values": {"base.name": "Max"}}).json()["data"]["id"]
    r1 = client.post(f"/process-tickets/{tid}:advance")
    assert r1.status_code == 200
    d1 = r1.json()["data"]
    assert d1["current_phase"] == "review" and d1["status"] == "in_request"
    # Zuständigkeit der review-Phase = Abteilung g_it
    assert d1["responsibility"]["kind"] == "departments"
    assert d1["responsibility"]["departments"][0]["group"] == "g_it"
    # Die Fachabteilung steht noch aus → Abschluss ist gesperrt.
    blocked = client.post(f"/process-tickets/{tid}:advance")
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "DEPARTMENT_FORBIDDEN"

    # Abteilung schließt ab → jetzt geht es weiter.
    done = client.post(f"/process-tickets/{tid}/departments/g_it:complete")
    assert done.status_code == 200
    dep = done.json()["data"]["responsibility"]["departments"][0]
    assert dep["status"] == "done" and dep["by"] == "u1"

    r2 = client.post(f"/process-tickets/{tid}:advance")
    assert r2.status_code == 200
    assert r2.json()["data"]["status"] == "archived"
    # danach ist das Ticket terminal → weitere Aktion 409
    r3 = client.post(f"/process-tickets/{tid}:advance")
    assert r3.status_code == 409


def test_fachabteilung_ueberspringen_zaehlt_als_erledigt(client):
    tid = client.post("/process-tickets",
                      json={"processKey": "demo", "values": {"base.name": "Max"}}).json()["data"]["id"]
    client.post(f"/process-tickets/{tid}:advance")
    assert client.post(f"/process-tickets/{tid}/departments/g_it:skip").status_code == 200
    # skipped blockiert nicht
    assert client.post(f"/process-tickets/{tid}:advance").json()["data"]["status"] == "archived"


def test_fachabteilung_ablehnung_lehnt_auftrag_ab(client):
    tid = client.post("/process-tickets",
                      json={"processKey": "demo", "values": {"base.name": "Max"}}).json()["data"]["id"]
    client.post(f"/process-tickets/{tid}:advance")
    r = client.post(f"/process-tickets/{tid}/departments/g_it:reject",
                    json={"note": "Budget fehlt"})
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "rejected"


def test_unbeteiligte_abteilung_kann_nicht_abschliessen(client):
    tid = client.post("/process-tickets",
                      json={"processKey": "demo", "values": {"base.name": "Max"}}).json()["data"]["id"]
    client.post(f"/process-tickets/{tid}:advance")
    # g_fremd ist an dieser Phase nicht beteiligt
    r = client.post(f"/process-tickets/{tid}/departments/g_fremd:complete")
    assert r.status_code in (403, 409)


def test_reject_then_locked(client):
    tid = client.post("/process-tickets", json={"processKey": "demo", "values": {"base.name": "Max"}}).json()["data"]["id"]
    r = client.post(f"/process-tickets/{tid}:reject", json={"reason": "Budget gestrichen"})
    assert r.json()["data"]["status"] == "rejected"
    assert client.patch(f"/process-tickets/{tid}", json={"values": {"base.age": 1}}).status_code == 409


def test_ablehnung_verlangt_eine_begruendung(client):
    """Ohne Grund ist eine Ablehnung im Verlauf nicht erklärbar und die
    antragstellende Person erfährt nie, was zu ändern wäre."""
    tid = client.post("/process-tickets", json={"processKey": "demo", "values": {"base.name": "Max"}}).json()["data"]["id"]
    r = client.post(f"/process-tickets/{tid}:reject", json={"reason": "   "})
    assert r.status_code == 422
    assert r.json()["error"]["fields"][0]["path"] == "reason"
    # Der Auftrag darf dadurch NICHT angefasst worden sein.
    assert client.get(f"/process-tickets/{tid}").json()["data"]["status"] == "in_progress"


def test_abteilungs_ablehnung_verlangt_eine_begruendung(client):
    """Sie lehnt den GANZEN Auftrag ab – derselbe Zwang wie bei :reject."""
    tid = client.post("/process-tickets", json={"processKey": "demo", "values": {"base.name": "Max"}}).json()["data"]["id"]
    client.post(f"/process-tickets/{tid}:advance")
    r = client.post(f"/process-tickets/{tid}/departments/g_it:reject", json={})
    assert r.status_code == 422
    assert r.json()["error"]["fields"][0]["path"] == "note"
    ok = client.post(f"/process-tickets/{tid}/departments/g_it:reject",
                     json={"note": "Gerät nicht lieferbar"})
    assert ok.status_code == 200 and ok.json()["data"]["status"] == "rejected"


def test_feld_zugriff_wird_mitgeliefert(client):
    """Das Formular kennt die Gruppen nicht – der Server sagt, was sichtbar und
    was in DIESER Phase bearbeitbar ist."""
    tid = client.post("/process-tickets", json={"processKey": "demo", "values": {"base.name": "Max"}}).json()["data"]["id"]
    d = client.get(f"/process-tickets/{tid}").json()["data"]
    assert d["visible_fields"] == ["base.age", "base.name"]
    assert d["editable_fields"] == ["base.age", "base.name"]
    # Zweite Phase: dort ist base.name nur noch readonly, base.age gar nicht dabei.
    client.post(f"/process-tickets/{tid}:advance")
    d2 = client.get(f"/process-tickets/{tid}").json()["data"]
    assert d2["editable_fields"] == []
    assert "base.name" in d2["visible_fields"]


def test_list_returns_meta(client):
    client.post("/process-tickets", json={"processKey": "demo", "values": {"base.name": "A"}})
    client.post("/process-tickets", json={"processKey": "demo", "values": {"base.name": "B"}})
    r = client.get("/process-tickets")
    assert r.status_code == 200
    body = r.json()
    assert body["meta"]["total"] == 2 and len(body["data"]) == 2


def test_list_does_not_load_definition_per_row(client, defs):
    """Regression N+1: gepinnte Definitionen sind unveränderlich und werden je
    (key, version) nur EINMAL pro Request geladen – nicht pro Zeile."""
    for name in ("A", "B", "C", "D"):
        client.post("/process-tickets", json={"processKey": "demo", "values": {"base.name": name}})
    defs.definition_loads = 0
    r = client.get("/process-tickets")
    assert r.status_code == 200 and len(r.json()["data"]) == 4
    assert defs.definition_loads == 1, f"{defs.definition_loads} Definitions-Ladevorgänge für 4 Zeilen"


def test_gepinnte_definition_haengt_am_ticket_zugriff(client):
    """Das Formular braucht die Definition. Sie über den Verwaltungs-Endpunkt zu
    holen, würde für normale Beteiligte in 403 laufen – deshalb ein eigener
    Endpunkt, der allein am Zugriff auf den AUFTRAG hängt."""
    tid = client.post("/process-tickets",
                      json={"processKey": "demo", "values": {"base.name": "Max"}}).json()["data"]["id"]
    r = client.get(f"/process-tickets/{tid}/definition")
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["key"] == "demo"
    assert [p["key"] for p in d["phases"]] == ["start", "review"]
    # Keine Feldwerte im Bauplan.
    assert "values" not in d


def test_definition_unbekanntes_ticket(client):
    assert client.get("/process-tickets/999/definition").status_code == 404


def test_prioritaet_laesst_sich_nachtraeglich_aendern(client):
    """Das Details-Panel bietet die Priorität wie im Alt-System zur Bearbeitung an –
    bisher war sie nach dem Anlegen unveränderlich (PATCH kannte nur title/values)."""
    tid = client.post("/process-tickets", json={"processKey": "demo",
                                                "values": {"base.name": "Max"}}).json()["data"]["id"]
    r = client.patch(f"/process-tickets/{tid}", json={"priority": "high"})
    assert r.status_code == 200
    assert r.json()["data"]["priority"] == "high"


# ── Admin-Werkzeuge (set-phase / raw-values) ─────────────────────────────────

def _client_mit(permissions: list[str]):
    """Zweiter Client über dieselben (bereits gemonkeypatchten) Fakes –
    angemeldet als Person mit genau diesen Berechtigungen."""
    app = FastAPI()
    _install_error_handlers(app)
    app.include_router(pt.router)
    app.dependency_overrides[get_current_user] = lambda: {
        "id": "u9", "displayName": "Normalo", "permissions": permissions}
    return TestClient(app)


def _client_ohne_admin():
    return _client_mit([])


def test_archivieren_duerfen_manager_und_admin(client):
    """Alt-System-Regel: viewer liest nur, manager darf zusätzlich archivieren,
    admin darf alles. Der Zwangsabschluss ist die einzige Schreibaktion der
    Manager-Rolle."""
    tid = client.post("/process-tickets", json={"processKey": "demo",
                                                "values": {"base.name": "Max"}}).json()["data"]["id"]
    viewer = _client_mit(["view"])
    r = viewer.post(f"/process-tickets/{tid}:archive", json={"reason": "x"})
    assert r.status_code == 403
    manager = _client_mit(["view", "manage"])
    r = manager.post(f"/process-tickets/{tid}:archive", json={"reason": "hängt seit Wochen"})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["status"] == "archived"
    # abilities spiegeln dieselbe Regel (auf einem frischen Auftrag).
    tid2 = client.post("/process-tickets", json={"processKey": "demo",
                                                 "values": {"base.name": "Max"}}).json()["data"]["id"]
    a = manager.get(f"/process-tickets/{tid2}").json()["data"]["abilities"]
    assert a["archive"] is True and a["edit"] is False and a["delete"] is False
    a = viewer.get(f"/process-tickets/{tid2}").json()["data"]["abilities"]
    assert a["archive"] is False


def test_set_phase_stellt_aktiven_auftrag_um(client):
    tid = client.post("/process-tickets", json={"processKey": "demo",
                                                "values": {"base.name": "Max"}}).json()["data"]["id"]
    r = client.post(f"/process-tickets/{tid}:set-phase",
                    json={"phase": "review", "reason": "Freigabe-Mail verloren"})
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["current_phase"] == "review"
    # Epoch-Bump: sonst blieben Timer stumm, die im ersten Durchlauf schon feuerten.
    assert d["runtime"]["epoch"] == 1
    # Auch ZURÜCK muss gehen (das ist der Reparatur-Fall schlechthin).
    r2 = client.post(f"/process-tickets/{tid}:set-phase",
                     json={"phase": "start", "reason": "versehentlich weitergeschaltet"})
    assert r2.json()["data"]["current_phase"] == "start"
    assert r2.json()["data"]["runtime"]["epoch"] == 2


def test_set_phase_verlangt_admin_und_grund(client):
    tid = client.post("/process-tickets", json={"processKey": "demo",
                                                "values": {"base.name": "Max"}}).json()["data"]["id"]
    r = client.post(f"/process-tickets/{tid}:set-phase", json={"phase": "review", "reason": " "})
    assert r.status_code == 422                       # Grund ist Pflicht
    r = client.post(f"/process-tickets/{tid}:set-phase",
                    json={"phase": "gibtsnicht", "reason": "x"})
    assert r.status_code == 422                       # unbekannte Phase
    fremd = _client_ohne_admin()
    r = fremd.post(f"/process-tickets/{tid}:set-phase", json={"phase": "review", "reason": "x"})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "ADMIN_REQUIRED"


def test_set_phase_nicht_fuer_terminale(client):
    """Fertige Aufträge nehmen den benannten Weg über :reopen."""
    tid = client.post("/process-tickets", json={"processKey": "demo",
                                                "values": {"base.name": "Max"}}).json()["data"]["id"]
    client.post(f"/process-tickets/{tid}:reject", json={"reason": "Budget"})
    r = client.post(f"/process-tickets/{tid}:set-phase", json={"phase": "start", "reason": "x"})
    assert r.status_code == 409


def test_raw_values_ersetzt_verbatim_und_nur_fuer_admins(client):
    tid = client.post("/process-tickets", json={"processKey": "demo",
                                                "values": {"base.name": "Max"}}).json()["data"]["id"]
    # Roh-Reparatur darf Dinge, die der normale PATCH nicht darf (Feld entfernen,
    # unbekannte Schlüssel stehen lassen) – genau dafür ist sie da.
    r = client.put(f"/process-tickets/{tid}/raw-values",
                   json={"values": {"base.age": 33, "alt.rest": "x"},
                         "reason": "kaputten Zustand repariert"})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["values"] == {"base.age": 33, "alt.rest": "x"}
    # Der Roh-LESE-Endpunkt liefert denselben ungefilterten Bestand – die
    # normale Ticket-Antwort filtert auf Katalog-Felder (alt.rest fehlt dort).
    roh = client.get(f"/process-tickets/{tid}/raw-values").json()["data"]["values"]
    assert roh == {"base.age": 33, "alt.rest": "x"}
    normal = client.get(f"/process-tickets/{tid}").json()["data"]["values"]
    assert "alt.rest" not in normal
    fremd = _client_ohne_admin()
    r = fremd.put(f"/process-tickets/{tid}/raw-values",
                  json={"values": {}, "reason": "x"})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "ADMIN_REQUIRED"
    assert fremd.get(f"/process-tickets/{tid}/raw-values").status_code == 403
    # Grund bleibt Pflicht – ein Roh-Eingriff ohne Erklärung wäre im Verlauf blind.
    r = client.put(f"/process-tickets/{tid}/raw-values", json={"values": {}})
    assert r.status_code == 422


def test_unbekannte_prioritaet_wird_abgelehnt(client):
    tid = client.post("/process-tickets", json={"processKey": "demo",
                                                "values": {"base.name": "Max"}}).json()["data"]["id"]
    r = client.patch(f"/process-tickets/{tid}", json={"priority": "mega"})
    assert r.status_code == 422
    assert r.json()["error"]["fields"][0]["path"] == "priority"
    # Der Auftrag ist unverändert.
    assert client.get(f"/process-tickets/{tid}").json()["data"]["priority"] == "normal"
