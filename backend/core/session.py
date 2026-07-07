import json
import time
import uuid
from typing import Dict, Any, Optional
from fastapi import Request
from starlette.middleware.sessions import SessionMiddleware
from backend.utils.config import config


class TokenStore:
    """Server-side token storage, was in server.py stand."""
    def __init__(self) -> None:
        self._db: Dict[str, Dict[str, Any]] = {}

    def put(self, sid: str, tokens: Dict[str, Any]) -> None:
        self._db[sid] = {
            "access_token": tokens.get("access_token"),
            "refresh_token": tokens.get("refresh_token"),
            "expires_at": time.time() + 3500,
        }

    def get(self, sid: str) -> Optional[Dict[str, Any]]:
        return self._db.get(sid)

    def delete(self, sid: str) -> None:
        self._db.pop(sid, None)


TOKENS = TokenStore()

# Eindeutige Kennung dieses Server-Prozesses. Wird beim Login in die Session
# geschrieben und bei jedem Request geprüft: Nach einem Neustart ändert sie sich,
# wodurch ALLE bestehenden Sessions ungültig werden (erzwungenes Re-Login).
SERVER_BOOT_ID = uuid.uuid4().hex


def ensure_sid(session: dict) -> str:
    sid = session.get("sid")
    if not sid:
        sid = uuid.uuid4().hex
        session["sid"] = sid
    return sid


def rotate_sid(session: dict) -> str:
    old = session.get("sid")
    new = uuid.uuid4().hex
    session["sid"] = new
    if old:
        TOKENS.delete(old)
    return new


def approx_cookie_size_bytes(session: dict) -> int:
    try:
        raw = json.dumps(session, separators=(",", ":"))
        return len(raw.encode("utf-8"))
    except Exception:
        return -1


def get_access_token_from_store(request: Request) -> Optional[str]:
    sid = request.session.get("sid")
    if not sid:
        return None
    rec = TOKENS.get(sid)
    if not rec:
        return None
    return rec.get("access_token")


def setup_session(app):
    """SessionMiddleware einrichten (war vorher in server.py)."""
    app.add_middleware(
        SessionMiddleware,
        secret_key=config.SECRET_KEY,
        session_cookie="app_session",
        same_site="lax",
        # Secure-Flag außerhalb der lokalen Entwicklung immer setzen (auch hinter
        # TLS-terminierendem Proxy, wo HTTPS evtl. nicht als Env gesetzt ist).
        https_only=config.HTTPS or config.APP_ENV != "development",
        max_age=config.SESSION_TIMEOUT,
        path="/",
    )
