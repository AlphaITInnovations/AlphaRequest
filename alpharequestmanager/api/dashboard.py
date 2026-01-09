from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, JSONResponse

from alpharequestmanager.core.dependencies import get_current_user
from alpharequestmanager.models.models import Ticket
from alpharequestmanager.services.ticket_permissions import get_allowed_ticket_types_for_user
from alpharequestmanager.services.workflow_state import get_department_requests_for_user
from alpharequestmanager.utils.config import config

router = APIRouter()

@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, user: dict = Depends(get_current_user)):
    """
    Dashboard mit Tickets, die dem User zugeordnet sind
    """
    manager = request.app.state.manager
    allowed_types = get_allowed_ticket_types_for_user(user["id"])
    tickets = manager.list_by_assignee(user_id=user["id"])
    #print(allowed_types)
    orders = [
        ticket_to_dashboard_item(t)
        for t in tickets
    ]

    department_requests = get_department_requests_for_user(user["id"])


    return request.app.templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": user,
            "orders": orders,
            "department_requests": department_requests,
            "is_admin": user.get("is_admin", False),
            "devpopup": config.DEVPOPUP,
            "allowed_ticket_types": allowed_types,
        }
    )


@router.get("/api/orders", response_class=JSONResponse)
async def api_orders(request: Request, user: dict = Depends(get_current_user)):
    """
    JSON-Endpoint für Dashboard-Polling
    """
    manager = request.app.state.manager

    tickets = manager.list_by_assignee(user_id=user["id"])

    return [
        {
            "id": t.id,
            "type": t.title,
            "type_key": t.ticket_type,
            "date": t.created_at.strftime("%d.%m.%Y"),
            "status": t.status.value,
            "priority": t.priority.value,
        }
        for t in tickets
    ]


def ticket_to_dashboard_item(ticket):
    return {
        "id": ticket.id,
        "type": ticket.title,
        "type_key": ticket.ticket_type,
        "date": ticket.created_at.strftime("%d.%m.%Y"),
        "status": ticket.status.value,
        "priority": ticket.priority.value if ticket.priority else "medium",
    }
