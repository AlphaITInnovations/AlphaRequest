from fastapi import APIRouter, Depends
from backend.core.dependencies import get_current_user
from backend.database import tickets as database
from backend.database.groups import get_group_ids_for_user, get_group_name_from_id
from backend.models.models import RequestStatus, TicketType
from backend.services.ticket_permissions import can_user_create_ticket
from backend.services.workflow_state import get_department_requests_for_user
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
        assignee_group_id=t.assignee_group_id or None,
        assignee_group_name=t.assignee_group_name or None,
    )


@router.get("/dashboard", response_model=DataResponse[DashboardResponse])
def get_dashboard(user: dict = Depends(get_current_user)):
    user_id = user["id"]
    user_group_ids = get_group_ids_for_user(user_id)

    # ── 1. Mir direkt zugewiesene Tickets ──────────────────────────────────────
    my_direct = database.list_tickets_by_assignee(user_id)
    my_orders = [_to_dashboard_ticket(t) for t in my_direct]

    # ── 2. Meiner Abteilung zugewiesene Tickets ───────────────────────────────
    group_tickets = database.list_tickets_by_groups(user_group_ids)
    group_orders = [_to_dashboard_ticket(t) for t in group_tickets]

    # ── 3. Erstellte Tickets ──────────────────────────────────────────────────
    my_created = database.list_tickets_by_owner(user_id)
    created_orders = [_to_dashboard_ticket(t) for t in my_created]

    # ── 4. Fachabteilungs-Aufgaben (Phase 3 Workflow) ─────────────────────────
    raw_depts = get_department_requests_for_user(user_id)
    department_requests = [
        DepartmentGroup(
            group_id=d["group_id"],
            group_name=d["group_name"] or d["group_id"],
            tickets=[
                DepartmentTicket(
                    id=t["id"],
                    title=t["title"],
                    type_key=t["type_key"],
                    created_at=t["created_at"][:10] if t["created_at"] else "",
                )
                for t in d["tickets"]
            ],
        )
        for d in raw_depts
    ]

    # ── Erlaubte Ticket-Typen ──────────────────────────────────────────────────
    user_groups = user.get("groups", []) or []
    allowed = [
        t.value for t in TicketType
        if can_user_create_ticket(t.value, user_id, user_groups)
    ]

    return DataResponse(data=DashboardResponse(
        orders=my_orders,
        group_orders=group_orders,
        created_orders=created_orders,
        department_requests=department_requests,
        allowed_ticket_types=allowed,
    ))