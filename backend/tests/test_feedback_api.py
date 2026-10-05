"""Feedback/Fehlerbericht-Endpoint (multipart) – Nachricht + optionale Anlagen.

Der Mailversand wird abgefangen; geprüft wird, dass Anlagen korrekt als
EmailAttachment durchgereicht und Größen-/Anzahl-Grenzen durchgesetzt werden."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.v1 import feedback as fb
from backend.core.dependencies import get_current_user
from backend.main import _install_error_handlers


@pytest.fixture
def client(monkeypatch):
    sent = {}
    monkeypatch.setattr(fb.config, "BUG_REPORT_MAIL", "bugs@x.de")
    monkeypatch.setattr(fb, "brand_logo_attachment", lambda: None)   # Logo im Test weglassen

    def fake_send(**kw):
        sent["attachments"] = kw.get("attachments") or []
        sent["body"] = kw.get("body")
    monkeypatch.setattr(fb, "send_mail_app_only", fake_send)

    app = FastAPI()
    _install_error_handlers(app)
    app.include_router(fb.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: {
        "displayName": "Tester", "email": "t@x.de", "id": "t@x.de"}
    c = TestClient(app)
    c._sent = sent      # type: ignore[attr-defined]
    return c


def test_message_only(client):
    r = client.post("/api/v1/feedback", data={"message": "Kaputt!", "page": "/x"})
    assert r.status_code == 200
    assert client._sent["attachments"] == []        # kein Logo (gemockt), keine Anlagen


def test_with_attachments(client):
    r = client.post("/api/v1/feedback",
                    data={"message": "Screenshot anbei", "page": "/x"},
                    files=[("files", ("a.png", b"\x89PNG....", "image/png")),
                           ("files", ("b.txt", b"hello", "text/plain"))])
    assert r.status_code == 200
    atts = client._sent["attachments"]
    assert [a.filename for a in atts] == ["a.png", "b.txt"]
    assert atts[0].content_type == "image/png"
    assert all(a.content_bytes_b64 for a in atts)


def test_empty_message_rejected(client):
    r = client.post("/api/v1/feedback", data={"message": "   "})
    assert r.status_code == 400


def test_too_many_files(client):
    files = [("files", (f"f{i}.txt", b"x", "text/plain")) for i in range(11)]
    r = client.post("/api/v1/feedback", data={"message": "viele"}, files=files)
    assert r.status_code == 400
    assert "Anlagen" in r.json()["error"]["message"]


def test_attachments_too_large(client, monkeypatch):
    monkeypatch.setattr(fb, "_ATTACH_TOTAL_B64_LIMIT", 8)   # künstlich winzig
    r = client.post("/api/v1/feedback", data={"message": "gross"},
                    files=[("files", ("big.bin", b"0123456789" * 5, "application/octet-stream"))])
    assert r.status_code == 413
