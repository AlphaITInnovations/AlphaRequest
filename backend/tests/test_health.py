"""Health-/Uptime-Endpunkt (backend/api/v1/health.py)."""

import json

from backend.api.v1 import health as h


def test_health_all_ok(monkeypatch):
    monkeypatch.setattr(h, "_check_database", lambda: (True, None))
    monkeypatch.setattr(h, "_check_frontend", lambda: ("ok", "HTTP 200"))
    resp = h.health()
    assert resp.status_code == 200
    body = json.loads(resp.body)
    assert body["status"] == "ok"
    assert body["components"]["backend"]["status"] == "ok"
    assert body["components"]["database"]["status"] == "ok"
    assert body["components"]["frontend"]["status"] == "ok"
    assert "uptime_seconds" in body and "timestamp" in body


def test_health_db_down_returns_503(monkeypatch):
    monkeypatch.setattr(h, "_check_database", lambda: (False, "connection refused"))
    monkeypatch.setattr(h, "_check_frontend", lambda: ("ok", None))
    resp = h.health()
    assert resp.status_code == 503
    body = json.loads(resp.body)
    assert body["status"] == "down"
    assert body["components"]["database"]["status"] == "down"
    assert body["components"]["database"]["detail"] == "connection refused"


def test_health_frontend_down_is_degraded_but_200(monkeypatch):
    monkeypatch.setattr(h, "_check_database", lambda: (True, None))
    monkeypatch.setattr(h, "_check_frontend", lambda: ("down", "timeout"))
    resp = h.health()
    # Backend + DB ok → weiterhin 200; Frontend-Ausfall nur informativ (degraded).
    assert resp.status_code == 200
    body = json.loads(resp.body)
    assert body["status"] == "degraded"
    assert body["components"]["frontend"]["status"] == "down"
