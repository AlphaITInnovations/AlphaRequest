import json
import uuid
from base64 import b64decode
from typing import Optional

from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import HTTPConnection
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


def _dump(session) -> str:
    return json.dumps(session, sort_keys=True, default=str)


class ChangeAwareSessionMiddleware(SessionMiddleware):
    """Wie Starlettes SessionMiddleware – schreibt das Cookie aber NUR, wenn sich die
    Session in diesem Request geändert hat (oder geleert wurde).

    Starlette setzt das Cookie sonst bei JEDER Antwort neu, auch unverändert. Das
    erzeugt ein Rennen: eine Antwort, die last_activity bewusst NICHT anfasst
    (Heartbeat /auth/check, Live-Abfragen mit X-Background-Poll, öffentliche
    Endpunkte), kommt nach einer echten Aktivität an und setzt das Cookie auf den
    ALTEN Stand zurück – die Session lief dann früher ab, obwohl gearbeitet wurde.

    Sicher bzgl. Ablauf: last_activity wird nur beim Schreiben geändert, und jedes
    Schreiben signiert neu. Signatur-Alter und Cookie-Max-Age laufen damit nie vor
    dem serverseitigen Inaktivitäts-Timeout ab. Die Original-Logik bleibt
    unangetastet; hier wird nur der überflüssige Set-Cookie wieder entfernt."""

    def _initial_session(self, scope) -> Optional[dict]:
        raw = HTTPConnection(scope).cookies.get(self.session_cookie)
        if not raw:
            return None
        try:
            data = self.signer.unsign(raw.encode("utf-8"), max_age=self.max_age)
            val = json.loads(b64decode(data))
        except Exception:
            return None
        return val if isinstance(val, dict) else None

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await super().__call__(scope, receive, send)
            return
        before = self._initial_session(scope)
        before_dump = _dump(before) if before else None
        prefix = f"{self.session_cookie}=".encode("latin-1")

        async def drop_unchanged_cookie(message):
            if message["type"] == "http.response.start" and before_dump is not None:
                session = scope.get("session")
                # Nicht-leer UND unverändert → das neu angehängte Session-Cookie
                # entfernen. Geleert (Logout/Timeout) bleibt das Lösch-Cookie stehen.
                if session and _dump(session) == before_dump:
                    message["headers"] = [
                        (k, v) for (k, v) in message.get("headers", [])
                        if not (k.lower() == b"set-cookie" and v.startswith(prefix))
                    ]
            await send(message)

        await super().__call__(scope, receive, drop_unchanged_cookie)


def setup_session(app):
    """SessionMiddleware einrichten (war vorher in server.py)."""
    app.add_middleware(
        ChangeAwareSessionMiddleware,
        secret_key=config.SECRET_KEY,
        session_cookie="app_session",
        same_site="lax",
        # Secure-Flag außerhalb der lokalen Entwicklung immer setzen (auch hinter
        # TLS-terminierendem Proxy, wo HTTPS evtl. nicht als Env gesetzt ist).
        https_only=config.HTTPS or config.APP_ENV != "development",
        max_age=config.SESSION_TIMEOUT,
        path="/",
    )
