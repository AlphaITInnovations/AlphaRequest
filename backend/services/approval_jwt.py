"""EdDSA-JWT (Ed25519) für den EXTERNEN Freigabe-Weg (AlphaApprove).

Warum nicht das bestehende itsdangerous-Token? Das wird mit `SECRET_KEY` signiert,
der ZUGLEICH die Session-Cookies signiert – dieser Schlüssel darf niemals auf die
öffentliche VM. Asymmetrisch (Ed25519) hält AlphaApprove nur den Public Key: es
kann verifizieren, aber KEINE Entscheidungen fälschen. Der Private Key bleibt
ausschließlich in AlphaRequest.

Vertrag (mit AlphaApprove abgestimmt):
  alg = EdDSA; Claims {iss, aud, tid:int, act:"approve"|"reject", phase:str(1..64),
  epoch:int, iat:int, exp:int} mit 0 < exp-iat ≤ 7 Tage; Token ≤ 4096 Zeichen.
"""
from __future__ import annotations

import base64
import os
import time
from typing import Any, Callable

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key

from backend.utils.config import config
from backend.utils.logger import logger

MAX_TTL_SECONDS = 7 * 24 * 3600
MAX_TOKEN_LEN = 4096
_INT63 = (1 << 63) - 1

ACTIONS = ("approve", "reject")


class TokenInvalid(Exception):
    """Dauerhaft unbrauchbarer Token (Signatur/iss/aud/Form/abgelaufen)."""


#: settings-Schlüssel, unter dem der PEM-Privatschlüssel in der DB liegt. Klartext –
#: wie alle anderen Secrets der App (die DB ist ohnehin die Vertrauensgrenze: wer sie
#: hat, kann Freigaben auch direkt setzen). Mit SECRET_KEY hat er NICHTS zu tun.
_SIGNING_KEY_SETTING = "approval_signing_key_pem"

_private_key_cache: Any = None


def _generate_pem() -> str:
    """Neues Ed25519-Paar als unverschlüsseltes PKCS8-PEM (wie gen_approval_key.py)."""
    key = Ed25519PrivateKey.generate()
    return key.private_bytes(serialization.Encoding.PEM,
                             serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption()).decode()


def _file_mode() -> bool:
    """Datei-Modus (Override): APPROVAL_PRIVATE_KEY_PATH gesetzt UND Datei vorhanden.
    Sonst DB-Modus (Schlüssel im settings-Store, wird bei Bedarf erzeugt)."""
    path = config.APPROVAL_PRIVATE_KEY_PATH
    return bool(path) and os.path.exists(path)


def _load_from_db():
    """PEM aus dem settings-Store laden; fehlt er, EINMALIG erzeugen und ablegen."""
    from backend.database.settings import settings_get, settings_set
    pem = settings_get(_SIGNING_KEY_SETTING)
    if not pem:
        pem = _generate_pem()
        settings_set(_SIGNING_KEY_SETTING, pem)
        logger.info("Freigabe-Signierschlüssel neu erzeugt und in settings gespeichert")
    return load_pem_private_key(pem.encode(), password=None)


def _private_key():
    """Ed25519-Privatschlüssel (einmal je Prozess geladen). Vorrang: Datei-Override
    (APPROVAL_PRIVATE_KEY_PATH), sonst persistenter DB-Schlüssel."""
    global _private_key_cache
    if _private_key_cache is None:
        if _file_mode():
            with open(config.APPROVAL_PRIVATE_KEY_PATH, "rb") as f:
                _private_key_cache = load_pem_private_key(f.read(), password=None)
        else:
            _private_key_cache = _load_from_db()
    return _private_key_cache


def public_key():
    """Der zugehörige Public Key – auch der Worker verifiziert damit (derselbe wie
    auf AlphaApprove)."""
    return _private_key().public_key()


def public_key_b64() -> str:
    """Public Key als base64(Raw) – exakt der `APPROVE_PUBLIC_KEY=…`-Wert für
    AlphaApprove (zum Anzeigen/Kopieren in den Einstellungen)."""
    raw = _private_key().public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode()


def key_source() -> str:
    """„file“ (Datei-Override) oder „db“ (persistenter settings-Schlüssel)."""
    return "file" if _file_mode() else "db"


def ensure_key() -> None:
    """Beim Start aufrufen: stellt sicher, dass ein Signierschlüssel existiert (im
    DB-Modus wird er bei Bedarf erzeugt). Im Datei-Modus passiert nichts weiter."""
    _private_key()


def regenerate_key() -> str:
    """Neuen Signierschlüssel erzeugen, in der DB ablegen, Cache zurücksetzen und den
    neuen Public Key (base64) zurückgeben. Macht ALLE bereits verschickten Links
    ungültig. Nur im DB-Modus – im Datei-Modus muss die Datei getauscht werden."""
    global _private_key_cache
    if _file_mode():
        raise RuntimeError(
            "Schlüssel kommt aus APPROVAL_PRIVATE_KEY_PATH (Datei) – Rotation dort "
            "vornehmen, nicht über die DB.")
    from backend.database.settings import settings_set
    pem = _generate_pem()
    settings_set(_SIGNING_KEY_SETTING, pem)
    _private_key_cache = load_pem_private_key(pem.encode(), password=None)
    return public_key_b64()


def make_external_token(ticket_id: int, action: str, phase_key: str, epoch: int,
                        *, ttl_seconds: int) -> str:
    """Signiertes EdDSA-JWT für genau eine Entscheidung in genau einem Durchlauf."""
    if action not in ACTIONS:
        raise ValueError(f"Ungültige Aktion: {action!r}")
    ttl = max(1, min(int(ttl_seconds), MAX_TTL_SECONDS))
    now = int(time.time())
    payload = {
        "iss": config.APPROVAL_ISSUER, "aud": config.APPROVAL_AUDIENCE,
        "tid": int(ticket_id), "act": action, "phase": str(phase_key),
        "epoch": int(epoch), "iat": now, "exp": now + ttl,
    }
    token = jwt.encode(payload, _private_key(), algorithm="EdDSA")
    if len(token) > MAX_TOKEN_LEN:
        raise ValueError(f"Freigabe-Token zu lang ({len(token)} > {MAX_TOKEN_LEN})")
    return token


def _is_int(v: Any, lo: int) -> bool:
    """Echter int (kein bool) im Bereich [lo, 2^63-1]."""
    return isinstance(v, int) and not isinstance(v, bool) and lo <= v <= _INT63


def _check_shape(claims: dict) -> None:
    if not _is_int(claims.get("tid"), 1):
        raise TokenInvalid("tid ungültig")
    if claims.get("act") not in ACTIONS:
        raise TokenInvalid("act ungültig")
    ph = claims.get("phase")
    if not (isinstance(ph, str) and 1 <= len(ph) <= 64):
        raise TokenInvalid("phase ungültig")
    if not _is_int(claims.get("epoch"), 0):
        raise TokenInvalid("epoch ungültig")
    iat, exp = claims.get("iat"), claims.get("exp")
    if not (_is_int(iat, 0) and _is_int(exp, 0) and 0 < exp - iat <= MAX_TTL_SECONDS):
        raise TokenInvalid("iat/exp-Fenster ungültig")


def make_verifier(pub_key, issuer: str, audience: str, *, clock_leeway: int = 30,
                  pickup_grace: int = 0,
                  clock: Callable[[], float] = time.time) -> Callable[[str], dict]:
    """Verifizierer-Funktion token→claims. Prüft EdDSA-Signatur, iss, aud, die
    Pflicht-Claims sowie iat/nbf mit der KLEINEN Toleranz (`clock_leeway`, z. B. 30 s,
    exakt wie AlphaApprove). NUR exp wird zusätzlich um das Abholfenster
    (`pickup_grace`) verlängert – und zwar MANUELL, nicht über den PyJWT-`leeway`:
    sonst würde dieselbe Toleranz auch iat/nbf aufweiten und ein Token mit iat weit in
    der Zukunft annehmen, das AlphaApprove längst abgelehnt hätte. received_at ist
    NICHT signiert und darf dafür NICHT verwendet werden."""
    def verify(token: str) -> dict:
        if not token or len(token) > MAX_TOKEN_LEN:
            raise TokenInvalid("leer oder zu lang")
        try:
            claims = jwt.decode(
                token, pub_key, algorithms=["EdDSA"], issuer=issuer, audience=audience,
                leeway=clock_leeway,
                options={"require": ["iss", "aud", "exp", "iat"], "verify_exp": False})
        except jwt.PyJWTError as exc:
            raise TokenInvalid(str(exc))
        _check_shape(claims)
        if clock() > claims["exp"] + clock_leeway + pickup_grace:
            raise TokenInvalid("abgelaufen (auch mit Abholfenster)")
        return claims
    return verify
