from datetime import datetime, timezone
from typing import Dict, Optional
from prometheus_client import Gauge, Counter
from backend.database import process_tickets as process_store
from backend.models.models import RequestStatus
from backend.services.workflow_state import current_responsibility
from backend.utils.timeutil import utcnow_iso


# ---------------------------------------------------------
# METRICS
# ---------------------------------------------------------

tickets_total = Gauge(
    "tickets_total",
    "Total tickets in system"
)

tickets_open = Gauge(
    "tickets_open",
    "Open tickets"
)

tickets_by_status = Gauge(
    "tickets_by_status",
    "Tickets grouped by status",
    ["status"]
)

tickets_by_priority = Gauge(
    "tickets_by_priority",
    "Tickets grouped by priority",
    ["priority"]
)

tickets_by_type = Gauge(
    "tickets_by_type",
    "Tickets grouped by type",
    ["type"]
)

# Aktive Tickets je aktueller Workflow-Phase (zeigt Staus, z.B. in „Freigabe Herr Lutz").
tickets_by_phase = Gauge(
    "tickets_by_phase",
    "Active tickets grouped by current workflow phase",
    ["phase"]
)

# Offene Tickets, die gerade auf eine Fachabteilung warten (aktive Durchführungs-Phase).
tickets_open_by_department = Gauge(
    "tickets_open_by_department",
    "Open tickets currently awaiting each department",
    ["department"]
)

# Erstellte Tickets je Typ (Rate über die Zeit).
tickets_created_total = Counter(
    "tickets_created_total",
    "Total tickets created",
    ["type"]
)

# Tickets, die einen Endzustand erreicht haben (Workflow-Ergebnis: archiviert/abgelehnt).
# Ereignis-Zähler → ergibt Durchsatz und Ablehnquote über die Zeit.
tickets_terminal_total = Counter(
    "tickets_terminal_total",
    "Tickets reaching a terminal state (workflow outcome)",
    ["outcome"],  # archived | rejected
)

# Alter des ältesten offenen Tickets je aktueller Phase → macht Staus/Liegenbleiber sichtbar.
tickets_oldest_open_age_seconds = Gauge(
    "tickets_oldest_open_age_seconds",
    "Age of the oldest open ticket per current workflow phase (seconds)",
    ["phase"],
)


# ── Prozess-Aufträge (neues, definitions-getriebenes System) ──────────────────
# Eigene Metrik-Familie (`process_tickets_*`) statt derselben Gauges: die alten
# Reihen zählen die Tabelle `tickets`, hier wird `process_tickets` gezählt. Beides
# in eine Reihe zu mischen würde die Historie während des Parallelbetriebs
# unbrauchbar machen.

process_tickets_total = Gauge(
    "process_tickets_total",
    "Total definition-driven process tickets in system"
)

process_tickets_open = Gauge(
    "process_tickets_open",
    "Open (non-terminal) process tickets"
)

process_tickets_by_status = Gauge(
    "process_tickets_by_status",
    "Process tickets grouped by status",
    ["status"]
)

process_tickets_by_priority = Gauge(
    "process_tickets_by_priority",
    "Process tickets grouped by priority",
    ["priority"]
)

# Nach Prozess-Schlüssel (statt Ticket-Typ – der Typ IST der Prozess).
process_tickets_by_process = Gauge(
    "process_tickets_by_process",
    "Process tickets grouped by process key",
    ["process"]
)

# Ältester offener Auftrag je Prozess → macht Staus/Liegenbleiber sichtbar.
process_tickets_oldest_open_age_seconds = Gauge(
    "process_tickets_oldest_open_age_seconds",
    "Age of the oldest open process ticket per process key (seconds)",
    ["process"],
)

# Fällige Timer (next_timer_due_at <= jetzt): steigt dauerhaft, wenn der
# Off-Loop-Scheduler nicht mehr abarbeitet.
process_tickets_timers_due = Gauge(
    "process_tickets_timers_due",
    "Active process tickets with an overdue timer"
)


# ---------------------------------------------------------
# EVENT RECORDER
# ---------------------------------------------------------

def record_ticket_terminal(outcome: str) -> None:
    """Beim Erreichen eines Endzustands aufrufen (archived/rejected). Best-effort."""
    try:
        tickets_terminal_total.labels(outcome=outcome).inc()
    except Exception:
        pass


# ---------------------------------------------------------
# HELPERS
# ---------------------------------------------------------

def _current_phase_label(t) -> Optional[str]:
    """Label der aktuell aktiven Phase, oder None (kein Workflow / abgeschlossen)."""
    wf = t.workflow_state_parsed or {}
    phases = wf.get("phases", [])
    idx = wf.get("current_phase_index", 0)
    if 0 <= idx < len(phases):
        return phases[idx].get("label") or "unbekannt"
    return None


def _iso_age_seconds(iso: Optional[str]) -> Optional[float]:
    """Alter eines ISO-Zeitstempels (naive UTC aus der DB) in Sekunden."""
    if not iso:
        return None
    try:
        return _age_seconds(datetime.fromisoformat(iso))
    except Exception:
        return None


def _age_seconds(created_at) -> Optional[float]:
    """Alter eines (evtl. tz-aware) created_at in Sekunden, sonst None."""
    if created_at is None:
        return None
    try:
        ca = created_at
        if getattr(ca, "tzinfo", None) is not None:
            ca = ca.astimezone(timezone.utc).replace(tzinfo=None)
        return max(0.0, (datetime.utcnow() - ca).total_seconds())
    except Exception:
        return None


# ---------------------------------------------------------
# COLLECTOR
# ---------------------------------------------------------

def collect_process_ticket_metrics() -> None:
    """Kennzahlen der Prozess-Aufträge einsammeln (alle Aggregate SQL-seitig).

    Best-effort: schlägt es fehl (z. B. Tabelle vor der ersten Migration noch
    nicht da), bleiben die alten Ticket-Metriken unberührt.
    """
    snap = process_store.metrics_snapshot(utcnow_iso())

    process_tickets_by_status.clear()
    process_tickets_by_priority.clear()
    process_tickets_by_process.clear()
    process_tickets_oldest_open_age_seconds.clear()

    process_tickets_total.set(snap["total"])
    process_tickets_open.set(snap["active"])
    process_tickets_timers_due.set(snap["timers_due"])

    for k, v in snap["by_status"].items():
        process_tickets_by_status.labels(status=k).set(v)

    for k, v in snap["by_priority"].items():
        process_tickets_by_priority.labels(priority=k).set(v)

    for k, v in snap["by_process"].items():
        process_tickets_by_process.labels(process=k).set(v)

    for k, iso in snap["oldest_active_created_at"].items():
        age = _iso_age_seconds(iso)
        if age is not None:
            process_tickets_oldest_open_age_seconds.labels(process=k).set(age)


def collect_ticket_metrics(ticket_manager):

    # Der Sammel-Thread (backend/metrics/metrics.py) ruft nur diese Funktion auf –
    # die Prozess-Aufträge hängen sich hier ein, damit sie im selben Takt (10 s)
    # aktualisiert werden. Isoliert im try, damit ein DB-Fehler im neuen System die
    # Metriken des Alt-Systems nicht mitnimmt.
    try:
        collect_process_ticket_metrics()
    except Exception as exc:
        print("Process ticket metrics error:", exc)

    tickets = ticket_manager.list_all()

    total = len(tickets)
    open_count = 0

    status_count: Dict[str, int] = {}
    priority_count: Dict[str, int] = {}
    type_count: Dict[str, int] = {}
    phase_count: Dict[str, int] = {}
    phase_oldest_age: Dict[str, float] = {}
    dept_open_count: Dict[str, int] = {}

    for t in tickets:

        # status
        s = t.status.value
        status_count[s] = status_count.get(s, 0) + 1

        # priority
        p = t.priority.value
        priority_count[p] = priority_count.get(p, 0) + 1

        # type
        tt = t.ticket_type.value
        type_count[tt] = type_count.get(tt, 0) + 1

        is_open = t.status in (
            RequestStatus.in_progress, RequestStatus.in_request, RequestStatus.waiting_contract,
        )
        if is_open:
            open_count += 1

            # Phase nur für aktive Tickets (terminale Tickets stehen in keiner Phase mehr)
            label = _current_phase_label(t)
            if label:
                phase_count[label] = phase_count.get(label, 0) + 1
                age = _age_seconds(getattr(t, "created_at", None))
                if age is not None and age > phase_oldest_age.get(label, -1.0):
                    phase_oldest_age[label] = age

        # Offene Fachabteilungen der AKTUELLEN Phase (nur department_review liefert kind=departments)
        try:
            resp = current_responsibility(t)
        except Exception:
            resp = {}
        if resp.get("kind") == "departments":
            for d in resp.get("departments", {}).values():
                if d.get("required") and d.get("status") != "done":
                    name = d.get("name") or "unbekannt"
                    dept_open_count[name] = dept_open_count.get(name, 0) + 1


    # reset gauges
    tickets_by_status.clear()
    tickets_by_priority.clear()
    tickets_by_type.clear()
    tickets_by_phase.clear()
    tickets_oldest_open_age_seconds.clear()
    tickets_open_by_department.clear()

    # set metrics
    tickets_total.set(total)
    tickets_open.set(open_count)

    for k, v in status_count.items():
        tickets_by_status.labels(status=k).set(v)

    for k, v in priority_count.items():
        tickets_by_priority.labels(priority=k).set(v)

    for k, v in type_count.items():
        tickets_by_type.labels(type=k).set(v)

    for k, v in phase_count.items():
        tickets_by_phase.labels(phase=k).set(v)

    for k, v in phase_oldest_age.items():
        tickets_oldest_open_age_seconds.labels(phase=k).set(v)

    for k, v in dept_open_count.items():
        tickets_open_by_department.labels(department=k).set(v)