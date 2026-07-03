import time
from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import RedirectResponse
from starlette import status
from starlette.status import HTTP_302_FOUND

from backend.core.dependencies import get_current_user, check_session_only
from backend.core.session import rotate_sid, approx_cookie_size_bytes, TOKENS
from backend.database.users import (
    upsert_user, get_user_permissions, get_user, set_group_admin, revoke_group_admin,
)
from backend.services.admin_sync import (
    decide_group_admin_action, ACTION_PROMOTE, ACTION_REVOKE,
)
from backend.metrics.auth_metrics import (
    record_login_attempt, record_login_success, record_logout,
)
from backend.schemas.responses import DataResponse
from backend.schemas.ticket import UserOut
from backend.services.microsoft_auth import (
    initiate_auth_flow, acquire_token_by_auth_code,
)
from backend.services.microsoft_graph import get_user_profile
from backend.database.audit_log import record_audit
from backend.utils.config import config
from backend.utils.logger import logger


def _client_ip(request: Request) -> str | None:
    try:
        return request.client.host if request.client else None
    except Exception:
        return None

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

    from backend.services.ticket_permissions import get_allowed_ticket_types_for_user

    permissions = list(db_user.permissions)
    user_groups = user.get("groups", []) or []

    if user_groups:
        group_types = get_allowed_ticket_types_for_user(user["id"], user_groups)
        for tt in group_types:
            perm = f"create_{tt}"
            if perm not in permissions:
                permissions.append(perm)

    request.session["user"]["permissions"] = permissions
    request.session["last_activity"] = int(time.time())

    return DataResponse(data=UserOut(
        id=user["id"],
        displayName=user["displayName"],
        mail=user.get("mail") or user.get("email"),
        permissions=permissions,
    ))


# ── /auth/me ──────────────────────────────────────────────────────────────────

@router.get("/auth/me", response_model=DataResponse[UserOut])
def me(request: Request, user: dict = Depends(get_current_user)):
    from backend.services.ticket_permissions import get_allowed_ticket_types_for_user

    permissions = get_user_permissions(user["id"])
    user_groups = user.get("groups", []) or []

    # Gruppen-basierte create_* Permissions hinzufügen
    if user_groups:
        group_types = get_allowed_ticket_types_for_user(user["id"], user_groups)
        for tt in group_types:
            perm = f"create_{tt}"
            if perm not in permissions:
                permissions.append(perm)

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
            record_audit(action="login_failed", actor_type="system", actor_name="?",
                         entity_type="auth", summary="Token konnte nicht bezogen werden",
                         details={"reason": "token_error"}, ip=_client_ip(request))
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

        # Die AAD-Admin-Gruppe ist maßgeblich für die Admin-Rolle.
        # Wichtig: nur auswerten, wenn ADMIN_GROUP_ID konfiguriert ist und der
        # groups-Claim tatsächlich geliefert wurde. Bei "groups overage" (User in
        # sehr vielen Gruppen) fehlt der Claim – dann NICHT anfassen (fail-safe),
        # sonst würde man Admins fälschlich degradieren.
        raw_groups = id_claims.get("groups")
        groups_authoritative = isinstance(raw_groups, list)  # kein Overage
        user_groups = raw_groups if groups_authoritative else []

        admin_group_configured = bool(config.ADMIN_GROUP_ID)
        is_in_admin_group = admin_group_configured and config.ADMIN_GROUP_ID in user_groups

        # Gruppen-GUIDs nur im DEBUG-Log (verraten Org-Struktur, nicht ins INFO-Log).
        logger.debug("Login groups for user %s: %s", id_claims.get("name"), user_groups)

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
            "groups":      id_claims.get("groups", []) or [],
        }

        # User anlegen / last_login aktualisieren (Rolle wird separat synchronisiert)
        db_user = upsert_user(
            microsoft_id=user_payload["id"],
            display_name=user_payload["displayName"] or "",
            email=user_payload["email"] or "",
        )

        # Admin-Rolle mit der AD-Gruppe abgleichen: gruppen-basierte Admins werden
        # bei Austritt entzogen; manuell vergebene Rollen bleiben unberührt
        # (siehe services.admin_sync). Defensiv – ein Fehler darf den Login nicht
        # blockieren.
        action = decide_group_admin_action(
            admin_group_configured=admin_group_configured,
            groups_authoritative=groups_authoritative,
            is_in_admin_group=is_in_admin_group,
            current_role=db_user.role,
            admin_via_group=db_user.admin_via_group,
        )
        try:
            if action == ACTION_PROMOTE:
                db_user = set_group_admin(user_payload["id"]) or db_user
                record_audit(action="admin_granted", actor_id=user_payload["id"],
                             actor_name=user_payload["displayName"] or "", entity_type="user",
                             entity_id=user_payload["id"], summary="Admin via AD-Gruppe",
                             ip=_client_ip(request))
            elif action == ACTION_REVOKE:
                logger.info("Admin-Rolle entzogen (nicht mehr in AAD-Admin-Gruppe): %s",
                            user_payload["id"])
                db_user = revoke_group_admin(user_payload["id"]) or db_user
                record_audit(action="admin_revoked", actor_id=user_payload["id"],
                             actor_name=user_payload["displayName"] or "", entity_type="user",
                             entity_id=user_payload["id"], summary="Nicht mehr in AD-Admin-Gruppe",
                             ip=_client_ip(request))
        except Exception:
            logger.exception("Admin-Gruppen-Sync fehlgeschlagen für %s", user_payload["id"])

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
        record_audit(action="login", actor_id=user_payload["id"],
                     actor_name=user_payload["displayName"] or "", entity_type="auth",
                     entity_id=user_payload["id"], ip=_client_ip(request))

        return RedirectResponse(config.FRONTEND_URL, status_code=HTTP_302_FOUND)

    except Exception:
        logger.exception("Login fehlgeschlagen")
        record_audit(action="login_failed", actor_type="system", actor_name="?",
                     entity_type="auth", summary="Login fehlgeschlagen",
                     details={"reason": "exception"}, ip=_client_ip(request))
        return RedirectResponse(
            f"{config.FRONTEND_URL}/login?error=login_failed",
            status_code=HTTP_302_FOUND,
        )


# ── Logout ────────────────────────────────────────────────────────────────────

@router.get("/logout", include_in_schema=False)
async def logout(request: Request):
    sid = request.session.get("sid")
    if sid:
        TOKENS.delete(sid)
    record_logout(request)
    u = request.session.get("user") or {}
    record_audit(action="logout", actor_id=u.get("id"), actor_name=u.get("displayName") or "",
                 entity_type="auth", entity_id=u.get("id"), ip=_client_ip(request))
    request.session.clear()
    return RedirectResponse(f"{config.FRONTEND_URL}/login", status_code=HTTP_302_FOUND)