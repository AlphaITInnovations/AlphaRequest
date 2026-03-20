import json
from fastapi import APIRouter, Request, Depends, Query
from alpharequestmanager.core.dependencies import get_current_user
from alpharequestmanager.database import tickets as database
from alpharequestmanager.models.models import RequestStatus
from alpharequestmanager.services.ticket_history import add_history_event
from alpharequestmanager.services.microsoft_graph import get_cached_user_mail
from alpharequestmanager.services.microsoft_mail import send_newrequest_mail
from alpharequestmanager.services.ticket_permissions import can_user_create_ticket
from alpharequestmanager.api.tickets import (
    generate_title, validate_assignee,
    complete_ticket_internal, _user_can_delete_ticket,
)
from alpharequestmanager.schemas.ticket import (
    TicketOut, TicketCreateRequest, TicketUpdateRequest, UserOut,
)
from alpharequestmanager.schemas.responses import (
    DataResponse, ListResponse, Meta, ErrorCode, api_error,
)
from alpharequestmanager.database.users import PERM_MANAGE, PERM_ADMIN

router = APIRouter()


# ── Permission helpers ─────────────────────────────────────────────────────────

def _require_admin(user: dict) -> dict:
    if PERM_ADMIN not in user.get("permissions", []):
        raise api_error(403, ErrorCode.ADMIN_REQUIRED, "Admin-Rechte erforderlich")
    return user


def _require_manage(user: dict) -> dict:
    if PERM_MANAGE not in user.get("permissions", []):
        raise api_error(403, ErrorCode.TICKET_FORBIDDEN, "Keine Berechtigung")
    return user


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    return _require_admin(user)


# ── Ticket helpers ─────────────────────────────────────────────────────────────

def _get_ticket_or_404(ticket_id: int):
    ticket = database.get_ticket(ticket_id)
    if not ticket:
        raise api_error(404, ErrorCode.TICKET_NOT_FOUND, "Ticket nicht gefunden")
    return ticket


def _assert_ticket_access(ticket, user: dict):
    """Owner darf immer, Manager/Admin ebenfalls."""
    if ticket.owner_id == user["id"]:
        return
    if PERM_MANAGE in user.get("permissions", []):
        return
    raise api_error(403, ErrorCode.TICKET_FORBIDDEN, "Kein Zugriff auf dieses Ticket")


# ══════════════════════════════════════════════════════════════════════════════
# AUTH
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/auth/me", response_model=DataResponse[UserOut])
def get_me(user: dict = Depends(get_current_user)):
    return DataResponse(data=UserOut(
        id=user["id"],
        displayName=user["displayName"],
        mail=user.get("mail") or user.get("email"),
        permissions=user.get("permissions", []),
    ))


# ══════════════════════════════════════════════════════════════════════════════
# TICKETS – User
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/tickets", response_model=ListResponse[TicketOut])
def list_my_tickets(user: dict = Depends(get_current_user)):
    items = database.list_tickets_by_owner(user["id"])
    return ListResponse(
        data=[TicketOut.from_ticket(t) for t in items],
        meta=Meta(total=len(items), limit=len(items), offset=0),
    )


@router.get("/tickets/{ticket_id}", response_model=DataResponse[TicketOut])
def get_ticket(ticket_id: int, user: dict = Depends(get_current_user)):
    ticket = _get_ticket_or_404(ticket_id)
    _assert_ticket_access(ticket, user)
    return DataResponse(data=TicketOut.from_ticket(ticket))


@router.post("/tickets", response_model=DataResponse[TicketOut], status_code=201)
async def create_ticket(
    data: TicketCreateRequest,
    request: Request,
    user: dict = Depends(get_current_user),
):
    if not can_user_create_ticket(data.ticket_type.value, user["id"]):
        raise api_error(403, ErrorCode.TICKET_FORBIDDEN,
                        f"Kein Recht zum Erstellen von '{data.ticket_type.value}'-Tickets")

    if not validate_assignee(request.app.state.user_cache, data.assignee_id):
        raise api_error(400, ErrorCode.INVALID_ASSIGNEE,
                        f"Unbekannter Assignee '{data.assignee_id}'")
    try:
        json.loads(data.description)
    except Exception:
        raise api_error(400, ErrorCode.INVALID_DESCRIPTION,
                        "description muss gültiges JSON sein")

    title = generate_title(data.ticket_type, user)
    ticket_id = request.app.state.manager.create_ticket(
        title=title,
        ticket_type=data.ticket_type,
        description=data.description,
        owner_id=user["id"],
        owner_name=user["displayName"],
        owner_info=json.dumps(user, ensure_ascii=False),
        comment=data.comment,
        assignee_id=data.assignee_id,
        assignee_name=data.assignee_name,
        accountable_id=data.accountable_id,
        accountable_name=data.accountable_name,
        priority=data.priority,
    )
    add_history_event(ticket_id, actor_id=user["id"],
                      actor_name=user["displayName"], action="ticket_created")

    mail_to = get_cached_user_mail(request.app, data.assignee_id)
    send_newrequest_mail(mail_to, data.priority, title, data.ticket_type, ticket_id)

    return DataResponse(data=TicketOut.from_ticket(database.get_ticket(ticket_id)))


@router.patch("/tickets/{ticket_id}", response_model=DataResponse[TicketOut])
async def update_ticket(
    ticket_id: int,
    data: TicketUpdateRequest,
    request: Request,
    user: dict = Depends(get_current_user),
):
    ticket = _get_ticket_or_404(ticket_id)
    _assert_ticket_access(ticket, user)

    if data.assignee_id and not validate_assignee(
        request.app.state.user_cache, data.assignee_id
    ):
        raise api_error(400, ErrorCode.INVALID_ASSIGNEE, "Unbekannter Assignee")

    updates = {k: v for k, v in {
        "description": data.description,
        "comment":     data.comment.strip() if data.comment else None,
        "priority":    data.priority,
    }.items() if v is not None}

    if updates:
        database.update_ticket(ticket_id=ticket_id, **updates)

    if ticket.status == RequestStatus.in_progress:
        if data.assignee_id and ticket.assignee_id != data.assignee_id:
            database.set_assignee(ticket_id, data.assignee_id, data.assignee_name or "")
        if data.accountable_id and ticket.accountable_id != data.accountable_id:
            database.set_accountable(ticket_id, data.accountable_id, data.accountable_name or "")

    add_history_event(ticket_id, actor_id=user["id"],
                      actor_name=user["displayName"], action="ticket_updated")

    return DataResponse(data=TicketOut.from_ticket(database.get_ticket(ticket_id)))


@router.post("/tickets/{ticket_id}/submit", response_model=DataResponse[TicketOut])
async def submit_ticket(
    ticket_id: int,
    request: Request,
    user: dict = Depends(get_current_user),
):
    ticket = _get_ticket_or_404(ticket_id)
    _assert_ticket_access(ticket, user)

    complete_ticket_internal(ticket, request, user)
    add_history_event(ticket_id, actor_id=user["id"],
                      actor_name=user["displayName"], action="ticket_submitted")

    return DataResponse(data=TicketOut.from_ticket(database.get_ticket(ticket_id)))


@router.delete("/tickets/{ticket_id}", status_code=204)
def delete_ticket(ticket_id: int, user: dict = Depends(get_current_user)):
    ticket = _get_ticket_or_404(ticket_id)
    ticket_id_val = ticket["id"] if isinstance(ticket, dict) else ticket.id
    if not _user_can_delete_ticket(user, ticket_id_val):
        raise api_error(403, ErrorCode.TICKET_FORBIDDEN, "Kein Zugriff")
    database.delete_ticket(ticket_id)


# ══════════════════════════════════════════════════════════════════════════════
# TICKETS – Admin / Manager
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/admin/tickets", response_model=ListResponse[TicketOut])
def list_all_tickets(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: dict = Depends(get_current_user),
):
    _require_manage(user)
    items = database.list_all_tickets(limit=limit, offset=offset)
    total = database.count_all_tickets()
    return ListResponse(
        data=[TicketOut.from_ticket(t) for t in items],
        meta=Meta(total=total, limit=limit, offset=offset),
    )


@router.post("/admin/tickets/{ticket_id}/archive", response_model=DataResponse[TicketOut])
def archive_ticket(
    ticket_id: int,
    request: Request,
    user: dict = Depends(get_current_user),
):
    _require_manage(user)
    ticket = _get_ticket_or_404(ticket_id)
    request.app.state.manager.update_ticket(ticket_id=ticket.id,
                                             status=RequestStatus.archived)
    add_history_event(ticket.id, actor_id=user["id"],
                      actor_name=user["displayName"], action="ticket_archived_manual")

    return DataResponse(data=TicketOut.from_ticket(database.get_ticket(ticket_id)))


# ══════════════════════════════════════════════════════════════════════════════
# DEPARTMENTS
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/tickets/{ticket_id}/departments")
def get_my_departments(ticket_id: int, user: dict = Depends(get_current_user)):
    from alpharequestmanager.services.workflow_state import get_departments_for_user
    return DataResponse(data=get_departments_for_user(ticket_id, user["id"]))


@router.get("/tickets/{ticket_id}/departments/all")
def get_all_departments(ticket_id: int, user: dict = Depends(get_current_user)):
    _require_manage(user)
    from alpharequestmanager.services.workflow_state import get_all_department_statuses
    return DataResponse(data=get_all_department_statuses(ticket_id))


@router.patch("/tickets/{ticket_id}/departments/{group_id}")
async def set_department_status(
    ticket_id: int,
    group_id: str,
    request: Request,
    user: dict = Depends(get_current_user),
):
    from alpharequestmanager.services.workflow_state import (
        user_can_complete_department, set_department_status, can_archive_ticket,
    )
    from alpharequestmanager.database.groups import get_group_name_from_id

    body = await request.json()
    status = body.get("status")

    if not user_can_complete_department(ticket_id, user["id"], group_id):
        raise api_error(403, ErrorCode.DEPARTMENT_FORBIDDEN,
                        "Keine Berechtigung für diese Fachabteilung")
    if status not in {"done", "rejected", "skipped"}:
        raise api_error(400, ErrorCode.INVALID_STATUS,
                        "Erlaubte Werte: done, rejected, skipped")

    set_department_status(ticket_id, group_id, status)
    add_history_event(ticket_id, actor_id=user["id"],
                      actor_name=user["displayName"], action="department_done",
                      details={"department_id": group_id,
                               "department_name": get_group_name_from_id(group_id)})

    if can_archive_ticket(ticket_id):
        database.update_ticket(ticket_id=ticket_id, status=RequestStatus.archived)
        add_history_event(ticket_id, actor_id=None, actor_name="System",
                          actor_type="system", action="ticket_archived")

    return {"ok": True}