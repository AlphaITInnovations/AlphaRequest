from fastapi import (
    APIRouter,
    Request,
    Depends,
    HTTPException,
    Query,
)
from fastapi.responses import RedirectResponse

from starlette.status import HTTP_302_FOUND

from alpharequestmanager.core.dependencies import get_current_user
from alpharequestmanager.utils.logger import logger
from alpharequestmanager.services import ninja_api
import secrets


router = APIRouter()


# ============================================================
# NinjaOne – Verbindung testen
# ============================================================

@router.get("/api/admin/ninja/test")
async def api_ninja_test(user: dict = Depends(get_current_user)):
    """Testet, ob NinjaOne mit current Admin-Token erreichbar ist."""
    if not user.get("is_admin"):
        raise HTTPException(403, "Not authorized")

    try:
        ok = ninja_api.test_connection(is_admin=user.get("is_admin", False))
        return {"ok": bool(ok)}
    except Exception as e:
        logger.exception("Ninja test_connection failed")
        raise HTTPException(500, f"Verbindung fehlgeschlagen: {e}")


# ============================================================
# NinjaOne – Auth Flow starten
# ============================================================

@router.post("/api/admin/ninja/start-auth")
async def api_ninja_start_auth(request: Request, user: dict = Depends(get_current_user)):
    if not user.get("is_admin"):
        raise HTTPException(403, "Not authorized")

    state = secrets.token_urlsafe(24)
    request.session["ninja_oauth_state"] = state

    auth_url = ninja_api.build_auth_url(state)

    return {
        "ok": True,
        "auth_url": auth_url,
    }


# ============================================================
# NinjaOne – OAuth Callback
# ============================================================

@router.get("/ninja/oauth/callback")
async def ninja_oauth_callback(
    request: Request,
    code: str = Query(...),
    state: str = Query(...),
):
    expect = request.session.get("ninja_oauth_state")
    if not expect or state != expect:
        raise HTTPException(status_code=400, detail="Ungültiger OAuth-State")

    try:
        ninja_api.exchange_code_for_token(code)
        request.session.pop("ninja_oauth_state", None)

        return RedirectResponse(
            url="/settings?tab=ninja&auth=ok",
            status_code=HTTP_302_FOUND,
        )

    except Exception as e:
        request.session.pop("ninja_oauth_state", None)
        raise HTTPException(status_code=500, detail=f"Token-Austausch fehlgeschlagen: {e}")


# ============================================================
# NinjaOne – Token Refresh
# ============================================================

@router.post("/api/admin/ninja/refresh")
async def api_ninja_refresh(user: dict = Depends(get_current_user)):
    if not user.get("is_admin"):
        raise HTTPException(403, "Not authorized")

    tok = ninja_api.load_token()
    if not tok or not tok.get("refresh_token"):
        raise HTTPException(400, "Kein Refresh-Token vorhanden. Bitte neuen Auth-Flow starten.")

    try:
        new_tok = ninja_api.refresh_token(tok["refresh_token"])
        return {
            "ok": True,
            "expires_at": new_tok.get("expires_at"),
        }

    except Exception as e:
        raise HTTPException(500, f"Refresh fehlgeschlagen: {e}")
