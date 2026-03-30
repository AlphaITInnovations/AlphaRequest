from typing import Dict
import time
from fastapi import Request, HTTPException, status
from backend.utils.config import config
from backend.utils.logger import logger
from backend.metrics.auth_metrics import update_last_activity
from backend.core.session import TOKENS
from backend.database.users import get_user_permissions

SAFE_UPDATE_INTERVAL = 60  # seconds


def get_current_user(request: Request) -> Dict:
    session = request.session
    user = session.get("user")
    now = int(time.time())
    last_activity_raw = session.get("last_activity")

    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    update_last_activity(request)

    try:
        cookie_len = sum((len(k) + len(v)) for k, v in request.cookies.items())
    except Exception:
        cookie_len = -1

    logger.info(
        "session_keys=%s sid=%s last=%s now=%s cookie_len=%s",
        list(session.keys()), session.get("sid"), last_activity_raw, now, cookie_len,
    )

    try:
        last_activity = int(last_activity_raw) if last_activity_raw is not None else 0
    except Exception:
        last_activity = 0

    if last_activity == 0:
        session["last_activity"] = now
        user["permissions"] = get_user_permissions(user["id"])
        return user

    if now - last_activity > int(config.SESSION_TIMEOUT):
        sid = session.get("sid")
        try:
            if sid:
                TOKENS.delete(sid)
        except Exception:
            logger.exception("token revoke failed for sid=%s", sid)
        session.clear()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    if now - last_activity >= SAFE_UPDATE_INTERVAL:
        session["last_activity"] = now

    # Permissions immer frisch aus der DB – nie aus der Session
    user["permissions"] = get_user_permissions(user["id"])
    return user