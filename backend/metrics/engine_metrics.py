"""
Ereignis-Kennzahlen des Workflow-MOTORS (Prometheus).

Die Bestands-Metriken (process_metrics.py) zeigen, WAS gerade offen ist. Diese
Datei zeigt, ob der Motor LÄUFT und WO Aufträge hängen: Phasen-Durchlaufzeiten,
gefeuerte/fehlgeschlagene Automationen, Scheduler-Gesundheit und Directus-
Schreibvorgänge. Alles Ereignis-Zähler/-Histogramme (kein Sammellauf) – sie
werden an den zentralen Choke-Points des Motors direkt hochgezählt.

Alle record_*-Funktionen sind BEST-EFFORT (try/except): eine kaputte Metrik darf
niemals einen Phasenübergang, einen Sweep oder ein Directus-Schreiben verhindern.

Datenschutz wie in process_metrics: Labels tragen ausschließlich Schlüssel aus
der Prozess-Definition (Prozess-Key, Phasen-Key), Trigger-/Action-Typen und
Ergebnis-Enums – niemals Feldwerte, Titel oder Personendaten.
"""
from typing import Optional

from prometheus_client import Counter, Histogram

# Phasen-Verweildauer: Spanne Minuten bis Monat (Freigaben/Rückläufe dauern Tage).
_PHASE_BUCKETS = (
    60, 300, 900, 3600, 4 * 3600, 12 * 3600,
    86400, 3 * 86400, 7 * 86400, 14 * 86400, 30 * 86400,
)

process_phase_duration_seconds = Histogram(
    "process_phase_duration_seconds",
    "Verweildauer je Phase bis zum Verlassen (Sekunden) – zeigt Engpass-Phasen",
    ["process", "phase"],
    buckets=_PHASE_BUCKETS,
)

process_automation_fired_total = Counter(
    "process_automation_fired_total",
    "Gefeuerte Automationen (Ereignis-Zähler) – wie viel der Motor autonom erledigt",
    ["process", "trigger", "action"],
)

process_automation_failed_total = Counter(
    "process_automation_failed_total",
    "Fehlgeschlagene Automationen (Ereignis-Zähler) – Zuverlässigkeit der Automatik",
    ["process", "action"],
)

# Scheduler-Lebenszeichen: steigt process_tickets_timers_due, aber sweeps_total
# bleibt flach → der Off-Loop-Motor steht (nicht bloß viel Last).
process_scheduler_sweeps_total = Counter(
    "process_scheduler_sweeps_total",
    "Durchläufe des Timer-Schedulers (Sweeps)",
)

process_scheduler_sweep_duration_seconds = Histogram(
    "process_scheduler_sweep_duration_seconds",
    "Dauer eines Scheduler-Sweeps (Sekunden)",
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60),
)

process_scheduler_ticket_failures_total = Counter(
    "process_scheduler_ticket_failures_total",
    "Tickets, deren Sweep fehlschlug und in den Backoff ging",
)

process_directus_write_total = Counter(
    "process_directus_write_total",
    "Directus-Schreibvorgänge aus Automationen (Integrations-Gesundheit)",
    ["operation", "outcome"],   # operation=create|update|delete, outcome=ok|error
)

process_http_request_total = Counter(
    "process_http_request_total",
    "Ausgehende API-Aufrufe aus Automationen (Integrations-Gesundheit)",
    ["method", "outcome"],   # method=GET|POST|…, outcome=ok|error
)

process_http_request_duration_seconds = Histogram(
    "process_http_request_duration_seconds",
    "Dauer eines ausgehenden API-Aufrufs aus einer Automation (Sekunden)",
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60),
)


def _s(v: Optional[str]) -> str:
    return str(v) if v else "unbekannt"


def record_phase_duration(process: Optional[str], phase: Optional[str], seconds: float) -> None:
    try:
        if seconds is not None and seconds >= 0:
            process_phase_duration_seconds.labels(process=_s(process), phase=_s(phase)).observe(seconds)
    except Exception:
        pass


def record_automation_fired(process: Optional[str], trigger: Optional[str], action: Optional[str]) -> None:
    try:
        process_automation_fired_total.labels(
            process=_s(process), trigger=_s(trigger), action=_s(action)).inc()
    except Exception:
        pass


def record_automation_failed(process: Optional[str], action: Optional[str]) -> None:
    try:
        process_automation_failed_total.labels(process=_s(process), action=_s(action)).inc()
    except Exception:
        pass


def record_scheduler_sweep(seconds: float) -> None:
    try:
        process_scheduler_sweeps_total.inc()
        if seconds is not None and seconds >= 0:
            process_scheduler_sweep_duration_seconds.observe(seconds)
    except Exception:
        pass


def record_scheduler_ticket_failure() -> None:
    try:
        process_scheduler_ticket_failures_total.inc()
    except Exception:
        pass


def record_directus_write(operation: Optional[str], outcome: str) -> None:
    try:
        process_directus_write_total.labels(operation=_s(operation), outcome=outcome).inc()
    except Exception:
        pass


def record_http_request(method: Optional[str], outcome: str,
                        seconds: Optional[float] = None) -> None:
    try:
        process_http_request_total.labels(method=_s(method), outcome=outcome).inc()
        if seconds is not None and seconds >= 0:
            process_http_request_duration_seconds.observe(seconds)
    except Exception:
        pass
