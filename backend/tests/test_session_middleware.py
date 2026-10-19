"""Session-Cookie wird nur geschrieben, wenn sich die Session geändert hat.

Starlette setzt das Cookie sonst bei JEDER Antwort neu. Antworten, die
last_activity bewusst nicht anfassen (Heartbeat, Live-Abfragen, öffentliche
Endpunkte), konnten so eine gleichzeitige echte Aktivität überschreiben – die
Session lief früher ab, obwohl gearbeitet wurde.
"""
from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient

from backend.core.session import ChangeAwareSessionMiddleware


def _client() -> TestClient:
    app = FastAPI()
    app.add_middleware(ChangeAwareSessionMiddleware, secret_key="x" * 32,
                       session_cookie="app_session", max_age=900)

    @app.get("/set/{v}")
    def set_(v: str, request: Request):
        request.session["v"] = v
        return {}

    @app.get("/noop")
    def noop(request: Request):
        _ = request.session.get("v")
        return {}

    @app.get("/other-cookie")
    def other(request: Request, response: Response):
        response.set_cookie("fremd", "1")
        return {}

    @app.get("/clear")
    def clear(request: Request):
        request.session.clear()
        return {}

    return TestClient(app)


def _session_cookies(resp):
    return [c for c in resp.headers.get_list("set-cookie") if c.startswith("app_session=")]


def test_aenderung_schreibt_das_cookie():
    c = _client()
    assert len(_session_cookies(c.get("/set/a"))) == 1
    assert len(_session_cookies(c.get("/set/b"))) == 1   # geänderter Wert


def test_unveraenderte_session_schreibt_kein_cookie():
    c = _client()
    c.get("/set/a")
    assert _session_cookies(c.get("/noop")) == []
    assert _session_cookies(c.get("/set/a")) == []       # gleicher Wert = unverändert
    # … und der Cookie bleibt gültig (Session weiter lesbar/änderbar).
    assert len(_session_cookies(c.get("/set/c"))) == 1


def test_fremde_cookies_bleiben_erhalten():
    c = _client()
    c.get("/set/a")
    r = c.get("/other-cookie")
    assert _session_cookies(r) == []
    assert any(x.startswith("fremd=") for x in r.headers.get_list("set-cookie"))


def test_geleerte_session_sendet_weiter_das_loesch_cookie():
    c = _client()
    c.get("/set/a")
    gesetzt = _session_cookies(c.get("/clear"))
    assert len(gesetzt) == 1 and "1970" in gesetzt[0]


def test_ohne_session_kein_cookie():
    assert _session_cookies(_client().get("/noop")) == []
