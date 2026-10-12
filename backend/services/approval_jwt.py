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
