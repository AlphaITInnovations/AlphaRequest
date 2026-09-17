"""Automations-Aktion company_email: Bildung, Transliteration, Exchange-Format,
Directus-Eindeutigkeit (services/company_email_action) – ohne Netz."""
from types import SimpleNamespace

import pytest

from backend.schemas.process_definition import ProcessDefinition
from backend.services import company_email_action as cea
from backend.services.directus_client import DirectusError


def _action():
    email = SimpleNamespace(
        targetField="mail", firstNameField="fn", lastNameField="ln", companyField="co",
        collection="mitarbeitende", emailField="email", conflictField="conflict")
    return SimpleNamespace(email=email)


COMPS = [{"name": "AlphaConsult", "domain": "alpha-consult.de"}]


def _row(values):
    return {"values": values}


def _exec(values, *, rows=(), configured=True, query=None):
    q = query or (lambda *a, **k: list(rows))
    return cea.execute(_action(), _row(values), None, None,
                       query=q, is_configured=lambda: configured, companies=COMPS)


def test_translit_und_bildung():
    out = _exec({"fn": "Jörg", "ln": "Müller", "co": "AlphaConsult"})
    assert out["values"]["mail"] == "joerg.mueller@alpha-consult.de"
    assert out["email_conflict"] is False
    assert out["values"]["conflict"] is False


def test_konflikt_wenn_existiert():
    out = _exec({"fn": "Jörg", "ln": "Müller", "co": "AlphaConsult"},
                rows=[{"email": "joerg.mueller@alpha-consult.de"}])
    assert out["email_conflict"] is True and out["email_conflict_reason"] == "exists"
    assert out["values"]["conflict"] is True


def test_manuelle_eingabe_hat_vorrang():
    out = _exec({"mail": "sonder@alpha-consult.de", "fn": "X", "ln": "Y", "co": "AlphaConsult"})
    assert out["values"]["mail"] == "sonder@alpha-consult.de"
    assert out["email_conflict"] is False


def test_ohne_domain_keine_aenderung():
    assert _exec({"fn": "A", "ln": "B", "co": "Unbekannt"}) == {}


def test_ohne_namen_keine_aenderung():
    assert _exec({"fn": "", "ln": "", "co": "AlphaConsult"}) == {}


def test_ungueltiges_format_ist_konflikt():
    out = _exec({"mail": "a b@x.de", "fn": "A", "ln": "B", "co": "AlphaConsult"})
    assert out["email_conflict"] is True and out["email_conflict_reason"] == "format"


def test_directus_ausfall_blockiert_nicht():
    def boom(*a, **k):
        raise DirectusError("down")
    out = _exec({"fn": "A", "ln": "B", "co": "AlphaConsult"}, query=boom)
    assert out["email_conflict"] is False


@pytest.mark.parametrize("email,ok", [
    ("joerg.mueller@alpha-consult.de", True),
    ("a" * 65 + "@x.de", False),          # local zu lang
    ("ohne-at-zeichen", False),
    (".fuehrend@x.de", False),            # führender Punkt
    ("doppel..punkt@x.de", False),        # Doppelpunkt
    ("mit leer@x.de", False),             # Leerzeichen
    ("ok@ohnepunkt", False),              # Domain ohne Punkt
])
def test_valid_exchange_email(email, ok):
    assert cea.valid_exchange_email(email) is ok


def test_slug_transliteriert():
    assert cea.build_local("Anna-Maria", "Groß") == "anna-maria.gross"
    assert cea.build_local("  ", "X") is None


def _defn_with_email():
    return ProcessDefinition.model_validate({
        "schemaVersion": 1, "key": "k", "name": "N",
        "fields": [{"key": "mail", "widget": "text"}, {"key": "fn", "widget": "text"},
                   {"key": "ln", "widget": "text"}, {"key": "co", "widget": "text"},
                   {"key": "conflict", "widget": "checkbox"}],
        "phases": [
            {"key": "start", "kind": "start", "responsibility": {"kind": "owner"},
             "fields": [{"ref": "fn"}]},
            {"key": "bearb", "kind": "task", "responsibility": {"kind": "owner"},
             "fields": [{"ref": "mail", "mode": "readonly", "editableWhen": {"truthy": "conflict"}}],
             "automations": [{"id": "mail", "trigger": {"type": "on_exit"},
                              "action": {"type": "company_email", "email": {
                                  "targetField": "mail", "firstNameField": "fn",
                                  "lastNameField": "ln", "companyField": "co",
                                  "collection": "mitarbeitende", "emailField": "email",
                                  "conflictField": "conflict"}}}]},
        ],
    })


def test_run_exit_blocking_blockt_und_persistiert(monkeypatch):
    from backend.services import process_engine as engine
    defn = _defn_with_email()
    phase = defn.phases[1]
    row = {"id": 1, "values": {"fn": "A", "ln": "B", "co": "AlphaConsult"}}
    monkeypatch.setattr(engine.actions, "run_action", lambda *a, **k: {
        "values": {"mail": "a.b@x.de", "conflict": True},
        "email_conflict": True, "email_conflict_reason": "exists"})
    applied = {}
    monkeypatch.setattr(engine.actions, "apply_action_changes",
                        lambda r, d, c, s: applied.update(c.get("values") or {}))
    monkeypatch.setattr(engine, "_audit_fired", lambda *a, **k: None)
    with pytest.raises(engine.EmailConflict) as ei:
        engine.run_exit_blocking(row, defn, phase)
    assert applied.get("conflict") is True          # Flag persistiert (trotz Block)
    assert ei.value.field == "mail" and ei.value.reason == "exists"


def test_run_exit_blocking_ok_kein_raise(monkeypatch):
    from backend.services import process_engine as engine
    defn = _defn_with_email()
    row = {"id": 1, "values": {"fn": "A", "ln": "B", "co": "AlphaConsult"}}
    monkeypatch.setattr(engine.actions, "run_action", lambda *a, **k: {
        "values": {"mail": "a.b@x.de", "conflict": False}, "email_conflict": False})
    monkeypatch.setattr(engine.actions, "apply_action_changes", lambda r, d, c, s: None)
    monkeypatch.setattr(engine, "_audit_fired", lambda *a, **k: None)
    engine.run_exit_blocking(row, defn, defn.phases[1])   # darf NICHT werfen
