import time
from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import RedirectResponse
from starlette import status
from starlette.status import HTTP_302_FOUND

from backend.core.dependencies import get_current_user
from backend.core.session import rotate_sid, approx_cookie_size_bytes, TOKENS
from backend.database.users import upsert_user, get_user_permissions, get_user, ROLE_ADMIN
from backend.metrics.auth_metrics import (
    record_login_attempt, record_login_success, record_logout,
)
from backend.schemas.responses import DataResponse
from backend.schemas.ticket import UserOut
from backend.services.microsoft_auth import (
    initiate_auth_flow, acquire_token_by_auth_code,
)
from backend.services.microsoft_graph import get_user_profile
from backend.utils.config import config
from backend.utils.logger import logger

router = APIRouter()


# ── /auth/refresh-session ─────────────────────────────────────────────────────

@router.post("/auth/refresh-session", response_model=DataResponse[UserOut])
def refresh_session(
    request: Request,
    user: dict = Depends(get_current_user),
):
    """
    Aktualisiert Permissions in der Session.
    Nützlich nachdem ein Admin einem User Rechte geändert hat.
    """
    db_user = get_user(user["id"])
    if not db_user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    request.session["user"]["permissions"] = db_user.permissions
    request.session["last_activity"] = int(time.time())

    return DataResponse(data=UserOut(
        id=user["id"],
        displayName=user["displayName"],
        mail=user.get("mail") or user.get("email"),
        permissions=db_user.permissions,
    ))


# ── /auth/me ──────────────────────────────────────────────────────────────────

@router.get("/auth/me", response_model=DataResponse[UserOut])
def me(user: dict = Depends(get_current_user)):
    permissions = get_user_permissions(user["id"])
    return DataResponse(data=UserOut(
        id=user["id"],
        displayName=user["displayName"],
        mail=user.get("mail") or user.get("email"),
        permissions=permissions,
    ))


# ── /auth/check (Heartbeat – aktualisiert last_activity NICHT) ────────────────

@router.get("/auth/check")
def check_session(user: dict = Depends(check_session_only)):
    """
    Prüft ob die Session noch gültig ist.
    Aktualisiert last_activity NICHT – damit der Heartbeat
    die Session nicht künstlich am Leben hält.
    """
    return {"status": "ok"}

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

        if not request.session.get("auth_flow"):
            raise HTTPException(status_code=400, detail="OAuth Flow fehlt")

        result = acquire_token_by_auth_code(request)


        if not result or "access_token" not in result:
            return RedirectResponse(
                f"{config.FRONTEND_URL}/login?error=token_error",
                status_code=HTTP_302_FOUND,
            )

        id_claims = result.get("id_token_claims", {}) or {}

        try:
            infos = await get_user_profile(result["access_token"])
        except Exception:
            logger.exception("Graph-Call fehlgeschlagen")
            infos = {}

        # Admin-Rolle automatisch setzen wenn User in der konfigurierten AAD-Gruppe ist
        is_in_admin_group = config.ADMIN_GROUP_ID in (id_claims.get("groups", []) or [])
        initial_role = ROLE_ADMIN if is_in_admin_group else None

        user_payload = {
            "id":          id_claims.get("oid") or id_claims.get("sub"),
            "displayName": id_claims.get("name") or infos.get("displayName"),
            "email":       id_claims.get("preferred_username")
                           or id_claims.get("email")
                           or infos.get("mail"),
            "phone":       infos.get("phone"),
            "mobile":      infos.get("mobile"),
            "company":     infos.get("company"),
            "position":    infos.get("position"),
            "address":     infos.get("address") or {},
        }

        # User anlegen / last_login aktualisieren; Admin-Rolle ggf. erzwingen
        db_user = upsert_user(
            microsoft_id=user_payload["id"],
            display_name=user_payload["displayName"] or "",
            email=user_payload["email"] or "",
            role=initial_role,
        )

        # Permissions in die Session schreiben
        user_payload["permissions"] = db_user.permissions

        sid = rotate_sid(request.session)
        TOKENS.put(sid, result)
        request.session.update({"user": user_payload, "last_activity": int(time.time())})
        request.session.pop("auth_flow", None)

        if approx_cookie_size_bytes(request.session) > 3000:
            logger.warning("Session cookie zu groß, shrinking")
            request.session.clear()
            request.session.update({
                "sid": sid,
                "user": user_payload,
                "last_activity": int(time.time()),
            })

        record_login_success(request)

        return RedirectResponse(config.FRONTEND_URL, status_code=HTTP_302_FOUND)

    except Exception as e:
        logger.exception("Login fehlgeschlagen")
        return RedirectResponse(
            f"{config.FRONTEND_URL}/login?error=login_failed",
            status_code=HTTP_302_FOUND,
        )


# ── Logout ────────────────────────────────────────────────────────────────────

@router.get("/logout", include_in_schema=False)
async def logout(request: Request):
    user_email = request.session.get("user", {}).get("email")
    sid = request.session.get("sid")
    if sid:
        TOKENS.delete(sid)
    record_logout(request)
    request.session.clear()
    return RedirectResponse(f"{config.FRONTEND_URL}/login", status_code=HTTP_302_FOUND)