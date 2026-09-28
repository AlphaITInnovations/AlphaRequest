"""
Bestätigte Löschung eines ganzen Prozesses.

Geprüft wird vor allem, was man später nicht mehr reparieren kann:
  * ohne Bestätigungs-Adresse (ADMIN_MAIL) ist Löschen gesperrt,
  * das Anfordern löscht NICHTS,
  * ein Token gilt nur für DIESEN Prozess in DIESEM Zustand,
  * Aufträge werden nur mitgelöscht, wenn das ausdrücklich angefordert wurde,
  * die Reihenfolge Aufträge → Definition (ein Auftrag ohne seine gepinnte
    Definition wäre nicht mehr lesbar).

Ebene 1: kein echtes MariaDB, Stores sind Attrappen.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core.dependencies import get_current_user
from backend.main import _install_error_handlers
from backend.api.v1 import processes as papi
from itsdangerous import SignatureExpired

from backend.services import process_delete as pdel

ADMIN = {"id": "u_admin", "displayName": "Admin", "permissions": ["admin"]}
MANAGER = {"id": "u_mgr", "displayName": "Verwaltung", "permissions": ["manage"]}

UEBERSICHT = {
    "key": "demo", "name": "Demo-Prozess",
    "versions": [{"version": 1, "status": "archived", "rev": 2, "tickets": 0},
                 {"version": 2, "status": "published", "rev": 5, "tickets": 3}],
    "tickets": 3,
    "fingerprint": "1:archived:2:0;2:published:5:3",
}


class FakeDefs:
    ProcessNotFound = papi.db.ProcessNotFound
    ProcessKeyExists = papi.db.ProcessKeyExists
    ProcessInvalidState = papi.db.ProcessInvalidState
    ProcessVersionInUse = papi.db.ProcessVersionInUse
    ProcessVersionConflict = papi.db.ProcessVersionConflict

    def __init__(self, uebersicht=UEBERSICHT):
        self.uebersicht = dict(uebersicht) if uebersicht else None
        self.deleted: list[str] = []

    def process_overview(self, key):
        if not self.uebersicht or key != self.uebersicht["key"]:
            return None
        return dict(self.uebersicht)

    def delete_process(self, key):
        self.deleted.append(key)
        self.uebersicht = None
        return 2


class FakeTicketStore:
    def __init__(self, rows):
        self.rows = list(rows)
        self.deleted: list[int] = []

    def list_tickets(self, **kw):
        return [dict(r) for r in self.rows], len(self.rows)

    def delete(self, tid):
        self.deleted.append(int(tid))
        return True


@pytest.fixture
def umgebung(monkeypatch):
    """API mit Attrappen. `state` steuert Nutzer, Mail-Adresse und Postausgang."""
    defs = FakeDefs()
    postausgang: list[dict] = []
    tickets = FakeTicketStore([{"id": 7, "status": "in_progress", "owner_id": "u1"},
                               {"id": 8, "status": "in_request", "owner_id": "u2"},
                               {"id": 9, "status": "archived", "owner_id": "u3"}])

    monkeypatch.setattr(papi, "db", defs)
    monkeypatch.setattr(papi, "record_audit", lambda **kw: None)
    # Mailversand abfangen: der Endpunkt importiert erst im Aufruf.
    import backend.services.microsoft_mail as mail
    monkeypatch.setattr(mail, "send_mail_app_only",
                        lambda **kw: postausgang.append(kw))
    # Der Ticket-Store wird im Endpunkt lokal importiert.
    import backend.database.process_tickets as tstore
    monkeypatch.setattr(tstore, "list_tickets", tickets.list_tickets)
    monkeypatch.setattr(tstore, "delete", tickets.delete)
    monkeypatch.setattr(pdel.config, "ADMIN_MAIL", "admin@example.org")
    monkeypatch.setattr(papi.config, "FRONTEND_URL", "https://app.example.org")

    state = {"user": dict(ADMIN)}
    app = FastAPI()
    _install_error_handlers(app)
    app.include_router(papi.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: state["user"]
    return TestClient(app), state, defs, tickets, postausgang


def anfordern(client, *, mit_auftraegen=True):
    return client.post("/api/v1/processes/demo:request-delete",
                       json={"includeTickets": mit_auftraegen})


def token_aus_mail(postausgang) -> str:
    (mail,) = postausgang
    body = mail["body"]
    marke = "token="
    start = body.index(marke) + len(marke)
    return body[start:].split("<")[0].split(" ")[0].strip()


# ── Anfordern ─────────────────────────────────────────────────────────────────

def test_anfordern_loescht_nichts_und_mailt_an_die_admin_adresse(umgebung):
    client, _state, defs, tickets, postausgang = umgebung
    r = anfordern(client)
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["recipient"] == "admin@example.org"
    assert d["tickets"] == 3 and len(d["versions"]) == 2
    # NICHTS wurde gelöscht.
    assert defs.deleted == [] and tickets.deleted == []
    # Die Mail nennt Umfang und Unumkehrbarkeit.
    (mail,) = postausgang
    assert mail["to_recipients"] == ["admin@example.org"]
    assert "3" in mail["body"] and "rueckgaengig" in mail["body"]


def test_ohne_admin_mail_ist_loeschen_gesperrt(umgebung, monkeypatch):
    """Der Bestätigungsweg IST die Sicherung – ohne Adresse kein Löschen."""
    client, _state, defs, _t, postausgang = umgebung
    monkeypatch.setattr(pdel.config, "ADMIN_MAIL", "")
    r = anfordern(client)
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "PROCESS_DELETE_NO_RECIPIENT"
    assert postausgang == [] and defs.deleted == []


def test_auftraege_muessen_ausdruecklich_mit_angefordert_werden(umgebung):
    client, _state, defs, _t, postausgang = umgebung
    r = anfordern(client, mit_auftraegen=False)
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "PROCESS_DELETE_NEEDS_TICKETS"
    assert "3" in r.json()["error"]["message"]
    assert postausgang == [] and defs.deleted == []


def test_prozess_ohne_auftraege_braucht_keine_zustimmung(umgebung, monkeypatch):
    client, _state, defs, _t, postausgang = umgebung
    defs.uebersicht = {**UEBERSICHT, "tickets": 0, "fingerprint": "2:published:5:0",
                       "versions": [{"version": 2, "status": "published",
                                     "rev": 5, "tickets": 0}]}
    assert anfordern(client, mit_auftraegen=False).status_code == 200
    assert len(postausgang) == 1


def test_nur_admin_darf_anfordern(umgebung):
    client, state, _defs, _t, postausgang = umgebung
    state["user"] = dict(MANAGER)
    assert anfordern(client).status_code == 403
    assert postausgang == []


def test_unbekannter_prozess(umgebung):
    client, *_ = umgebung
    assert client.post("/api/v1/processes/gibtsnicht:request-delete",
                       json={"includeTickets": True}).status_code == 404


def test_mailfehler_wird_gemeldet_statt_verschwiegen(umgebung, monkeypatch):
    """Ohne Mail gibt es keine Bestätigung – das muss der Aufrufende erfahren."""
    client, _state, defs, _t, _post = umgebung
    import backend.services.microsoft_mail as mail

    def boom(**kw):
        raise RuntimeError("Graph down")
    monkeypatch.setattr(mail, "send_mail_app_only", boom)
    r = anfordern(client)
    assert r.status_code == 502
    assert r.json()["error"]["code"] == "PROCESS_DELETE_MAIL_FAILED"
    assert defs.deleted == []


# ── Vorschau ──────────────────────────────────────────────────────────────────

def test_vorschau_zeigt_den_umfang_ohne_zu_loeschen(umgebung):
    client, _state, defs, tickets, postausgang = umgebung
    anfordern(client)
    t = token_aus_mail(postausgang)
    r = client.get("/api/v1/processes:delete-preview", params={"token": t})
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["key"] == "demo" and d["tickets"] == 3 and d["with_tickets"] is True
    assert d["requested_by"] == "u_admin"
    assert defs.deleted == [] and tickets.deleted == []


def test_kaputtes_token(umgebung):
    client, *_ = umgebung
    r = client.get("/api/v1/processes:delete-preview", params={"token": "quatsch"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "PROCESS_DELETE_INVALID"


def test_geaenderter_prozess_macht_das_token_ungueltig(umgebung):
    """Sonst bestätigt man einen Stand, den man nie zu sehen bekam – etwa
    inzwischen 30 statt 3 betroffene Aufträge."""
    client, _state, defs, _t, postausgang = umgebung
    anfordern(client)
    t = token_aus_mail(postausgang)
    defs.uebersicht = {**UEBERSICHT, "tickets": 30,
                       "fingerprint": "1:archived:2:0;2:published:5:30"}
    r = client.get("/api/v1/processes:delete-preview", params={"token": t})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "PROCESS_DELETE_SUPERSEDED"


def test_abgelaufenes_token(umgebung, monkeypatch):
    """Ein echtes Warten ist nicht testbar, deshalb wird der Ablauf am Serializer
    erzeugt. Geprüft wird die Kette: SignatureExpired -> Code „expired" -> 410."""
    client, _state, _defs, _t, postausgang = umgebung
    anfordern(client)
    t = token_aus_mail(postausgang)

    class Abgelaufen:
        def loads(self, *a, **k):
            raise SignatureExpired("zu alt")

    monkeypatch.setattr(pdel, "_serializer", lambda: Abgelaufen())
    r = client.get("/api/v1/processes:delete-preview", params={"token": t})
    assert r.status_code == 410
    assert r.json()["error"]["code"] == "PROCESS_DELETE_EXPIRED"


def test_nicht_positive_gueltigkeit_faellt_auf_den_standard_zurueck(monkeypatch):
    """Eine Fehlkonfiguration (0 oder negativ) darf nicht „sofort abgelaufen"
    bedeuten – das würde das Löschen unmöglich machen, ohne es zu sagen."""
    monkeypatch.setattr(pdel.config, "PROCESS_DELETE_LINK_MAX_AGE", 0)
    assert pdel.max_age_seconds() == 24 * 3600
    monkeypatch.setattr(pdel.config, "PROCESS_DELETE_LINK_MAX_AGE", -5)
    assert pdel.max_age_seconds() == 24 * 3600


# ── Bestätigen ────────────────────────────────────────────────────────────────

def test_bestaetigen_loescht_erst_die_auftraege_dann_die_definition(umgebung):
    client, _state, defs, tickets, postausgang = umgebung
    anfordern(client)
    t = token_aus_mail(postausgang)
    r = client.post("/api/v1/processes:confirm-delete", json={"token": t})
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["tickets_deleted"] == 3 and d["versions_deleted"] == 2
    assert tickets.deleted == [7, 8, 9]
    assert defs.deleted == ["demo"]


def test_zweite_bestaetigung_findet_nichts_mehr(umgebung):
    client, _state, _defs, _t, postausgang = umgebung
    anfordern(client)
    t = token_aus_mail(postausgang)
    assert client.post("/api/v1/processes:confirm-delete", json={"token": t}).status_code == 200
    r = client.post("/api/v1/processes:confirm-delete", json={"token": t})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "PROCESS_DELETE_NOT_FOUND"


def test_bestaetigen_nur_als_admin(umgebung):
    client, state, defs, tickets, postausgang = umgebung
    anfordern(client)
    t = token_aus_mail(postausgang)
    state["user"] = dict(MANAGER)
    r = client.post("/api/v1/processes:confirm-delete", json={"token": t})
    assert r.status_code == 403
    assert defs.deleted == [] and tickets.deleted == []


def test_token_eines_anderen_prozesses_greift_nicht(umgebung):
    client, _state, defs, tickets, _post = umgebung
    fremd = pdel.make_token("anderer", {**UEBERSICHT, "key": "anderer"},
                            requested_by="u_admin", include_tickets=True)
    r = client.post("/api/v1/processes:confirm-delete", json={"token": fremd})
    # „anderer" gibt es in der Attrappe nicht → nichts zu löschen.
    assert r.status_code == 404
    assert defs.deleted == [] and tickets.deleted == []


def test_token_ohne_auftrags_zustimmung_wird_beim_bestaetigen_abgewiesen(umgebung):
    """Ein von Hand gebautes Token darf die Zustimmung nicht überspringen."""
    client, _state, defs, tickets, _post = umgebung
    schmal = pdel.make_token("demo", UEBERSICHT, requested_by="u_admin",
                             include_tickets=False)
    r = client.post("/api/v1/processes:confirm-delete", json={"token": schmal})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "PROCESS_DELETE_NEEDS_TICKETS"
    assert defs.deleted == [] and tickets.deleted == []
