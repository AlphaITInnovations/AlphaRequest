from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from alpharequestmanager.core.dependencies import get_current_user
from alpharequestmanager.database import tickets as database
from alpharequestmanager.schemas.responses import DataResponse
from alpharequestmanager.services.workflow_state import (
    get_department_info,
    user_can_complete_department,
)

router = APIRouter()


class TicketMeta(BaseModel):
    id: int
    title: str
    ticket_type: str
    status: str
    priority: str
    owner_name: str
    accountable_name: Optional[str]
    comment: Optional[str]
    created_at: str


class DepartmentInfo(BaseModel):
    group_id: str
    name: str
    status: str
    required: bool
    can_complete: bool


class TicketViewResponse(BaseModel):
    ticket: TicketMeta
    description: dict
    department: DepartmentInfo


@router.get(
    "/tickets/{ticket_id}/view",
    response_model=DataResponse[TicketViewResponse],
)
def get_ticket_view(
    ticket_id: int,
    department: str,
    user: dict = Depends(get_current_user),
):
    ticket = database.get_ticket(ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket nicht gefunden")

    dept = get_department_info(ticket_id, department)
    if not dept:
        raise HTTPException(403, "Fachabteilung nicht Teil dieses Tickets")

    can_complete = user_can_complete_department(ticket_id, user["id"], department)

    import json
    try:
        desc = json.loads(ticket.description or "{}")
    except Exception:
        desc = {}

    return DataResponse(data=TicketViewResponse(
        ticket=TicketMeta(
            id=ticket.id,
            title=ticket.title,
            ticket_type=ticket.ticket_type if isinstance(ticket.ticket_type, str) else ticket.ticket_type.value,
            status=ticket.status if isinstance(ticket.status, str) else ticket.status.value,
            priority=ticket.priority if isinstance(ticket.priority, str) else ticket.priority.value,
            owner_name=ticket.owner_name,
            accountable_name=ticket.accountable_name,
            comment=ticket.comment or "",
            created_at=ticket.created_at.strftime("%d.%m.%Y %H:%M") if hasattr(ticket.created_at, "strftime") else str(ticket.created_at)[:16],
        ),
        description=desc,
        department=DepartmentInfo(
            group_id=department,
            name=dept.get("name", department),
            status=dept.get("status", "open"),
            required=dept.get("required", True),
            can_complete=can_complete,
        ),
    ))