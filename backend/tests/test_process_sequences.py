"""
Ebene-1: fortlaufende Nummern-Vergabe (`assign_sequence` / widget=server_generated).

Drei Schichten, alle OHNE echte DB:
  1. Fälligkeit – reine Logik auf der Definition (welche Phase vergibt was?).
  2. Ledger (`database.process_sequences`) – die Transaktion selbst: die SQL-Helfer
     werden abgefangen, gegen eine Mini-Tabelle beantwortet und mitgeschnitten
     (Muster: test_attachments_admin). Geprüft wird, was man später nicht mehr
     reparieren kann: FOR UPDATE, Idempotenz, der IntegrityError-Pfad.
  3. Dienst (`services.process_sequences`) – Fachlogik gegen eine Ledger-Attrappe
     mit derselben Zusage wie das echte Ledger (allocate läuft nur beim ERSTEN Mal).

Fachliche Messlatte ist überall das Alt-System: Nummernkreis je Firma,
führende Nullen aus der Bereichsbreite, Warn-Schwelle, erschöpfter Bereich = Fehler.
"""
import json

import pymysql
import pytest
from pydantic import ValidationError

from backend.database import process_sequences as ledger
from backend.database.process_tickets import ProcessTicketConflict
from backend.schemas.process_definition import ProcessDefinition
from backend.services import process_sequences as svc


# ── Definition ────────────────────────────────────────────────────────────────

def make_defn(*, counter: str = "personalnummer", company_ref: str = "base.company",
              zweite_phase_fuehrt_nummer: bool = True) -> ProcessDefinition:
    """Onboarding-Zuschnitt: die Firma wird in der Bearbeitungsphase endgültig
    gewählt, dort taucht auch die (readonly) Personalnummer auf."""
    spaeter = ([{"ref": "personal.number", "mode": "readonly"}]
               if zweite_phase_fuehrt_nummer else [])
    return ProcessDefinition.model_validate({
        "schemaVersion": 1, "key": "onboarding", "name": "Einstellung",
        "fields": [
            {"key": "base.name", "widget": "text"},
            {"key": "base.company", "widget": "company"},
            {"key": "personal.number", "widget": "server_generated",
             "assign": {"action": "assign_sequence", "counter": counter,
                        "companyRef": company_ref}},
        ],
        "phases": [
            {"key": "start", "kind": "start", "responsibility": {"kind": "owner"},
             "fields": [{"ref": "base.name", "required": True}]},
            {"key": "backoffice", "kind": "task",
             "responsibility": {"kind": "group", "group": "g_hr"},
             "fields": [{"ref": "base.company", "mode": "editable"}] + spaeter},
            {"key": "fertig", "kind": "end", "responsibility": {"kind": "owner"},
             "fields": [{"ref": "personal.number", "mode": "readonly"}]},
        ],
    })


def phase(defn: ProcessDefinition, key: str):
    return next(p for p in defn.phases if p.key == key)


def company(name="Alpha GmbH", *, pnr_from="00001", pnr_to="09999", current=895,
            warned=False, mandant="42", shared=None) -> dict:
    return {"name": name, "pnr_from": pnr_from, "pnr_to": pnr_to, "pnr_current": current,
            "pnr_warned": warned, "mandant": mandant, "pnr_shared_with": shared}


# ── 1. Fälligkeit ─────────────────────────────────────────────────────────────

def test_faellig_beim_abschluss_der_ersten_phase_die_das_feld_fuehrt():
    defn = make_defn()
    assert svc.assigning_phase_key(defn, "personal.number") == "backoffice"
    faellig = svc.due_assignments(defn, phase(defn, "backoffice"), {})
    assert [f.key for f in faellig] == ["personal.number"]
    # Spätere Phasen zeigen die Nummer nur noch an – sie vergeben nichts mehr.
    assert svc.due_assignments(defn, phase(defn, "fertig"), {}) == []
    assert svc.due_assignments(defn, phase(defn, "start"), {}) == []


def test_bereits_gefuellte_nummer_ist_nicht_mehr_faellig():
    defn = make_defn()
    assert svc.due_assignments(defn, phase(defn, "backoffice"),
                               {"personal.number": "00896"}) == []
    # Leerstring zählt als „noch nicht vergeben"
    assert len(svc.due_assignments(defn, phase(defn, "backoffice"),
                                   {"personal.number": "  "})) == 1


def test_ohne_phase_die_das_feld_fuehrt_gibt_es_keinen_vergabe_zeitpunkt():
    """Ein server_generated-Feld, das keine Phase einbindet, wird NIE vergeben –
    das muss beim Veröffentlichen auffallen (siehe Bericht/Integration)."""
    defn = make_defn(zweite_phase_fuehrt_nummer=False)
    defn.phases[2].fields = []
    assert svc.assigning_phase_key(defn, "personal.number") is None
    for p in defn.phases:
        assert svc.due_assignments(defn, p, {}) == []


# ── 2. Ledger (Transaktion) ───────────────────────────────────────────────────

class FakeConn:
    def __init__(self, log):
        self.log = log

    def begin(self):
        self.log.append(("BEGIN", ()))

    def commit(self):
        self.log.append(("COMMIT", ()))

    def rollback(self):
        self.log.append(("ROLLBACK", ()))

    def close(self):
        self.log.append(("CLOSE", ()))


class MiniDb:
    """Winzige Nachbildung der beiden beteiligten Tabellen (settings + Ledger),
    inklusive der beiden UNIQUE-Schlüssel. Schneidet jede Anweisung mit."""

    def __init__(self, companies: list[dict]):
        self.settings = json.dumps(companies, ensure_ascii=False)
        self.claims: list[dict] = []
        self.log: list[tuple[str, tuple]] = []
        self.on_insert_claim = None      # Hook: parallele Schreiber simulieren

    # -- Helfer für die Tests
    @property
    def statements(self) -> list[str]:
        return [s for s, _ in self.log]

    def companies_now(self) -> list[dict]:
        return json.loads(self.settings)

    def counter_of(self, name: str):
        return next(c["pnr_current"] for c in self.companies_now() if c["name"] == name)

    def sql_like(self, needle: str) -> list[str]:
        return [s for s in self.statements if needle in s]

    # -- DB-Helfer-Ersatz
    def fetchone(self, conn, sql, params=()):
        self.log.append((sql, tuple(params)))
        if "FROM process_sequence_claims" in sql:
            for c in self.claims:
                if (c["ticket_id"], c["field_key"]) == (params[0], params[1]):
                    return dict(c)
            return None
        if "FROM settings" in sql:
            return {"value": self.settings}
        raise AssertionError(f"unerwartete Abfrage: {sql}")

    def exec(self, conn, sql, params=()):
        self.log.append((sql, tuple(params)))
        if "INSERT INTO process_sequence_claims" in sql:
            if self.on_insert_claim is not None:
                self.on_insert_claim(self, params)
            tid, fkey, counter, scope, num, val = params
            for c in self.claims:
                if (c["ticket_id"], c["field_key"]) == (tid, fkey):
                    raise pymysql.err.IntegrityError(1062, "Duplicate entry for uq_claim")
                if (c["counter"], c["scope_key"], c["numeric_value"]) == (counter, scope, num):
                    raise pymysql.err.IntegrityError(1062, "Duplicate entry for uq_number")
            self.claims.append({"id": len(self.claims) + 1, "ticket_id": tid, "field_key": fkey,
                                "counter": counter, "scope_key": scope, "numeric_value": num,
                                "value": val, "created_at": "2026-08-12T10:00:00"})
            return None
        if "INSERT INTO settings" in sql:
            self.settings = params[1]
            return None
        raise AssertionError(f"unerwartete Anweisung: {sql}")


@pytest.fixture
def db(monkeypatch):
    mini = MiniDb([company()])
    monkeypatch.setattr(ledger, "get_connection", lambda: FakeConn(mini.log))
    monkeypatch.setattr(ledger, "_fetchone", mini.fetchone)
    monkeypatch.setattr(ledger, "_exec", mini.exec)
    return mini


def pnr_allocate(company_name: str, warn_remaining: int = 10):
    """Dasselbe `allocate`, das der Dienst baut – die Alt-System-Rechnung."""
    from backend.database.personalnummer import compute_next_personalnummer

    def allocate(companies):
        companies, res = compute_next_personalnummer(companies, company_name, warn_remaining)
        return companies, {"value": str(res["number"]),
                           "numeric_value": int(str(res["number"])),
                           "scope_key": res["company_name"], "info": res}
    return allocate


def test_ledger_sperrt_anspruch_und_zaehler_mit_for_update(db):
    out = ledger.claim_company_sequence(ticket_id=7, field_key="personal.number",
                                        counter="personalnummer",
                                        allocate=pnr_allocate("Alpha GmbH"))
    assert out["value"] == "00896" and out["reused"] is False
    anspruch = db.sql_like("FROM process_sequence_claims")[0]
    zaehler = db.sql_like("FROM settings")[0]
    assert anspruch.endswith("FOR UPDATE"), anspruch
    assert "FOR UPDATE" in zaehler, zaehler
    # Reihenfolge: erst der Anspruch, dann der Zähler (überall gleich → kein Deadlock).
    assert db.statements.index(anspruch) < db.statements.index(zaehler)
    assert ("COMMIT", ()) in db.log


def test_zweiter_aufruf_gibt_dieselbe_nummer_und_ruehrt_den_zaehler_nicht_an(db):
    erst = ledger.claim_company_sequence(ticket_id=7, field_key="personal.number",
                                         counter="personalnummer",
                                         allocate=pnr_allocate("Alpha GmbH"))
    assert db.counter_of("Alpha GmbH") == 896
    db.log.clear()

    def darf_nicht_laufen(_companies):
        raise AssertionError("Zähler wurde beim Retry angefasst")

    zweit = ledger.claim_company_sequence(ticket_id=7, field_key="personal.number",
                                          counter="personalnummer",
                                          allocate=darf_nicht_laufen)
    assert zweit["value"] == erst["value"] == "00896"
    assert zweit["reused"] is True and zweit["allocation"] is None
    assert db.counter_of("Alpha GmbH") == 896            # KEINE zweite Nummer verbrannt
    assert db.sql_like("FROM settings") == []            # Zähler nicht einmal gelesen
    assert db.sql_like("INSERT INTO settings") == []
    assert ("ROLLBACK", ()) in db.log and ("COMMIT", ()) not in db.log


def test_zwei_auftraege_bekommen_aufeinanderfolgende_nummern(db):
    a = ledger.claim_company_sequence(ticket_id=1, field_key="personal.number",
                                      counter="personalnummer",
                                      allocate=pnr_allocate("Alpha GmbH"))
    b = ledger.claim_company_sequence(ticket_id=2, field_key="personal.number",
                                      counter="personalnummer",
                                      allocate=pnr_allocate("Alpha GmbH"))
    assert (a["value"], b["value"]) == ("00896", "00897")
    assert db.counter_of("Alpha GmbH") == 897


def test_paralleler_anspruch_integrityerror_liefert_den_bestehenden_anspruch(db):
    """Der andere Request war schneller und hat committet: kein Fehler nach außen,
    dieselbe Nummer – und unser Zähler-Schreibvorgang wird zurückgerollt."""
    def parallel(mini: MiniDb, _params):
        mini.claims.append({"id": 99, "ticket_id": 7, "field_key": "personal.number",
                            "counter": "personalnummer", "scope_key": "Alpha GmbH",
                            "numeric_value": 896, "value": "00896",
                            "created_at": "2026-08-12T09:59:00"})
    db.on_insert_claim = parallel

    out = ledger.claim_company_sequence(ticket_id=7, field_key="personal.number",
                                        counter="personalnummer",
                                        allocate=pnr_allocate("Alpha GmbH"))
    assert out["value"] == "00896" and out["reused"] is True
    assert db.counter_of("Alpha GmbH") == 895            # Rollback: Zähler unverändert
    assert ("ROLLBACK", ()) in db.log


def test_doppelte_nummer_ist_ein_lauter_fehler(db):
    """uq_number schlägt an, ohne dass es einen Anspruch für (Ticket, Feld) gibt:
    Zähler und Ledger laufen auseinander – das darf NICHT still durchgehen."""
    db.claims.append({"id": 1, "ticket_id": 3, "field_key": "personal.number",
                      "counter": "personalnummer", "scope_key": "Alpha GmbH",
                      "numeric_value": 896, "value": "00896",
                      "created_at": "2026-08-12T09:00:00"})
    with pytest.raises(ledger.SequenceNumberCollision):
        ledger.claim_company_sequence(ticket_id=7, field_key="personal.number",
                                      counter="personalnummer",
                                      allocate=pnr_allocate("Alpha GmbH"))
    assert db.counter_of("Alpha GmbH") == 895            # nichts fortgeschrieben


def test_erschoepfter_bereich_rollt_zurueck_und_wirft(db):
    from backend.database.personalnummer import PersonalnummerExhausted
    db.settings = json.dumps([company(pnr_to="00896", current=896)])
    with pytest.raises(PersonalnummerExhausted):
        ledger.claim_company_sequence(ticket_id=7, field_key="personal.number",
                                      counter="personalnummer",
                                      allocate=pnr_allocate("Alpha GmbH"))
    assert db.claims == []
    assert db.sql_like("INSERT INTO settings") == []
    assert ("ROLLBACK", ()) in db.log


def test_ddl_traegt_beide_unique_schluessel():
    ddl = ledger.PROCESS_SEQUENCE_CLAIMS_DDL
    assert "UNIQUE KEY uq_claim (ticket_id, field_key)" in ddl
    assert "UNIQUE KEY uq_number (`counter`, scope_key, numeric_value)" in ddl


# ── 3. Dienst ─────────────────────────────────────────────────────────────────

class FakeLedger:
    """Ledger-Attrappe mit der Zusage des echten: `allocate` läuft NUR, wenn es
    für (ticket_id, field_key) noch keinen Anspruch gibt."""

    def __init__(self, companies: list[dict]):
        self.companies = companies
        self.claims: dict[tuple, dict] = {}
        self.allocations = 0

    def claim(self, *, ticket_id, field_key, counter, allocate):
        key = (ticket_id, field_key)
        if key in self.claims:
            return {**self.claims[key], "reused": True, "allocation": None}
        self.allocations += 1
        self.companies, alloc = allocate(self.companies)
        rec = {"ticket_id": ticket_id, "field_key": field_key, "counter": counter,
               "scope_key": alloc["scope_key"], "numeric_value": alloc["numeric_value"],
               "value": alloc["value"]}
        self.claims[key] = rec
        return {**rec, "reused": False, "allocation": alloc}

    def counter_of(self, name: str):
        return next(c["pnr_current"] for c in self.companies if c["name"] == name)


class FakeStore:
    def __init__(self, row: dict):
        self.row = row
        self.writes: list[dict] = []
        self.conflicts = 0            # so viele update_values scheitern zuerst

    def get(self, tid):
        return dict(self.row)

    def update_values(self, tid, values_json, title=None, expected_rev=None):
        if self.conflicts > 0:
            self.conflicts -= 1
            self.row["rev"] += 1      # jemand anderes hat geschrieben
            raise ProcessTicketConflict(f"#{tid} geändert")
        if expected_rev is not None and expected_rev != self.row["rev"]:
            raise ProcessTicketConflict(f"#{tid} geändert")
        self.writes.append({"values_json": values_json, "expected_rev": expected_rev})
        self.row["values"] = json.loads(values_json)
        self.row["values_json"] = values_json
        self.row["rev"] += 1
        return dict(self.row)


def make_row(values: dict | None = None) -> dict:
    return {"id": 7, "rev": 3, "title": "Einstellung Meier", "status": "in_progress",
            "runtime": {"current_index": 1, "phases": [{"key": "start"}, {"key": "backoffice"}],
                        "epoch": 0},
            "values": dict(values or {"base.name": "Meier", "base.company": "Alpha GmbH"})}


@pytest.fixture
def stille_nebenwirkungen(monkeypatch):
    """Audit und Verlauf schreiben in die DB – hier abschalten und mitzählen."""
    audits: list[dict] = []
    verlauf: list[tuple] = []
    monkeypatch.setattr(svc, "record_audit", lambda **kw: audits.append(kw))
    monkeypatch.setattr(svc.events, "system",
                        lambda row, action, **kw: verlauf.append((action, kw)))
    return audits, verlauf


def run(defn, row, ph, *, ledger_fake, store, warn=None, actor=None, warn_remaining=10):
    return svc.assign_due_sequences(defn, row, ph, actor=actor, warn_remaining=warn_remaining,
                                    store=store, claim=ledger_fake.claim,
                                    warn=warn or (lambda *a: None))


def test_nummer_landet_formatiert_im_auftrag(stille_nebenwirkungen):
    defn, row = make_defn(), make_row()
    lg, st = FakeLedger([company()]), FakeStore(row)
    out = run(defn, row, phase(defn, "backoffice"), ledger_fake=lg, store=st)

    assert out == {"personal.number": "00896"}          # Breite wie im Alt-System
    assert row["values"]["personal.number"] == "00896"
    assert json.loads(st.writes[0]["values_json"])["personal.number"] == "00896"
    # Bestehende Werte bleiben erhalten (es wird der ganze Blob geschrieben).
    assert row["values"]["base.name"] == "Meier"


def test_geschrieben_wird_nur_mit_rev_guard(stille_nebenwirkungen):
    """Ohne rev-Guard könnte ein paralleler Schreibvorgang die Nummer wieder
    entfernen (er schreibt den kompletten values-Blob zurück)."""
    defn, row = make_defn(), make_row()
    st = FakeStore(row)
    run(defn, row, phase(defn, "backoffice"), ledger_fake=FakeLedger([company()]), store=st)
    assert st.writes[0]["expected_rev"] == 3


def test_schreibkonflikt_wird_einmal_neu_versucht(stille_nebenwirkungen):
    defn, row = make_defn(), make_row()
    st = FakeStore(row)
    st.conflicts = 1
    run(defn, row, phase(defn, "backoffice"), ledger_fake=FakeLedger([company()]), store=st)
    assert row["values"]["personal.number"] == "00896"
    assert st.writes[0]["expected_rev"] == 4            # frisch gelesener Stand


def test_dauerhafter_schreibkonflikt_meldet_sich_statt_die_nummer_zu_verlieren(
        stille_nebenwirkungen):
    defn, row = make_defn(), make_row()
    st = FakeStore(row)
    st.conflicts = 2
    with pytest.raises(svc.SequenceWriteConflict):
        run(defn, row, phase(defn, "backoffice"), ledger_fake=FakeLedger([company()]), store=st)


def test_zweiter_abschluss_vergibt_dieselbe_nummer_und_zaehlt_nicht_weiter(
        stille_nebenwirkungen):
    """Retry/Doppelklick: derselbe Anspruch, kein zweiter Zählerschritt."""
    defn, row = make_defn(), make_row()
    lg, st = FakeLedger([company()]), FakeStore(row)
    run(defn, row, phase(defn, "backoffice"), ledger_fake=lg, store=st)
    assert lg.allocations == 1 and lg.counter_of("Alpha GmbH") == 896

    # Der Wert steht im Auftrag → gar nicht mehr fällig.
    assert run(defn, row, phase(defn, "backoffice"), ledger_fake=lg, store=st) == {}

    # Und selbst wenn er (parallel) verloren ginge: das Ledger gibt dieselbe Nummer.
    row["values"].pop("personal.number")
    erneut = run(defn, row, phase(defn, "backoffice"), ledger_fake=lg, store=st)
    assert erneut == {"personal.number": "00896"}
    assert lg.allocations == 1 and lg.counter_of("Alpha GmbH") == 896


def test_erschoepfter_nummernkreis_blockiert_und_schreibt_nichts(stille_nebenwirkungen):
    audits, _ = stille_nebenwirkungen
    defn, row = make_defn(), make_row()
    lg = FakeLedger([company(pnr_to="00896", current=896)])
    st = FakeStore(row)
    with pytest.raises(svc.SequenceExhausted) as exc:
        run(defn, row, phase(defn, "backoffice"), ledger_fake=lg, store=st)
    assert "erschöpft" in str(exc.value)
    assert st.writes == [] and "personal.number" not in row["values"]
    assert [a["action"] for a in audits] == ["personalnummer_exhausted"]


def test_warn_schwelle_meldet_knappen_bereich(stille_nebenwirkungen):
    audits, _ = stille_nebenwirkungen
    gewarnt: list[tuple] = []
    defn, row = make_defn(), make_row()
    lg = FakeLedger([company(pnr_to="00900", current=895)])
    run(defn, row, phase(defn, "backoffice"), ledger_fake=lg, store=FakeStore(row),
        warn=lambda *a: gewarnt.append(a), warn_remaining=10)

    assert gewarnt == [("Alpha GmbH", 4, "00900")]      # 900 - 896 = 4 frei
    assert "personalnummer_range_low" in [a["action"] for a in audits]
    # Warn-Flag wurde gesetzt → beim nächsten Mal nicht erneut mailen.
    assert lg.companies[0]["pnr_warned"] is True


def test_warn_schwelle_schweigt_bei_genug_reserve(stille_nebenwirkungen):
    audits, _ = stille_nebenwirkungen
    gewarnt: list[tuple] = []
    defn, row = make_defn(), make_row()
    run(defn, row, phase(defn, "backoffice"), ledger_fake=FakeLedger([company()]),
        store=FakeStore(row), warn=lambda *a: gewarnt.append(a), warn_remaining=10)
    assert gewarnt == []
    assert [a["action"] for a in audits] == ["personalnummer_assigned"]


def test_mail_fehler_kostet_die_nummer_nicht(stille_nebenwirkungen):
    defn, row = make_defn(), make_row()
    lg = FakeLedger([company(pnr_to="00900", current=895)])

    def kaputt(*_a):
        raise RuntimeError("Graph nicht erreichbar")

    out = run(defn, row, phase(defn, "backoffice"), ledger_fake=lg,
              store=FakeStore(row), warn=kaputt)
    assert out == {"personal.number": "00896"}


def test_geteilter_zaehler_wird_wie_im_alt_system_aufgeloest(stille_nebenwirkungen):
    """Tochterfirma ohne eigenen Bereich zieht aus dem Zähler der Quell-Firma –
    und der Ledger-Scope ist die QUELLE (sonst schützt uq_number nicht)."""
    defn = make_defn()
    row = make_row({"base.name": "Meier", "base.company": "Beta GmbH"})
    lg = FakeLedger([company(), company("Beta GmbH", pnr_from=None, pnr_to=None,
                                        current=None, shared="Alpha GmbH")])
    out = run(defn, row, phase(defn, "backoffice"), ledger_fake=lg, store=FakeStore(row))
    assert out == {"personal.number": "00896"}
    assert lg.counter_of("Alpha GmbH") == 896
    assert lg.claims[(7, "personal.number")]["scope_key"] == "Alpha GmbH"


def test_unbekannter_nummernkreis_wird_schon_beim_speichern_abgelehnt():
    """Ehrlichkeits-Regel: `counter: "rechnungsnummer"` darf nicht klaglos eine
    Personalnummer liefern – und der Fehler gehört ans Veröffentlichen, nicht an
    den Phasenabschluss. Eine solche Definition ist deshalb gar nicht speicherbar."""
    with pytest.raises(ValidationError) as exc:
        make_defn(counter="rechnungsnummer")
    assert "rechnungsnummer" in str(exc.value)


def test_unbekannter_nummernkreis_blockiert_auch_zur_laufzeit(stille_nebenwirkungen):
    """Zweite Verteidigungslinie: eine GEPINNTE Definition kann aus einer Zeit
    stammen, in der dieser Nummernkreis noch erlaubt war. Dann darf die Vergabe
    nicht raten – sie muss den Phasenabschluss blockieren. Das Schema wird hier
    bewusst umgangen (model_construct), sonst käme man an diesen Pfad nicht heran."""
    defn = make_defn()
    feld = next(f for f in defn.fields if f.key == "personal.number")
    feld.assign = feld.assign.model_copy(update={"counter": "rechnungsnummer"})
    row = make_row()
    lg, st = FakeLedger([company()]), FakeStore(row)
    with pytest.raises(svc.SequenceNotConfigured) as exc:
        run(defn, row, phase(defn, "backoffice"), ledger_fake=lg, store=st)
    assert "rechnungsnummer" in str(exc.value)
    assert lg.allocations == 0 and st.writes == []


def test_fehlende_firma_blockiert_mit_klarer_ansage(stille_nebenwirkungen):
    defn = make_defn()
    row = make_row({"base.name": "Meier"})
    lg, st = FakeLedger([company()]), FakeStore(row)
    with pytest.raises(svc.SequenceNotConfigured) as exc:
        run(defn, row, phase(defn, "backoffice"), ledger_fake=lg, store=st)
    assert "base.company" in str(exc.value)
    assert lg.allocations == 0 and st.writes == []


def test_firma_ohne_hinterlegten_bereich_blockiert(stille_nebenwirkungen):
    defn = make_defn()
    row = make_row({"base.name": "Meier", "base.company": "Gamma GmbH"})
    lg = FakeLedger([company()])
    with pytest.raises(svc.SequenceNotConfigured):
        run(defn, row, phase(defn, "backoffice"), ledger_fake=lg, store=FakeStore(row))


def test_verlauf_nennt_nur_den_feldschluessel_nie_die_nummer(stille_nebenwirkungen):
    """Sichtbarkeit: die Nummer ist ein Feldwert. Im Verlauf steht nur der
    Schlüssel – nur so kann `process_events.redact` sie überhaupt verbergen."""
    audits, verlauf = stille_nebenwirkungen
    defn, row = make_defn(), make_row()
    run(defn, row, phase(defn, "backoffice"), ledger_fake=FakeLedger([company()]),
        store=FakeStore(row))
    assert len(verlauf) == 1
    action, kw = verlauf[0]
    assert action == svc.events.UPDATED
    assert kw["details"] == {"fields": ["personal.number"]}
    assert "00896" not in json.dumps(kw)
    # Im Audit-Log (nur Admin, revisionssicher) steht die Nummer weiterhin – wie bisher.
    assert audits[0]["details"]["number"] == "00896"


def test_ohne_faellige_felder_passiert_nichts(stille_nebenwirkungen):
    audits, verlauf = stille_nebenwirkungen
    defn, row = make_defn(), make_row()
    st = FakeStore(row)
    assert run(defn, row, phase(defn, "start"), ledger_fake=FakeLedger([company()]),
               store=st) == {}
    assert st.writes == [] and audits == [] and verlauf == []
