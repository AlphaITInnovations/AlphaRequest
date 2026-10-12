"""Ebene-1: EdDSA-JWT für den externen Freigabe-Weg (mint + verify + Abweisungen)."""
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from backend.services import approval_jwt as aj

ISS, AUD = "alpharequest-prod", "alphaapprove-prod"


@pytest.fixture
def key(monkeypatch):
    k = Ed25519PrivateKey.generate()
    monkeypatch.setattr(aj, "_private_key_cache", k)
    monkeypatch.setattr(aj.config, "APPROVAL_ISSUER", ISS)
    monkeypatch.setattr(aj.config, "APPROVAL_AUDIENCE", AUD)
    return k


def _verify(k, *, clock_leeway=30, pickup_grace=0, clock=None):
    kw = {"clock_leeway": clock_leeway, "pickup_grace": pickup_grace}
    if clock is not None:
        kw["clock"] = clock
    return aj.make_verifier(k.public_key(), ISS, AUD, **kw)


def _raw(k, **claims):
    """JWT mit beliebigen Claims direkt signieren (für Form-/Fenster-Tests)."""
    now = int(time.time())
    payload = {"iss": ISS, "aud": AUD, "tid": 7, "act": "approve", "phase": "freigabe",
               "epoch": 0, "iat": now, "exp": now + 3600}
    payload.update(claims)
    return jwt.encode(payload, k, algorithm="EdDSA")


def test_roundtrip(key):
    t = aj.make_external_token(7, "approve", "freigabe", 3, ttl_seconds=3600)
    c = _verify(key)(t)
    assert (c["iss"], c["aud"], c["tid"], c["act"], c["phase"], c["epoch"]) == \
        (ISS, AUD, 7, "approve", "freigabe", 3)
    assert 0 < c["exp"] - c["iat"] <= aj.MAX_TTL_SECONDS


def test_ttl_wird_auf_sieben_tage_gedeckelt(key):
    t = aj.make_external_token(7, "approve", "freigabe", 0, ttl_seconds=30 * 24 * 3600)
    c = _verify(key)(t)
    assert c["exp"] - c["iat"] == aj.MAX_TTL_SECONDS


def test_unbekannte_aktion_wird_beim_mint_abgelehnt(key):
    with pytest.raises(ValueError):
        aj.make_external_token(7, "vielleicht", "freigabe", 0, ttl_seconds=3600)


def test_manipuliertes_token(key):
    t = aj.make_external_token(7, "approve", "freigabe", 0, ttl_seconds=3600)
    kaputt = t[:-3] + ("AAA" if t[-3:] != "AAA" else "BBB")
    with pytest.raises(aj.TokenInvalid):
        _verify(key)(kaputt)


def test_fremder_schluessel_wird_abgelehnt(key):
    t = aj.make_external_token(7, "approve", "freigabe", 0, ttl_seconds=3600)
    fremd = Ed25519PrivateKey.generate().public_key()
    with pytest.raises(aj.TokenInvalid):
        aj.make_verifier(fremd, ISS, AUD)(t)


def test_falscher_issuer_oder_audience(key):
    t = aj.make_external_token(7, "approve", "freigabe", 0, ttl_seconds=3600)
    with pytest.raises(aj.TokenInvalid):
        aj.make_verifier(key.public_key(), "boeser-iss", AUD)(t)
    with pytest.raises(aj.TokenInvalid):
        aj.make_verifier(key.public_key(), ISS, "boese-aud")(t)


def test_abgelaufen_jenseits_der_toleranz(key):
    now = int(time.time())
    t = _raw(key, iat=now - 4000, exp=now - 100)
    with pytest.raises(aj.TokenInvalid):
        _verify(key, clock_leeway=0)(t)
    # Innerhalb des Abholfensters (pickup_grace) noch gültig.
    assert _verify(key, pickup_grace=200)(t)["tid"] == 7


def test_form_tid_bool_oder_string(key):
    with pytest.raises(aj.TokenInvalid):
        _verify(key)(_raw(key, tid=True))          # Bool ist kein gültiges tid
    with pytest.raises(aj.TokenInvalid):
        _verify(key)(_raw(key, tid="7"))           # String ist kein gültiges tid
    with pytest.raises(aj.TokenInvalid):
        _verify(key)(_raw(key, tid=0))             # < 1


def test_form_act_phase_epoch(key):
    with pytest.raises(aj.TokenInvalid):
        _verify(key)(_raw(key, act="genehmigen"))
    with pytest.raises(aj.TokenInvalid):
        _verify(key)(_raw(key, phase="x" * 65))    # > 64 Zeichen
    with pytest.raises(aj.TokenInvalid):
        _verify(key)(_raw(key, phase=""))
    with pytest.raises(aj.TokenInvalid):
        _verify(key)(_raw(key, epoch=True))        # Bool ist kein gültiger epoch


def test_fehlende_pflicht_claims(key):
    # jwt.decode(require=[iss,aud,exp,iat]) → fehlt eines, ist das Token ungültig.
    now = int(time.time())
    ohne_iss = jwt.encode({"aud": AUD, "tid": 7, "act": "approve", "phase": "p",
                           "epoch": 0, "iat": now, "exp": now + 10}, key, algorithm="EdDSA")
    with pytest.raises(aj.TokenInvalid):
        _verify(key)(ohne_iss)


def test_zu_grosses_ttl_fenster(key):
    now = int(time.time())
    t = _raw(key, iat=now, exp=now + aj.MAX_TTL_SECONDS + 100)
    with pytest.raises(aj.TokenInvalid):
        _verify(key, clock_leeway=0)(t)


# ── B1: Abholfenster verlängert NUR exp, nicht iat/nbf ────────────────────────

def test_iat_weit_in_der_zukunft_wird_trotz_abholfenster_abgelehnt(key):
    """pickup_grace darf nur exp dehnen. Ein iat 30 min in der Zukunft (das
    AlphaApprove mit 30 s Toleranz ablehnt) muss auch hier scheitern – sonst würde
    das große Abholfenster via PyJWT-leeway auch iat aufweiten."""
    now = int(time.time())
    t = _raw(key, iat=now + 1800, exp=now + 1800 + 3600)
    with pytest.raises(aj.TokenInvalid):
        _verify(key, pickup_grace=3600)(t)


def test_nbf_in_der_zukunft_wird_trotz_abholfenster_abgelehnt(key):
    now = int(time.time())
    t = _raw(key, nbf=now + 1800)
    with pytest.raises(aj.TokenInvalid):
        _verify(key, pickup_grace=3600)(t)


def test_exp_knapp_abgelaufen_innerhalb_abholfenster_gueltig(key):
    now = int(time.time())
    t = _raw(key, iat=now - 700, exp=now - 600)          # vor 10 min abgelaufen
    assert _verify(key, pickup_grace=3600)(t)["tid"] == 7


def test_exp_lange_abgelaufen_jenseits_abholfenster_ungueltig(key):
    now = int(time.time())
    t = _raw(key, iat=now - 7300, exp=now - 7200)        # vor 2 h abgelaufen
    with pytest.raises(aj.TokenInvalid):
        _verify(key, pickup_grace=3600)(t)


def test_form_iat_bool_oder_negativ(key):
    with pytest.raises(aj.TokenInvalid):
        _verify(key)(_raw(key, iat=True))               # Bool ist kein gültiges iat
    with pytest.raises(aj.TokenInvalid):
        _verify(key)(_raw(key, iat=-1))                 # negativ
