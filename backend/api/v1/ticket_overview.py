import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from backend.core.dependencies import get_current_user
from backend.database import tickets as database
from backend.schemas.responses import DataResponse, ListResponse, Meta
from backend.services.ticket_history import get_ticket_history
from backend.services.workflow_state import responsibility_label

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
    responsible: str = "—"   # aktuell zuständige Stelle (Person/Gruppe/Fachabteilung)
    phase: str = "—"         # Label der aktuellen Workflow-Phase


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


class LockInfo(BaseModel):
    locked: bool = False
    holder_id: Optional[str] = None
    holder_name: Optional[str] = None
    age_seconds: Optional[int] = None


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
    phase: str = "—"   # Label der aktuellen Workflow-Phase
    phases: list[dict] = []   # Workflow-Phasen (für die Fortschritts-Anzeige)
    lock: LockInfo = LockInfo()   # aktueller Edit-Lock (wer bearbeitet gerade)


# ── Permission helpers ─────────────────────────────────────────────────────────

def _require_view(user: dict) -> None:
    """view, manage und admin dürfen lesen."""
    if "view" not in user.get("permissions", []):
        raise HTTPException(403, "Kein Zugriff auf die Ticketübersicht")


def _assert_overview_detail_access(user: dict, ticket) -> None:
    """
    Einzelnes Ticket darf öffnen, wer es überhaupt lesen darf (view/manage/admin)
    ODER an diesem Ticket beteiligt ist/war (Ersteller, Beobachter, Zuständig,
    Bearbeiter, Mitglied einer involvierten Fachabteilung) – passend zum
    „Involviert"-Tab, der auch ohne globale view-Rolle funktionieren muss.
    """
    perms = user.get("permissions", [])
    if any(p in perms for p in ("view", "manage", "admin")):
        return
    from backend.services.workflow_state import user_involved_in_ticket
    if user_involved_in_ticket(ticket, user["id"]):
        return
    raise HTTPException(403, "Kein Zugriff auf dieses Ticket")


# ── Helpers ────────────────────────────────────────────────────────────────────

def _fmt_dt(val) -> str:
    if val is None:
        return ""
    if hasattr(val, "isoformat"):
        return val.isoformat()
    return str(val)


def _current_phase_label(workflow: dict) -> str:
    """Label der aktuell aktiven Phase, oder '—' (z.B. nach Archivierung)."""
    phases = workflow.get("phases", [])
    idx = workflow.get("current_phase_index", 0)
    if 0 <= idx < len(phases):
        return phases[idx].get("label") or "—"
    return "—"


def _dept_review_phase(workflow: dict) -> Optional[dict]:
    for p in workflow.get("phases", []):
        if p.get("type") == "department_review":
            return p
    return None


# ── Endpunkte ──────────────────────────────────────────────────────────────────

@router.get("/overview/tickets", response_model=ListResponse[TicketOverviewItem])
def list_overview_tickets(
    page:      int = Query(1,  ge=1),
    # Höheres Limit erlaubt clientseitiges Sortieren/Filtern über alle Tickets.
    page_size: int = Query(50, ge=10, le=2000),
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
            responsible=responsibility_label(t),
            phase=_current_phase_label(t.workflow_state_parsed or {}),
        )
        for t in tickets
    ]

    return ListResponse(
        data=items,
        meta=Meta(total=total, limit=page_size, offset=offset),
    )


def build_overview_detail(ticket) -> TicketOverviewDetail:
    """Baut das (read-only) Detail-Objekt eines Tickets. Wird sowohl vom normalen
    Overview-Endpunkt als auch vom Admin-Detail (tickets.py) genutzt."""
    try:
        description = json.loads(ticket.description or "{}")
    except Exception:
        description = {}

    workflow = ticket.workflow_state_parsed or {}
    # departments aus der department_review-Phase (neues Format), Fallback altes Format.
    # Erst anzeigen, wenn die Durchführungs-Phase auch erreicht ist (nicht 'pending') –
    # vorher (z.B. in Freigabe/BackOffice) sind die Fachabteilungen noch nicht „offen".
    dept_phase = _dept_review_phase(workflow)
    if dept_phase is not None:
        dept_reached = dept_phase.get("status") != "pending"
        dept_map = dept_phase.get("departments", {}) if dept_reached else {}
    else:
        # Altformat ohne Phasen: wie bisher anzeigen
        dept_map = workflow.get("departments", {})
    departments = {
        gid: DepartmentStatus(
            name=d.get("name", gid),
            status=d.get("status", "open"),
            required=d.get("required", True),
        )
        for gid, d in dept_map.items()
    }

    from backend.services.workflow_state import primary_responsibility
    resp = primary_responsibility(ticket)

    raw_history = get_ticket_history(ticket.id)
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

    from backend.database.ticket_locks import get_active_lock
    active_lock = get_active_lock(ticket.id)
    lock = LockInfo(
        locked=True,
        holder_id=active_lock["holder_id"],
        holder_name=active_lock["holder_name"],
        age_seconds=active_lock["age_seconds"],
    ) if active_lock else LockInfo()

    return TicketOverviewDetail(
        id=ticket.id,
        title=ticket.title,
        type_key=ticket.ticket_type if isinstance(ticket.ticket_type, str) else ticket.ticket_type.value,
        status=ticket.status        if isinstance(ticket.status,        str) else ticket.status.value,
        priority=ticket.priority    if isinstance(ticket.priority,      str) else ticket.priority.value,
        created_at=_fmt_dt(ticket.created_at),
        updated_at=_fmt_dt(ticket.updated_at) or None,
        owner_name=ticket.owner_name,
        accountable_name=resp.get("name") if resp else None,
        comment=ticket.comment or "",
        description=description,
        departments=departments,
        history=history,
        phase=_current_phase_label(workflow),
        phases=workflow.get("phases", []),
        lock=lock,
    )


@router.get("/overview/tickets/{ticket_id}", response_model=DataResponse[TicketOverviewDetail])
def get_overview_ticket(
    ticket_id: int,
    user: dict = Depends(get_current_user),
):
    ticket = database.get_ticket(ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket nicht gefunden")

    _assert_overview_detail_access(user, ticket)
    return DataResponse(data=build_overview_detail(ticket))