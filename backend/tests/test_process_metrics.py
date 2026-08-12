"""Ebene-1: Prometheus-Kennzahlen der Prozess-Aufträge – ohne DB.

Geprüft wird das, was beim Rückbau des Alt-Systems schiefgehen KANN:
  * Entkopplung: die neuen Reihen entstehen OHNE gesetzten TICKET_MANAGER,
  * Robustheit: ein Fehler in einer Einzelmetrik beendet den Sammellauf nicht,
  * Fachlichkeit: offene Fachabteilungen werden korrekt gezählt
    („skipped" gilt als erledigt, optionale Abteilungen bleiben unterscheidbar),
  * Datenschutz: in keinem Label steht etwas Personenbezogenes.

Der Store (`backend.database.process_tickets`) wird durch Attrappen ersetzt –
diese Test-Ebene fasst keine Datenbank an (siehe conftest).
"""
import pytest
from prometheus_client import REGISTRY, generate_latest

from backend.database import process_tickets as pstore
from backend.metrics import collect_guard as guard
from backend.metrics import metrics as met
from backend.metrics import process_metrics as pm


SNAP = {
    "total": 7, "active": 5,
    "by_status": {"in_progress": 3, "in_request": 2, "archived": 2},
    "by_priority": {"normal": 6, "high": 1},
    "by_process": {"demo": 7},
    # Weit in der Vergangenheit → Alter > 0.
    "oldest_active_created_at": {"demo": "2020-01-01T00:00:00"},
    "timers_due": 4,
}


def _dept(group: str, status: str = "open", required: bool = True, **extra) -> dict:
    """Abteilungs-Eintrag wie process_runtime ihn schreibt – inkl. Personenfeldern."""
    entry = {"group": group, "required": required, "status": status,
             "by": None, "by_name": None, "at": None, "note": None}
    entry.update(extra)
    return entry


def _rt(process: str, phase: str, departments=()) -> dict:
    """Zeile, wie `active_runtime_rows` sie liefert (Blob bereits geparst)."""
    return {"process_key": process, "phase_key": phase,
            "departments": list(departments)}


@pytest.fixture
def snapshot(monkeypatch):
    """Kopf-Kennzahlen aus einer Attrappe statt aus der DB."""
    monkeypatch.setattr(pm.process_store, "metrics_snapshot", lambda now: dict(SNAP))


@pytest.fixture
def runtime_rows(monkeypatch):
    """Setzt die Laufzeit-Zeilen; gibt einen Setter zurück."""
    box = {"rows": []}
    monkeypatch.setattr(pm.process_store, "active_runtime_rows", lambda: list(box["rows"]))

    def setzen(rows):
        box["rows"] = rows
    return setzen


# ── Kopf-Kennzahlen ──────────────────────────────────────────────────────────

def test_kopf_kennzahlen_werden_gesetzt(snapshot, runtime_rows):
    pm.collect_process_ticket_metrics()

    assert REGISTRY.get_sample_value("process_tickets_total") == 7
    assert REGISTRY.get_sample_value("process_tickets_open") == 5
    assert REGISTRY.get_sample_value("process_tickets_timers_due") == 4
    assert REGISTRY.get_sample_value(
        "process_tickets_by_status", {"status": "in_progress"}) == 3
    assert REGISTRY.get_sample_value(
        "process_tickets_by_priority", {"priority": "high"}) == 1
    age = REGISTRY.get_sample_value(
        "process_tickets_oldest_open_age_seconds", {"process": "demo"})
    assert age is not None and age > 0


def test_created_total_ist_ein_counter(snapshot, runtime_rows):
    """Gegenstück zu `tickets_created_total` – aus der DB, aber mit TYPE counter,
    damit `increase()` fachlich zulässig ist."""
    pm.collect_process_ticket_metrics()

    assert REGISTRY.get_sample_value(
        "process_tickets_created_total", {"process": "demo"}) == 7
    text = generate_latest(REGISTRY).decode()
    assert "# TYPE process_tickets_created_total counter" in text


# ── Phase und Fachabteilungen aus dem Ablaufzustand ──────────────────────────

def test_phase_wird_je_prozess_gezaehlt(snapshot, runtime_rows):
    runtime_rows([
        _rt("demo", "pruefung"),
        _rt("demo", "pruefung"),
        _rt("demo", "umsetzung"),
        _rt("andere", "pruefung"),
    ])
    pm.collect_process_ticket_metrics()

    assert REGISTRY.get_sample_value(
        "process_tickets_by_phase", {"process": "demo", "phase": "pruefung"}) == 2
    assert REGISTRY.get_sample_value(
        "process_tickets_by_phase", {"process": "demo", "phase": "umsetzung"}) == 1
    assert REGISTRY.get_sample_value(
        "process_tickets_by_phase", {"process": "andere", "phase": "pruefung"}) == 1


def test_offene_abteilungen_werden_gezaehlt(snapshot, runtime_rows):
    runtime_rows([
        _rt("demo", "fach", [_dept("g_it"), _dept("g_hr")]),
        _rt("demo", "fach", [_dept("g_it")]),
    ])
    pm.collect_process_ticket_metrics()

    assert REGISTRY.get_sample_value(
        "process_tickets_open_by_department",
        {"department": "g_it", "required": "true"}) == 2
    assert REGISTRY.get_sample_value(
        "process_tickets_open_by_department",
        {"department": "g_hr", "required": "true"}) == 1


def test_erledigt_und_uebersprungen_zaehlen_nicht(snapshot, runtime_rows):
    """„skipped" ist eine Antwort („nicht zuständig"), keine offene Aufgabe."""
    runtime_rows([
        _rt("demo", "fach", [
            _dept("g_it", status="done", by="u1", by_name="Max Muster"),
            _dept("g_hr", status="skipped", by="u2", by_name="Erika Muster"),
            _dept("g_fuhrpark", status="open"),
        ]),
    ])
    pm.collect_process_ticket_metrics()

    assert REGISTRY.get_sample_value(
        "process_tickets_open_by_department",
        {"department": "g_it", "required": "true"}) is None
    assert REGISTRY.get_sample_value(
        "process_tickets_open_by_department",
        {"department": "g_hr", "required": "true"}) is None
    assert REGISTRY.get_sample_value(
        "process_tickets_open_by_department",
        {"department": "g_fuhrpark", "required": "true"}) == 1


def test_optionale_abteilung_bleibt_unterscheidbar(snapshot, runtime_rows):
    """Optionale Abteilungen blockieren den Abschluss nicht – Arbeit liegt aber
    trotzdem bei ihnen. Deshalb gezählt, aber mit required=false."""
    runtime_rows([
        _rt("demo", "fach", [_dept("g_it", required=False), _dept("g_hr")]),
    ])
    pm.collect_process_ticket_metrics()

    assert REGISTRY.get_sample_value(
        "process_tickets_open_by_department",
        {"department": "g_it", "required": "false"}) == 1
    assert REGISTRY.get_sample_value(
        "process_tickets_open_by_department",
        {"department": "g_it", "required": "true"}) is None
    assert REGISTRY.get_sample_value(
        "process_tickets_open_by_department",
        {"department": "g_hr", "required": "true"}) == 1


def test_alte_reihen_verschwinden_beim_naechsten_lauf(snapshot, runtime_rows):
    """Sonst bliebe eine abgearbeitete Abteilung für immer als „offen" stehen."""
    runtime_rows([_rt("demo", "fach", [_dept("g_it")])])
    pm.collect_process_ticket_metrics()
    assert REGISTRY.get_sample_value(
        "process_tickets_open_by_department",
        {"department": "g_it", "required": "true"}) == 1

    runtime_rows([])
    pm.collect_process_ticket_metrics()
    assert REGISTRY.get_sample_value(
        "process_tickets_open_by_department",
        {"department": "g_it", "required": "true"}) is None
    assert REGISTRY.get_sample_value(
        "process_tickets_by_phase", {"process": "demo", "phase": "fach"}) is None


def test_aggregat_ignoriert_kaputte_eintraege():
    """Reine Funktion: Müll im Ablaufzustand darf nicht werfen."""
    by_phase, by_dept = pm.aggregate_runtime([
        {"process_key": None, "phase_key": None, "departments": ["kein dict", None]},
        {"process_key": "demo", "phase_key": "fach", "departments": [{"status": "open"}]},
    ])
    assert by_phase[("unbekannt", "unbekannt")] == 1
    assert by_dept == {("unbekannt", True): 1}


# ── Datenschutz ──────────────────────────────────────────────────────────────

def test_keine_personenbezogenen_labels(snapshot, runtime_rows):
    """/metrics kennt keinen Sichtbarkeitsfilter – es dürfen nur Schlüssel raus."""
    runtime_rows([
        _rt("demo", "fach", [
            _dept("g_it", status="open", by="u-4711", by_name="Max Muster",
                  note="Bitte Laptop XPS 15 bestellen"),
        ]),
    ])
    pm.collect_process_ticket_metrics()

    text = generate_latest(REGISTRY).decode()
    for verboten in ("Max Muster", "u-4711", "XPS 15"):
        assert verboten not in text, f"{verboten} steht in /metrics"

    erlaubt = {"process", "phase", "status", "priority", "department", "required",
               "outcome"}
    for metric in REGISTRY.collect():
        if not metric.name.startswith("process_tickets"):
            continue
        for sample in metric.samples:
            assert set(sample.labels) <= erlaubt, f"{sample.name}: {sample.labels}"


def test_abfrage_liest_keine_feldwerte_und_nur_aktive():
    """Die SQL-Seite ist der eigentliche Schutz: `values_json` wird nicht gelesen,
    und terminale Aufträge fallen schon in der DB weg (kein Full-Table-Scan)."""
    sql = pstore.ACTIVE_RUNTIME_SQL
    assert "values_json" not in sql
    assert pstore._ACTIVE_CLAUSE in sql
    assert "runtime_json" in sql and "SELECT runtime_json" not in sql


# ── Ereignis-Zähler ──────────────────────────────────────────────────────────

def test_terminal_zaehler_steigt():
    vorher = REGISTRY.get_sample_value(
        "process_tickets_terminal_total", {"outcome": "rejected"})
    pm.record_process_terminal("rejected")
    nachher = REGISTRY.get_sample_value(
        "process_tickets_terminal_total", {"outcome": "rejected"})
    assert nachher == (vorher or 0) + 1


def test_terminal_zaehler_existiert_von_anfang_an():
    """Ohne vorangelegte Reihe zeigt das Dashboard „No data" statt einer Null."""
    for outcome in ("archived", "rejected"):
        assert REGISTRY.get_sample_value(
            "process_tickets_terminal_total", {"outcome": outcome}) is not None


# ── Robustheit des Sammellaufs ───────────────────────────────────────────────

def test_fehler_in_einer_teilmetrik_killt_den_lauf_nicht(monkeypatch, runtime_rows):
    """Kippt die Kopf-Abfrage, müssen die Laufzeit-Reihen trotzdem entstehen."""
    def boom(now):
        raise RuntimeError("Tabelle fehlt")

    monkeypatch.setattr(pm.process_store, "metrics_snapshot", boom)
    runtime_rows([_rt("demo", "nachlauf", [_dept("g_it")])])

    vorher = REGISTRY.get_sample_value(
        "metrics_collect_failures_total", {"part": "process_snapshot"}) or 0
    pm.collect_process_ticket_metrics()   # darf nicht werfen

    assert REGISTRY.get_sample_value(
        "process_tickets_by_phase", {"process": "demo", "phase": "nachlauf"}) == 1
    assert REGISTRY.get_sample_value(
        "metrics_collect_failures_total", {"part": "process_snapshot"}) == vorher + 1


def test_sammellauf_setzt_prozess_metriken(monkeypatch, snapshot, runtime_rows):
    """Kern der Entkopplung: der Sammellauf kennt das Alt-System nicht mehr –
    die Prozess-Reihen entstehen trotzdem (vorher hingen sie an TICKET_MANAGER)."""
    runtime_rows([_rt("demo", "ohne_alt", [_dept("g_it")])])

    met.collect_all()   # der echte Durchlauf, inkl. Session-/System-Teil

    assert REGISTRY.get_sample_value("process_tickets_total") == 7
    assert REGISTRY.get_sample_value(
        "process_tickets_by_phase", {"process": "demo", "phase": "ohne_alt"}) == 1
    assert REGISTRY.get_sample_value(
        "process_tickets_open_by_department",
        {"department": "g_it", "required": "true"}) == 1


def test_prozess_metriken_haengen_an_keiner_alt_bedingung():
    """Der Sammellauf enthält den Prozess-Teil unbedingt und kein Alt-System mehr:
    ein Teil, der nur „manchmal" läuft, wäre ein stilles Monitoring-Loch."""
    parts = [p for p, _ in met._COLLECTORS]
    assert "process_tickets" in parts
    assert "legacy_tickets" not in parts
    assert not hasattr(met, "TICKET_MANAGER")


def test_ein_kaputter_collector_stoppt_die_uebrigen_nicht(monkeypatch):
    gelaufen = []

    def kaputt():
        raise RuntimeError("weg")

    monkeypatch.setattr(met, "_COLLECTORS", (
        ("test_kaputt", kaputt),
        ("test_danach", lambda: gelaufen.append("danach")),
    ))
    vorher = REGISTRY.get_sample_value(
        "metrics_collect_failures_total", {"part": "test_kaputt"}) or 0

    met.collect_all()   # darf nicht werfen

    assert gelaufen == ["danach"]
    assert REGISTRY.get_sample_value(
        "metrics_collect_failures_total", {"part": "test_kaputt"}) == vorher + 1


def test_run_part_meldet_erfolg_und_fehlschlag():
    assert guard.run_part("test_ok", lambda: None) is True
    assert guard.run_part("test_fehler", _raise) is False


def _raise():
    raise ValueError("kaputt")
