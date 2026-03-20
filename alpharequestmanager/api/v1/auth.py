import time
from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.status import HTTP_302_FOUND

from alpharequestmanager.core.dependencies import get_current_user
from alpharequestmanager.core.session import rotate_sid, approx_cookie_size_bytes, TOKENS
from alpharequestmanager.metrics.auth_metrics import (
    record_login_attempt, record_login_success, record_logout,
)
from alpharequestmanager.schemas.responses import DataResponse
from alpharequestmanager.schemas.ticket import UserOut
from alpharequestmanager.services.microsoft_auth import (
    initiate_auth_flow, acquire_token_by_auth_code,
)
from alpharequestmanager.services.microsoft_graph import get_user_profile
from alpharequestmanager.utils.config import config
from alpharequestmanager.utils.logger import logger

router = APIRouter()


# ── Vue-Endpunkt ───────────────────────────────────────────────────────────────

@router.get("/auth/me", response_model=DataResponse[UserOut])
def me(user: dict = Depends(get_current_user)):
    return DataResponse(data=UserOut(
        id=user["id"],
        displayName=user["displayName"],
        mail=user.get("mail") or user.get("email"),
        is_admin=user.get("is_admin", False),
    ))


# ── Login-Flow ─────────────────────────────────────────────────────────────────


@router.get("/start-auth", include_in_schema=False)
async def start_auth(request: Request):
    record_login_attempt()
    if request.session.get("user"):
        return RedirectResponse(config.FRONTEND_URL, status_code=HTTP_302_FOUND)
    auth_url = initiate_auth_flow(request)
    return RedirectResponse(auth_url)


@router.get("/auth/callback", include_in_schema=False)
async def auth_callback(request: Request):
    try:
        logger.info("Session vor Token-Abruf: %s", dict(request.session))

        if not request.session.get("auth_flow"):
            raise HTTPException(status_code=400, detail="OAuth Flow fehlt")

        result = acquire_token_by_auth_code(request)
        logger.info("Token Result keys: %s",
                    list(result.keys()) if isinstance(result, dict) else type(result))

        if not result or "access_token" not in result:
            return request.app.templates.TemplateResponse(
                "login.html", {"request": request, "error": "Tokenfehler"}
            )

        id_claims = result.get("id_token_claims", {}) or {}

        try:
            infos = await get_user_profile(result["access_token"])
        except Exception:
            logger.exception("Graph-Call fehlgeschlagen")
            infos = {}

        user_payload = {
            "id":          id_claims.get("oid") or id_claims.get("sub"),
            "displayName": id_claims.get("name") or infos.get("displayName"),
            "email":       id_claims.get("preferred_username")
                           or id_claims.get("email")
                           or infos.get("mail"),
            "is_admin":    config.ADMIN_GROUP_ID in (id_claims.get("groups", []) or []),
            "phone":       infos.get("phone"),
            "mobile":      infos.get("mobile"),
            "company":     infos.get("company"),
            "position":    infos.get("position"),
            "address":     infos.get("address") or {},
        }

        sid = rotate_sid(request.session)
        TOKENS.put(sid, result)

        request.session.update({"user": user_payload, "last_activity": int(time.time())})
        record_login_success(request)
        request.session.pop("auth_flow", None)

        if approx_cookie_size_bytes(request.session) > 3000:
            logger.warning("Session cookie zu groß, shrinking")
            request.session.clear()
            request.session.update({"sid": sid, "user": user_payload,
                                    "last_activity": int(time.time())})

        logger.info("Session nach Login: %s", dict(request.session))

        # Nach Login → Vue-App (FRONTEND_URL aus .env)
        return RedirectResponse(config.FRONTEND_URL, status_code=HTTP_302_FOUND)

    except Exception as e:
        logger.exception("Login fehlgeschlagen")
        return request.app.templates.TemplateResponse(
            "login.html", {"request": request, "error": str(e)}
        )


@router.get("/logout", include_in_schema=False)
async def logout(request: Request):
    user_email = request.session.get("user", {}).get("email")
    sid = request.session.get("sid")
    if sid:
        TOKENS.delete(sid)
    record_logout(request)
    request.session.clear()
    logger.info("User logged out: %s", user_email)
    # Nach Logout → Login-Seite direkt auf Backend
    return RedirectResponse(f"{config.FRONTEND_URL}", status_code=HTTP_302_FOUND)