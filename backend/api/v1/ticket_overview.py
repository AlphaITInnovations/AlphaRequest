import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from backend.core.dependencies import get_current_user
from backend.database import tickets as database
from backend.schemas.responses import DataResponse, ListResponse, Meta
from backend.services.ticket_history import get_ticket_history

router = APIRouter()


# ── Schemas ────────────────────────────────────────────────────────────────────

class TicketOverviewItem(BaseModel):
    id: int
    title: str
    type_key: str
    status: str
    priority: str
    created_at: str
    creator: str


class DepartmentStatus(BaseModel):
    name: str
    status: str
    required: bool


class HistoryActor(BaseModel):
    id: Optional[str] = None
    name: str
    type: str = "user"


class HistoryEvent(BaseModel):
    timestamp: str
    actor: HistoryActor
    action: str
    details: dict = {}


class TicketOverviewDetail(BaseModel):
    id: int
    title: str
    type_key: str
    status: str
    priority: str
    created_at: str
    updated_at: Optional[str] = None
    owner_name: str
    accountable_name: Optional[str] = None
    comment: Optional[str] = None
    description: dict
    departments: dict[str, DepartmentStatus]
    history: list[HistoryEvent]


# ── Permission helpers ─────────────────────────────────────────────────────────

def _require_view(user: dict) -> None:
    """view, manage und admin dürfen lesen."""
    if "view" not in user.get("permissions", []):
        raise HTTPException(403, "Kein Zugriff auf die Ticketübersicht")


def _require_manage(user: dict) -> None:
    """Nur manage (und admin, da admin ⊇ manage) darf schreiben."""
    if "manage" not in user.get("permissions", []):
        raise HTTPException(403, "Keine Berechtigung zum Bearbeiten")


# ── Helpers ────────────────────────────────────────────────────────────────────

def _fmt_dt(val) -> str:
    if val is None:
        return ""
    if hasattr(val, "isoformat"):
        return val.isoformat()
    return str(val)


# ── Endpunkte ──────────────────────────────────────────────────────────────────

@router.get("/overview/tickets", response_model=ListResponse[TicketOverviewItem])
def list_overview_tickets(
    page:      int = Query(1,  ge=1),
    page_size: int = Query(50, ge=10, le=100),
    user: dict = Depends(get_current_user),
):
    _require_view(user)

    offset  = (page - 1) * page_size
    tickets = database.list_all_tickets(limit=page_size, offset=offset)
    total   = database.count_all_tickets()

    items = [
        TicketOverviewItem(
            id=t.id,
            title=t.title,
            type_key=t.ticket_type if isinstance(t.ticket_type, str) else t.ticket_type.value,
            status=t.status        if isinstance(t.status,        str) else t.status.value,
            priority=t.priority    if isinstance(t.priority,      str) else t.priority.value,
            created_at=_fmt_dt(t.created_at),
            creator=t.owner_name,
        )
        for t in tickets
    ]

    return ListResponse(
        data=items,
        meta=Meta(total=total, limit=page_size, offset=offset),
    )


@router.delete("/overview/tickets/{ticket_id}", status_code=204)
def delete_overview_ticket(
    ticket_id: int,
    user: dict = Depends(get_current_user),
):
    _require_view(user)
    _require_manage(user)
    if not database.delete_ticket(ticket_id):
        raise HTTPException(404, "Ticket nicht gefunden")


@router.get("/overview/tickets/{ticket_id}", response_model=DataResponse[TicketOverviewDetail])
def get_overview_ticket(
    ticket_id: int,
    user: dict = Depends(get_current_user),
):
    _require_view(user)

    ticket = database.get_ticket(ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket nicht gefunden")

    try:
        description = json.loads(ticket.description or "{}")
    except Exception:
        description = {}

    workflow    = ticket.workflow_state_parsed or {}
    departments = {
        gid: DepartmentStatus(
            name=d.get("name", gid),
            status=d.get("status", "open"),
            required=d.get("required", True),
        )
        for gid, d in workflow.get("departments", {}).items()
    }

    raw_history = get_ticket_history(ticket_id)
    history = []
    for e in raw_history:
        actor_raw = e.get("actor", {})
        if isinstance(actor_raw, dict):
            actor = HistoryActor(
                id=actor_raw.get("id"),
                name=actor_raw.get("name") or "System",
                type=actor_raw.get("type", "user"),
            )
        else:
            actor = HistoryActor(name=str(actor_raw) or "System")
        history.append(HistoryEvent(
            timestamp=e.get("timestamp", ""),
            actor=actor,
            action=e.get("action", ""),
            details=e.get("details") or {},
        ))

    return DataResponse(data=TicketOverviewDetail(
        id=ticket.id,
        title=ticket.title,
        type_key=ticket.ticket_type if isinstance(ticket.ticket_type, str) else ticket.ticket_type.value,
        status=ticket.status        if isinstance(ticket.status,        str) else ticket.status.value,
        priority=ticket.priority    if isinstance(ticket.priority,      str) else ticket.priority.value,
        created_at=_fmt_dt(ticket.created_at),
        updated_at=_fmt_dt(ticket.updated_at) or None,
        owner_name=ticket.owner_name,
        accountable_name=ticket.accountable_name,
        comment=ticket.comment or "",
        description=description,
        departments=departments,
        history=history,
    ))