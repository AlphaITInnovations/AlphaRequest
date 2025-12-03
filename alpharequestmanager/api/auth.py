from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.status import HTTP_302_FOUND

from alpharequestmanager.services.microsoft_auth import (
    initiate_auth_flow,
    acquire_token_by_auth_code,
)
from alpharequestmanager.services.microsoft_graph import get_user_profile
from alpharequestmanager.core.session import (
    rotate_sid,
    approx_cookie_size_bytes,
    TOKENS,
)
from alpharequestmanager.services.metrics import (
    record_login_success,
    record_login_failure,
    record_logout,
)
from alpharequestmanager.utils.logger import logger
from alpharequestmanager.utils.config import config

import time


router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Login-Seite anzeigen."""
    if request.session.get("user"):
        return RedirectResponse("/dashboard", status_code=HTTP_302_FOUND)
    return request.app.templates.TemplateResponse("login.html", {"request": request})


@router.get("/start-auth")
async def start_auth(request: Request):
    """OAuth Flow starten."""
    if request.session.get("user"):
        return RedirectResponse("/dashboard", status_code=HTTP_302_FOUND)
    auth_url = initiate_auth_flow(request)
    return RedirectResponse(auth_url)


@router.get("/auth/callback")
async def auth_callback(request: Request):
    """
    OAuth Callback – übernimmt Token-Abruf, erstellt Session,
    User-Infos und rotiert SID.
    """
    try:
        logger.info("➡️ Session vor Token-Abruf: %s", dict(request.session))

        flow = request.session.get("auth_flow")
        if not flow:
            raise HTTPException(status_code=400, detail="OAuth Flow fehlt")

        # Token über OAuth holen
        result = acquire_token_by_auth_code(request)
        logger.info(
            "🔁 Token Result keys: %s",
            list(result.keys()) if isinstance(result, dict) else type(result),
        )

        if not result or "access_token" not in result:
            return request.app.templates.TemplateResponse(
                "login.html",
                {"request": request, "error": "Tokenfehler"},
            )

        # Claims / Benutzerprofil erfassen
        id_claims = result.get("id_token_claims", {}) or {}
        logger.info("🪪 ID Claims keys: %s", list(id_claims.keys()))

        try:
            infos = await get_user_profile(result["access_token"])
        except Exception:
            logger.exception("Graph-Call fehlgeschlagen")
            infos = {}

        # Session-User
        user_payload = {
            "id": id_claims.get("oid") or id_claims.get("sub"),
            "displayName": id_claims.get("name") or infos.get("displayName"),
            "email": id_claims.get("preferred_username")
            or id_claims.get("email")
            or infos.get("mail"),
            "is_admin": config.ADMIN_GROUP_ID in (id_claims.get("groups", []) or []),
            "phone": infos.get("phone"),
            "mobile": infos.get("mobile"),
            "company": infos.get("company"),
            "position": infos.get("position"),
            "address": infos.get("address") or {},
        }

        # SID rotieren & Token speichern
        sid = rotate_sid(request.session)
        TOKENS.put(sid, result)

        request.session.update(
            {
                "user": user_payload,
                "last_activity": int(time.time()),
            }
        )
        record_login_success(request)

        # Flow entfernen
        request.session.pop("auth_flow", None)

        # Cookie-Größe prüfen
        size = approx_cookie_size_bytes(request.session)
        if size < 0 or size > 3000:
            logger.warning("Session cookie too large (%s bytes). Shrinking.", size)
            request.session.clear()
            request.session["sid"] = sid
            request.session["user"] = user_payload
            request.session["last_activity"] = int(time.time())

        logger.info("✅ Session nach Schreiben: %s", dict(request.session))
        return RedirectResponse("/dashboard", status_code=HTTP_302_FOUND)

    except Exception as e:
        logger.exception("Login fehlgeschlagen")
        record_login_failure("auth_callback_failed")
        return request.app.templates.TemplateResponse(
            "login.html",
            {"request": request, "error": str(e)},
        )


@router.get("/logout")
async def logout(request: Request):
    """Session löschen & Token entfernen."""
    user_email = request.session.get("user", {}).get("email")
    sid = request.session.get("sid")
    if sid:
        TOKENS.delete(sid)

    record_logout(request)
    request.session.clear()

    logger.info("User logged out: %s", user_email)
    return RedirectResponse("/login", status_code=HTTP_302_FOUND)
