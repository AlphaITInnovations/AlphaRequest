from fastapi import APIRouter, Depends
from backend.core.dependencies import get_current_user
from backend.database import tickets as database
from backend.models.models import TicketType
from backend.services.ticket_permissions import can_user_create_ticket
from backend.services.workflow_state import get_dashboard_work
from backend.schemas.dashboard import (
    DashboardResponse, DashboardTicket, DepartmentGroup, DepartmentTicket,
)
from backend.schemas.responses import DataResponse

router = APIRouter()


def _to_dashboard_ticket(t) -> DashboardTicket:
    return DashboardTicket(
        id=t.id,
        title=t.title,
        type_key=t.ticket_type if isinstance(t.ticket_type, str) else t.ticket_type.value,
        status=t.status if isinstance(t.status, str) else t.status.value,
        priority=t.priority if isinstance(t.priority, str) else t.priority.value,
        created_at=t.created_at.strftime("%d.%m.%Y") if hasattr(t.created_at, "strftime") else str(t.created_at)[:10],
    )


def _board_item_to_dashboard_ticket(it: dict) -> DashboardTicket:
    return DashboardTicket(
        id=it["id"],
        title=it["title"],
        type_key=it["type_key"],
        status=it["status"],
        priority=it["priority"],
        created_at=(it["created_at"] or "")[:10],
    )


@router.get("/dashboard", response_model=DataResponse[DashboardResponse])
def get_dashboard(user: dict = Depends(get_current_user)):
    user_id = user["id"]

    # ── Arbeitslisten aus der aktuellen Zuständigkeit (ein Durchlauf) ──────────
    work = get_dashboard_work(user_id)

    # 1. Mir persönlich zugewiesen (aktuelle Phase: kind=user)
    my_orders = [_board_item_to_dashboard_ticket(it) for it in work["assigned"]]

    # 2. Meine Abteilung (Bearbeitung + Durchführung, jedes Ticket einmal)
    department_board = [
        DepartmentGroup(
            group_id=d["group_id"],
            group_name=d["group_name"] or d["group_id"],
            tickets=[
                DepartmentTicket(
                    id=t["id"],
                    title=t["title"],
                    type_key=t["type_key"],
                    created_at=(t["created_at"] or "")[:10],
                    status=t["status"],
                    priority=t["priority"],
                    phase_type=t["phase_type"],
                    phase_label=t["phase_label"],
                    department_id=t["department_id"],
                )
                for t in d["tickets"]
            ],
        )
        for d in work["departments"]
    ]

    # 3. Beobachtete Tickets (Ersteller ist automatisch Beobachter)
    from backend.database.ticket_watchers import list_ticket_ids_for_watcher
    watched_tickets = [database.get_ticket(tid) for tid in list_ticket_ids_for_watcher(user_id)]
    watched_orders = [_to_dashboard_ticket(t) for t in watched_tickets if t]

    # ── Erlaubte Ticket-Typen ──────────────────────────────────────────────────
    user_groups = user.get("groups", []) or []
    allowed = [
        t.value for t in TicketType
        if can_user_create_ticket(t.value, user_id, user_groups)
    ]

    return DataResponse(data=DashboardResponse(
        orders=my_orders,
        watched_orders=watched_orders,
        department_board=department_board,
        allowed_ticket_types=allowed,
    ))
