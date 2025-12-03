from fastapi import APIRouter, Request, Depends, HTTPException
from alpharequestmanager.core.dependencies import get_current_user

router = APIRouter()


@router.get("/api/admin/users")
async def api_admin_users(request: Request, user: dict = Depends(get_current_user)):
    # Optional: Admin-Pflicht aktivieren
    #if not user.get("is_admin", False):
    #    raise HTTPException(status_code=403, detail="Not authorized")

    return {
        "last_update": request.app.state.user_cache_timestamp,
        "count": len(request.app.state.user_cache),
        "users": request.app.state.user_cache
    }
