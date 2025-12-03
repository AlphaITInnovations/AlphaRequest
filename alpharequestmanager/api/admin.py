from fastapi import (
    APIRouter,
    Request,
    HTTPException,
    Form,
    Depends,
    Body,
)
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.status import HTTP_302_FOUND

from alpharequestmanager.core.dependencies import get_current_user
from alpharequestmanager.utils.logger import logger
from alpharequestmanager.models.models import RequestStatus
from alpharequestmanager.utils.config import config
from alpharequestmanager.database.database import (
    update_ticket,
    load_ticket_permissions,
    save_ticket_permissions,
    set_companies,
)
from alpharequestmanager.core.session import get_access_token_from_store

import json

router = APIRouter()


# =====================================================================
# SECTION: TICKET PRÜFUNG (Admin)
# =====================================================================

@router.get("/pruefung", response_class=HTMLResponse)
async def pruefung_page(request: Request, user: dict = Depends(get_current_user)):
    if not user.get("is_admin"):
        return RedirectResponse("/dashboard", status_code=HTTP_302_FOUND)

    manager = request.app.state.manager
    items = []

    for t in manager.list_all():
        try:
            description_parsed = json.loads(t.description)
        except Exception as e:
            print(f"Fehler beim Parsen der Ticketbeschreibung (ID {t.id}):", e)
            description_parsed = {}

        item = {
            "id": t.id,
            "type": t.title,
            "date": t.created_at.strftime("%d.%m.%Y"),
            "creator": t.owner_name,
            "status": t.status.value,
            "description": description_parsed,
            "owner_info": json.loads(t.owner_info) if t.owner_info else None,
            "ninja_metadata": json.loads(t.ninja_metadata) if t.ninja_metadata else None
        }
        items.append(item)

    items_json = json.dumps(items, ensure_ascii=False)

    return request.app.templates.TemplateResponse(
        "pruefung.html",
        {"request": request, "user": user, "items_json": items_json, "is_admin": True}
    )


@router.post("/pruefung/approve")
async def approve_ticket(
    request: Request,
    ticket_id: int = Form(...),
    comment: str = Form(""),
    description_json: str = Form(""),
    user: dict = Depends(get_current_user)
):
    if not user.get("is_admin"):
        raise HTTPException(403, "Not authorized")

    if description_json.strip():
        try:
            description_data = json.loads(description_json)
            update_ticket(ticket_id, description=json.dumps(description_data, ensure_ascii=False))
        except Exception as e:
            print(f"Fehler beim Speichern der Beschreibung (ID {ticket_id}):", e)

    update_ticket(ticket_id, status=RequestStatus.approved)

    manager = request.app.state.manager
    manager.set_comment(ticket_id, comment)
    logger.info("Ticket approved: %s by admin %s", ticket_id, user["displayName"])

    # Optional: Graph-APIs über Token
    access_token = get_access_token_from_store(request)

    return RedirectResponse("/pruefung", status_code=HTTP_302_FOUND)


@router.post("/pruefung/reject")
async def reject_ticket(
    ticket_id: int = Form(...),
    comment: str = Form(""),
    description_json: str = Form(""),
    user: dict = Depends(get_current_user)
):
    if not user.get("is_admin"):
        raise HTTPException(403, "Not authorized")

    if description_json.strip():
        try:
            description_data = json.loads(description_json)
            update_ticket(ticket_id, description=json.dumps(description_data, ensure_ascii=False))
        except Exception as e:
            print(f"Fehler beim Speichern der Beschreibung (ID {ticket_id}):", e)

    update_ticket(ticket_id, status=RequestStatus.rejected)

    manager = request.app.state.manager
    manager.set_comment(ticket_id, comment)
    logger.info("Ticket rejected: %s by admin %s", ticket_id, user["displayName"])

    return RedirectResponse("/pruefung", status_code=HTTP_302_FOUND)



# =====================================================================
# SECTION: SETTINGS PAGE (Admin)
# =====================================================================

@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, user: dict = Depends(get_current_user)):
    if not user.get("is_admin", False):
        return RedirectResponse("/dashboard", status_code=HTTP_302_FOUND)

    env_view = {
        "general": {
            "TICKET_MAIL": {"value": config.TICKET_MAIL or "—", "is_set": bool(config.TICKET_MAIL), "sensitive": False},
            "APP_ENV": {"value": config.APP_ENV, "is_set": True, "sensitive": False},
            "PORT": {"value": config.PORT, "is_set": True, "sensitive": False},
            "HTTPS": {"value": bool(config.HTTPS), "is_set": True, "sensitive": False},
        },
        "microsoft": {
            "CLIENT_ID": {"is_set": bool(config.CLIENT_ID), "sensitive": True},
            "CLIENT_SECRET": {"is_set": bool(config.CLIENT_SECRET), "sensitive": True},
            "TENANT_ID": {"is_set": bool(config.TENANT_ID), "sensitive": True},
            "REDIRECT_URI": {"value": config.REDIRECT_URI or "—", "is_set": bool(config.REDIRECT_URI), "sensitive": False},
            "SCOPE": {"value": ", ".join(config.SCOPE) if getattr(config, "SCOPE", None) else "—", "is_set": bool(getattr(config, "SCOPE", None)), "sensitive": False},
            "ADMIN_GROUP_ID": {"is_set": bool(config.ADMIN_GROUP_ID), "sensitive": True},
        },
        "ninja": {
            "NINJA_CLIENT_ID": {"is_set": bool(config.NINJA_CLIENT_ID), "sensitive": True},
            "NINJA_CLIENT_SECRET": {"is_set": bool(config.NINJA_CLIENT_SECRET), "sensitive": True},
            "NINJA_REDIRECT_URI": {"value": config.NINJA_REDIRECT_URI or "—", "is_set": bool(config.NINJA_REDIRECT_URI), "sensitive": False},
            "NINJA_POLL_INTERVAL": {"value": getattr(config, "NINJA_POLL_INTERVAL", None), "is_set": getattr(config, "NINJA_POLL_INTERVAL", None) is not None, "sensitive": False},
        },
        "session": {
            "SESSION_TIMEOUT": {"value": config.SESSION_TIMEOUT, "is_set": True, "sensitive": False},
            "SECRET_KEY": {"is_set": bool(config.SECRET_KEY), "sensitive": True},
        },
    }

    return request.app.templates.TemplateResponse(
        "settings.html",
        {"request": request, "user": user, "is_admin": True, "env": env_view},
    )



# =====================================================================
# SECTION: COMPANIES API
# =====================================================================

@router.get("/api/companies")
async def api_get_companies(user: dict = Depends(get_current_user)):
    items = list(config.COMPANIES)
    return {"companies": items, "count": len(items)}


def _normalize_companies(items: list[str]) -> list[str]:
    out = []
    seen = set()
    for raw in items:
        name = str(raw).strip()
        if not name:
            continue
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(name)
    return out


@router.put("/api/companies")
async def api_set_companies(payload: dict = Body(...), user: dict = Depends(get_current_user)):
    if not user.get("is_admin"):
        raise HTTPException(403)

    items = payload.get("companies")
    if not isinstance(items, list):
        raise HTTPException(422, "companies must be a list")

    normalized = _normalize_companies(items)
    if not normalized:
        raise HTTPException(422, "list must contain at least one value")

    try:
        set_companies(normalized)
    except Exception as e:
        logger.exception("Failed to update COMPANIES: %s", e)
        raise HTTPException(500, "failed to persist")

    return {"companies": list(config.COMPANIES), "count": len(config.COMPANIES)}



# =====================================================================
# SECTION: TICKET PERMISSIONS
# =====================================================================

@router.get("/api/admin/ticket-permissions")
async def api_get_ticket_permissions(user: dict = Depends(get_current_user)):
    if not user.get("is_admin"):
        raise HTTPException(403)
    return load_ticket_permissions()


@router.put("/api/admin/ticket-permissions")
async def api_set_ticket_permissions(payload: dict = Body(...), user: dict = Depends(get_current_user)):
    if not user.get("is_admin"):
        raise HTTPException(403)

    if not isinstance(payload, dict):
        raise HTTPException(422)

    save_ticket_permissions(payload)
    return {"ok": True}



# =====================================================================
# SECTION: Helper (wird von Tickets & Ninja verwendet)
# =====================================================================

def format_user_info_plain(user: dict) -> str:
    address = user.get("address", {})
    return (
        "\n\n---\n"
        f"Erstellt von: {user.get('displayName')} ({user.get('email')})\n"
        f"Firma: {user.get('company')}\n"
        f"Position: {user.get('position')}\n"
        f"Telefon: {user.get('phone') or '-'}\n"
        f"Mobil: {user.get('mobile') or '-'}\n"
        f"Adresse: {address.get('street', '-')}, {address.get('zip', '')} {address.get('city', '')}\n"
        "---\n"
    )


def format_user_info_html(user: dict) -> str:
    address = user.get("address", {})
    return (
        "<hr>"
        f"<p><b>Erstellt von:</b> {user.get('displayName')} ({user.get('email')})<br>"
        f"<b>Firma:</b> {user.get('company')}<br>"
        f"<b>Position:</b> {user.get('position')}<br>"
        f"<b>Telefon:</b> {user.get('phone') or '-'}<br>"
        f"<b>Mobil:</b> {user.get('mobile') or '-'}<br>"
        f"<b>Adresse:</b> {address.get('street', '-')}, {address.get('zip', '')} {address.get('city', '')}</p>"
        "<hr>"
    )

@router.get("/api/admin/can-create")
async def api_can_create(ticket_type: str, user: dict = Depends(get_current_user)):
    from alpharequestmanager.database.database import load_ticket_permissions
    user_id = user.get("id") or user.get("mail")
    perms = load_ticket_permissions()
    allowed = perms.get(ticket_type)


    if not allowed:
        return {"ok": True}



    return {"ok": user_id in allowed}