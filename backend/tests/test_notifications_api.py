"""API der In-App-Benachrichtigungen: jede Person sieht/ändert nur IHRE Einträge."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.v1 import notifications as api
from backend.core.dependencies import get_current_user
from backend.main import _install_error_handlers


def _client(monkeypatch, calls):
    app = FastAPI()
    _install_error_handlers(app)
    app.include_router(api.router)
    app.dependency_overrides[get_current_user] = lambda: {"id": "ich@x", "permissions": []}
    rows = [{"id": i, "user_id": "ich@x", "ticket_id": 7, "kind": "progress", "title": "T",
             "body": f"b{i}", "link": "/prozess-auftraege/7", "actor_name": None,
             "created_at": "2026-10-19T10:00:00+00:00", "read_at": None} for i in (5, 4, 3)]

    def list_for_user(uid, limit, before_id=None):
        calls.append(("list", uid, limit, before_id))
        return rows[:limit]
    monkeypatch.setattr(api.store, "list_for_user", list_for_user)
    monkeypatch.setattr(api.store, "unread_count", lambda uid: calls.append(("count", uid)) or 3)
    monkeypatch.setattr(api.store, "mark_read", lambda uid, nid: calls.append(("read", uid, nid)))
    monkeypatch.setattr(api.store, "mark_all_read", lambda uid: calls.append(("read_all", uid)))
    return TestClient(app)


def test_liste_mit_has_more_und_ungelesen(monkeypatch):
    calls = []
    r = _client(monkeypatch, calls).get("/notifications?limit=2")
    d = r.json()["data"]
    assert r.status_code == 200 and [i["id"] for i in d["items"]] == [5, 4]
    assert d["has_more"] is True and d["unread"] == 3
    assert calls[0] == ("list", "ich@x", 3, None)      # limit+1 zur has_more-Erkennung


def test_nur_eigene_eintraege_werden_gelesen_markiert(monkeypatch):
    calls = []
    c = _client(monkeypatch, calls)
    assert c.post("/notifications/99:read").status_code == 200
    assert ("read", "ich@x", 99) in calls                # user_id aus der Session, nie aus dem Request
    assert c.post("/notifications:read-all").json()["data"]["unread"] == 0
    assert ("read_all", "ich@x") in calls


def test_ungelesen_zaehler(monkeypatch):
    calls = []
    assert _client(monkeypatch, calls).get("/notifications/unread-count").json()["data"] == {"unread": 3}
