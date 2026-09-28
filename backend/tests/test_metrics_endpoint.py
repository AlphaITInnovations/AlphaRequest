"""Absicherung des /metrics-Endpunkts: fail-closed in Produktion, Basic-Auth."""
import asyncio
import base64

from backend.metrics import metrics as m


class _Req:
    def __init__(self, headers=None):
        self.headers = headers or {}


def _basic(user: str, pwd: str) -> str:
    return "Basic " + base64.b64encode(f"{user}:{pwd}".encode()).decode()


def test_ohne_creds_in_produktion_fail_closed(monkeypatch):
    monkeypatch.setattr(m, "METRICS_USERNAME", None)
    monkeypatch.setattr(m, "METRICS_PASSWORD", None)
    monkeypatch.setattr(m.config, "APP_ENV", "production")
    assert m._check_basic_auth(_Req()) is False


def test_ohne_creds_in_entwicklung_offen(monkeypatch):
    monkeypatch.setattr(m, "METRICS_USERNAME", None)
    monkeypatch.setattr(m, "METRICS_PASSWORD", None)
    monkeypatch.setattr(m.config, "APP_ENV", "development")
    assert m._check_basic_auth(_Req()) is True


def test_mit_creds_verlangt_gueltige_basic_auth(monkeypatch):
    monkeypatch.setattr(m, "METRICS_USERNAME", "u")
    monkeypatch.setattr(m, "METRICS_PASSWORD", "geheim")
    monkeypatch.setattr(m.config, "APP_ENV", "production")
    # Ohne Header / falsches Passwort → abgelehnt.
    assert m._check_basic_auth(_Req()) is False
    assert m._check_basic_auth(_Req({"Authorization": _basic("u", "falsch")})) is False
    assert m._check_basic_auth(_Req({"Authorization": "Bearer x"})) is False
    assert m._check_basic_auth(_Req({"Authorization": "Basic !!nichtbase64"})) is False
    # Korrekte Zugangsdaten → erlaubt.
    assert m._check_basic_auth(_Req({"Authorization": _basic("u", "geheim")})) is True


def test_endpoint_liefert_401_ohne_auth_in_produktion(monkeypatch):
    monkeypatch.setattr(m, "ENABLE_METRICS", True)
    monkeypatch.setattr(m, "METRICS_USERNAME", None)
    monkeypatch.setattr(m, "METRICS_PASSWORD", None)
    monkeypatch.setattr(m.config, "APP_ENV", "production")
    resp = asyncio.run(m.metrics_endpoint(_Req()))
    assert resp.status_code == 401


def test_endpoint_404_wenn_deaktiviert(monkeypatch):
    monkeypatch.setattr(m, "ENABLE_METRICS", False)
    resp = asyncio.run(m.metrics_endpoint(_Req()))
    assert resp.status_code == 404
