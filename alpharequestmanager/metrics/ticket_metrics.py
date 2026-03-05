
from typing import Dict
from datetime import datetime

from prometheus_client import Counter, Gauge, Histogram

from alpharequestmanager.models.models import RequestStatus


# ---------------------------------------------------------
# LIFECYCLE METRICS
# ---------------------------------------------------------

tickets_created_total = Counter(
    "tickets_created_total",
    "Total tickets created",
    ["type"],
)

tickets_closed_total = Counter(
    "tickets_closed_total",
    "Total tickets closed",
    ["type", "status"],
)

ticket_resolution_seconds = Histogram(
    "ticket_resolution_seconds",
    "Time required to resolve tickets",
    ["type"],
    buckets=(60,300,600,1800,3600,7200,14400,28800,86400),
)


# ---------------------------------------------------------
# CURRENT STATE METRICS
# ---------------------------------------------------------

tickets_status_total = Gauge(
    "tickets_status_total",
    "Current number of tickets per status",
    ["status"],
)

tickets_by_type = Gauge(
    "tickets_by_type",
    "Current number of tickets per type",
    ["type"],
)

tickets_by_group = Gauge(
    "tickets_by_group",
    "Tickets per support group",
    ["group"],
)

tickets_by_priority = Gauge(
    "tickets_by_priority",
    "Tickets per priority",
    ["priority"],
)

tickets_open = Gauge(
    "tickets_open",
    "Total open tickets",
)


# ---------------------------------------------------------
# COLLECTOR
# ---------------------------------------------------------

def collect_ticket_metrics(ticket_manager):

    tickets = ticket_manager.list_all()

    status_count: Dict[str, int] = {}
    type_count: Dict[str, int] = {}
    group_count: Dict[str, int] = {}
    priority_count: Dict[str, int] = {}

    open_count = 0

    for t in tickets:

        # ----------------------------
        # STATUS
        # ----------------------------

        status = t.status.value

        status_count[status] = status_count.get(status, 0) + 1


        # ----------------------------
        # TYPE
        # ----------------------------

        ttype = t.ticket_type.value

        type_count[ttype] = type_count.get(ttype, 0) + 1


        # ----------------------------
        # GROUP
        # ----------------------------

        group = t.assignee_group_name or "unassigned"

        group_count[group] = group_count.get(group, 0) + 1


        # ----------------------------
        # PRIORITY
        # ----------------------------

        prio = t.priority.value

        priority_count[prio] = priority_count.get(prio, 0) + 1


        # ----------------------------
        # OPEN TICKETS
        # ----------------------------

        if t.status in (
            RequestStatus.in_progress,
            RequestStatus.in_request,
        ):
            open_count += 1


        # ----------------------------
        # RESOLUTION TIME
        # ----------------------------

        if (
            t.status in (RequestStatus.archived, RequestStatus.rejected)
            and t.updated_at
        ):

            duration = (t.updated_at - t.created_at).total_seconds()

            ticket_resolution_seconds.labels(type=ttype).observe(duration)


    # -----------------------------------------------------
    # RESET GAUGES
    # -----------------------------------------------------

    tickets_status_total.clear()
    tickets_by_type.clear()
    tickets_by_group.clear()
    tickets_by_priority.clear()


    # -----------------------------------------------------
    # UPDATE METRICS
    # -----------------------------------------------------

    for status, count in status_count.items():
        tickets_status_total.labels(status=status).set(count)

    for ttype, count in type_count.items():
        tickets_by_type.labels(type=ttype).set(count)

    for group, count in group_count.items():
        tickets_by_group.labels(group=group).set(count)

    for prio, count in priority_count.items():
        tickets_by_priority.labels(priority=prio).set(count)


    tickets_open.set(open_count)