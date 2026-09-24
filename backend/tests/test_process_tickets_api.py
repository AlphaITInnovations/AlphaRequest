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


#: Start -> Freigabe(approval, on_enter-auto_advance per Haken) -> Ende.
#: Prueft: gesetzter Haken ueberspringt die Freigabe (kein Halt, keine Mail).
DEFN_SKIP = {
    "schemaVersion": 1, "key": "skip", "name": "Skip-Flow",
    "fields": [{"key": "base.name", "widget": "text"},
               {"key": "ueberspringen", "widget": "checkbox"}],
    "phases": [
        {"key": "start", "kind": "start", "responsibility": {"kind": "owner"},
         "fields": [{"ref": "base.name", "required": True}, {"ref": "ueberspringen"}],
         "automations": [{"id": "go", "trigger": {"type": "on_enter"},
                          "action": {"type": "auto_advance"}}]},
        {"key": "frei", "kind": "approval", "view": "approval",
         "responsibility": {"kind": "owner"},
         "approval": {"question": "Freigeben?", "externalLink": True, "emailBody": "x"},
         "fields": [{"ref": "base.name", "mode": "readonly"}],
         "automations": [{"id": "skip", "trigger": {"type": "on_enter"},
                          "guard": {"truthy": "ueberspringen"},
                          "action": {"type": "auto_advance"}}]},
        {"key": "ende", "kind": "task", "responsibility": {"kind": "owner"},
         "fields": [{"ref": "base.name", "mode": "readonly"}]},
    ],
}


#: Start-Phase mit einem BEDINGTEN Pflichtfeld, dessen Bedingung an einem
#: Directus-SNAPSHOT-Ziel hängt (dienstwagen). Prüft, dass die frisch ausgefüllten
#: bedingten Felder beim Anlegen NICHT vom Schreibschutz verworfen werden, bevor der
#: Snapshot das Ziel setzt (Regression: „Pflichtfeld" trotz Eingabe → 422).
DEFN_COND = {
    "schemaVersion": 1, "key": "cond", "name": "Cond-Flow",
    "fields": [
        {"key": "mitarbeiter", "widget": "directus", "directusSource": "ma",
         "directusFieldMap": [{"source": "has_car", "target": "dienstwagen"}]},
        {"key": "dienstwagen", "widget": "text"},
        {"key": "ret", "widget": "text"},
    ],
    "phases": [
        {"key": "start", "kind": "start", "responsibility": {"kind": "owner"},
         "fields": [
             {"ref": "mitarbeiter", "mode": "editable", "required": True},
             {"ref": "dienstwagen", "mode": "readonly"},
             {"ref": "ret", "mode": "editable",
              "requiredWhen": {"==": ["dienstwagen", "Ja"]},
              "visibleWhen": {"==": ["dienstwagen", "Ja"]}},
         ],
         "automations": [{"id": "go", "trigger": {"type": "on_enter"},
                          "action": {"type": "auto_advance"}}]},
        {"key": "ende", "kind": "task", "responsibility": {"kind": "owner"},
         "fields": [{"ref": "ret", "mode": "readonly"}]},
    ],
}


#: Prozess mit Dokument-Phase + bindings – für den .docx-Export (Fill-Engine).
#: `stadt` ist einem LEEREN Feld zugeordnet → muss als Lücke landen, nicht „—".
DEFN_DOC = {
    "schemaVersion": 1, "key": "doc", "name": "Doc-Flow",
    "fields": [{"key": "base.name", "widget": "text"},
               {"key": "base.city", "widget": "text"}],
    "phases": [
        {"key": "start", "kind": "start", "responsibility": {"kind": "owner"},
         "fields": [{"ref": "base.name", "required": True}]},
        {"key": "vertrag", "kind": "task", "view": "document",
         "responsibility": {"kind": "owner"},
         "document": {"title": "Vertrag", "filename": "Vertrag_{{base.name}}",
                      "bindings": {"name": "base.name", "stadt": "base.city"}}},
    ],
}


#: Bindings mit Rechen-Versatz (offset) und der Sonderquelle @today (aktuelles Datum).
DEFN_CALC = {
    "schemaVersion": 1, "key": "calc", "name": "Calc-Flow",
    "fields": [{"key": "base.name", "widget": "text"},
               {"key": "urlaub.tage", "widget": "text"}],
    "phases": [
        {"key": "start", "kind": "start", "responsibility": {"kind": "owner"},
         "fields": [{"ref": "base.name", "required": True},
                    {"ref": "urlaub.tage", "mode": "editable"}]},
        {"key": "vertrag", "kind": "task", "view": "document",
         "responsibility": {"kind": "owner"},
         "document": {"title": "V", "filename": "V",
                      "bindings": {"name": "base.name",
                                   "zusatz": {"field": "urlaub.tage", "offset": -20},
                                   "heute": {"field": "@today"}}}},
    ],
}


#: Wie DEFN_DOC, aber `base.salary` ist VERTRAULICH (nur g_hr) und einem Marker
#: zugeordnet – prüft, dass der Export die harte confidential-Sperre nicht umgeht.
DEFN_CONF = {
    "schemaVersion": 1, "key": "conf", "name": "Conf-Flow",
    "fields": [{"key": "base.name", "widget": "text"},
               {"key": "base.salary", "widget": "text",
                "visibility": {"confidential": True, "visibleToGroups": ["g_hr"]}}],
    "phases": [
        {"key": "start", "kind": "start", "responsibility": {"kind": "owner"},
         "fields": [{"ref": "base.name", "required": True},
                    {"ref": "base.salary", "mode": "editable"}]},
        {"key": "vertrag", "kind": "task", "view": "document",
         "responsibility": {"kind": "owner"},
         "document": {"title": "Vertrag", "filename": "Vertrag",
                      "bindings": {"name": "base.name", "gehalt": "base.salary"}}},
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

    def list_tickets(self, *, status=None, process_key=None, owner_id=None, q=None,
                     limit=50, offset=0):
        rows = [dict(r) for r in self.rows.values()]
        if owner_id is not None:
            rows = [r for r in rows if r.get("owner_id") == owner_id]
        if status:
            rows = [r for r in rows if r.get("status") == status]
        if process_key:
            rows = [r for r in rows if r.get("process_key") == process_key]
        if q:
            rows = [r for r in rows if q.lower() in str(r.get("title") or "").lower()]
        return rows[offset:offset + limit], len(rows)

    def get_many(self, ids):
        return [dict(self.rows[i]) for i in ids if i in self.rows]

    def list_active_full(self, limit=3000):
        return [dict(r) for r in self.rows.values()
                if r.get("status") not in ("archived", "rejected")][:limit]

    def list_all_lightweight(self, limit=2000, include_runtime=True):
        return [dict(r) for r in self.rows.values()][:limit]

    def list_global_archive(self, *, status=None, process_key=None, created_by=None, q=None,
                            date_from=None, date_to=None, date_field="updated",
                            sort="updated_desc", limit=25, offset=0):
        rows = [dict(r) for r in self.rows.values()]
        if status:
            rows = [r for r in rows if r.get("status") in status]
        if process_key:
            rows = [r for r in rows if r.get("process_key") == process_key]
        if created_by:
            cb = created_by.lower()
            rows = [r for r in rows if cb in str(r.get("owner_name") or "").lower()]
        if q:
            ql = q.lower()
            rows = [r for r in rows if ql in str(r.get("title") or "").lower()
                    or ql in str(r.get("owner_name") or "").lower() or ql in str(r.get("id"))]
        col = "created_at" if date_field == "created" else "updated_at"
        if date_from:
            rows = [r for r in rows if str(r.get(col) or "")[:10] >= date_from[:10]]
        if date_to:
            rows = [r for r in rows if str(r.get(col) or "")[:10] <= date_to[:10]]
        scol = "created_at" if sort.startswith("created") else "updated_at"
        rows.sort(key=lambda r: (str(r.get(scol) or ""), r["id"]), reverse=sort.endswith("desc"))
        return rows[offset:offset + limit], len(rows)

    def values_for_tickets(self, ids):
        return {int(i): dict(self.rows[int(i)]["values"]) for i in ids if int(i) in self.rows}


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


#: Für das View-Scoping (Sicht nach Entry-Modus): base.name = Basis (jede:r),
#: it.note = nur g_it, it.secret = vertraulich + nur g_it. review-Phase = g_it.
DEFN_VIS = {
    "schemaVersion": 1, "key": "vis", "name": "Vis-Flow",
    "fields": [
        {"key": "base.name", "widget": "text"},
        {"key": "it.note", "widget": "text", "visibility": {"visibleToGroups": ["g_it"]}},
        {"key": "it.secret", "widget": "text",
         "visibility": {"confidential": True, "visibleToGroups": ["g_it"]}},
    ],
    "phases": [
        {"key": "start", "kind": "start", "responsibility": {"kind": "owner"},
         "fields": [{"ref": "base.name", "required": True},
                    {"ref": "it.note", "mode": "editable"},
                    {"ref": "it.secret", "mode": "editable"}]},
        {"key": "review", "kind": "review",
         "responsibility": {"kind": "departments", "rule": [{"group": "g_it"}]},
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
        if key == "skip":
            return {"version": 1, "definition": DEFN_SKIP}
        if key == "cond":
            return {"version": 1, "definition": DEFN_COND}
        if key == "doc":
            return {"version": 1, "definition": DEFN_DOC}
        if key == "conf":
            return {"version": 1, "definition": DEFN_CONF}
        if key == "calc":
            return {"version": 1, "definition": DEFN_CALC}
        if key == "vis":
            return {"version": 1, "definition": DEFN_VIS}
        return None

    def get_definition(self, key, ver):
        self.definition_loads += 1
        if key == "demo":
            return {"version": ver, "definition": DEFN}
        if key == "fix":
            return {"version": ver, "definition": DEFN_FIXED}
        if key == "flow":
            return {"version": ver, "definition": DEFN_FLOW}
        if key == "skip":
            return {"version": ver, "definition": DEFN_SKIP}
        if key == "cond":
            return {"version": ver, "definition": DEFN_COND}
        if key == "doc":
            return {"version": ver, "definition": DEFN_DOC}
        if key == "conf":
            return {"version": ver, "definition": DEFN_CONF}
        if key == "calc":
            return {"version": ver, "definition": DEFN_CALC}
        if key == "vis":
            return {"version": ver, "definition": DEFN_VIS}
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


def test_document_export_fuellt_docx_vorlage(client, monkeypatch, tmp_path):
    """Ist eine .docx-Vorlage hinterlegt, füllt der Server ihre {{marker}} aus den
    Auftragswerten (bindings) und liefert die gefüllte .docx – nicht zugeordnete
    Marker werden zur Lücke; Rest bleibt."""
    from backend.services.html_to_docx import html_to_docx
    from backend.database import process_templates as tpl_db
    from backend.services import attachment_storage as storage
    from backend.services.docx_fill import GAP

    tplfile = tmp_path / "vertrag.docx"
    tplfile.write_bytes(html_to_docx("<p>Name {{name}} in {{ort}}, Stadt {{stadt}}.</p>"))
    monkeypatch.setattr(
        tpl_db, "get_template",
        lambda key, phase, doc=None: ({"process_key": key, "phase_key": phase, "stored_path": "v.docx"}
                            if key == "doc" and phase == "vertrag" else None))
    monkeypatch.setattr(storage, "full_path", lambda sp: str(tplfile))

    tid = client.post("/process-tickets",
                      json={"processKey": "doc", "values": {"base.name": "Max Mustermann"}}
                      ).json()["data"]["id"]
    r = client.post(f"/process-tickets/{tid}/document:export", json={})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document")

    import io
    import zipfile
    doc = zipfile.ZipFile(io.BytesIO(r.content)).read("word/document.xml").decode("utf-8")
    assert "Max Mustermann" in doc         # bindings name -> base.name
    assert GAP in doc                       # {{ort}} ohne Zuordnung -> Lücke
    assert "{{" not in doc                  # keine rohen Marker mehr
    # {{stadt}} ist einem LEEREN Feld zugeordnet → Lücke, NICHT „—".
    assert "—" not in doc


def test_document_export_respektiert_confidential(client, monkeypatch, tmp_path):
    """Der gefüllte Vertrag darf ein vertrauliches Feld (Gehalt) NICHT enthalten,
    wenn der Exportierende zwar Vollsicht hat (Owner), aber nicht in der Gruppe des
    Feldes ist. Die harte confidential-Sperre gilt auch hier (§5.1)."""
    from backend.services.html_to_docx import html_to_docx
    from backend.database import process_templates as tpl_db
    from backend.services import attachment_storage as storage
    from backend.services.docx_fill import GAP

    tplfile = tmp_path / "v.docx"
    tplfile.write_bytes(html_to_docx("<p>{{name}} verdient {{gehalt}}.</p>"))
    monkeypatch.setattr(
        tpl_db, "get_template",
        lambda key, phase, doc=None: ({"process_key": key, "phase_key": phase, "stored_path": "v"}
                            if key == "conf" and phase == "vertrag" else None))
    monkeypatch.setattr(storage, "full_path", lambda sp: str(tplfile))

    # Als Admin anlegen (darf das vertrauliche Feld schreiben).
    tid = client.post("/process-tickets",
                      json={"processKey": "conf",
                            "values": {"base.name": "Max", "base.salary": "50000"}}
                      ).json()["data"]["id"]
    # Export als Nicht-Admin, aber Owner (u1) und NICHT in g_hr: Vollsicht per
    # Ownership, das vertrauliche Feld bleibt aber gesperrt.
    client.app.dependency_overrides[get_current_user] = lambda: {
        "id": "u1", "displayName": "Chef", "permissions": []}
    r = client.post(f"/process-tickets/{tid}/document:export", json={})
    assert r.status_code == 200

    import io
    import zipfile
    doc = zipfile.ZipFile(io.BytesIO(r.content)).read("word/document.xml").decode("utf-8")
    assert "Max" in doc
    assert "50000" not in doc               # vertraulich -> NICHT im Vertrag
    assert GAP in doc                       # gesperrtes Feld -> Lücke


def test_document_fields_liefert_marker_mit_werten(client, monkeypatch, tmp_path):
    """Der Feld-Endpunkt listet alle Marker der Vorlage mit vorausgefüllten
    (sichtbaren) Werten – Grundlage für den Editor."""
    from backend.services.html_to_docx import html_to_docx
    from backend.database import process_templates as tpl_db
    from backend.services import attachment_storage as storage

    tplfile = tmp_path / "v.docx"
    tplfile.write_bytes(html_to_docx("<p>{{name}} in {{ort}}, Stadt {{stadt}}.</p>"))
    monkeypatch.setattr(
        tpl_db, "get_template",
        lambda key, phase, doc=None: ({"process_key": key, "phase_key": phase, "stored_path": "v"}
                            if key == "doc" and phase == "vertrag" else None))
    monkeypatch.setattr(storage, "full_path", lambda sp: str(tplfile))

    tid = client.post("/process-tickets",
                      json={"processKey": "doc", "values": {"base.name": "Max Mustermann"}}
                      ).json()["data"]["id"]
    r = client.get(f"/process-tickets/{tid}/document:fields")
    assert r.status_code == 200
    markers = {m["name"]: m for m in r.json()["data"]["markers"]}
    assert set(markers) == {"name", "ort", "stadt"}
    assert markers["name"]["bound"] and markers["name"]["value"] == "Max Mustermann"
    assert markers["ort"]["bound"] is False and markers["ort"]["value"] == ""
    assert markers["stadt"]["bound"] and markers["stadt"]["value"] == ""   # base.city leer


def test_document_export_overrides_gewinnen(client, monkeypatch, tmp_path):
    """Mit overrides füllt der Server GENAU die gesendeten Werte (Editor); leere
    Marker bleiben Lücke, unerwähnte Marker ebenfalls."""
    from backend.services.html_to_docx import html_to_docx
    from backend.database import process_templates as tpl_db
    from backend.services import attachment_storage as storage
    from backend.services.docx_fill import GAP

    tplfile = tmp_path / "v.docx"
    tplfile.write_bytes(html_to_docx("<p>{{name}} in {{ort}}, Stadt {{stadt}}.</p>"))
    monkeypatch.setattr(
        tpl_db, "get_template",
        lambda key, phase, doc=None: ({"process_key": key, "phase_key": phase, "stored_path": "v"}
                            if key == "doc" and phase == "vertrag" else None))
    monkeypatch.setattr(storage, "full_path", lambda sp: str(tplfile))

    tid = client.post("/process-tickets",
                      json={"processKey": "doc", "values": {"base.name": "Max Mustermann"}}
                      ).json()["data"]["id"]
    r = client.post(f"/process-tickets/{tid}/document:export",
                    json={"overrides": {"name": "Editor-Name", "ort": "Nürnberg", "stadt": ""}})
    assert r.status_code == 200
    import io
    import zipfile
    doc = zipfile.ZipFile(io.BytesIO(r.content)).read("word/document.xml").decode("utf-8")
    assert "Editor-Name" in doc and "Nürnberg" in doc   # overrides gesetzt
    assert "Max Mustermann" not in doc                   # Auto-Wert überschrieben
    assert GAP in doc                                    # leeres stadt -> Lücke


def test_document_export_pdf_ueber_libreoffice(client, monkeypatch, tmp_path):
    """format=pdf füllt die Vorlage und lässt LibreOffice sie nach PDF wandeln."""
    from backend.services.html_to_docx import html_to_docx
    from backend.database import process_templates as tpl_db
    from backend.services import attachment_storage as storage
    from backend.services import docx_to_pdf

    tplfile = tmp_path / "v.docx"
    tplfile.write_bytes(html_to_docx("<p>{{name}}</p>"))
    monkeypatch.setattr(
        tpl_db, "get_template",
        lambda key, phase, doc=None: ({"process_key": key, "phase_key": phase, "stored_path": "v"}
                            if key == "doc" and phase == "vertrag" else None))
    monkeypatch.setattr(storage, "full_path", lambda sp: str(tplfile))
    seen = {}
    def _fake_convert(b):
        seen["docx"] = b
        return b"%PDF-1.7 fake-pdf"
    monkeypatch.setattr(docx_to_pdf, "convert", _fake_convert)

    tid = client.post("/process-tickets",
                      json={"processKey": "doc", "values": {"base.name": "Max"}}
                      ).json()["data"]["id"]
    r = client.post(f"/process-tickets/{tid}/document:export", json={"format": "pdf"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/pdf")
    assert r.content == b"%PDF-1.7 fake-pdf"
    assert seen["docx"][:2] == b"PK"          # es wurde eine echte (gefüllte) .docx übergeben


def test_document_export_pdf_konvertierungsfehler(client, monkeypatch, tmp_path):
    """Scheitert LibreOffice, kommt ein klarer 500 statt einer kaputten Datei."""
    from backend.services.html_to_docx import html_to_docx
    from backend.database import process_templates as tpl_db
    from backend.services import attachment_storage as storage
    from backend.services import docx_to_pdf

    tplfile = tmp_path / "v.docx"
    tplfile.write_bytes(html_to_docx("<p>{{name}}</p>"))
    monkeypatch.setattr(
        tpl_db, "get_template",
        lambda key, phase, doc=None: ({"process_key": key, "phase_key": phase, "stored_path": "v"}
                            if key == "doc" and phase == "vertrag" else None))
    monkeypatch.setattr(storage, "full_path", lambda sp: str(tplfile))
    def _boom(b):
        raise docx_to_pdf.ConversionError("soffice fehlt")
    monkeypatch.setattr(docx_to_pdf, "convert", _boom)

    tid = client.post("/process-tickets",
                      json={"processKey": "doc", "values": {"base.name": "Max"}}
                      ).json()["data"]["id"]
    r = client.post(f"/process-tickets/{tid}/document:export", json={"format": "pdf"})
    assert r.status_code == 500
    assert r.json()["error"]["code"] == "PDF_CONVERSION_FAILED"


def test_document_export_offset_und_aktuelles_datum(client, monkeypatch, tmp_path):
    """Rechen-Versatz auf einem numerischen Feld (30 - 20 = 10) und die Sonderquelle
    @today (aktuelles Datum) werden korrekt eingesetzt."""
    from datetime import date
    from backend.services.html_to_docx import html_to_docx
    from backend.database import process_templates as tpl_db
    from backend.services import attachment_storage as storage

    tplfile = tmp_path / "v.docx"
    tplfile.write_bytes(html_to_docx("<p>{{name}}: {{zusatz}} am {{heute}}.</p>"))
    monkeypatch.setattr(
        tpl_db, "get_template",
        lambda key, phase, doc=None: ({"process_key": key, "phase_key": phase, "stored_path": "v"}
                            if key == "calc" and phase == "vertrag" else None))
    monkeypatch.setattr(storage, "full_path", lambda sp: str(tplfile))

    tid = client.post("/process-tickets",
                      json={"processKey": "calc",
                            "values": {"base.name": "Max", "urlaub.tage": "30"}}
                      ).json()["data"]["id"]

    # :fields zeigt die berechneten Werte + sprechende Labels.
    felder = {m["name"]: m for m in
              client.get(f"/process-tickets/{tid}/document:fields").json()["data"]["markers"]}
    assert felder["zusatz"]["value"] == "10" and "(-20)" in felder["zusatz"]["label"]
    assert felder["heute"]["label"] == "Aktuelles Datum"
    assert felder["heute"]["value"] == date.today().strftime("%d.%m.%Y")

    # Export setzt dieselben Werte ins .docx.
    import io
    import zipfile
    r = client.post(f"/process-tickets/{tid}/document:export", json={})
    doc = zipfile.ZipFile(io.BytesIO(r.content)).read("word/document.xml").decode("utf-8")
    assert "Max: 10 am " + date.today().strftime("%d.%m.%Y") in doc


def test_document_fields_ohne_leserecht_gibt_404(client):
    """Der Feld-Endpunkt darf Fremden NICHT die Existenz/Dokument-Lage verraten:
    ohne Leserecht 404 – vor jedem TEMPLATE_MISSING-Zweig."""
    tid = client.post("/process-tickets",
                      json={"processKey": "doc", "values": {"base.name": "Max"}}
                      ).json()["data"]["id"]
    client.app.dependency_overrides[get_current_user] = lambda: {
        "id": "stranger", "displayName": "X", "permissions": []}
    r = client.get(f"/process-tickets/{tid}/document:fields")
    assert r.status_code == 404


def test_document_export_ohne_vorlage_meldet_fehler(client, monkeypatch):
    """.docx-Modus ohne hinterlegte Vorlage (und ohne HTML): statt einer leeren
    Datei ein klarer 409 – der Admin soll erst eine Vorlage hochladen."""
    from backend.database import process_templates as tpl_db
    monkeypatch.setattr(tpl_db, "get_template", lambda key, phase, doc=None: None)

    tid = client.post("/process-tickets",
                      json={"processKey": "doc", "values": {"base.name": "Max"}}
                      ).json()["data"]["id"]
    r = client.post(f"/process-tickets/{tid}/document:export", json={})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "TEMPLATE_MISSING"


def test_create_rendert_titel_aus_vorlage(client):
    """Ist eine titleTemplate gesetzt, wird der Titel beim Anlegen daraus erzeugt
    (aus den Startphasen-Werten) statt aus dem manuell gesendeten Titel."""
    r = client.post("/process-tickets", json={"processKey": "flow",
                    "title": "wird ignoriert", "values": {"base.name": "Max Mustermann"}})
    assert r.status_code == 200
    assert r.json()["data"]["title"] == "Neuer Auftrag – Max Mustermann"


def test_gesetzter_haken_ueberspringt_freigabe(client):
    """Haken gesetzt: der Auftrag schaltet durch die Freigabe-Phase hindurch
    direkt in die Folgephase (kein Halt, keine Freigabe-Benachrichtigung)."""
    r = client.post("/process-tickets", json={"processKey": "skip",
                    "values": {"base.name": "Max", "ueberspringen": True}})
    assert r.status_code == 200
    assert r.json()["data"]["current_phase"] == "ende"


def test_ohne_haken_haelt_in_der_freigabe(client):
    """Haken NICHT gesetzt: der Auftrag bleibt in der Freigabe-Phase stehen."""
    r = client.post("/process-tickets", json={"processKey": "skip",
                    "values": {"base.name": "Max"}})
    assert r.status_code == 200
    assert r.json()["data"]["current_phase"] == "frei"


def test_create_bedingtes_pflichtfeld_an_snapshot_wird_nicht_verworfen(client, monkeypatch):
    """Regression: ein AUSGEFÜLLTES bedingtes Pflichtfeld, dessen visibleWhen/
    requiredWhen an einem Directus-Snapshot-Ziel (dienstwagen) hängt, darf beim
    Anlegen NICHT vom Schreibschutz verworfen werden (→ fälschlich „Pflichtfeld"/422).
    Der Snapshot (hier gefälscht: mitarbeiter gewählt → dienstwagen=Ja) muss VOR dem
    Schreibschutz greifen."""
    monkeypatch.setattr(pt.directus_snapshot, "apply_snapshots",
                        lambda defn, values, stored, **kw:
                        ({**values, "dienstwagen": "Ja"} if values.get("mitarbeiter")
                         else dict(values)))
    r = client.post("/process-tickets", json={"processKey": "cond",
                    "values": {"mitarbeiter": "123", "ret": "Nürnberg", "dienstwagen": "Ja"}})
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["values"].get("ret") == "Nürnberg"          # nicht verworfen
    assert d["values"].get("dienstwagen") == "Ja"        # autoritativer Snapshot
    assert d["current_phase"] == "ende"                  # auto_advance ging durch


def test_create_bedingtes_feld_ohne_auto_nicht_pflicht(client, monkeypatch):
    """Kehrseite (kein Über-Fix): ist kein Fahrzeug da (dienstwagen=Nein), ist das
    bedingte Feld weder sichtbar noch Pflicht – Anlegen ohne es klappt."""
    monkeypatch.setattr(pt.directus_snapshot, "apply_snapshots",
                        lambda defn, values, stored, **kw:
                        ({**values, "dienstwagen": "Nein"} if values.get("mitarbeiter")
                         else dict(values)))
    r = client.post("/process-tickets", json={"processKey": "cond",
                    "values": {"mitarbeiter": "123"}})
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["values"].get("dienstwagen") == "Nein"
    assert not d["values"].get("ret")                    # nicht erfasst, nicht verlangt
    assert d["current_phase"] == "ende"


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


def test_abilities_completable_departments_nur_eigene(client, monkeypatch):
    # u1 als Mitglied von g_it ausweisen (die Fixture ist Admin OHNE Gruppen).
    monkeypatch.setattr("backend.database.groups.get_group_ids_for_user",
                        lambda uid: ["g_it"])
    tid = client.post("/process-tickets",
                      json={"processKey": "demo", "values": {"base.name": "Max"}}).json()["data"]["id"]
    # Erstellungs-Phase: keine Fachabteilung → leer.
    ab0 = client.get(f"/process-tickets/{tid}").json()["data"]["abilities"]
    assert ab0["completable_departments"] == []
    client.post(f"/process-tickets/{tid}:advance")  # → review-Phase (Abteilung g_it)
    ab = client.get(f"/process-tickets/{tid}").json()["data"]["abilities"]
    assert ab["completable_departments"] == ["g_it"]


def test_abilities_completable_departments_leer_ohne_mitgliedschaft(client, monkeypatch):
    # Admin OHNE Gruppen-Mitgliedschaft bekommt KEINE Normal-Knöpfe (rein
    # Mitgliedschaft, kein Admin-Override) – der Endpunkt erlaubt den Eingriff weiter.
    monkeypatch.setattr("backend.database.groups.get_group_ids_for_user", lambda uid: [])
    tid = client.post("/process-tickets",
                      json={"processKey": "demo", "values": {"base.name": "Max"}}).json()["data"]["id"]
    client.post(f"/process-tickets/{tid}:advance")
    ab = client.get(f"/process-tickets/{tid}").json()["data"]["abilities"]
    assert ab["completable_departments"] == []


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


# ── Persönliches Archiv ───────────────────────────────────────────────────────

def test_archive_admin_sees_all_and_pages(client):
    for i in range(3):
        client.post("/process-tickets", json={"processKey": "demo", "values": {"base.name": f"N{i}"}})
    d = client.get("/process-tickets/archive?limit=2&offset=0").json()["data"]
    assert d["total"] == 3 and len(d["items"]) == 2 and d["truncated"] is False
    d2 = client.get("/process-tickets/archive?limit=2&offset=2").json()["data"]
    assert len(d2["items"]) == 1


def test_archive_list_department_member_vs_outsider(client, monkeypatch):
    from backend.core.dependencies import get_current_user
    tid = client.post("/process-tickets",
                      json={"processKey": "demo", "values": {"base.name": "Max"}}).json()["data"]["id"]
    monkeypatch.setattr("backend.database.groups.get_group_ids_for_user",
                        lambda uid: ["g_it"] if uid == "u_it" else [])
    # g_it ist erst in der review-Phase zuständig: SOLANGE der Auftrag in der Start-
    # Phase steht, taucht er beim g_it-Mitglied NICHT im Archiv auf.
    client.app.dependency_overrides[get_current_user] = lambda: {"id": "u_it", "permissions": []}
    d0 = client.get("/process-tickets/archive").json()["data"]
    assert all(it["id"] != tid for it in d0["items"])
    # Sobald der Auftrag die review-Phase (g_it) ERREICHT, erscheint er.
    client.app.dependency_overrides[get_current_user] = lambda: {"id": "u1", "permissions": ["admin"]}
    client.post(f"/process-tickets/{tid}:advance")                    # → review (g_it)
    client.app.dependency_overrides[get_current_user] = lambda: {"id": "u_it", "permissions": []}
    d = client.get("/process-tickets/archive").json()["data"]
    assert any(it["id"] == tid for it in d["items"])
    # Echte Unbeteiligte sehen ihn NICHT.
    client.app.dependency_overrides[get_current_user] = lambda: {"id": "u_out", "permissions": []}
    d2 = client.get("/process-tickets/archive").json()["data"]
    assert all(it["id"] != tid for it in d2["items"])


def test_archive_detail_widening_but_no_history(client, monkeypatch):
    import backend.api.v1.process_tickets as pt
    from backend.core.dependencies import get_current_user
    tid = client.post("/process-tickets",
                      json={"processKey": "demo", "values": {"base.name": "Max"}}).json()["data"]["id"]
    client.post(f"/process-tickets/{tid}:advance")                    # → review (g_it)
    client.post(f"/process-tickets/{tid}/departments/g_it:complete")  # Admin-Override
    client.post(f"/process-tickets/{tid}:advance")                    # → archiviert
    assert pt.store.rows[tid]["status"] == "archived"

    monkeypatch.setattr("backend.database.groups.get_group_ids_for_user",
                        lambda uid: ["g_it"] if uid == "u_it" else [])
    # g_it-Mitglied: darf das ARCHIVIERTE Ticket über die Archiv-Beteiligung öffnen …
    client.app.dependency_overrides[get_current_user] = lambda: {"id": "u_it", "permissions": []}
    assert client.get(f"/process-tickets/{tid}").status_code == 200
    # Die Definition MUSS mitkommen – sonst bricht die Leseansicht (braucht beide).
    assert client.get(f"/process-tickets/{tid}/definition").status_code == 200
    # … aber KEINEN Verlauf sehen (Events-Route bleibt streng: may_view, hier False).
    assert client.get(f"/process-tickets/{tid}/events").status_code in (403, 404)
    # Echte Unbeteiligte: 404 (verrät nicht mal die Existenz) – Detail UND Definition.
    client.app.dependency_overrides[get_current_user] = lambda: {"id": "u_out", "permissions": []}
    assert client.get(f"/process-tickets/{tid}").status_code == 404
    assert client.get(f"/process-tickets/{tid}/definition").status_code == 404


def test_archive_filters_status_and_process(client):
    import backend.api.v1.process_tickets as pt
    a = client.post("/process-tickets", json={"processKey": "demo", "values": {"base.name": "A"}}).json()["data"]["id"]
    b = client.post("/process-tickets", json={"processKey": "demo", "values": {"base.name": "B"}}).json()["data"]["id"]
    pt.store.rows[b]["status"] = "archived"
    # Status-Filter (Admin sieht alles): nur archivierte.
    d = client.get("/process-tickets/archive?status=archived").json()["data"]
    ids = {it["id"] for it in d["items"]}
    assert b in ids and a not in ids
    # Komma-separierte Mehrfachauswahl schließt beide ein.
    both = client.get(f"/process-tickets/archive?status=archived,{pt.store.rows[a]['status']}").json()["data"]
    assert {a, b} <= {it["id"] for it in both["items"]}
    # Prozess-Filter.
    assert {a, b} <= {it["id"] for it in client.get("/process-tickets/archive?process_key=demo").json()["data"]["items"]}
    assert client.get("/process-tickets/archive?process_key=gibtsnicht").json()["data"]["total"] == 0


def test_archive_global_scope_requires_oversight(client):
    from backend.core.dependencies import get_current_user
    for i in range(2):
        client.post("/process-tickets", json={"processKey": "demo", "values": {"base.name": f"N{i}"}})
    # Aufsicht (Admin-Fixture) sieht im globalen Archiv ALLES.
    d = client.get("/process-tickets/archive?scope=all").json()["data"]
    assert d["total"] == 2
    # Ohne Aufsicht: globales Archiv verboten (403) …
    client.app.dependency_overrides[get_current_user] = lambda: {"id": "u_norm", "permissions": []}
    assert client.get("/process-tickets/archive?scope=all").status_code == 403
    # … das persönliche Archiv bleibt für alle offen.
    assert client.get("/process-tickets/archive").status_code == 200


# ── View-Scoping: Feld-Sicht nach Entry-Modus (?view / ?department) ───────────

def _vis_ticket(client):
    """vis-Ticket (Basis + IT + vertrauliches IT-Feld), erstellt vom Admin-Owner
    u1 und in die review-Phase (Zuständigkeit g_it) gebracht."""
    tid = client.post("/process-tickets", json={"processKey": "vis", "values": {
        "base.name": "Max", "it.note": "N", "it.secret": "S"}}).json()["data"]["id"]
    assert client.post(f"/process-tickets/{tid}:advance").status_code == 200
    return tid


def _as(client, uid, perms):
    client.app.dependency_overrides[get_current_user] = lambda: {
        "id": uid, "displayName": uid, "permissions": list(perms)}


def test_view_normal_admin_sieht_nur_basis(client, monkeypatch):
    """Ein Admin, der NICHT beteiligt ist, sieht in der Normal-/Leseansicht nur die
    Basisdaten – der volle Admin-Blick ist der Admin-Ansicht vorbehalten."""
    monkeypatch.setattr("backend.database.groups.get_group_ids_for_user", lambda uid: [])
    tid = _vis_ticket(client)
    _as(client, "u_admin2", ["admin"])          # Admin, nicht Owner, ohne Gruppen
    vis = client.get(f"/process-tickets/{tid}").json()["data"]["visible_fields"]
    assert vis == ["base.name"]


def test_view_admin_modus_sieht_alles(client, monkeypatch):
    """Erst über ?view=admin sieht der Admin ALLE Felder – auch vertrauliche."""
    monkeypatch.setattr("backend.database.groups.get_group_ids_for_user", lambda uid: [])
    tid = _vis_ticket(client)
    _as(client, "u_admin2", ["admin"])
    vis = client.get(f"/process-tickets/{tid}?view=admin").json()["data"]["visible_fields"]
    assert vis == ["base.name", "it.note", "it.secret"]
    # Nicht-Admin kann sich diese Sicht NICHT über den Parameter erschleichen.
    monkeypatch.setattr("backend.database.groups.get_group_ids_for_user",
                        lambda uid: ["g_it"] if uid == "u_it" else [])
    _as(client, "u_it", [])
    vis2 = client.get(f"/process-tickets/{tid}?view=admin").json()["data"]["visible_fields"]
    assert "it.secret" in vis2  # u_it ist g_it-Mitglied → sieht es ohnehin …
    _as(client, "u_out", [])    # … ein Fremder aber nicht (kein Admin, keine Gruppe)
    # u_out hat gar keinen Zugriff (kein may_view) → 404, kein Sicht-Leak.
    assert client.get(f"/process-tickets/{tid}?view=admin").status_code == 404


def test_view_department_scoped_auf_mitglied(client, monkeypatch):
    """Fachabteilungs-Link (?view=department&department=g_it): Mitglied sieht Basis
    + genau diese Abteilung (inkl. vertraulich); Reichweite unabhängig vom Modus."""
    monkeypatch.setattr("backend.database.groups.get_group_ids_for_user",
                        lambda uid: ["g_it"] if uid == "u_it" else [])
    tid = _vis_ticket(client)
    _as(client, "u_it", [])
    vis = client.get(
        f"/process-tickets/{tid}?view=department&department=g_it").json()["data"]["visible_fields"]
    assert vis == ["base.name", "it.note", "it.secret"]


def test_view_department_kein_leak_fuer_nichtmitglied(client, monkeypatch):
    """Scope-DOWN: Wer über den g_it-Link reingeht, aber NICHT Mitglied von g_it ist
    (hier ein Admin), sieht nur die Basisdaten – der Link weitet nie über die echte
    Berechtigung hinaus aus."""
    monkeypatch.setattr("backend.database.groups.get_group_ids_for_user",
                        lambda uid: ["g_it"] if uid == "u_it" else [])
    tid = _vis_ticket(client)
    _as(client, "u_admin2", ["admin"])           # Zugriff via Aufsicht, aber kein g_it
    vis = client.get(
        f"/process-tickets/{tid}?view=department&department=g_it").json()["data"]["visible_fields"]
    assert vis == ["base.name"]
    # Und ein g_it-Mitglied, das den FALSCHEN Abteilungslink (g_hr) nutzt, sieht auch
    # nur Basis – die eigene g_it-Sicht wird über den Link nicht „mitgenommen".
    _as(client, "u_it", [])
    vis2 = client.get(
        f"/process-tickets/{tid}?view=department&department=g_hr").json()["data"]["visible_fields"]
    assert vis2 == ["base.name"]


def test_view_mutation_antwort_widert_nicht_auf(client, monkeypatch):
    """Befund 1: Eine Mutations-Antwort (hier PATCH) zeigt einem Admin NICHT mehr
    als der Detail-GET in der Normalansicht – der Admin-Bonus bleibt aus, die
    Antwort weitet die Sicht nicht wieder auf."""
    monkeypatch.setattr("backend.database.groups.get_group_ids_for_user", lambda uid: [])
    tid = client.post("/process-tickets", json={"processKey": "vis", "values": {
        "base.name": "Max", "it.note": "N", "it.secret": "S"}}).json()["data"]["id"]
    _as(client, "u_admin2", ["admin"])           # Admin, nicht Owner, ohne Gruppen
    r = client.patch(f"/process-tickets/{tid}", json={"values": {"base.name": "Y"}})
    assert r.status_code == 200
    d = r.json()["data"]
    assert "it.secret" not in d["visible_fields"]
    assert "it.secret" not in d["values"]


def test_view_liste_kein_admin_bonus(client, monkeypatch):
    """Befund 3: Die Auftrags-Liste zeigt einem Admin OHNE ?view=admin keine
    vertraulichen Felder – der volle Admin-Blick gilt nur im Detail mit ?view=admin."""
    monkeypatch.setattr("backend.database.groups.get_group_ids_for_user", lambda uid: [])
    tid = client.post("/process-tickets", json={"processKey": "vis", "values": {
        "base.name": "Max", "it.note": "N", "it.secret": "S"}}).json()["data"]["id"]
    _as(client, "u_admin2", ["admin"])
    rows = client.get("/process-tickets").json()["data"]
    row = next(r for r in rows if r["id"] == tid)
    assert "it.secret" not in row["visible_fields"]
    assert "it.secret" not in row["values"]


def test_redact_responsibility_verbirgt_vertrauliches_quellfeld():
    """Befund: die aus einem Auftragsfeld gewählte Zuständigkeit (group_from_field/
    assignable) folgt der Feld-Sicht – ein confidential-Quellfeld darf nicht über
    `responsibility` leaken."""
    from backend.schemas.process_definition import ProcessDefinition
    from backend.services import process_visibility as vis
    defn = ProcessDefinition.model_validate({
        "schemaVersion": 1, "key": "k", "name": "N",
        "fields": [{"key": "resp_grp", "widget": "group",
                    "visibility": {"confidential": True, "visibleToGroups": ["g_hr"]}}],
        "phases": [{"key": "start", "kind": "start",
                    "responsibility": {"kind": "group_from_field", "fromField": "resp_grp"},
                    "fields": [{"ref": "resp_grp"}]}],
    })
    resp = {"kind": "group", "group": "g_secret", "from_field": "resp_grp", "assignable": True}
    # Vollsicht hilft bei confidential NICHT → Wert ausgeblendet.
    ctx_no = vis.ViewerCtx(full_view=True, is_admin=False, group_ids=set())
    assert pt._redact_responsibility(resp, defn, ctx_no)["group"] is None
    # HR (Gruppe hinterlegt) sieht den Wert.
    ctx_hr = vis.ViewerCtx(full_view=False, is_admin=False, group_ids={"g_hr"})
    assert pt._redact_responsibility(resp, defn, ctx_hr)["group"] == "g_secret"
    # Feste Zuständigkeit ohne from_field bleibt unangetastet.
    fixed = {"kind": "group", "group": "g_fix"}
    assert pt._redact_responsibility(fixed, defn, ctx_no) == fixed


# ── Übersichts-Liste: Sichtbarkeit VOR der Paginierung (Skalierung) ───────────

def test_liste_nichtaufsicht_zeigt_eigene_und_zaehlt_korrekt(client, monkeypatch):
    """Ohne Aufsicht sieht man den eigenen Auftrag – und die Gesamtzahl zählt nur
    die sichtbaren (nicht die global neuesten)."""
    from backend.core.dependencies import get_current_user
    monkeypatch.setattr("backend.database.groups.get_group_ids_for_user", lambda uid: [])
    a = client.post("/process-tickets", json={"processKey": "demo",
        "values": {"base.name": "A"}}).json()["data"]["id"]
    b = client.post("/process-tickets", json={"processKey": "demo",
        "values": {"base.name": "B"}}).json()["data"]["id"]
    pt.store.rows[a]["owner_id"] = "u_norm"
    pt.store.rows[b]["owner_id"] = "u_other"
    client.app.dependency_overrides[get_current_user] = lambda: {"id": "u_norm", "permissions": []}
    body = client.get("/process-tickets").json()
    ids = [t["id"] for t in body["data"]]
    assert a in ids and b not in ids
    assert body["meta"]["total"] == 1


def test_liste_nichtaufsicht_zeigt_gruppen_zustaendige_erst_ab_erreichter_phase(client, monkeypatch):
    """Eine Fachabteilung sieht den Auftrag in der Übersicht erst, wenn ihre Phase
    aktuell ist – vorher nicht (der Aktiv-Scan wertet die aktuelle Zuständigkeit aus)."""
    from backend.core.dependencies import get_current_user
    monkeypatch.setattr("backend.database.groups.get_group_ids_for_user",
                        lambda uid: ["g_it"] if uid == "u_it" else [])
    tid = client.post("/process-tickets", json={"processKey": "demo",
        "values": {"base.name": "X"}}).json()["data"]["id"]
    pt.store.rows[tid]["owner_id"] = "u1"                      # nicht u_it
    client.app.dependency_overrides[get_current_user] = lambda: {"id": "u_it", "permissions": []}
    assert all(t["id"] != tid for t in client.get("/process-tickets").json()["data"])
    # → review-Phase (g_it)
    client.app.dependency_overrides[get_current_user] = lambda: {"id": "u1", "permissions": ["admin"]}
    client.post(f"/process-tickets/{tid}:advance")
    client.app.dependency_overrides[get_current_user] = lambda: {"id": "u_it", "permissions": []}
    assert any(t["id"] == tid for t in client.get("/process-tickets").json()["data"])


def test_liste_nichtaufsicht_zeigt_beobachtete(client, monkeypatch):
    """Ein beobachteter (fremder) Auftrag erscheint in der Übersicht."""
    from backend.core.dependencies import get_current_user
    monkeypatch.setattr("backend.database.groups.get_group_ids_for_user", lambda uid: [])
    tid = client.post("/process-tickets", json={"processKey": "demo",
        "values": {"base.name": "W"}}).json()["data"]["id"]
    pt.store.rows[tid]["owner_id"] = "u1"                      # fremd für u_norm
    monkeypatch.setattr(pt.watchers, "ticket_ids_for_watcher",
                        lambda uid: [tid] if uid == "u_norm" else [])
    client.app.dependency_overrides[get_current_user] = lambda: {"id": "u_norm", "permissions": []}
    assert any(t["id"] == tid for t in client.get("/process-tickets").json()["data"])


def test_liste_aufsicht_sieht_alles_paginiert(client):
    """Aufsicht (admin) sieht alle Aufträge – die DB paginiert, total = alle."""
    for i in range(3):
        client.post("/process-tickets", json={"processKey": "demo",
            "values": {"base.name": f"T{i}"}})
    body = client.get("/process-tickets").json()
    assert body["meta"]["total"] == 3 and len(body["data"]) == 3


def test_create_haelt_erst_eingaben_als_angaben_geaendert_fest(client, monkeypatch):
    """Beim Anlegen wird zusätzlich zum CREATED-Eintrag festgehalten, WAS in die
    Felder eingetragen wurde – als „Angaben geändert" (alt=leer → neu=Wert)."""
    calls = []
    monkeypatch.setattr(pt.events, "record",
                        lambda row, action, **kw: calls.append((action, kw)))
    client.post("/process-tickets", json={"processKey": "demo",
                "values": {"base.name": "Max", "base.age": 30}})
    actions = [a for a, _ in calls]
    assert pt.events.CREATED in actions
    assert pt.events.UPDATED in actions
    upd = next(kw for a, kw in calls if a == pt.events.UPDATED)
    changes = upd["details"]["changes"]
    assert changes["base.name"] == {"from": None, "to": "Max"}
    assert changes["base.age"]["to"] == 30
    assert set(upd["details"]["fields"]) == {"base.name", "base.age"}


def test_create_ohne_eingaben_kein_leerer_angaben_eintrag(client, monkeypatch):
    """Ohne (nicht-leere) Eingaben entsteht KEIN „Angaben geändert"-Eintrag."""
    calls = []
    monkeypatch.setattr(pt.events, "record",
                        lambda row, action, **kw: calls.append((action, kw)))
    client.post("/process-tickets", json={"processKey": "demo", "values": {}})
    assert pt.events.CREATED in [a for a, _ in calls]
    assert pt.events.UPDATED not in [a for a, _ in calls]
