"""Audit-Logging beim Mailversand (microsoft_mail._audit_mail)."""

from backend.services import microsoft_mail as mm
from backend.database import audit_log


def _capture(monkeypatch) -> dict:
    captured: dict = {}
    monkeypatch.setattr(audit_log, "record_audit", lambda **kw: captured.update(kw))
    return captured


def test_audit_mail_records_recipients_kind_and_subject(monkeypatch):
    captured = _capture(monkeypatch)
    payload = {"message": {
        "subject": "Neuer Antrag #5",
        "toRecipients": [{"emailAddress": {"address": "a@x.de"}},
                         {"emailAddress": {"address": "c@x.de"}}],
        "ccRecipients": [{"emailAddress": {"address": "b@x.de"}}],
    }}
    mm._audit_mail(payload, "newrequest", "sent")

    assert captured["action"] == "mail_sent"
    assert captured["actor_type"] == "system"
    assert captured["entity_type"] == "mail"
    assert captured["entity_id"] == "newrequest"
    d = captured["details"]
    assert d["kind"] == "newrequest"
    assert d["to"] == ["a@x.de", "c@x.de"]
    assert d["cc"] == ["b@x.de"]
    assert d["subject"] == "Neuer Antrag #5"
    assert "a@x.de" in captured["summary"]


def test_audit_mail_failed(monkeypatch):
    captured = _capture(monkeypatch)
    mm._audit_mail({"message": {"subject": "x", "toRecipients": []}}, "freigabe", "failed", "HTTP 500")
    assert captured["action"] == "mail_failed"
    assert captured["details"]["error"] == "HTTP 500"
    assert captured["details"]["outcome"] == "failed"


def test_audit_mail_never_raises_on_bad_payload(monkeypatch):
    _capture(monkeypatch)
    # Defekter Payload darf keine Exception werfen (Versand nie stören).
    mm._audit_mail(None, "test", "sent")
    mm._audit_mail({}, "test", "sent")
