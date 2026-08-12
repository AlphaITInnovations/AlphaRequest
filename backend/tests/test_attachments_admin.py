"""
Admin-Anhang-Übersicht (/settings/attachments) – Ebene-1 (KEINE echte DB).

Die Übersicht ist die EINZIGE Stelle, an der Anhänge beider Welten in einer
Liste stehen. Geprüft wird deshalb:
  1. DB-Schicht (database.attachments.list_all/_search_where): trägt die Ausgabe
     `entity_type`, wirkt der Welt-Filter auf Seite UND Gesamtzahl, und
     verschluckt der Titel-Join keine Zeilen? Dafür werden nur die SQL-Helfer
     abgefangen und die ECHTE Query inspiziert.
  2. API-Schicht (api.v1.attachments): Admin-Schutz, Filter-Validierung (422)
     und Durchreichen von entity_type/ticket_title.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.v1 import attachments as att_api
from backend.core.dependencies import get_current_user
from backend.database import attachments as att_db
from backend.database.users import PERM_ADMIN, PERM_VIEW
from backend.main import _install_error_handlers


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


def _count_and_page(calls: list[tuple[str, tuple]]) -> tuple[tuple[str, tuple], tuple[str, tuple]]:
    """list_all stellt genau zwei Abfragen: erst COUNT, dann die Seite."""
    assert len(calls) == 2, f"erwartet COUNT + Seite, bekommen: {len(calls)} Abfragen"
    return calls[0], calls[1]


def test_liste_ohne_filter_enthaelt_beide_welten(sql):
    """`entity_type=None` = keine Einschränkung: Alt-Tickets UND Prozess-Aufträge."""
    att_db.list_all(limit=10, offset=0)
    (count_sql, count_params), (page_sql, page_params) = _count_and_page(sql)
    assert "entity_type=%s" not in count_sql
    assert "entity_type=%s" not in page_sql
    assert count_params == ()
    assert page_params == (10, 0)          # nur Paginierung, kein Welt-Filter


def test_entity_type_filter_wirkt_auf_seite_und_gesamtzahl(sql):
    """Nur die Seite zu filtern würde die Paginierung verfälschen (zu viele Seiten)."""
    att_db.list_all(entity_type=att_db.ENTITY_PROCESS_TICKET, limit=25, offset=25)
    (count_sql, count_params), (page_sql, page_params) = _count_and_page(sql)
    assert "a.entity_type=%s" in count_sql and count_params == ("process_ticket",)
    assert "a.entity_type=%s" in page_sql and page_params == ("process_ticket", 25, 25)

    sql.clear()
    att_db.list_all(entity_type=att_db.ENTITY_TICKET)
    (_, count_params), (_, page_params) = _count_and_page(sql)
    assert count_params == ("ticket",)
    assert page_params[0] == "ticket"


def test_projektion_liefert_entity_type_und_aufgeloesten_titel(sql):
    """Ohne `entity_type` in der Ausgabe kann die Oberfläche nicht richtig verlinken;
    der Titel muss je Welt aus der passenden Tabelle kommen."""
    att_db.list_all()
    _, (page_sql, _) = _count_and_page(sql)
    assert "a.entity_type" in page_sql
    assert "a.field_key" in page_sql
    assert "COALESCE(t.title, pt.title) AS ticket_title" in page_sql


def test_titel_join_verschluckt_keine_zeilen_und_verwechselt_die_welten_nicht(sql):
    """Zwei LEFT JOINs (kein INNER) und entity_type in der ON-Bedingung: sonst
    fielen Prozess-Zeilen aus der Liste bzw. bekämen den Titel des Alt-Tickets
    mit derselben ID (Ticket #7 und Prozess-Ticket #7 existieren gleichzeitig)."""
    att_db.list_all()
    (count_sql, _), (page_sql, _) = _count_and_page(sql)
    for stmt in (count_sql, page_sql):
        assert stmt.count("LEFT JOIN") == 2
        assert "INNER JOIN" not in stmt
        assert "LEFT JOIN tickets t ON a.entity_type='ticket' AND t.id=a.ticket_id" in stmt
        assert ("LEFT JOIN process_tickets pt ON a.entity_type='process_ticket' "
                "AND pt.id=a.ticket_id") in stmt
    # Ein einziges Statement je Seite → kein N+1 für die Titel.
    assert page_sql.count("SELECT") == 1


def test_suche_greift_dateiname_person_und_titel_beider_welten(sql):
    att_db.list_all(q="Vertrag")
    _, (page_sql, page_params) = _count_and_page(sql)
    assert "a.original_filename LIKE %s" in page_sql
    assert "a.uploaded_by_name LIKE %s" in page_sql
    assert "t.title LIKE %s" in page_sql and "pt.title LIKE %s" in page_sql
    assert page_params == ("%Vertrag%", "%Vertrag%", "%Vertrag%", "%Vertrag%", 50, 0)


def test_numerische_suche_trifft_weiterhin_die_ticket_nummer(sql):
    """Verhalten des Alt-Systems bleibt erhalten: „7" findet Ticket #7."""
    att_db.list_all(q="7")
    _, (page_sql, page_params) = _count_and_page(sql)
    assert "a.ticket_id=%s" in page_sql
    assert page_params[-3:] == (7, 50, 0)


def test_suche_und_welt_filter_kombinierbar(sql):
    att_db.list_all(q="7", entity_type=att_db.ENTITY_PROCESS_TICKET)
    (count_sql, count_params), _ = _count_and_page(sql)
    assert "a.entity_type=%s" in count_sql and "a.ticket_id=%s" in count_sql
    # Reihenfolge: erst der Welt-Filter, dann die Suchparameter.
    assert count_params[0] == "process_ticket"
    assert count_params[-1] == 7


def test_search_where_default_ist_beide_welten():
    where, params = att_db._search_where()
    assert where == "a.deleted_at IS NULL" and params == ()


def test_ungueltiger_entity_type_wird_in_der_db_schicht_abgelehnt(sql):
    """Ein Tippfehler darf nicht still zu „beide Welten" werden."""
    with pytest.raises(ValueError):
        att_db.list_all(entity_type="prozess_ticket")
    assert sql == []                      # keine Abfrage abgesetzt


# ── API-Schicht: In-Memory-Attrappe ───────────────────────────────────────────

ADMIN = {"id": "u_admin", "displayName": "Admin", "permissions": [PERM_VIEW, PERM_ADMIN]}
VIEWER = {"id": "u_view", "displayName": "Aufsicht", "permissions": [PERM_VIEW]}


def _row(aid: int, entity_type: str, ticket_id: int, title: str | None,
         filename: str = "datei.pdf", field_key=None) -> dict:
    return {"id": aid, "entity_type": entity_type, "ticket_id": ticket_id,
            "field_key": field_key, "ticket_title": title, "phase_key": None,
            "family_id": f"fam{aid}", "version": 1, "is_current": 1,
            "original_filename": filename, "stored_path": f"ab/{aid}",
            "content_type": "application/pdf", "size_bytes": 1024, "sha256": "0" * 64,
            "uploaded_by_id": "u_owner", "uploaded_by_name": "Owner",
            "uploaded_at": "2026-08-10T10:00:00", "deleted_at": None}


ROWS = [
    _row(1, att_db.ENTITY_TICKET, 7, "Alt-Ticket sieben", "alt.pdf"),
    _row(2, att_db.ENTITY_PROCESS_TICKET, 7, "Onboarding Meier", "vertrag.pdf",
         field_key="vertrag"),
    _row(3, att_db.ENTITY_PROCESS_TICKET, 9, "Zugang Schulz", "ausweis.pdf"),
]


class FakeAdminDb:
    """Ersatz der DB-Schicht mit derselben Filter-/Zähl-Semantik wie list_all."""

    ENTITY_TICKET = att_db.ENTITY_TICKET
    ENTITY_PROCESS_TICKET = att_db.ENTITY_PROCESS_TICKET
    ENTITY_TYPES = att_db.ENTITY_TYPES

    def __init__(self, rows: list[dict]):
        self.rows = rows
        self.calls: list[dict] = []

    def list_all(self, *, q=None, entity_type=None, limit=50, offset=0):
        self.calls.append({"q": q, "entity_type": entity_type, "limit": limit, "offset": offset})
        if entity_type is not None and entity_type not in self.ENTITY_TYPES:
            raise ValueError(entity_type)
        sel = [r for r in self.rows
               if entity_type is None or r["entity_type"] == entity_type]
        if q:
            ql = q.strip().lower()
            sel = [r for r in sel
                   if ql in r["original_filename"].lower()
                   or ql in (r.get("ticket_title") or "").lower()]
        return [dict(r) for r in sel[offset:offset + limit]], len(sel)

    def stats(self):
        return {"count": len(self.rows),
                "total_bytes": sum(r["size_bytes"] for r in self.rows)}


@pytest.fixture
def fake_db(monkeypatch):
    fake = FakeAdminDb([dict(r) for r in ROWS])
    monkeypatch.setattr(att_api, "att_db", fake)
    return fake


def make_client(user: dict) -> TestClient:
    app = FastAPI()
    _install_error_handlers(app)
    app.include_router(att_api.router)
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


@pytest.fixture
def admin_client(fake_db):
    return make_client(ADMIN)


def test_liste_ohne_filter_zeigt_beide_welten_mit_entity_type(admin_client, fake_db):
    r = admin_client.get("/settings/attachments")
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["total"] == 3
    assert [i["entity_type"] for i in data["items"]] == ["ticket", "process_ticket", "process_ticket"]
    assert fake_db.calls[-1]["entity_type"] is None      # kein Filter durchgereicht


def test_liste_reicht_titel_und_feld_mit_aus(admin_client):
    items = admin_client.get("/settings/attachments").json()["data"]["items"]
    nach_id = {i["id"]: i for i in items}
    assert nach_id[1]["ticket_title"] == "Alt-Ticket sieben"
    assert nach_id[2]["ticket_title"] == "Onboarding Meier"
    assert nach_id[2]["field_key"] == "vertrag"
    assert nach_id[1]["field_key"] is None
    # Alt-Spalten bleiben unverändert vorhanden
    assert nach_id[1]["size_human"] and nach_id[1]["family_id"] == "fam1"


def test_filter_beschraenkt_liste_und_gesamtzahl(admin_client, fake_db):
    r = admin_client.get("/settings/attachments", params={"entity_type": "process_ticket"})
    data = r.json()["data"]
    assert data["total"] == 2                            # Gesamtzahl folgt dem Filter
    assert {i["entity_type"] for i in data["items"]} == {"process_ticket"}
    assert fake_db.calls[-1]["entity_type"] == "process_ticket"

    alt = admin_client.get("/settings/attachments", params={"entity_type": "ticket"}).json()["data"]
    assert alt["total"] == 1 and alt["items"][0]["id"] == 1


def test_paginierung_bleibt_unabhaengig_von_der_seite(admin_client):
    seite = admin_client.get("/settings/attachments",
                             params={"entity_type": "process_ticket", "limit": 1}).json()["data"]
    assert len(seite["items"]) == 1 and seite["total"] == 2


def test_ungueltiger_filterwert_ist_422(admin_client, fake_db):
    r = admin_client.get("/settings/attachments", params={"entity_type": "prozess"})
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "VALIDATION_FAILED"
    assert err["fields"][0]["path"] == "entity_type"
    assert fake_db.calls == []                           # nichts abgefragt


def test_leerer_filterwert_ist_422_und_nicht_still_beide_welten(admin_client):
    assert admin_client.get("/settings/attachments",
                            params={"entity_type": ""}).status_code == 422


def test_erlaubte_filterwerte_entsprechen_den_db_konstanten(admin_client):
    """Route-Literal und att_db-Konstanten dürfen nicht auseinanderlaufen."""
    schema = admin_client.get("/openapi.json").json()
    params = schema["paths"]["/settings/attachments"]["get"]["parameters"]
    p = next(p for p in params if p["name"] == "entity_type")
    # Optional[Literal[...]] steht als anyOf(enum, null) im Schema; robust gegen beides.
    subs = p["schema"].get("anyOf") or [p["schema"]]
    enums = [e for sub in subs for e in sub.get("enum", []) if e is not None]
    assert set(enums) == {att_db.ENTITY_TICKET, att_db.ENTITY_PROCESS_TICKET}


def test_nur_admins_sehen_die_uebersicht(fake_db):
    viewer = make_client(VIEWER)
    r = viewer.get("/settings/attachments")
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "ADMIN_REQUIRED"
    r = viewer.get("/settings/attachments/stats")
    assert r.status_code == 403
    assert fake_db.calls == []
