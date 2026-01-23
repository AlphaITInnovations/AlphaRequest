from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse
from alpharequestmanager.core.dependencies import get_current_user
import json

from alpharequestmanager.services.ticket_overview_service import is_overview_groups_member

router = APIRouter()

@router.get("/ticket-overview", response_class=HTMLResponse)
async def ticket_overview(
    request: Request,
    page: int = 1,
    page_size: int = 50,
    user: dict = Depends(get_current_user),
):
    if not is_overview_groups_member(user.get("id")) and not user.get("is_admin"):
        raise HTTPException(403)


    page = max(page, 1)
    page_size = min(max(page_size, 10), 100)  # Schutz
    offset = (page - 1) * page_size

    manager = request.app.state.manager

    tickets = manager.list_all(limit=page_size, offset=offset)
    total = manager.count_all()

    items = []
    for t in tickets:
        items.append({
            "id": t.id,
            "title": t.title,
            "type_key": t.ticket_type.value,
            "status": t.status.value if hasattr(t.status, "value") else t.status,
            "priority": t.priority.value if hasattr(t.priority, "value") else t.priority,
            "created_at": t.created_at.isoformat() if hasattr(t.created_at, "isoformat") else t.created_at,
            "creator": t.owner_name,
        })

    return request.app.templates.TemplateResponse(
        "ticket_overview/list.html",
        {
            "request": request,
            "user": user,
            "tickets": items,
            "page": page,
            "page_size": page_size,
            "total": total,
            "is_admin": True,
        },
    )



@router.get("/ticket-overview/{ticket_id}", response_class=HTMLResponse)
async def ticket_overview_detail(
    ticket_id: int,
    request: Request,
    user: dict = Depends(get_current_user),
):

    if not is_overview_groups_member(user.get("id")) and not user.get("is_admin"):
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

