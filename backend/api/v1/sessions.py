"""
Admin-Endpunkte für die Live-Session-Liste und Force-Logout.

Alle Endpunkte sind Admin-only. Force-Logout entfernt die serverseitige
Session-Row (→ `get_current_user`/Heartbeat liefern beim nächsten Request 401)
und purged den In-Memory-Token-Store, sodass auch kein Graph-Token mehr nutzbar
ist. Jede Abmeldung wird auditiert.
"""

from fastapi import APIRouter, Request, Depends

from backend.core.dependencies import get_current_user
from backend.core.session import TOKENS
from backend.database import sessions as session_store
from backend.database.users import PERM_ADMIN
from backend.database.audit_log import record_audit
from backend.schemas.responses import ErrorCode, api_error
from backend.utils.logger import logger

router = APIRouter()


def _require_admin(user: dict) -> dict:
    if PERM_ADMIN not in user.get("permissions", []):
        raise api_error(403, ErrorCode.ADMIN_REQUIRED, "Admin-Rechte erforderlich")
    return user


def _client_ip(request: Request):
    return request.client.host if request.client else None


@router.get("/admin/sessions")
def list_sessions(request: Request, user: dict = Depends(get_current_user)):
    """Aktive Sessions. Die eigene Session ist mit `current=true` markiert."""
    _require_admin(user)
    my_sid = request.session.get("sid")
    sessions = session_store.list_active_sessions()
    for s in sessions:
        s["current"] = (s.get("sid") == my_sid)
    return {"data": {"sessions": sessions}}


@router.delete("/admin/sessions/{sid}", status_code=204)
def revoke_session(sid: str, request: Request, user: dict = Depends(get_current_user)):
    """Einzelne Session abmelden."""
    _require_admin(user)
    row = None
    try:
        row = session_store.get_session(sid)
    except Exception:
        logger.exception("Session-Lookup vor Force-Logout fehlgeschlagen (sid=%s)", sid)

    TOKENS.delete(sid)
    session_store.delete_session(sid)

    target = (row or {}).get("user_name") or (row or {}).get("user_id") or sid
    record_audit(
        action="session_revoked",
        actor_id=user["id"], actor_name=user["displayName"],
        entity_type="auth", entity_id=(row or {}).get("user_id"),
        summary=f"Session abgemeldet: {target}",
        details={"sid": sid}, ip=_client_ip(request),
    )


@router.delete("/admin/sessions/user/{user_id}", status_code=204)
def revoke_user_sessions(user_id: str, request: Request, user: dict = Depends(get_current_user)):
    """Alle Sessions einer Person abmelden."""
    _require_admin(user)
    sids = session_store.delete_sessions_for_user(user_id)
    for s in sids:
        TOKENS.delete(s)
    record_audit(
        action="session_revoked",
        actor_id=user["id"], actor_name=user["displayName"],
        entity_type="auth", entity_id=user_id,
        summary=f"{len(sids)} Session(s) einer Person abgemeldet",
        details={"count": len(sids), "sids": sids}, ip=_client_ip(request),
    )


@router.post("/admin/sessions/logout-others", status_code=204)
def logout_others(request: Request, user: dict = Depends(get_current_user)):
    """Alle Sessions außer der eigenen abmelden."""
    _require_admin(user)
    my_sid = request.session.get("sid")
    count = 0
    for s in session_store.list_active_sessions():
        sid = s.get("sid")
        if not sid or sid == my_sid:
            continue
        TOKENS.delete(sid)
        session_store.delete_session(sid)
        count += 1
    record_audit(
        action="session_revoked",
        actor_id=user["id"], actor_name=user["displayName"],
        entity_type="auth",
        summary=f"Alle anderen Sessions abgemeldet ({count})",
        details={"count": count}, ip=_client_ip(request),
    )
