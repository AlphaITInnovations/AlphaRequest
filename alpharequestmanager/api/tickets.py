from datetime import datetime

from fastapi import (
    APIRouter,
    Request,
    Form,
    HTTPException,
    Depends,
)
from fastapi.responses import RedirectResponse
from starlette.status import HTTP_302_FOUND
from alpharequestmanager.core.dependencies import get_current_user
from alpharequestmanager.database.database import get_groupID_from_name, get_group_name_from_id
from alpharequestmanager.services.ticket_history import add_history_event
from alpharequestmanager.services.ticket_permissions import can_user_create_ticket
from alpharequestmanager.services.workflow_state import build_workflow, set_workflow_state
from alpharequestmanager.utils.logger import logger
from alpharequestmanager.database import database
import json
from alpharequestmanager.models.models import TicketType, RequestStatus, TicketPriority, Ticket
from alpharequestmanager.utils.ticket_labels import TICKET_LABELS


router = APIRouter()

def _desc_with_user_info(text: str, user: dict) -> dict:
    from alpharequestmanager.api.admin import format_user_info_plain, format_user_info_html
    html = f"<p>{text}</p>" + format_user_info_html(user)
    body = f"{text}\n\n{format_user_info_plain(user)}"
    return {"public": True, "body": body, "htmlBody": html}



def _user_can_delete_ticket(user: dict, ticket_id: int) -> bool:
    """Admins oder Besitzer dürfen löschen."""
    if user.get("is_admin", False):
        return True

    try:
        owned = database.list_tickets_by_owner(user["id"])
    except Exception:
        logger.exception("Konnte Tickets des Users nicht laden")
        return False

    return any(t.id == ticket_id for t in owned)


def generate_title(ticket_type, user):
    # Titel generieren
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    if ticket_type == TicketType.zugang_beantragen:
        label = "Onboarding Mitarbeiter:innen"
    elif ticket_type == TicketType.zugang_sperren:
        label = "Offboarding Mitarbeiter:innen"
    else:
        label = TICKET_LABELS.get(ticket_type, ticket_type.value)

    generated_title = f"{label} – {user['displayName']} – {now_str}"

    return generated_title


@router.post("/tickets")
async def create_ticket(
    request: Request,
    ticket_type: TicketType = Form(...),
    description: str = Form(...),

    assignee_id: str = Form(...),
    assignee_name: str = Form(...),

    supervisor_id: str = Form(...),
    supervisor_name: str = Form(...),

    accountable_id: str = Form(...),
    accountable_name: str = Form(...),

    comment: str = Form(""),
    priority: TicketPriority = Form(TicketPriority.medium),
    user: dict = Depends(get_current_user),
):
    require_ticket_permission(user, ticket_type)


    user_cache = request.app.state.user_cache

    # Kommentar trimmen
    comment = (comment or "").strip()

    # Assignee prüfen
    if not assignee_id:
        raise HTTPException(400, "Assignee ist ein Pflichtfeld")

    if not supervisor_id:
        raise HTTPException(400, "Assignee ist ein Pflichtfeld")

    if not validate_assignee(user_cache, assignee_id):
        raise HTTPException(
            400,
            f"Ungültiger Assignee (User-ID '{assignee_id}')"
        )

    # Beschreibung validieren
    try:
        json.loads(description)
    except Exception:
        raise HTTPException(400, "Ticketdaten sind kein gültiges JSON")



    manager = request.app.state.manager

    ticket_id = manager.create_ticket(
        title=generate_title(ticket_type, user),
        ticket_type=ticket_type,
        description=description,
        owner_id=user["id"],
        owner_name=user["displayName"],
        owner_info=json.dumps(user, ensure_ascii=False),
        comment=comment,
        assignee_id=assignee_id,
        assignee_name=assignee_name,
        supervisor_id=supervisor_id,
        supervisor_name=supervisor_name,
        accountable_id=accountable_id,
        accountable_name=accountable_name,
        priority=priority,
    )

    add_history_event(
        ticket_id,
        actor_id=user["id"],
        actor_name=user["displayName"],
        action="ticket_created",
    )

    logger.info("Ticket erstellt: %s", ticket_id)
    return RedirectResponse("/dashboard", status_code=302)






@router.post("/tickets/update/{ticket_id}")
async def update_ticket(
    request: Request,
    ticket_id: int,
    description: str = Form(...),
    comment: str = Form(""),
    assignee_id: str = Form(...),
    assignee_name: str = Form(...),
    accountable_id: str = Form(...),
    accountable_name: str = Form(...),
    supervisor_id: str = Form(...),
    supervisor_name: str = Form(...),
    priority: TicketPriority = Form(...),
    action: str = Form("save"),
    user: dict = Depends(get_current_user),
):
    comment = (comment or "").strip()

    if not validate_assignee(request.app.state.user_cache, assignee_id):
        raise HTTPException(400, "Ungültiger Assignee")

    if not validate_assignee(request.app.state.user_cache, supervisor_id):
        raise HTTPException(400, "Ungültiger Supervisor")

    database.update_ticket(
        ticket_id=ticket_id,
        description=description,
        comment=comment,
        priority=priority,
    )

    ticket = request.app.state.manager.get_ticket(ticket_id)

    if ticket.status == RequestStatus.in_progress:
        if ticket.assignee_id != assignee_id:
            database.set_assignee(ticket_id, assignee_id, assignee_name)

        if ticket.accountable_id != accountable_id:
            database.set_accountable(ticket_id, accountable_id, accountable_name)

        if ticket.supervisor_id != supervisor_id:
            database.set_supervisor(ticket_id, supervisor_id, supervisor_name)

    if action == "complete":
        complete_ticket_internal(ticket, request, user)
        add_history_event(
            ticket.id,
            actor_id=user["id"],
            actor_name=user["displayName"],
            action="ticket_submitted",
        )
    else:
        add_history_event(
            ticket_id,
            actor_id=user["id"],
            actor_name=user["displayName"],
            action="ticket_updated",
        )

    return RedirectResponse("/dashboard", status_code=303)




@router.post("/tickets/{ticket_id}/delete")
async def delete_ticket_form(ticket_id: int, user: dict = Depends(get_current_user)):
    if not _user_can_delete_ticket(user, ticket_id):
        raise HTTPException(status_code=403, detail="Kein Zugriff auf dieses Ticket")

    ok = database.delete_ticket(ticket_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Ticket nicht gefunden")

    logger.info("Ticket gelöscht: id=%s von %s", ticket_id, user.get("email"))

    target = "/pruefung" if user.get("is_admin", False) else "/dashboard"

    return RedirectResponse(target, status_code=HTTP_302_FOUND)


def validate_assignee(user_cache, assignee_id: str) -> bool:
    if not assignee_id:
        return False
    print(assignee_id)
    if assignee_id == "fachabteilung":
        return True
    return any(u.get("id") == assignee_id for u in user_cache)


def validate_group(group_cache, group_id: str) -> bool:
    if not group_id:
        return False
    return any(g.get("id") == group_id for g in group_cache)


@router.get("/tickets/new/{ticket_type}")
async def create_ticket_page(
    ticket_type: TicketType,
    request: Request,
    user: dict = Depends(get_current_user),
):
    require_ticket_permission(user, ticket_type)

    template = f"tickets/{ticket_type.value}/create.html"

    return request.app.templates.TemplateResponse(
        template,
        {
            "request": request,
            "user": user,
            "ticket_type": ticket_type,
            "is_admin": user.get("is_admin", False),
            "phase": "create",
        },
    )




@router.get("/tickets/edit/{ticket_type}/{ticket_id}")
async def edit_ticket_page(
    ticket_type: TicketType,
    ticket_id: int,
    request: Request,
    user: dict = Depends(get_current_user),
):
    ticket = request.app.state.manager.get_ticket(ticket_id)

    if not ticket:
        raise HTTPException(404, "Ticket nicht gefunden")

    if ticket.ticket_type != ticket_type.value:
        raise HTTPException(400, "Tickettyp passt nicht")

    try:
        description_parsed = json.loads(ticket.description or "{}")
    except Exception:
        description_parsed = {}
    print(description_parsed)
    return request.app.templates.TemplateResponse(
        f"tickets/{ticket_type.value}/edit.html",
        {
            "request": request,
            "ticket": ticket,
            "user": user,

            "assignee_id": ticket.assignee_id,
            "assignee_name": ticket.assignee_name,

            "supervisor_id": ticket.supervisor_id,
            "supervisor_name": ticket.supervisor_name,

            "description": description_parsed,

            "is_admin": user.get("is_admin", False),
            "priority": ticket.priority.value,
            "phase": "edit",
        },
    )


@router.get("/tickets/group/{ticket_type}/{ticket_id}")
async def group_ticket_view(
    request: Request,
    ticket_type: TicketType,
    ticket_id: int,
    user: dict = Depends(get_current_user),
):
    from alpharequestmanager.services.workflow_state import (
        get_department_info,
        user_can_complete_department,
    )

    department_id = request.query_params.get("department")
    if not department_id:
        raise HTTPException(400, "Department fehlt")

    manager = request.app.state.manager
    ticket = manager.get_ticket(ticket_id)

    if not ticket:
        raise HTTPException(404, "Ticket nicht gefunden")

    # Beschreibung
    try:
        description_parsed = json.loads(ticket.description or "{}")
    except Exception:
        description_parsed = {}

    # Department-Daten
    department = get_department_info(ticket_id, department_id)
    if not department:
        raise HTTPException(403, "Dieses Ticket gehört nicht zu deiner Fachabteilung")

    can_complete = user_can_complete_department(
        ticket_id,
        user["id"],
        department_id
    )

    return request.app.templates.TemplateResponse(
        f"tickets/{ticket_type.value}/view.html",
        {
            "request": request,
            "ticket": ticket,
            "description": description_parsed,
            "user": user,
            "priority": ticket.priority.value,

            # 🔑 WICHTIG
            "department_id": department_id,
            "department": department,
            "department_status": department.get("status"),
            "can_complete": can_complete,

            "is_admin": user.get("is_admin", False),
            "phase": "view",
        }
    )



@router.post("/tickets/archive/{ticket_id}")
async def archive_ticket(
    ticket_id: int,
    request: Request,
    user: dict = Depends(get_current_user),
):
    manager = request.app.state.manager
    ticket = manager.get_ticket(ticket_id)

    if not ticket:
        raise HTTPException(404, "Ticket nicht gefunden")

    manager.update_ticket(
        ticket_id=ticket.id,
        status=RequestStatus.archived
    )

    logger.info(
        f"Ticket archiviert | ID={ticket.id} | User={user.get('displayName')}"
    )

    add_history_event(
        ticket.id,
        actor_id=user["id"],
        actor_name=user["displayName"],
        action="ticket_archived_manual",
    )

    return RedirectResponse("/dashboard", status_code=303)



def complete_ticket_internal(ticket, request, user):
    # Pflichtfelder prüfen
    if not ticket.priority:
        raise HTTPException(400, "Priorität fehlt")

    try:
        json.loads(ticket.description or "{}")
    except Exception:
        raise HTTPException(400, "Ticketbeschreibung ungültig")

    workflow = build_workflow(ticket)

    if not workflow or "departments" not in workflow:
        raise HTTPException(500, "Workflow konnte nicht erstellt werden")



    request.app.state.manager.update_ticket(
        ticket_id=ticket.id,
        status=RequestStatus.in_request,
    )

    database.set_assignee(
        ticket_id=ticket.id,
        user_id = "fachabteilung",
        user_name= "fachabteilung",
    )

    database.set_accountable(
        ticket_id=ticket.id,
        user_id="fachabteilung",
        user_name="fachabteilung",
    )

    database.set_supervisor(
        ticket_id=ticket.id,
        user_id = "fachabteilung",
        user_name= "fachabteilung",
    )

    set_workflow_state(ticket.id, workflow)

    logger.info(
        "Ticket %s in in_request überführt | Departments=%s",
        ticket.id,
        list(workflow["departments"].keys())
    )



def require_ticket_permission(user: dict, ticket_type: TicketType):
    if not can_user_create_ticket(ticket_type.value, user["id"]):
        raise HTTPException(
            status_code=403,
            detail="Keine Berechtigung diesen Auftrag zu erstellen"
        )


### departments

@router.get("/tickets/{ticket_id}/departments")
async def get_my_departments(
    ticket_id: int,
    user: dict = Depends(get_current_user),
):
    from alpharequestmanager.services.workflow_state import get_departments_for_user

    return get_departments_for_user(ticket_id, user["id"])


@router.post("/tickets/{ticket_id}/departments/{group_id}/status")
async def set_department_status_api(
    ticket_id: int,
    group_id: str,
    status: str = Form(...),
    user: dict = Depends(get_current_user),
):
    from alpharequestmanager.services.workflow_state import (
        user_can_complete_department,
        set_department_status,
        can_archive_ticket,
    )

    if not user_can_complete_department(ticket_id, user["id"], group_id):
        raise HTTPException(403, "Keine Berechtigung für diese Fachabteilung")

    if status not in {"done", "rejected", "skipped"}:
        raise HTTPException(400, "Ungültiger Status")

    set_department_status(ticket_id, group_id, status)
    add_history_event(
        ticket_id,
        actor_id=user["id"],
        actor_name=user["displayName"],
        action="department_done",
        details={
            "department_id": group_id,
            "department_name": get_group_name_from_id(group_id),
        },
    )

    # Optional: Auto-Archiv
    if can_archive_ticket(ticket_id):
        database.update_ticket(
            ticket_id=ticket_id,
            status=RequestStatus.archived,
        )

        add_history_event(
            ticket_id,
            actor_id=None,
            actor_name="System",
            actor_type="system",
            action="ticket_archived",
        )

    return {"ok": True}


@router.get("/tickets/{ticket_id}/departments/all")
async def get_all_departments(
    ticket_id: int,
    user: dict = Depends(get_current_user),
):
    if not user.get("is_admin"):
        raise HTTPException(403)

    from alpharequestmanager.services.workflow_state import get_all_department_statuses
    return get_all_department_statuses(ticket_id)
