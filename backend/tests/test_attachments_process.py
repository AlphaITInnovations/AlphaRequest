"""
Datei-Anhänge für Prozess-Tickets – Ebene-1 (KEINE echte DB).

Zwei Ebenen werden geprüft:
  1. DB-Schicht (database.attachments): trägt jede Abfrage `entity_type` mit?
     Dafür werden nur die SQL-Helfer abgefangen und SQL/Parameter inspiziert –
     so wird die ECHTE Query geprüft, nicht eine Attrappe davon.
  2. API-Schicht (api.v1.attachments): field_key-Validierung, Welten-Trennung
     (Ticket #7 vs. Prozess-Ticket #7) und Zugriff für Unbeteiligte.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.v1 import attachments as att_api
from backend.core.dependencies import get_current_user
from backend.database import attachments as att_db
from backend.main import _install_error_handlers
from backend.schemas.process_definition import ProcessDefinition
from backend.services import attachment_storage as real_storage
from backend.services import process_runtime as pr
from backend.utils.files import human_size


# ── Definition + Ticket ───────────────────────────────────────────────────────

DEFN_DICT = {
    "schemaVersion": 1, "key": "demo", "name": "Demo-Prozess",
    "fields": [
        {"key": "vertrag", "widget": "attachment"},
        {"key": "base.name", "widget": "text"},
    ],
    "phases": [
        {"key": "start", "kind": "start", "responsibility": {"kind": "owner"},
         "fields": [{"ref": "vertrag"}, {"ref": "base.name"}]},
        {"key": "review", "kind": "review",
         "responsibility": {"kind": "departments", "rule": [{"group": "g_it"}]},
         "fields": [{"ref": "base.name", "mode": "readonly"}]},
    ],
}
DEFN = ProcessDefinition.model_validate(DEFN_DICT)

OWNER = {"id": "u_owner", "displayName": "Owner", "permissions": []}
FREMD = {"id": "u_x", "displayName": "Fremd", "permissions": []}


# ── DB-Schicht: SQL mitschneiden ──────────────────────────────────────────────

class _CapturingConn:
    def close(self):
        pass


@pytest.fixture
def sql(monkeypatch):
    """Fängt die SQL-Helfer der DB-Schicht ab und sammelt (sql, params)."""
    calls: list[tuple[str, tuple]] = []

    def _fetchall(conn, sql, params=()):
        calls.append((sql, tuple(params)))
        return []

    def _fetchone(conn, sql, params=()):
        calls.append((sql, tuple(params)))
        return {"c": 0, "v": 0}

    monkeypatch.setattr(att_db, "get_connection", lambda: _CapturingConn())
    monkeypatch.setattr(att_db, "_fetchall", _fetchall)
    monkeypatch.setattr(att_db, "_fetchone", _fetchone)
    return calls


def test_list_for_ticket_filtert_immer_nach_entity_type(sql):
    """Ohne entity_type-Filter würden Alt-Ticket #7 und Prozess-Ticket #7 dieselben
    Anhänge sehen – die Alt-Zeilen liegen weiter in derselben Tabelle und teilen
    den Spaltennamen `ticket_id`, obwohl die ID-Räume verschieden sind."""
    att_db.list_for_ticket(7)
    stmt, params = sql[-1]
    assert "entity_type=%s" in stmt
    assert params == ("process_ticket", 7)              # Default = Prozess-Welt

    att_db.list_for_ticket(7, entity_type=att_db.ENTITY_TICKET)
    assert sql[-1][1] == ("ticket", 7)


def test_list_for_ticket_field_key_ist_optionaler_filter(sql):
    att_db.list_for_ticket(7, entity_type=att_db.ENTITY_PROCESS_TICKET, field_key="vertrag")
    stmt, params = sql[-1]
    assert "field_key=%s" in stmt and params == ("process_ticket", 7, "vertrag")
    # ohne field_key: KEIN Filter (alle Anhänge des Auftrags)
    att_db.list_for_ticket(7, entity_type=att_db.ENTITY_PROCESS_TICKET)
    stmt, params = sql[-1]
    assert "field_key=%s" not in stmt and params == ("process_ticket", 7)


def test_count_for_field_none_meint_allgemeiner_anhang(sql):
    att_db.count_for_field(att_db.ENTITY_PROCESS_TICKET, 7, None)
    stmt, params = sql[-1]
    assert "field_key IS NULL" in stmt and params == ("process_ticket", 7)
    att_db.count_for_field(att_db.ENTITY_PROCESS_TICKET, 7, "vertrag")
    assert sql[-1][1] == ("process_ticket", 7, "vertrag")


def test_migrationen_sind_idempotent_und_additiv():
    """`entity_type` braucht einen Default, sonst wären bestehende Zeilen ungültig."""
    joined = " | ".join(att_db.ATTACHMENTS_MIGRATIONS)
    assert "IF NOT EXISTS" in joined
    assert "entity_type VARCHAR(32) NOT NULL DEFAULT 'ticket'" in joined
    assert "field_key VARCHAR(255) NULL" in joined
    assert "idx_att_entity (entity_type, ticket_id)" in joined


# ── API-Schicht: In-Memory-Attrappen ──────────────────────────────────────────

class FakeAttDb:
    """In-Memory-Ersatz der DB-Schicht mit derselben Filter-Semantik."""

    ENTITY_TICKET = att_db.ENTITY_TICKET
    ENTITY_PROCESS_TICKET = att_db.ENTITY_PROCESS_TICKET

    def __init__(self):
        self.rows: list[dict] = []
        self.seq = 0

    def insert_attachment(self, *, ticket_id, phase_key, family_id, original_filename,
                          stored_path, content_type, size_bytes, sha256,
                          uploaded_by_id, uploaded_by_name,
                          entity_type=att_db.ENTITY_PROCESS_TICKET, field_key=None):
        self.seq += 1
        version = 1
        if family_id:
            same = [r for r in self.rows if r["family_id"] == family_id]
            version = max((r["version"] for r in same), default=0) + 1
            for r in same:
                r["is_current"] = 0
        else:
            family_id = f"fam{self.seq}"
        row = {"id": self.seq, "entity_type": entity_type, "ticket_id": ticket_id,
               "field_key": field_key, "phase_key": phase_key, "family_id": family_id,
               "version": version, "is_current": 1, "original_filename": original_filename,
               "stored_path": stored_path, "content_type": content_type,
               "size_bytes": size_bytes, "sha256": sha256,
               "uploaded_by_id": uploaded_by_id, "uploaded_by_name": uploaded_by_name,
               "uploaded_at": "2026-08-10T10:00:00", "deleted_at": None}
        self.rows.append(row)
        return dict(row)

    def get_attachment(self, aid):
        return next((dict(r) for r in self.rows if r["id"] == aid), None)

    def list_for_ticket(self, ticket_id, *, include_versions=False,
                        entity_type=att_db.ENTITY_PROCESS_TICKET, field_key=None):
        out = [r for r in self.rows
               if r["entity_type"] == entity_type and r["ticket_id"] == ticket_id
               and r["deleted_at"] is None
               and (field_key is None or r["field_key"] == field_key)
               and (include_versions or r["is_current"])]
        return [dict(r) for r in out]

    def soft_delete(self, aid):
        for r in self.rows:
            if r["id"] == aid:
                r["deleted_at"] = "2026-08-10T11:00:00"
                r["is_current"] = 0


class FakeStore:
    """Prozess-Ticket-Store (nur `get`)."""

    def __init__(self):
        rt = pr.initial_runtime(DEFN, "t0", {})
        self.rows = {7: {"id": 7, "process_key": "demo", "process_version": 1,
                         "title": "Demo", "status": "in_progress", "priority": "normal",
                         "owner_id": "u_owner", "owner_name": "Owner",
                         "values": {}, "runtime": rt, "rev": 0}}

    def get(self, tid):
        r = self.rows.get(tid)
        return dict(r) if r else None


class FakeDefs:
    def get_definition(self, key, ver):
        return {"version": ver, "definition": DEFN_DICT} if key == "demo" else None


class FakeStorage:
    FileTooLarge = real_storage.FileTooLarge

    def __init__(self):
        self.deleted: list[str] = []

    def save_stream(self, fileobj, *, max_bytes=None):
        data = fileobj.read()
        return f"ab/blob{len(data)}", len(data), "0" * 64

    def full_path(self, stored_path):
        raise ValueError("in Tests kein echter Blob")

    def delete(self, stored_path):
        self.deleted.append(stored_path)


class FakeVis:
    """Gruppen-Mitgliedschaft ohne DB (aus dem User-Dict)."""

    @staticmethod
    def user_group_ids(user):
        return set(user.get("groups") or [])


class FakeWatchers:
    """Beobachter-Store ohne DB (nur watcher_ids)."""

    def __init__(self):
        self.ids: dict[int, set] = {}

    def watcher_ids(self, tid):
        return set(self.ids.get(tid, set()))


@pytest.fixture
def ctx(monkeypatch):
    fake_att = FakeAttDb()
    fake_store = FakeStore()
    fake_watchers = FakeWatchers()
    audits: list[dict] = []
    monkeypatch.setattr(att_api, "att_db", fake_att)
    monkeypatch.setattr(att_api, "pstore", fake_store)
    monkeypatch.setattr(att_api, "defstore", FakeDefs())
    monkeypatch.setattr(att_api, "storage", FakeStorage())
    monkeypatch.setattr(att_api, "vis", FakeVis())
    monkeypatch.setattr(att_api, "watchers", fake_watchers)
    monkeypatch.setattr(att_api, "record_audit", lambda **kw: audits.append(kw))
    return {"att": fake_att, "audits": audits, "store": fake_store,
            "watchers": fake_watchers}


def make_client(user: dict) -> TestClient:
    app = FastAPI()
    _install_error_handlers(app)
    app.include_router(att_api.router)
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


@pytest.fixture
def owner_client(ctx):
    return make_client(OWNER)


def upload(client: TestClient, *, tid: int = 7, field_key=None, family_id=None,
           content: bytes = b"PDF-Inhalt"):
    data = {}
    if field_key is not None:
        data["field_key"] = field_key
    if family_id is not None:
        data["family_id"] = family_id
    return client.post(f"/process-tickets/{tid}/attachments",
                       files={"file": ("vertrag.pdf", content, "application/pdf")},
                       data=data)


# ── field_key-Validierung ─────────────────────────────────────────────────────

def test_upload_an_anhang_feld_ok(owner_client, ctx):
    r = upload(owner_client, field_key="vertrag")
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["field_key"] == "vertrag"
    assert d["entity_type"] == "process_ticket"
    assert d["ticket_id"] == 7 and d["version"] == 1
    assert d["phase_key"] == "start"           # Phase, in der die Datei entstand
    assert d["size_human"] == human_size(len(b"PDF-Inhalt"))
    assert any(a["action"] == "file_uploaded" for a in ctx["audits"])


def test_upload_ohne_field_key_ist_allgemeiner_anhang(owner_client):
    r = upload(owner_client)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["field_key"] is None


def test_upload_an_nicht_anhang_feld_wird_abgelehnt(owner_client, ctx):
    r = upload(owner_client, field_key="base.name")     # widget=text
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "VALIDATION_FAILED"
    assert err["fields"][0]["path"] == "base.name"
    assert err["fields"][0]["code"] == "NOT_AN_ATTACHMENT_FIELD"
    assert ctx["att"].rows == []                        # nichts gespeichert


def test_upload_an_unbekanntes_feld_wird_abgelehnt(owner_client, ctx):
    r = upload(owner_client, field_key="gibtsnicht")
    assert r.status_code == 422
    assert r.json()["error"]["fields"][0]["path"] == "gibtsnicht"
    assert ctx["att"].rows == []


def test_liste_lehnt_unbekanntes_feld_ab(owner_client):
    """Ein Tippfehler soll nicht als „keine Dateien" durchgehen."""
    r = owner_client.get("/process-tickets/7/attachments", params={"field_key": "base.name"})
    assert r.status_code == 422


def test_liste_filtert_nach_feld(owner_client):
    upload(owner_client, field_key="vertrag")
    upload(owner_client)                                 # allgemein
    alle = owner_client.get("/process-tickets/7/attachments").json()["data"]
    assert len(alle) == 2
    nur_feld = owner_client.get("/process-tickets/7/attachments",
                                params={"field_key": "vertrag"}).json()["data"]
    assert [a["field_key"] for a in nur_feld] == ["vertrag"]


def test_neue_version_ueber_family_id(owner_client):
    first = upload(owner_client, field_key="vertrag").json()["data"]
    second = upload(owner_client, field_key="vertrag",
                    family_id=first["family_id"]).json()["data"]
    assert second["version"] == 2 and second["family_id"] == first["family_id"]
    aktuell = owner_client.get("/process-tickets/7/attachments").json()["data"]
    assert [a["version"] for a in aktuell] == [2]
    mit_historie = owner_client.get("/process-tickets/7/attachments",
                                    params={"include_versions": True}).json()["data"]
    assert len(mit_historie) == 2


# ── Abgrenzung zu den verbliebenen Alt-Zeilen ─────────────────────────────────

def test_alt_endpunkte_gibt_es_nicht_mehr(owner_client):
    """Die Alt-Routen /tickets/{id}/attachments sind mit dem Alt-System entfallen –
    der Pfad /tickets ist damit frei."""
    assert owner_client.get("/tickets/7/attachments").status_code == 404
    assert owner_client.post("/tickets/7/attachments").status_code == 404


def test_alt_anhang_erscheint_nicht_in_der_prozess_liste(owner_client, ctx):
    """Alt-Ticket #7 und Prozess-Ticket #7 sind verschiedene Aufträge – die
    Alt-Zeilen liegen weiter in derselben Tabelle."""
    ctx["att"].insert_attachment(
        ticket_id=7, phase_key=None, family_id=None, original_filename="alt.pdf",
        stored_path="ab/alt", content_type="application/pdf", size_bytes=3, sha256=None,
        uploaded_by_id="u_owner", uploaded_by_name="Owner",
        entity_type=att_db.ENTITY_TICKET)
    assert owner_client.get("/process-tickets/7/attachments").json()["data"] == []


def test_alt_anhang_ist_nur_fuer_admins_erreichbar(owner_client, ctx):
    """Ohne das Alt-Ticket ist nicht mehr entscheidbar, wer die Datei sehen durfte
    (vertrauliche Beschreibungsteile hingen daran) – also fail-closed."""
    ctx["att"].insert_attachment(
        ticket_id=7, phase_key=None, family_id=None, original_filename="alt.pdf",
        stored_path="ab/alt", content_type="application/pdf", size_bytes=3, sha256=None,
        uploaded_by_id="u_owner", uploaded_by_name="Owner",
        entity_type=att_db.ENTITY_TICKET)
    # Selbst die hochladende Person kommt nicht mehr heran …
    r = owner_client.delete("/attachments/1")
    assert r.status_code == 403 and r.json()["error"]["code"] == "ADMIN_REQUIRED"
    assert owner_client.get("/attachments/1/download").status_code == 403
    assert ctx["att"].rows[0]["deleted_at"] is None
    # … die Aufsicht schon (zum Aufräumen des Speichers).
    admin = make_client({"id": "u_admin", "displayName": "Admin",
                         "permissions": ["view", "manage", "admin"]})
    assert admin.delete("/attachments/1").status_code == 200
    assert ctx["att"].rows[0]["deleted_at"] is not None


# ── Zugriff ───────────────────────────────────────────────────────────────────

def test_unbeteiligte_sehen_und_laden_nicht(ctx, owner_client):
    upload(owner_client, field_key="vertrag")
    fremd = make_client(FREMD)
    # 404 statt 403: die Existenz des Auftrags wird nicht verraten.
    assert fremd.get("/process-tickets/7/attachments").status_code == 404
    assert upload(fremd, field_key="vertrag").status_code == 404
    assert fremd.get("/attachments/1/download").status_code == 404
    assert fremd.delete("/attachments/1").status_code == 404
    assert ctx["att"].rows[0]["deleted_at"] is None       # nichts gelöscht


def test_nur_zustaendige_stelle_darf_hochladen(ctx, owner_client):
    """Aufsicht (view) darf LESEN, aber nicht eingreifen → 403 beim Upload."""
    upload(owner_client, field_key="vertrag")
    aufsicht = make_client({"id": "u_view", "displayName": "Aufsicht",
                            "permissions": ["view"]})
    assert aufsicht.get("/process-tickets/7/attachments").status_code == 200
    r = upload(aufsicht, field_key="vertrag")
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "TICKET_FORBIDDEN"


def test_zustaendige_stelle_darf_loeschen_auch_fremde_datei(ctx, owner_client):
    """Anhänge gehören zum Auftrag, nicht zur hochladenden Person."""
    upload(owner_client, field_key="vertrag")
    admin = make_client({"id": "u_admin", "displayName": "Admin",
                         "permissions": ["view", "manage", "admin"]})
    assert admin.delete("/attachments/1").status_code == 200
    assert ctx["att"].rows[0]["deleted_at"] is not None
    assert any(a["action"] == "file_deleted" for a in ctx["audits"])
    # danach ist der Anhang weg (Soft-Delete)
    assert admin.delete("/attachments/1").status_code == 404


# ── Ersteller:in darf Dateien nachreichen ─────────────────────────────────────
# Beim Basis-Ticket wandert die Bearbeitung schon beim Anlegen zur Fachabteilung
# (auto-advance) – die antragstellende Person ist danach NICHT mehr may_edit,
# muss aber Unterlagen (Screenshot, Vertrag) nachreichen können.

IT_USER = {"id": "u_it", "displayName": "IT", "permissions": [], "groups": ["g_it"]}


def _zur_fachabteilung(ctx):
    """Phase 'review' aktiv: zuständig ist g_it, nicht mehr die Ersteller:in."""
    rt = ctx["store"].rows[7]["runtime"]
    rt["phases"][0]["status"] = "done"
    rt["phases"][1]["status"] = "open"
    rt["current_index"] = 1


def _abgeschlossen(ctx):
    """Alle Phasen durch – Auftrag archiviert."""
    rt = ctx["store"].rows[7]["runtime"]
    for p in rt["phases"]:
        p["status"] = "done"
    rt["current_index"] = len(rt["phases"])
    ctx["store"].rows[7]["status"] = "archived"


def test_ersteller_darf_nach_weitergabe_hochladen(ctx, owner_client):
    _zur_fachabteilung(ctx)
    r = upload(owner_client)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["phase_key"] == "review"


def test_ersteller_darf_nur_eigene_dateien_loeschen(ctx, owner_client):
    _zur_fachabteilung(ctx)
    it = make_client(IT_USER)
    upload(it)                                   # id 1: Datei der Fachabteilung
    upload(owner_client)                         # id 2: eigene Datei
    r = owner_client.delete("/attachments/1")
    assert r.status_code == 403
    assert ctx["att"].rows[0]["deleted_at"] is None
    assert owner_client.delete("/attachments/2").status_code == 200
    assert ctx["att"].rows[1]["deleted_at"] is not None


def test_ersteller_darf_fremde_datei_nicht_ueberschreiben(ctx, owner_client):
    """Neue Version = die aktuelle Datei verdrängen – für die Ersteller:in nur
    bei EIGENEN Dateien (dieselbe Grenze wie beim Löschen)."""
    _zur_fachabteilung(ctx)
    it = make_client(IT_USER)
    fremd = upload(it).json()["data"]
    assert upload(owner_client, family_id=fremd["family_id"]).status_code == 403
    eigene = upload(owner_client).json()["data"]
    r = upload(owner_client, family_id=eigene["family_id"])
    assert r.status_code == 200 and r.json()["data"]["version"] == 2


def test_ersteller_kommt_nach_abschluss_nicht_mehr_heran(ctx, owner_client):
    """Abgeschlossen: nichts mehr nachreichen und nichts mehr löschen – der
    Nachreich-Weg gilt nur für LAUFENDE Aufträge. Lesen bleibt erlaubt."""
    upload(owner_client)                         # noch in Phase 'start'
    _abgeschlossen(ctx)
    assert upload(owner_client).status_code == 403
    assert owner_client.delete("/attachments/1").status_code == 403
    assert owner_client.get("/process-tickets/7/attachments").status_code == 200


def test_zustaendige_fachabteilung_darf_weiterhin_alles(ctx, owner_client):
    _zur_fachabteilung(ctx)
    upload(owner_client)                         # Datei der Ersteller:in
    it = make_client(IT_USER)
    assert upload(it).status_code == 200
    assert it.delete("/attachments/1").status_code == 200


def test_beobachter_liest_dateien_aber_ruehrt_nichts_an(ctx, owner_client):
    """Beobachten heißt mitlesen: Liste und Download ja – Upload/Löschen nein."""
    upload(owner_client)
    ctx["watchers"].ids[7] = {"u_watch"}
    beob = make_client({"id": "u_watch", "displayName": "Beobachter", "permissions": []})
    assert beob.get("/process-tickets/7/attachments").status_code == 200
    r = upload(beob)
    assert r.status_code == 403                  # sehen ja, anfassen nein
    assert beob.delete("/attachments/1").status_code == 403
