from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, JSONResponse

from alpharequestmanager.core.dependencies import get_current_user
from alpharequestmanager.utils.config import config


router = APIRouter()


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, user: dict = Depends(get_current_user)):
    """
    Dashboard-Seite mit Übersicht der Tickets des Users.
    """
    manager = request.app.state.manager
    raw = manager.list_by_assignee(user_id=user["id"])

    orders = [
        {
            "id": t.id,
            "type": t.title,
            "date": t.created_at.strftime("%d.%m.%Y"),
            "status": t.status.value,
            "comment": t.comment,
            "description": t.description,
            "assignee_id": t.assignee_id,
            "assignee_name": t.assignee_name,
            "assignee_history": t.assignee_history,
        }
        for t in raw
    ]

    companies = config.COMPANIES
    is_admin = user.get("is_admin", False)

    return request.app.templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": user,
            "orders": orders,
            "is_admin": is_admin,
            "companies_json": companies,
            "devpopup": config.DEVPOPUP,
        }
    )


@router.get("/api/orders", response_class=JSONResponse)
async def api_orders(user: dict = Depends(get_current_user), request: Request = None):
    """
    Gibt alle Tickets des Users als JSON aus (für Frontend-Integrationen).
    """
    manager = request.app.state.manager
    raw = manager.list_by_assignee(user_id=user["id"])

    orders = [
        {
            "id": t.id,
            "type": t.title,
            "date": t.created_at.strftime("%d.%m.%Y"),
            "status": t.status.value,
            "comment": t.comment,
            "description": t.description,
        }
        for t in raw
    ]

    return orders
