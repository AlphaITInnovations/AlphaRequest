from typing import Dict, Optional
from prometheus_client import Gauge, Counter
from backend.models.models import RequestStatus
from backend.services.workflow_state import current_responsibility


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


# ---------------------------------------------------------
# COLLECTOR
# ---------------------------------------------------------

def collect_ticket_metrics(ticket_manager):

    tickets = ticket_manager.list_all()

    total = len(tickets)
    open_count = 0

    status_count: Dict[str, int] = {}
    priority_count: Dict[str, int] = {}
    type_count: Dict[str, int] = {}
    phase_count: Dict[str, int] = {}
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

        is_open = t.status in (RequestStatus.in_progress, RequestStatus.in_request)
        if is_open:
            open_count += 1

            # Phase nur für aktive Tickets (terminale Tickets stehen in keiner Phase mehr)
            label = _current_phase_label(t)
            if label:
                phase_count[label] = phase_count.get(label, 0) + 1

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

    for k, v in dept_open_count.items():
        tickets_open_by_department.labels(department=k).set(v)