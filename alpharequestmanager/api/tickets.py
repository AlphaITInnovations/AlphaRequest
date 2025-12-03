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
from alpharequestmanager.utils.logger import logger
from alpharequestmanager.database import database
from alpharequestmanager.services import ninja_api
from alpharequestmanager.services.metrics import tickets_created_total
from alpharequestmanager.services.ninja_api import NinjaAuthFlowRequired
import json
from datetime import datetime
from alpharequestmanager.models.models import TicketType


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
    title: str = Form(...),
    ticket_type: TicketType = Form(...),
    description: str = Form(...),
    assignee_id: str = Form(...),
    assignee_name: str = Form(...),
    user: dict = Depends(get_current_user),
):

    user_cache = request.app.state.user_cache

    if assignee_id and not validate_assignee(user_cache, assignee_id):
        raise HTTPException(
            status_code=400,
            detail=f"Ungültiger Assignee (User-ID '{assignee_id}') nicht in AD gefunden"
        )

    manager = request.app.state.manager

    # description (data) aus JSON parsen
    desc_obj = json.loads(description)
    data = desc_obj.get("data", {})

    user_mail = user["email"]


    try:
        ninja_ticket = None

        match ticket_type:
            case TicketType.hardware:
                ninja_ticket = ninja_api.create_ticket_hardware(
                    description=desc_obj,
                    requester_mail=user_mail,
                    is_admin=user.get("is_admin", False),
                )

            case TicketType.zugangSperren:
                ninja_ticket = ninja_api.create_ticket_edv_sperren(
                    description=desc_obj,
                    requester_mail=user_mail,
                    is_admin=user.get("is_admin", False),
                )

            case TicketType.zugangBeantragen:
                arbeitsbeginn_ts = None
                if data.get("arbeitsbeginn"):
                    arbeitsbeginn_ts = int(datetime.fromisoformat(data["arbeitsbeginn"]).timestamp())

                ninja_ticket = ninja_api.create_ticket_edv_beantragen(
                    description=desc_obj,
                    vorname=data.get("vorname", ""),
                    nachname=data.get("nachname", ""),
                    firma=data.get("firma", ""),
                    arbeitsbeginn=arbeitsbeginn_ts,
                    titel=data.get("titel", ""),
                    strasse=data.get("strasse", ""),
                    ort=data.get("ort", ""),
                    plz=data.get("plz", ""),
                    handy=data.get("handy", ""),
                    telefon=data.get("telefon", ""),
                    fax=data.get("fax", ""),
                    niederlassung=data.get("niederlassung", ""),
                    kostenstelle=data.get("kostenstelle", ""),
                    kommentar=data.get("kommentar", ""),
                    requester_mail=user_mail,
                    checkbox_datev_user=bool(data.get("datev")),
                    checkbox_elo_user=bool(data.get("elo")),
                    elo_vorgesetzter=data.get("eloVorgesetzter", ""),
                    is_admin=user.get("is_admin", False),
                )

            case TicketType.niederlassungAnmeldung:
                ninja_ticket = ninja_api.create_ticket_niederlassung_anmelden(
                    description=desc_obj,
                    requester_mail=user_mail,
                    is_admin=user.get("is_admin", False),
                )

            case TicketType.niederlassungUmzug:
                ninja_ticket = ninja_api.create_ticket_niederlassung_umziehen(
                    description=desc_obj,
                    requester_mail=user_mail,
                    is_admin=user.get("is_admin", False),
                )

            case TicketType.niederlassungAbmeldung:
                ninja_ticket = ninja_api.create_ticket_niederlassung_schließen(
                    description=desc_obj,
                    requester_mail=user_mail,
                    is_admin=user.get("is_admin", False),
                )

        if not ninja_ticket or "id" not in ninja_ticket:
            raise HTTPException(status_code=500, detail="Ticket konnte in Ninja nicht erstellt werden")

    except NinjaAuthFlowRequired:
        return RedirectResponse("/dashboard?ninja_auth=needed", status_code=HTTP_302_FOUND)


    local_id = manager.create_ticket(
        title=title,
        ticket_type=ticket_type,
        description=description,
        owner_id=user["id"],
        owner_name=user["displayName"],
        owner_info=json.dumps(user, ensure_ascii=False),
    )

    manager.set_assignee(local_id, assignee_id, assignee_name)
    manager.set_ninja_metadata(local_id, ninja_ticket["id"])

    logger.info(
        "Ticket erstellt: lokal=%s / ninja=%s / user=%s",
        local_id, ninja_ticket["id"], user_mail
    )

    # Metrics
    tickets_created_total.labels(
        type=ticket_type.value,
        domain=user["email"].split("@")[1],
        company=user.get("company", ""),
    ).inc()

    return RedirectResponse("/dashboard", status_code=HTTP_302_FOUND)



@router.post("/tickets/update/{ticket_id}")
async def update_ticket_route(
    request: Request,
    ticket_id: int,
    title: str = Form(...),
    description: str = Form(...),
    comment: str = Form(""),
    assignee_id: str = Form(...),
    assignee_name: str = Form(...)
):
    manager = request.app.state.manager
    if assignee_id:
        if not validate_assignee(request.app.state.user_cache, assignee_id):
            raise HTTPException(400, f"Ungültiger Assignee (User-ID {assignee_id})")
        manager.set_assignee(ticket_id, assignee_id, assignee_name)
    database.update_ticket(
        ticket_id,
        title=title,
        description=description,
        comment=comment,
    )

    database.set_assignee(ticket_id, assignee_id, assignee_name)

    return RedirectResponse("/?updated=1", status_code=303)



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

