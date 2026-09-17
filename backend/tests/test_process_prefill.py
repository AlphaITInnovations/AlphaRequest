"""Vorbelegung aus den Daten der angemeldeten Person (services/process_prefill)."""
import pytest

from backend.schemas.process_definition import ProcessDefinition
from backend.services.process_prefill import apply_prefill


def _defn():
    return ProcessDefinition.model_validate({
        "schemaVersion": 1, "key": "k", "name": "N",
        "fields": [
            {"key": "b.nachname", "widget": "text",
             "prefill": {"source": "employee", "field": "last_name"}},
            {"key": "b.vorname", "widget": "text",
             "prefill": {"source": "employee", "field": "first_name"}},
            {"key": "b.mail", "widget": "text",
             "prefill": {"source": "user", "field": "email"}},
            {"key": "b.nl", "widget": "text",
             "prefill": {"source": "employee", "field": "location.name"}},
            {"key": "b.frei", "widget": "text"},   # ohne prefill
        ],
        "phases": [{"key": "start", "kind": "start", "responsibility": {"kind": "owner"},
                    "fields": [{"ref": "b.nachname", "mode": "readonly"},
                               {"ref": "b.vorname", "mode": "readonly"},
                               {"ref": "b.mail", "mode": "readonly"},
                               {"ref": "b.nl", "mode": "readonly"},
                               {"ref": "b.frei"}]}],
    })


USER = {"id": "helmut.popp@x.org", "email": "helmut.popp@x.org",
        "employee": {"first_name": "Helmut", "last_name": "Popp",
                     "location": {"name": "Nürnberg"}}}


def test_prefill_fuellt_aus_employee_und_user():
    out = apply_prefill(_defn(), {"b.frei": "x"}, USER)
    assert out["b.nachname"] == "Popp"
    assert out["b.vorname"] == "Helmut"
    assert out["b.mail"] == "helmut.popp@x.org"   # source=user
    assert out["b.nl"] == "Nürnberg"              # dot-Pfad über Relation
    assert out["b.frei"] == "x"                    # unangetastet


def test_prefill_ueberschreibt_client_wert_autoritativ():
    out = apply_prefill(_defn(), {"b.nachname": "Faelschung"}, USER)
    assert out["b.nachname"] == "Popp"


def test_prefill_laesst_leere_quelle_unangetastet():
    user = {"id": "a@b.de", "email": "a@b.de", "employee": {"last_name": "Popp"}}
    out = apply_prefill(_defn(), {"b.vorname": ""}, user)
    assert out["b.nachname"] == "Popp"
    assert out.get("b.vorname") in (None, "")      # nicht mit None überschrieben
    assert out.get("b.nl") in (None, "")           # Relation fehlt -> nicht gesetzt


def test_prefill_ohne_employee_nutzt_user_quelle():
    out = apply_prefill(_defn(), {}, {"id": "a@b.de", "email": "a@b.de"})
    assert out["b.mail"] == "a@b.de"               # user-Quelle greift
    assert "b.nachname" not in out                 # employee leer -> nichts gesetzt


def test_prefill_source_unbekannt_wird_abgewiesen():
    with pytest.raises(ValueError):
        ProcessDefinition.model_validate({
            "schemaVersion": 1, "key": "k", "name": "N",
            "fields": [{"key": "b.x", "widget": "text",
                        "prefill": {"source": "quatsch", "field": "x"}}],
            "phases": [{"key": "start", "kind": "start", "responsibility": {"kind": "owner"},
                        "fields": [{"ref": "b.x"}]}],
        })
