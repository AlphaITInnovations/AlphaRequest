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
from alpharequestmanager.database.database import get_groupID_from_name
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



@router.post("/tickets")
async def create_ticket(
    request: Request,
    ticket_type: TicketType = Form(...),
    description: str = Form(...),
    assignee_id: str = Form(...),
    assignee_name: str = Form(...),
    comment: str = Form(""),
    priority: TicketPriority = Form(TicketPriority.medium),
    user: dict = Depends(get_current_user),
):
    user_cache = request.app.state.user_cache

    # Kommentar trimmen
    comment = (comment or "").strip()

    # Assignee prüfen
    if not assignee_id:
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

    # Titel generieren
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    label = TICKET_LABELS.get(ticket_type, ticket_type.value)
    generated_title = f"{label} – {user['displayName']} – {now_str}"

    manager = request.app.state.manager

    ticket_id = manager.create_ticket(
        title=generated_title,
        ticket_type=ticket_type,
        description=description,
        owner_id=user["id"],
        owner_name=user["displayName"],
        owner_info=json.dumps(user, ensure_ascii=False),
        comment=comment,
        status=RequestStatus.in_progress,
        assignee_id=assignee_id,
        assignee_name=assignee_name,
        priority=priority,
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
    priority: TicketPriority = Form(...),
    action: str = Form("save"),
    user: dict = Depends(get_current_user),
):
    comment = (comment or "").strip()
    #print(action)
    if not validate_assignee(request.app.state.user_cache, assignee_id):
        raise HTTPException(400, "Ungültiger Assignee")

    database.update_ticket(
        ticket_id=ticket_id,
        description=description,
        comment=comment,
        priority=priority,
    )

    database.set_assignee(ticket_id, assignee_id, assignee_name)

    ticket = request.app.state.manager.get_ticket(ticket_id)

    if action == "complete":
        complete_ticket_internal(ticket, request, user)

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
    template = f"tickets/{ticket_type.value}/create.html"

    return request.app.templates.TemplateResponse(
        template,
        {
            "request": request,
            "user": user,
            "ticket_type": ticket_type,
            "is_admin": user.get("is_admin", False),
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

    return request.app.templates.TemplateResponse(
        f"tickets/{ticket_type.value}/edit.html",
        {
            "request": request,
            "ticket": ticket,
            "user": user,
            "assignee_id": ticket.assignee_id,
            "assignee_name": ticket.assignee_name,
            "is_admin": user.get("is_admin", False),
            "priority": ticket.priority.value,
        },
    )


@router.get("/tickets/group/{ticket_type}/{ticket_id}")
async def group_ticket_view(
    request: Request,
    ticket_type: TicketType,
    ticket_id: int,
    user: dict = Depends(get_current_user),
):
    manager = request.app.state.manager
    ticket = manager.get_ticket(ticket_id)

    if not ticket:
        raise HTTPException(404, "Ticket nicht gefunden")

    try:
        description_parsed = json.loads(ticket.description or "{}")
    except Exception:
        description_parsed = {}

    # Optional: prüfen ob User Mitglied der Gruppe ist
    #if not user_is_in_group(user["id"], ticket.assignee_group_id):
    #    raise HTTPException(403, "Kein Zugriff")

    return request.app.templates.TemplateResponse(
        f"tickets/{ticket_type.value}/group_view.html",
        {
            "request": request,
            "ticket": ticket,
            "description": description_parsed,
            "user": user,
            "priority": ticket.priority.value,
            "is_admin": user.get("is_admin", False),
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

    return RedirectResponse("/dashboard", status_code=303)



def complete_ticket_internal(ticket, request, user):
    # Pflichtfelder prüfen
    if not ticket.priority:
        raise HTTPException(400, "Priorität fehlt")

    try:
        json.loads(ticket.description or "{}")
    except Exception:
        raise HTTPException(400, "Ticketbeschreibung ungültig")

    group_id = get_groupID_from_name(ticket.ticket_type)
    if not group_id:
        raise HTTPException(500, "Keine Fachabteilung konfiguriert")

    request.app.state.manager.update_ticket(
        ticket_id=ticket.id,
        status=RequestStatus.in_request,
        assignee_id="system",
        assignee_name="System",
        assignee_group_id=group_id,
    )
