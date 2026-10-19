"""Login/Logout dürfen den (einzigen) Server-Prozess nicht blockieren.

Das Backend läuft als EIN uvicorn-Prozess. Blockierende Aufrufe (MSAL-Token-
Tausch, DB, Directus mit 15-s-Timeout, Audit) direkt in einer `async def`
legten während jedes Logins die App für alle anderen Nutzer still.
"""
import asyncio
import inspect
from types import SimpleNamespace

from backend.api.v1 import auth


def _on_event_loop() -> bool:
    try:
        asyncio.get_running_loop()
        return True
    except RuntimeError:
        return False


def test_start_auth_und_logout_laufen_im_threadpool():
    # Sync-Endpunkte führt FastAPI automatisch im Thread-Pool aus.
    assert not inspect.iscoroutinefunction(auth.start_auth)
    assert not inspect.iscoroutinefunction(auth.logout)


def test_callback_fuehrt_blockierendes_ausserhalb_des_event_loops_aus(monkeypatch):
    seen = {}

    def fake_token(request):
        seen["token_auf_loop"] = _on_event_loop()
        return {"access_token": "t", "id_token_claims": {}}

    async def fake_profile(token):
        seen["graph_auf_loop"] = _on_event_loop()   # bleibt async auf dem Loop
        return {}

    def fake_complete(request, result, infos):
        seen["abschluss_auf_loop"] = _on_event_loop()
        return "OK"

    monkeypatch.setattr(auth, "acquire_token_by_auth_code", fake_token)
    monkeypatch.setattr(auth, "get_user_profile", fake_profile)
    monkeypatch.setattr(auth, "_complete_login", fake_complete)
    out = asyncio.run(auth.auth_callback(SimpleNamespace(session={"auth_flow": {"x": 1}})))
    assert out == "OK"
    assert seen == {"token_auf_loop": False, "graph_auf_loop": True, "abschluss_auf_loop": False}


def test_callback_fehler_wird_im_threadpool_auditiert(monkeypatch):
    seen = {}

    def boom(request):
        raise RuntimeError("MSAL kaputt")

    def fake_failed(request):
        seen["fehler_auf_loop"] = _on_event_loop()
        return "FAILED"

    monkeypatch.setattr(auth, "acquire_token_by_auth_code", boom)
    monkeypatch.setattr(auth, "_login_failed", fake_failed)
    out = asyncio.run(auth.auth_callback(SimpleNamespace(session={"auth_flow": {"x": 1}})))
    assert out == "FAILED" and seen == {"fehler_auf_loop": False}
