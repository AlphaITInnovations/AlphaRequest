"""
Signierte, zeitlich begrenzte Tokens für die Onboarding-Freigabe per Mail-Link.

Der Link in der Freigabe-Mail (JA/NEIN) enthält ein signiertes Token, das
Ticket-ID und Aktion (approve/reject) trägt. So kann die Freigabe ohne Login
ausgelöst werden, ohne dass der Link fälschbar ist. Verwendet itsdangerous
(bereits installiert) mit dem SECRET_KEY der App.
"""

from typing import Optional, Tuple

from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

from backend.utils.config import config

_SALT = "freigabe-v1"
# Gültigkeit des Links (Sekunden) – großzügig, da die Freigabe Tage dauern kann.
MAX_AGE_SECONDS = 30 * 24 * 60 * 60  # 30 Tage

VALID_ACTIONS = ("approve", "reject")


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(config.SECRET_KEY, salt=_SALT)


def make_token(ticket_id: int, action: str) -> str:
    """Erzeugt ein signiertes Token für (ticket_id, action)."""
    if action not in VALID_ACTIONS:
        raise ValueError(f"Ungültige Aktion: {action!r}")
    return _serializer().dumps({"tid": int(ticket_id), "act": action})


def load_token(token: str) -> Optional[Tuple[int, str]]:
    """
    Prüft das Token und gibt (ticket_id, action) zurück, oder None bei
    ungültiger Signatur / Ablauf / falschem Format.
    """
    if not token:
        return None
    try:
        data = _serializer().loads(token, max_age=MAX_AGE_SECONDS)
    except (BadSignature, SignatureExpired, Exception):
        return None
    if not isinstance(data, dict):
        return None
    tid = data.get("tid")
    act = data.get("act")
    if not isinstance(tid, int) or act not in VALID_ACTIONS:
        return None
    return tid, act
