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

import time
from typing import Any, Callable

import jwt
from cryptography.hazmat.primitives.serialization import load_pem_private_key

from backend.utils.config import config

MAX_TTL_SECONDS = 7 * 24 * 3600
MAX_TOKEN_LEN = 4096
_INT63 = (1 << 63) - 1

ACTIONS = ("approve", "reject")


class TokenInvalid(Exception):
    """Dauerhaft unbrauchbarer Token (Signatur/iss/aud/Form/abgelaufen)."""


_private_key_cache: Any = None


def _private_key():
    """Ed25519-Privatschlüssel aus APPROVAL_PRIVATE_KEY_PATH (einmal geladen)."""
    global _private_key_cache
    if _private_key_cache is None:
        with open(config.APPROVAL_PRIVATE_KEY_PATH, "rb") as f:
            _private_key_cache = load_pem_private_key(f.read(), password=None)
    return _private_key_cache


def public_key():
    """Der zugehörige Public Key – auch der Worker verifiziert damit (derselbe wie
    auf AlphaApprove)."""
    return _private_key().public_key()


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


def _check_shape(claims: dict) -> None:
    tid = claims.get("tid")
    if not (isinstance(tid, int) and not isinstance(tid, bool) and 1 <= tid <= _INT63):
        raise TokenInvalid("tid ungültig")
    if claims.get("act") not in ACTIONS:
        raise TokenInvalid("act ungültig")
    ph = claims.get("phase")
    if not (isinstance(ph, str) and 1 <= len(ph) <= 64):
        raise TokenInvalid("phase ungültig")
    ep = claims.get("epoch")
    if not (isinstance(ep, int) and not isinstance(ep, bool) and 0 <= ep <= _INT63):
        raise TokenInvalid("epoch ungültig")
    iat, exp = claims.get("iat"), claims.get("exp")
    if not (isinstance(iat, int) and isinstance(exp, int) and 0 < exp - iat <= MAX_TTL_SECONDS):
        raise TokenInvalid("iat/exp-Fenster ungültig")


def make_verifier(pub_key, issuer: str, audience: str, leeway: int) -> Callable[[str], dict]:
    """Verifizierer-Funktion token→claims. Prüft EdDSA-Signatur, iss, aud, exp
    (mit `leeway` Sekunden Toleranz) und die Claim-Form. Wirft TokenInvalid.

    `leeway` soll die Collector-Toleranz (30 s) PLUS die maximale Abhol-Verzögerung
    abdecken – sonst würde ein Token, das AlphaApprove noch angenommen hat, beim
    verspäteten Abholen hier fälschlich als abgelaufen gelten. received_at ist NICHT
    signiert und darf dafür NICHT verwendet werden."""
    def verify(token: str) -> dict:
        if not token or len(token) > MAX_TOKEN_LEN:
            raise TokenInvalid("leer oder zu lang")
        try:
            claims = jwt.decode(
                token, pub_key, algorithms=["EdDSA"], issuer=issuer, audience=audience,
                leeway=leeway, options={"require": ["iss", "aud", "exp", "iat"]})
        except jwt.PyJWTError as exc:
            raise TokenInvalid(str(exc))
        _check_shape(claims)
        return claims
    return verify
