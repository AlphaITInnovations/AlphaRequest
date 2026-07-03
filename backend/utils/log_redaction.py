"""Reine Redaction-Logik: entfernt Secrets aus Logzeilen (ohne I-O, testbar).

Hauptzweck: der OAuth-Authorization-Code (und Tokens) sollen NIE im Klartext in
den Logs stehen – z.B. im uvicorn-Access-Log der Callback-URL
`/auth/callback?code=…&state=…`.
"""

import re

# Schlüssel, deren Werte redigiert werden (Query-Parameter und JSON-Felder).
SENSITIVE_KEYS = (
    "code", "state", "session_state",
    "id_token", "access_token", "refresh_token", "token",
    "client_secret", "secret", "password", "authorization",
)

_KEYS_RE = "|".join(SENSITIVE_KEYS)
# key=value  (Query-String, z.B. ?code=abc&state=xyz)
_QS_RE = re.compile(r"(?i)\b(" + _KEYS_RE + r")=([^&\s#]+)")
# "key": "value"  (JSON-ähnlich)
_JSON_RE = re.compile(r'(?i)(["\'](?:' + _KEYS_RE + r')["\']\s*:\s*["\'])([^"\']+)')

REDACTED = "<redacted>"


def redact_secrets(text: str) -> str:
    """Ersetzt Werte sensibler Parameter/Felder durch <redacted>."""
    if not text or not isinstance(text, str):
        return text
    text = _QS_RE.sub(r"\1=" + REDACTED, text)
    text = _JSON_RE.sub(r"\1" + REDACTED, text)
    return text
