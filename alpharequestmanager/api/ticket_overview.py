from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse
from alpharequestmanager.core.dependencies import get_current_user
import json

router = APIRouter()

@router.get("/ticket-overview", response_class=HTMLResponse)
async def ticket_overview(
    request: Request,
    user: dict = Depends(get_current_user),
):
    if not user.get("is_admin"):
        raise HTTPException(403)

    manager = request.app.state.manager
    items = []

    for t in manager.list_all():
        items.append({
            "id": t.id,
            "title": t.title,
            "type_key": t.ticket_type.value,  # <-- STRING!
            "status": t.status.value if hasattr(t.status, "value") else t.status,
            "priority": t.priority.value if hasattr(t.priority, "value") else t.priority,
            "created_at": t.created_at.isoformat() if hasattr(t.created_at, "isoformat") else t.created_at,
            "creator": t.owner_name,  # <-- frontend erwartet creator
        })

    #print(items)
    return request.app.templates.TemplateResponse(
        "ticket_overview/list.html",
        {
            "request": request,
            "user": user,
            "tickets": items,
            "is_admin": True,
        },
    )


@router.get("/ticket-overview/{ticket_id}", response_class=HTMLResponse)
async def ticket_overview_detail(
    ticket_id: int,
    request: Request,
    user: dict = Depends(get_current_user),
):
    if not user.get("is_admin"):
        raise HTTPException(403)

    manager = request.app.state.manager
    ticket = manager.get_ticket(ticket_id)

    if not ticket:
        raise HTTPException(404, "Ticket nicht gefunden")

    # Beschreibung
    try:
        description = json.loads(ticket.description or "{}")
    except Exception:
        description = {}

    # Timeline / History
    from alpharequestmanager.services.ticket_history import get_ticket_history
    history = get_ticket_history(ticket_id) or []

    #print(history)

    return request.app.templates.TemplateResponse(
        "ticket_overview/detail.html",
        {
            "request": request,
            "user": user,
            "ticket": ticket,
            "description": description,

            # 🔑 WICHTIG: Name passt jetzt zum Template
            "history": history,

            "is_admin": True,
        },
    )

