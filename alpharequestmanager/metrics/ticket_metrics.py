from typing import Dict
from prometheus_client import Gauge
from alpharequestmanager.models.models import RequestStatus


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

        if t.status in (
            RequestStatus.in_progress,
            RequestStatus.in_request,
        ):
            open_count += 1


    # reset gauges
    tickets_by_status.clear()
    tickets_by_priority.clear()
    tickets_by_type.clear()

    # set metrics
    tickets_total.set(total)
    tickets_open.set(open_count)

    for k, v in status_count.items():
        tickets_by_status.labels(status=k).set(v)

    for k, v in priority_count.items():
        tickets_by_priority.labels(priority=k).set(v)

    for k, v in type_count.items():
        tickets_by_type.labels(type=k).set(v)