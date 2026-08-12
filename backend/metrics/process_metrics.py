"""
Kennzahlen der definitions-getriebenen Prozess-Aufträge (Prometheus).

Eigene Datei mit eigenem Einstiegspunkt, bewusst OHNE Bezug zum Alt-System:
vorher hing `collect_process_ticket_metrics` im Sammellauf der alten Tickets und
lief nur, wenn ein TicketManager gesetzt war. Mit dem Wegfall des Alt-Systems
hätte das die neuen Reihen STILL mit abgeschaltet – ein Monitoring, das nach
einem Umbau schweigt, sieht aus wie eine ruhige Anlage.

Sichtbarkeit: /metrics ist ein Ausgabekanal OHNE Sichtbarkeitsprüfung – wer den
Endpunkt erreicht, liest alle Reihen. Deshalb gilt hier ausnahmslos: Labels
tragen nur Schlüssel aus der Prozess-Definition (Prozess-Key, Phasen-Key),
Gruppen-IDs und Status. Niemals Feldwerte, Titel, Namen oder Kennungen von
Personen. Die Abfrage in `database/process_tickets.active_runtime_rows` liest
`values_json` gar nicht erst, und aus dem Abteilungs-Stand werden ausschließlich
`group`, `required` und `status` ausgewertet – nicht `by`/`by_name`/`note`.
"""
from datetime import datetime, timezone
from typing import Optional

from prometheus_client import REGISTRY, Counter, Gauge
from prometheus_client.metrics_core import CounterMetricFamily

from backend.database import process_tickets as process_store
from backend.metrics import collect_guard as guard
from backend.utils.timeutil import utcnow_iso

# Ein Abteilungs-Eintrag gilt als erledigt, wenn er quittiert ODER als „nicht
# zuständig" übersprungen wurde – „skipped" ist eine Antwort, keine offene Aufgabe.
_DEPARTMENT_DONE = ("done", "skipped")


# ---------------------------------------------------------
# METRIKEN
# ---------------------------------------------------------

process_tickets_total = Gauge(
    "process_tickets_total",
    "Prozess-Aufträge insgesamt"
)

process_tickets_open = Gauge(
    "process_tickets_open",
    "Offene (nicht-terminale) Prozess-Aufträge"
)

process_tickets_by_status = Gauge(
    "process_tickets_by_status",
    "Prozess-Aufträge nach Status",
    ["status"]
)

process_tickets_by_priority = Gauge(
    "process_tickets_by_priority",
    "Prozess-Aufträge nach Priorität",
    ["priority"]
)

# Offene Aufträge nach aktueller Phase. Der Phasen-Key allein ist mehrdeutig –
# „pruefung" gibt es in mehreren Prozessen –, deshalb immer mit Prozess-Key.
# Ersetzt `tickets_by_phase` des Alt-Systems (dort war das Label die Phasen-
# BESCHRIFTUNG; ein Key ist stabil, eine Beschriftung ändert sich mit jeder
# Textkorrektur und zerreißt die Reihe).
process_tickets_by_phase = Gauge(
    "process_tickets_by_phase",
    "Offene Prozess-Aufträge nach aktueller Phase",
    ["process", "phase"]
)

# DER Stau-Indikator des neuen Systems: eine Fachabteilungs-Phase schließt erst
# ab, wenn alle Pflicht-Abteilungen quittiert haben. Was hier steht, wartet auf
# genau diese Gruppe. `required` bleibt sichtbar, weil optionale Abteilungen den
# Auftrag nicht blockieren – Arbeit liegt aber trotzdem bei ihnen.
process_tickets_open_by_department = Gauge(
    "process_tickets_open_by_department",
    "Offene Fachabteilungs-Quittierungen je Gruppe (aktuelle Phase)",
    ["department", "required"]
)

# Ältester offener Auftrag je Prozess → macht Liegenbleiber sichtbar.
process_tickets_oldest_open_age_seconds = Gauge(
    "process_tickets_oldest_open_age_seconds",
    "Alter des ältesten offenen Prozess-Auftrags je Prozess (Sekunden)",
    ["process"],
)

# Fällige Timer (next_timer_due_at <= jetzt): steigt dauerhaft, wenn der
# Off-Loop-Scheduler nicht mehr abarbeitet.
process_tickets_timers_due = Gauge(
    "process_tickets_timers_due",
    "Aktive Prozess-Aufträge mit überfälligem Timer"
)

# Aufträge, die einen Endzustand erreicht haben (Durchsatz und Ablehnquote).
process_tickets_terminal_total = Counter(
    "process_tickets_terminal_total",
    "Prozess-Aufträge, die einen Endzustand erreicht haben (Ereignis-Zähler)",
    ["outcome"],   # archived | rejected
)
# Beide Ausprägungen vorab anlegen: ohne Reihe zeigt das Dashboard „No data"
# statt einer ehrlichen Null.
for _outcome in ("archived", "rejected"):
    process_tickets_terminal_total.labels(outcome=_outcome)


_CREATED_NAME = "process_tickets_created_total"
_CREATED_DOC = "Insgesamt angelegte Prozess-Aufträge je Prozess (kumulativ)"


class _CreatedTotalCollector:
    """`process_tickets_created_total` als echter Counter – Wert aus der DB.

    Warum nicht der übliche Weg (im Code hochzählen, wie es das Alt-System mit
    `tickets_created_total` tut)? Die Zahl steht bereits in der Datenbank
    (`COUNT(*)` je Prozess-Key) und ist dort monoton: Aufträge werden nur
    archiviert, nie gelöscht (`process_tickets` kennt kein DELETE). Der DB-Wert
    ist damit die ehrlichere Quelle – er überlebt Neustarts und stimmt auch für
    die Zeit vor dem Start, während ein Zähler im Prozessspeicher nach jedem
    Deploy bei 0 beginnt.

    prometheus_client kennt keinen setzbaren Counter (`Counter` kann nur `inc()`),
    deshalb ein eigener Collector: er liefert die Reihe mit dem korrekten TYPE
    `counter`, damit `rate()`/`increase()` fachlich zulässig sind.

    Grenze, die man kennen muss: würden Zeilen doch einmal gelöscht (Datenbank
    zurückgespielt, Aufräum-Skript), fällt der Wert – Prometheus liest das als
    Zähler-Neustart und zählt das Fenster einmalig zu hoch.
    """

    def __init__(self) -> None:
        self._values: dict[str, float] = {}

    def set_values(self, by_process: dict) -> None:
        self._values = {str(k): float(v) for k, v in (by_process or {}).items()}

    def _family(self) -> CounterMetricFamily:
        return CounterMetricFamily(_CREATED_NAME, _CREATED_DOC, labels=["process"])

    def describe(self):
        # Ohne describe() würde die Registry beim Registrieren collect() rufen –
        # das ist hier harmlos, aber describe() macht die Namen explizit.
        return [self._family()]

    def collect(self):
        fam = self._family()
        for key, value in self._values.items():
            fam.add_metric([key], value)
        yield fam


process_tickets_created = _CreatedTotalCollector()
REGISTRY.register(process_tickets_created)


# ---------------------------------------------------------
# EREIGNIS-ZÄHLER
# ---------------------------------------------------------

def record_process_terminal(outcome: str) -> None:
    """Beim Erreichen eines Endzustands aufrufen ('archived' / 'rejected').

    Bewusst ein Ereignis-Zähler und KEIN aus der DB gelesener Stand: `status`
    allein taugt dafür nicht, weil ein Reopen einen Auftrag aus dem Endzustand
    zurückholt. Die Zahl der archivierten/abgelehnten Aufträge fällt dann wieder,
    und Prometheus liest jeden Rückgang als Zähler-Neustart – der Durchsatz wäre
    systematisch zu hoch. Der Preis dieser Wahl: der Zähler beginnt nach einem
    Neustart bei 0; damit gehen `rate()`/`increase()` korrekt um.

    Best-effort: eine kaputte Metrik darf keinen Phasenübergang verhindern.
    """
    try:
        process_tickets_terminal_total.labels(outcome=outcome).inc()
    except Exception:
        pass


# ---------------------------------------------------------
# HILFEN
# ---------------------------------------------------------

def _iso_age_seconds(iso: Optional[str]) -> Optional[float]:
    """Alter eines ISO-Zeitstempels (naive UTC aus der DB) in Sekunden."""
    if not iso:
        return None
    try:
        created = datetime.fromisoformat(iso)
    except (ValueError, TypeError):
        return None
    if created.tzinfo is not None:
        created = created.astimezone(timezone.utc).replace(tzinfo=None)
    # Die DB liefert naive UTC – deshalb „jetzt" ebenfalls naiv in UTC.
    jetzt = datetime.now(timezone.utc).replace(tzinfo=None)
    return max(0.0, (jetzt - created).total_seconds())


def aggregate_runtime(rows) -> tuple[dict, dict]:
    """Phasen- und Abteilungs-Zählung aus den Laufzeit-Zeilen.

    Reine Funktion (kein DB-Zugriff, keine Metrik-Objekte) – damit ist die
    fachliche Regel testbar, ohne Prometheus anzufassen.

    Rückgabe: ({(prozess, phase): anzahl}, {(gruppe, pflicht): anzahl}).
    Gezählt werden nur Abteilungen der AKTUELLEN Phase, die weder quittiert
    ('done') noch übersprungen ('skipped') sind.
    """
    by_phase: dict[tuple[str, str], int] = {}
    by_department: dict[tuple[str, bool], int] = {}
    for row in rows or []:
        process = row.get("process_key") or "unbekannt"
        phase = row.get("phase_key") or "unbekannt"
        key = (process, phase)
        by_phase[key] = by_phase.get(key, 0) + 1
        for dept in row.get("departments") or []:
            if not isinstance(dept, dict):
                continue
            if dept.get("status") in _DEPARTMENT_DONE:
                continue
            # Nur Gruppen-ID und Pflicht-Kennzeichen – KEINE Personendaten aus
            # `by`/`by_name`/`note`.
            group = dept.get("group") or "unbekannt"
            dkey = (str(group), bool(dept.get("required", True)))
            by_department[dkey] = by_department.get(dkey, 0) + 1
    return by_phase, by_department


# ---------------------------------------------------------
# SAMMELN
# ---------------------------------------------------------

def _collect_snapshot() -> None:
    """Kopf-Kennzahlen – alle Aggregate SQL-seitig, eine Verbindung."""
    snap = process_store.metrics_snapshot(utcnow_iso())

    process_tickets_by_status.clear()
    process_tickets_by_priority.clear()
    process_tickets_oldest_open_age_seconds.clear()

    process_tickets_total.set(snap["total"])
    process_tickets_open.set(snap["active"])
    process_tickets_timers_due.set(snap["timers_due"])

    for status, count in snap["by_status"].items():
        process_tickets_by_status.labels(status=status).set(count)

    for priority, count in snap["by_priority"].items():
        process_tickets_by_priority.labels(priority=priority).set(count)

    # `by_process` zählt ALLE Zeilen je Prozess – das ist exakt „insgesamt
    # angelegt". Deshalb keine zweite Abfrage und keine doppelte Reihe.
    process_tickets_created.set_values(snap["by_process"])

    for process, iso in snap["oldest_active_created_at"].items():
        age = _iso_age_seconds(iso)
        if age is not None:
            process_tickets_oldest_open_age_seconds.labels(process=process).set(age)


def _collect_runtime() -> None:
    """Phase und offene Fachabteilungen – aus dem Ablaufzustand aktiver Aufträge."""
    by_phase, by_department = aggregate_runtime(process_store.active_runtime_rows())

    process_tickets_by_phase.clear()
    process_tickets_open_by_department.clear()

    for (process, phase), count in by_phase.items():
        process_tickets_by_phase.labels(process=process, phase=phase).set(count)

    for (group, required), count in by_department.items():
        process_tickets_open_by_department.labels(
            department=group, required="true" if required else "false").set(count)


def collect_process_ticket_metrics() -> None:
    """Alle Prozess-Kennzahlen einsammeln.

    Die beiden Teile sind einzeln abgesichert: sie hängen an verschiedenen
    Abfragen, und ein Ausfall der einen (z. B. fehlende JSON-Funktionen) darf die
    andere nicht mitnehmen. Wirft nicht.
    """
    guard.run_part("process_snapshot", _collect_snapshot)
    guard.run_part("process_runtime", _collect_runtime)
