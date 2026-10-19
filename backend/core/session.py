import uuid
from starlette.middleware.sessions import SessionMiddleware
from backend.utils.config import config

# Microsoft-Tokens (Access/Refresh) werden bewusst NICHT aufbewahrt: der Login
# braucht das Access-Token nur einmal (Graph-Profil), danach nichts mehr. Ein
# früherer In-Memory-Token-Speicher wurde nie gelesen, hielt aber die (monatelang
# gültigen) Refresh-Tokens aller Logins bis zum Neustart im Prozess.

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
        # Alte serverseitige Session-Row mit aufräumen (Lifecycle an einer Stelle).
        try:
            from backend.database.sessions import delete_session
            delete_session(old)
        except Exception:
            pass
    return new


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
