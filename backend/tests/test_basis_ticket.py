"""Ebene-1: Das ausgelieferte Basis-Ticket (Handoff-Ticket) – Definition + Laufzeit.

Geprüft wird der ECHTE Seed (`backend/seeds/processes/prozess-basis-ticket.json`),
nicht eine Nachbildung: er ist das fachliche Versprechen „ein ganz normales
Ticket, um sich Aufträge zwischen Fachabteilungen hin und her zu schieben".

Warum der Seed so aussieht, wie er aussieht (JSON kann keine Kommentare tragen,
darum steht die Begründung hier):

* **Zuständigkeit über ein FELD** (`responsibility.kind=group_from_field` mit
  `fromField=ticket.fachabteilung`). Das Alt-System ließ die anlegende Person
  eine Gruppe auswählen („Verantwortlich", nur Gruppen) und schrieb sie per
  `set_phase_responsibility` in den Workflow. Datengetrieben ist das genau
  `group_from_field`: die Gruppe steht im Auftrag, nicht in der Definition –
  deshalb braucht der Seed auch keinen Gruppen-Platzhalter mehr und der Seeder
  keine Konfiguration.
* **Das Feld ist in der Bearbeitungsphase editierbar.** Auch das ist Alt-Verhalten
  (`useBasisTicket._performEdit` schickte `assignee_id`/`accountable_id` bei JEDEM
  Speichern mit) und der ganze Zweck des Tickets: die bearbeitende Abteilung gibt
  weiter, die Zuständigkeit wandert mit dem Feldwert.
* **Freitext als `collection`/append_only statt `textarea`.** Der Auftrags-Verlauf
  (`process_ticket_events`) trägt bewusst NUR Feld-SCHLÜSSEL, nie Feld-WERTE
  (§5.1 / process_events-Docstring). Ein einzelnes, editierbares Textfeld könnte
  die nächste Abteilung also überschreiben, ohne dass der alte Text irgendwo
  wiederherstellbar wäre. Append-only-Einträge mit serverseitigem Namen und
  Zeitstempel sind genau das, was fachlich verlangt ist („Freitextfeld mit
  Historie im Ticket"), und sie sind zugleich das Alt-Verhalten
  (`ticket.eintraege`).
* **Kein eigenes Titel-FELD.** Der Auftrag hat schon einen Titel (Spalte `title`,
  im Anlege-Formular als „Titel" eingegeben, in Listen und Kopfzeile sichtbar).
  Ein zweites `ticket.titel` würde die Betreffzeile doppelt abfragen und die
  Fassung im Feld würde nirgends als Titel erscheinen – im Alt-System war der
  eingegebene Titel der TICKET-Titel (`title = data.title`), nicht ein
  Beschreibungsfeld.
"""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core.dependencies import get_current_user
from backend.database.process_tickets import ProcessTicketConflict
from backend.main import _install_error_handlers
from backend.api.v1 import process_tickets as pt
from backend.schemas.process_definition import (
    FieldMode, ProcessDefinition, ResponsibilityKind, Widget,
)
from backend.seeds import PROCESS_SEED_DIR
from backend.services import process_access as acc
from backend.services import process_actions as pactions
from backend.services import process_runtime as pr
from backend.services import process_visibility as vis

SEED_ROH = json.loads((PROCESS_SEED_DIR / "prozess-basis-ticket.json")
                      .read_text(encoding="utf-8"))
DEFN = ProcessDefinition.model_validate(SEED_ROH)
START, BEARBEITUNG = DEFN.phases

FELD = "ticket.fachabteilung"
IT, FUHRPARK = "gid-it", "gid-fp"

GRUPPEN = [
    {"id": IT, "name": "IT", "distributions": ["it@example.org"]},
    {"id": FUHRPARK, "name": "Fuhrpark", "distributions": ["fuhrpark@example.org"]},
]

ANLEGER = {"id": "u_anleger", "displayName": "Anna Anleger", "permissions": [], "gruppen": []}
ITLER = {"id": "u_it", "displayName": "Ida IT", "permissions": [], "gruppen": [IT]}
FUHRPARKLER = {"id": "u_fp", "displayName": "Frank Fuhrpark", "permissions": [], "gruppen": [FUHRPARK]}
AUFSICHT = {"id": "u_view", "displayName": "Vera View", "permissions": ["view"], "gruppen": []}
ADMIN = {"id": "u_admin", "displayName": "Adam Admin", "permissions": ["admin"], "gruppen": []}


# ── Die Definition selbst ─────────────────────────────────────────────────────

def test_seed_validiert_und_braucht_keinen_platzhalter():
    """Ohne Platzhalter gibt es für den Seeder nichts zu konfigurieren."""
    assert "HIER_" not in json.dumps(SEED_ROH, ensure_ascii=False)
    assert DEFN.key == "basis-ticket"
    # Jede:r eingeloggte Mensch durfte Basis-Tickets anlegen (Alt: keine Prüfung).
    assert DEFN.createPermissions.everyone is True


def test_titel_ist_fest():
    """Der Titel wird beim Anlegen festgelegt und ist danach überall nur lesbar –
    der PATCH-Endpunkt weist Änderungen mit TITLE_LOCKED ab."""
    assert DEFN.titleEditable is False


def test_immer_gleich_aufgebaut_ein_gruppenfeld_und_ein_freitext_verlauf():
    felder = {f.key: f for f in DEFN.fields}
    assert set(felder) == {FELD, "ticket.eintraege"}
    assert felder[FELD].widget == Widget.group
    eintraege = felder["ticket.eintraege"]
    assert eintraege.widget == Widget.collection
    assert eintraege.mode == FieldMode.append_only
    # Autor und Zeitpunkt stempelt der Server – nicht fälschbar.
    gestempelt = {sf.key: sf.value for sf in eintraege.item
                  if sf.widget == Widget.server_stamped}
    assert gestempelt == {"author_name": "actor", "timestamp": "now"}


def test_zustaendigkeit_haengt_am_feld_und_bleibt_dort_editierbar():
    assert BEARBEITUNG.responsibility.kind == ResponsibilityKind.group_from_field
    assert BEARBEITUNG.responsibility.fromField == FELD
    # Der eigentliche Zweck: die bearbeitende Abteilung darf weiterreichen.
    modi = {fr.ref: fr.mode for fr in BEARBEITUNG.fields}
    assert modi[FELD] == FieldMode.editable
    assert modi["ticket.eintraege"] == FieldMode.append_only


def test_weitergabe_wird_gemeldet():
    """Ohne Automation erfährt die neue Abteilung nichts: die Zuständigkeits-Mail
    hängt am Phasen-EINTRITT, und die Phase wechselt beim Weitergeben nicht."""
    (auto,) = BEARBEITUNG.automations
    assert auto.trigger.type.value == "on_field_change"
    assert auto.trigger.field == FELD
    assert auto.action.type.value == "notify" and auto.action.to == "responsible"


# ── Zuständigkeit folgt dem Feldwert (reine Logik) ─────────────────────────────

def auftrag(gruppe, *, eintraege=None, in_bearbeitung=True) -> dict:
    values = {FELD: gruppe, "ticket.eintraege": eintraege or []}
    runtime = pr.initial_runtime(DEFN, "t0", values)
    if in_bearbeitung:
        runtime, _status = pr.advance(DEFN, runtime, "t1", values)
    return {"id": 1, "owner_id": ANLEGER["id"], "status": "in_progress",
            "values": values, "runtime": runtime}


def test_gewaehlte_abteilung_ist_zustaendig():
    t = auftrag(IT)
    assert acc.responsible_groups(DEFN, t) == {IT}
    assert acc.may_edit(DEFN, t, ITLER, [IT]) is True


def test_fremde_abteilung_darf_weder_sehen_noch_bearbeiten():
    t = auftrag(IT)
    assert acc.may_view(DEFN, t, FUHRPARKLER, [FUHRPARK]) is False
    assert acc.may_edit(DEFN, t, FUHRPARKLER, [FUHRPARK]) is False


def test_zustaendigkeit_wandert_beim_weiterreichen_mit():
    t = auftrag(IT)
    t["values"][FELD] = FUHRPARK              # IT reicht an den Fuhrpark weiter
    assert acc.responsible_groups(DEFN, t) == {FUHRPARK}
    assert acc.may_edit(DEFN, t, FUHRPARKLER, [FUHRPARK]) is True
    # …und die abgebende Abteilung ist es nicht mehr.
    assert acc.may_edit(DEFN, t, ITLER, [IT]) is False


def test_aufsicht_liest_admin_greift_ein():
    t = auftrag(IT)
    assert acc.may_view(DEFN, t, AUFSICHT, []) is True
    assert acc.may_edit(DEFN, t, AUFSICHT, []) is False
    assert acc.may_edit(DEFN, t, ADMIN, []) is True


def test_zustaendigkeit_wird_als_normale_gruppe_aufgeloest():
    """Nach außen eine gewöhnliche Gruppen-Zuständigkeit – so greifen Mailversand
    und Rechte unverändert."""
    resp = pr.resolve_responsibility(BEARBEITUNG, {FELD: IT})
    assert resp["kind"] == "group" and resp["group"] == IT
    assert resp["from_field"] == FELD


def test_ohne_abteilung_ist_niemand_zustaendig():
    """Bekannte Kehrseite: wird das Feld geleert, kann nur noch ein Admin
    eingreifen. Deshalb ist es in beiden Phasen `required`."""
    t = auftrag("")
    assert acc.responsible_groups(DEFN, t) == set()
    assert acc.may_edit(DEFN, t, ITLER, [IT]) is False
    assert acc.may_edit(DEFN, t, ADMIN, []) is True
    assert all(fr.required for p in DEFN.phases for fr in p.fields if fr.ref == FELD)


def test_bekannte_luecke_bearbeitende_gruppe_gilt_nicht_als_bearbeitende_seite():
    """`staff_groups` liest die Definition – bei `group_from_field` steht die
    Gruppe aber im Auftrag. Interne Nachträge bleiben deshalb der Aufsicht
    vorbehalten (siehe process_access.is_process_staff). Schlägt dieser Test fehl,
    wurde die Einschränkung behoben – dann hier nachziehen."""
    assert acc.staff_groups(DEFN) == set()
    assert acc.is_process_staff(DEFN, ITLER, [IT]) is False
    assert acc.is_process_staff(DEFN, AUFSICHT, []) is True


# ── Schreibschutz: weitergeben ja, Einträge umschreiben nein ───────────────────

def ctx_fuer(gruppe) -> vis.ViewerCtx:
    return vis.ViewerCtx(full_view=False, is_admin=False, group_ids={gruppe})


def test_zustaendige_gruppe_darf_die_abteilung_umschreiben():
    stored = {FELD: IT, "ticket.eintraege": []}
    merged = vis.apply_writes(DEFN, BEARBEITUNG, stored, {FELD: FUHRPARK}, ctx_fuer(IT))
    assert merged[FELD] == FUHRPARK


def test_bestehende_eintraege_sind_unantastbar():
    alt = [{"text": "Bitte prüfen", "author_name": "Anna", "timestamp": "t0"}]
    stored = {FELD: IT, "ticket.eintraege": alt}
    # Anhängen: erlaubt.
    merged = vis.apply_writes(
        DEFN, BEARBEITUNG, stored,
        {"ticket.eintraege": alt + [{"text": "läuft"}]}, ctx_fuer(IT))
    assert len(merged["ticket.eintraege"]) == 2
    # Umschreiben/Löschen: nicht.
    with pytest.raises(vis.AppendOnlyViolation):
        vis.apply_writes(DEFN, BEARBEITUNG, stored,
                         {"ticket.eintraege": [{"text": "war nie so"}]}, ctx_fuer(IT))


def test_titel_bleibt_der_auftrags_titel():
    """Kein Feld für den Betreff – sonst stünde er zweimal im Formular."""
    assert not [f for f in DEFN.fields if "titel" in f.key or "betreff" in f.key]


# ── Benachrichtigung: die NEUE Abteilung wird angeschrieben ───────────────────

def test_weitergabe_mail_geht_an_den_verteiler_der_neuen_abteilung():
    t = auftrag(FUHRPARK)                    # Stand NACH dem Weiterreichen
    empfaenger = pactions.resolve_recipients("responsible", t, BEARBEITUNG, GRUPPEN)
    assert empfaenger == ["fuhrpark@example.org"]


# ── Ende zu Ende über die API ─────────────────────────────────────────────────

class FakeStore:
    ProcessTicketConflict = ProcessTicketConflict

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
        r["values"] = json.loads(values_json)
        if title is not None:
            r["title"] = title
        r["rev"] += 1
        return dict(r)

    def update_runtime(self, tid, *, runtime_json, status, next_timer_due_at=None,
                       expected_rev=None):
        r = self.rows[tid]
        self._guard(r, expected_rev)
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


class FakeDefs:
    def get_published(self, key):
        return {"version": 1, "definition": SEED_ROH} if key == DEFN.key else None

    def get_definition(self, key, ver):
        return {"version": ver, "definition": SEED_ROH} if key == DEFN.key else None


class FakeFires:
    def fired_map(self, tid, pk, ep):
        return {}

    def claim(self, *a, **k):
        return True


@pytest.fixture
def umgebung(monkeypatch):
    """API mit In-Memory-Store; angemeldete Person und Postausgang umschaltbar."""
    from backend.database import groups as groupsdb
    from backend.services import process_engine as engine

    store = FakeStore()
    monkeypatch.setattr(pt, "store", store)
    monkeypatch.setattr(pt, "defstore", FakeDefs())
    monkeypatch.setattr(engine, "store", store)
    monkeypatch.setattr(engine, "fires", FakeFires())
    # Gruppen-Mitgliedschaft steckt in der Test-Person, nicht in einer DB.
    monkeypatch.setattr(vis, "user_group_ids", lambda u: set(u.get("gruppen") or []))
    monkeypatch.setattr(pt, "get_group_ids_for_user", lambda uid: [])
    monkeypatch.setattr(groupsdb, "get_groups", lambda: [dict(g) for g in GRUPPEN])

    postausgang: list[tuple] = []
    monkeypatch.setattr(engine, "SENDER",
                        lambda to, subject, body, kind="automation":
                        postausgang.append((sorted(to), subject, kind)))

    angemeldet = {"user": ANLEGER}
    app = FastAPI()
    _install_error_handlers(app)
    app.include_router(pt.router)
    app.dependency_overrides[get_current_user] = lambda: angemeldet["user"]
    return TestClient(app), angemeldet, postausgang


def anlegen(client, gruppe=IT, text="Drucker im 2. OG druckt nicht"):
    r = client.post("/process-tickets", json={
        "processKey": DEFN.key, "title": "Drucker defekt",
        "values": {FELD: gruppe, "ticket.eintraege": [{"text": text}]}})
    assert r.status_code == 200, r.text
    return r.json()["data"]


def test_jede_person_darf_anlegen_und_der_server_stempelt_den_eintrag(umgebung):
    client, _angemeldet, _post = umgebung
    d = anlegen(client)
    # Der Auftrag landet SOFORT bei der gewählten Fachabteilung – wie im
    # Alt-System, wo /tickets/basis über die Erstellungsphase hinweg schaltete.
    # Ohne das läge er unbemerkt bei der erstellenden Person.
    assert d["current_phase"] == "bearbeitung"
    (eintrag,) = d["values"]["ticket.eintraege"]
    assert eintrag["author_name"] == ANLEGER["displayName"] and eintrag["timestamp"]


def test_anlegen_legt_den_auftrag_direkt_bei_der_gewaehlten_abteilung(umgebung):
    client, angemeldet, postausgang = umgebung
    d = anlegen(client)
    tid = d["id"]

    assert d["current_phase"] == "bearbeitung"
    assert d["responsibility"] == {"kind": "group", "group": IT,
                                   "from_field": FELD, "assignable": True}
    # Die gewählte Abteilung wird beim Eintritt in die Bearbeitung benachrichtigt.
    assert [(to, kind) for to, _s, kind in postausgang] == [
        (["it@example.org"], "phase_entry")]

    # Die fremde Abteilung sieht den Auftrag nicht einmal (bewusst 404).
    angemeldet["user"] = FUHRPARKLER
    assert client.patch(f"/process-tickets/{tid}",
                        json={"values": {FELD: FUHRPARK}}).status_code == 404
    # Aufsicht darf lesen, aber nicht eingreifen.
    angemeldet["user"] = AUFSICHT
    assert client.get(f"/process-tickets/{tid}").status_code == 200
    r = client.patch(f"/process-tickets/{tid}", json={"values": {FELD: FUHRPARK}})
    assert r.status_code == 403 and r.json()["error"]["code"] == "TICKET_FORBIDDEN"


def test_hin_und_her_schieben_die_zustaendigkeit_wandert_und_wird_gemeldet(umgebung):
    client, angemeldet, postausgang = umgebung
    tid = anlegen(client)["id"]

    # Die IT ergänzt einen Eintrag und gibt an den Fuhrpark weiter.
    angemeldet["user"] = ITLER
    bestand = client.get(f"/process-tickets/{tid}").json()["data"]["values"]["ticket.eintraege"]
    postausgang.clear()
    r = client.patch(f"/process-tickets/{tid}", json={"values": {
        FELD: FUHRPARK,
        "ticket.eintraege": bestand + [{"text": "Nicht die IT, sondern der Fuhrpark"}]}})
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["responsibility"]["group"] == FUHRPARK
    assert d["current_phase"] == "bearbeitung"          # kein Phasenwechsel
    assert d["abilities"]["edit"] is False              # die IT ist raus
    # Der zweite Eintrag ist auf die IT gestempelt, der erste unverändert.
    namen = [e["author_name"] for e in d["values"]["ticket.eintraege"]]
    assert namen == [ANLEGER["displayName"], ITLER["displayName"]]
    # …und der neue Verteiler wurde angeschrieben.
    assert [(to, kind) for to, _s, kind in postausgang] == [
        (["fuhrpark@example.org"], "notify")]

    # Jetzt arbeitet der Fuhrpark – und schließt ab.
    angemeldet["user"] = FUHRPARKLER
    assert client.get(f"/process-tickets/{tid}").json()["data"]["abilities"]["edit"] is True
    fertig = client.post(f"/process-tickets/{tid}:advance")
    assert fertig.status_code == 200
    assert fertig.json()["data"]["status"] == "archived"


def test_abteilung_ist_pflicht_beim_anlegen(umgebung):
    """Weil direkt weitergeschaltet wird, greift die Pflichtprüfung schon beim
    Anlegen – ein Auftrag ohne Abteilung dürfte nicht unvollständig in die
    Bearbeitung rutschen."""
    client, _angemeldet, _post = umgebung
    r = client.post("/process-tickets", json={
        "processKey": DEFN.key,
        "values": {"ticket.eintraege": [{"text": "ohne Abteilung"}]}})
    assert r.status_code == 422
    assert any(f["path"] == FELD and f["code"] == "REQUIRED"
               for f in r.json()["error"]["fields"])


def test_zustaendigkeit_darf_nicht_geleert_werden(umgebung):
    """Ein PATCH mit leerem Gruppenfeld käme sonst durch beide Validierungspässe
    (`validate_values` lässt explizites Leeren zu, die Pflicht greift erst beim
    Phasenabschluss) – danach wäre NIEMAND mehr zuständig und nur noch ein Admin
    käme an den Auftrag. Das ist kein halbfertiger Entwurf, sondern Rechteverlust."""
    client, angemeldet, _post = umgebung
    tid = anlegen(client)["id"]
    angemeldet["user"] = ITLER

    r = client.patch(f"/process-tickets/{tid}", json={"values": {FELD: None}})
    assert r.status_code == 422
    assert any(f["path"] == FELD and f["code"] == "REQUIRED"
               for f in r.json()["error"]["fields"])
    # Der Auftrag hängt unverändert bei der IT.
    d = client.get(f"/process-tickets/{tid}").json()["data"]
    assert d["responsibility"]["group"] == IT
    assert d["abilities"]["edit"] is True

    # Ein leerer STRING ist derselbe Fall.
    assert client.patch(f"/process-tickets/{tid}",
                        json={"values": {FELD: ""}}).status_code == 422


def test_weitergabe_mail_heisst_nicht_erinnerung(umgebung):
    """`template` der Automation trägt den Anlass. Ohne ihn betitelte
    process_actions jede notify-Mail als „Erinnerung" – für eine Aufgabe, die die
    Abteilung zum ERSTEN Mal sieht, ist das schlicht falsch."""
    client, angemeldet, postausgang = umgebung
    tid = anlegen(client)["id"]
    angemeldet["user"] = ITLER
    postausgang.clear()
    client.patch(f"/process-tickets/{tid}", json={"values": {FELD: FUHRPARK}})
    betreffe = [s for _to, s, _k in postausgang]
    assert betreffe, "die neue Abteilung muss benachrichtigt werden"
    assert any("Neue Aufgabe" in s for s in betreffe)
    assert not any("Erinnerung" in s for s in betreffe)
