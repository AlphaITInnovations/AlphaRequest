"""Automations-Aktion http_request (services/http_action) – ohne Netz."""
import pytest
from pydantic import ValidationError

from backend.schemas.process_definition import (
    Action, HttpHeader, HttpMethod, HttpRequestOnError, HttpRequestSpec,
)
from backend.services import http_action as ha


class FakeResp:
    def __init__(self, status_code=200, text=""):
        self.status_code = status_code
        self.text = text


class FakeClient:
    """Ein requests-artiger Client mit aufgezeichnetem Aufruf."""
    def __init__(self, resp=None, exc=None):
        self.resp = resp if resp is not None else FakeResp(200)
        self.exc = exc
        self.calls = []

    def request(self, method, url, headers=None, data=None, timeout=None):
        self.calls.append({"method": method, "url": url, "headers": headers,
                           "data": data, "timeout": timeout})
        if self.exc:
            raise self.exc
        return self.resp


def _action(**kw):
    kw.setdefault("method", HttpMethod.post)
    kw.setdefault("url", "https://example.test/hook")
    return Action(type="http_request", http=HttpRequestSpec(**kw))


ROW = {"id": 7, "title": "Onboarding Max", "values": {"base.first_name": "Max Mustermann",
       "base.pn": "12345", "base.aktiv": True, "base.tags": ["a", "b"]}}


# ── Rendering ────────────────────────────────────────────────────────────────

def test_render_url_percent_encodes_values():
    url = ha.render_url("https://x.test/e/{{base.first_name}}?pn={{base.pn}}", ROW)
    assert url == "https://x.test/e/Max%20Mustermann?pn=12345"


def test_render_url_specials_and_missing():
    url = ha.render_url("https://x.test/{{id}}/{{fehlt}}", ROW)
    assert url == "https://x.test/7/"


def test_render_text_raw_and_types():
    body = ha.render_text('{"n":"{{base.first_name}}","a":{{base.aktiv}},"t":"{{base.tags}}"}', ROW)
    assert body == '{"n":"Max Mustermann","a":true,"t":"a,b"}'


# ── Ausführung ───────────────────────────────────────────────────────────────

def test_execute_success_sends_body_and_default_content_type():
    client = FakeClient(FakeResp(200))
    action = _action(body='{"pn":"{{base.pn}}"}')
    assert ha.execute(action, ROW, None, None, client=client) == {}
    call = client.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == "https://example.test/hook"
    assert call["data"] == b'{"pn":"12345"}'
    assert call["headers"]["Content-Type"].startswith("application/json")
    assert call["timeout"] == 10


def test_execute_get_without_body_sends_no_data():
    client = FakeClient(FakeResp(204))
    action = _action(method=HttpMethod.get, url="https://x.test/ping")
    ha.execute(action, ROW, None, None, client=client)
    assert client.calls[0]["data"] is None


def test_execute_custom_header_wins_over_content_type_default():
    client = FakeClient(FakeResp(200))
    action = _action(body="x=1", headers=[HttpHeader(name="Content-Type", value="text/plain")])
    ha.execute(action, ROW, None, None, client=client)
    assert client.calls[0]["headers"]["Content-Type"] == "text/plain"


def test_execute_header_value_templated():
    client = FakeClient(FakeResp(200))
    action = _action(headers=[HttpHeader(name="X-Ticket", value="#{{id}}")])
    ha.execute(action, ROW, None, None, client=client)
    assert client.calls[0]["headers"]["X-Ticket"] == "#7"


def test_execute_http_error_reports_and_continues():
    client = FakeClient(FakeResp(500, "boom"))
    reported = []
    action = _action()
    changes = ha.execute(action, ROW, None, None, client=client,
                         on_error=lambda *a: reported.append(a))
    assert changes == {}
    assert len(reported) == 1


def test_execute_network_error_reports_and_continues():
    import requests
    client = FakeClient(exc=requests.ConnectionError("secret-token-in-url"))
    reported = []
    action = _action()
    ha.execute(action, ROW, None, None, client=client,
               on_error=lambda row, phase, spec, exc: reported.append(exc))
    assert reported
    # Der gemeldete Fehler darf die (evtl. token-behaftete) Ausnahmenachricht NICHT tragen.
    assert "secret-token-in-url" not in str(reported[0])


def test_execute_block_raises_on_http_error():
    client = FakeClient(FakeResp(502, "down"))
    action = _action(onError=HttpRequestOnError.block)
    with pytest.raises(ha.HttpActionError):
        ha.execute(action, ROW, None, None, client=client)


def test_execute_block_raises_on_network_error():
    import requests
    client = FakeClient(exc=requests.Timeout("t"))
    action = _action(onError=HttpRequestOnError.block)
    with pytest.raises(ha.HttpActionError):
        ha.execute(action, ROW, None, None, client=client)


def test_report_uses_url_template_not_rendered(monkeypatch):
    """Der Bericht (Audit/Verlauf) führt die URL-VORLAGE, nie die gefüllte URL."""
    import backend.database.audit_log as audit
    import backend.services.process_events as events
    seen = {}
    monkeypatch.setattr(ha, "_notify_bug_mail", lambda *a, **k: None)
    monkeypatch.setattr(audit, "record_audit", lambda **kw: seen.__setitem__("audit", kw))
    monkeypatch.setattr(events, "system",
                        lambda row, ev, phase_key=None, details=None: seen.__setitem__("details", details))
    spec = HttpRequestSpec(url="https://x.test/e/{{base.pn}}")
    ha._report_failure(ROW, None, spec, ha.HttpActionError("HTTP 500: err"))
    # Vorlage bleibt stehen, der eingesetzte Wert (12345) taucht NICHT auf.
    assert seen["details"]["url"] == "https://x.test/e/{{base.pn}}"
    assert "12345" not in seen["details"]["url"]
    assert seen["audit"]["action"] == "process_http_request_failed"


# ── Schema-Validierung ───────────────────────────────────────────────────────

def test_schema_requires_http_block():
    with pytest.raises(ValidationError):
        Action(type="http_request")


def test_schema_rejects_non_http_scheme():
    with pytest.raises(ValidationError):
        _action(url="ftp://x.test/e")


def test_schema_rejects_http_block_on_other_action():
    with pytest.raises(ValidationError):
        Action(type="notify", to="responsible",
               http=HttpRequestSpec(url="https://x.test"))


def test_schema_timeout_bounds():
    with pytest.raises(ValidationError):
        _action(timeoutSeconds=0)
    with pytest.raises(ValidationError):
        _action(timeoutSeconds=61)


def test_schema_header_name_required():
    with pytest.raises(ValidationError):
        _action(headers=[HttpHeader(name="  ", value="x")])
