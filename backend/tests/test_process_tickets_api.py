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


class FakeDefs:
    def __init__(self):
        self.definition_loads = 0

    def get_published(self, key):
        return {"version": 1, "definition": DEFN} if key == "demo" else None

    def get_definition(self, key, ver):
        self.definition_loads += 1
        return {"version": ver, "definition": DEFN} if key == "demo" else None


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


def test_create_ok(client):
    r = client.post("/process-tickets", json={"processKey": "demo", "values": {"base.name": "Max"}})
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["status"] == "in_progress"
    assert d["current_phase"] == "start"
    assert d["process_version"] == 1
    assert d["values"] == {"base.name": "Max"}


def test_patch_merges_values(client):
    tid = client.post("/process-tickets", json={"processKey": "demo", "values": {"base.name": "Max"}}).json()["data"]["id"]
    r = client.patch(f"/process-tickets/{tid}", json={"values": {"base.age": 30}})
    assert r.status_code == 200
    assert r.json()["data"]["values"] == {"base.name": "Max", "base.age": 30}


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


def test_unbekannte_prioritaet_wird_abgelehnt(client):
    tid = client.post("/process-tickets", json={"processKey": "demo",
                                                "values": {"base.name": "Max"}}).json()["data"]["id"]
    r = client.patch(f"/process-tickets/{tid}", json={"priority": "mega"})
    assert r.status_code == 422
    assert r.json()["error"]["fields"][0]["path"] == "priority"
    # Der Auftrag ist unverändert.
    assert client.get(f"/process-tickets/{tid}").json()["data"]["priority"] == "normal"
