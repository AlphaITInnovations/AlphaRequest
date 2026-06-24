"""
Öffentlicher (unauthentifizierter) Endpoint für die Onboarding-Freigabe per
Mail-Link. Der JA/NEIN-Knopf in der Freigabe-Mail an Herrn Lutz zeigt auf
`/api/v1/freigabe?token=...`. Das Token ist signiert (siehe freigabe_token) und
trägt Ticket-ID + Aktion. 1-Klick: der GET führt die Aktion direkt aus und
rendert eine Ergebnisseite. Idempotent – ist die Freigabe-Phase schon vorbei,
erscheint „bereits bearbeitet".
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request, Query
from fastapi.responses import HTMLResponse

from backend.database import tickets as database
from backend.models.models import RequestStatus
from backend.services.freigabe_token import load_token
from backend.services.workflow_state import get_current_phase, advance_phase, reject_workflow
from backend.services.ticket_history import add_history_event
from backend.utils.logger import logger

router = APIRouter()

FREIGABE_PHASE_KEY = "freigabe"


def _render(request: Request, status: str, ticket=None) -> HTMLResponse:
    return request.app.templates.TemplateResponse(
        "freigabe_result.html",
        {"request": request, "status": status, "ticket": ticket},
    )


@router.get("/freigabe", response_class=HTMLResponse)
def freigabe_action(request: Request, token: str = Query("")):
    parsed = load_token(token)
    if not parsed:
        return _render(request, "invalid")

    ticket_id, action = parsed
    ticket = database.get_ticket(ticket_id)
    if not ticket:
        return _render(request, "invalid")

    # Nur gültig, solange das Ticket noch in der Freigabe-Phase ist.
    phase = get_current_phase(ticket_id)
    if (not phase or phase.get("key") != FREIGABE_PHASE_KEY
            or ticket.status in (RequestStatus.archived, RequestStatus.rejected)):
        return _render(request, "already", ticket=ticket)

    if action == "approve":
        advance_phase(ticket_id)
        ticket = database.get_ticket(ticket_id)
        add_history_event(
            ticket_id, actor_id=None, actor_name="Freigabe (Mail-Link)",
            actor_type="system", action="freigabe_approved_mail", details={},
        )
        # BackOffice (jetzt aktive Phase) benachrichtigen
        try:
            from backend.api.v1.tickets import notify_phase_entry
            notify_phase_entry(request, ticket, get_current_phase(ticket_id))
        except Exception:
            logger.exception("BackOffice-Benachrichtigung nach Mail-Freigabe fehlgeschlagen (Ticket %s)", ticket_id)
        return _render(request, "approved", ticket=ticket)

    # action == "reject"
    rejected_at = datetime.now(ZoneInfo("Europe/Berlin")).isoformat()
    reject_workflow(ticket_id, message="", rejected_by="Freigabe (Mail-Link)", rejected_at=rejected_at)
    add_history_event(
        ticket_id, actor_id=None, actor_name="Freigabe (Mail-Link)",
        actor_type="system", action="freigabe_rejected_mail", details={},
    )
    try:
        from backend.services.microsoft_mail import send_rejection_mail
        from backend.services.microsoft_graph import get_cached_user_mail
        owner_mail = ticket.owner_info_parsed.get("mail") or get_cached_user_mail(request.app, ticket.owner_id)
        send_rejection_mail(ticket, "", owner_mail)
    except Exception:
        logger.exception("Ablehnungs-Mail (Mail-Freigabe) fehlgeschlagen (Ticket %s)", ticket_id)
    return _render(request, "rejected", ticket=ticket)
