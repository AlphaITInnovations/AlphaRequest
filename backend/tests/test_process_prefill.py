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


def _kst_defn(field="cost_center"):
    return ProcessDefinition.model_validate({
        "schemaVersion": 1, "key": "k", "name": "N",
        "fields": [{"key": "b.kst", "widget": "text",
                    "prefill": {"source": "employee", "field": field}}],
        "phases": [{"key": "start", "kind": "start", "responsibility": {"kind": "owner"},
                    "fields": [{"ref": "b.kst", "mode": "readonly"}]}],
    })


def test_prefill_loest_relation_auf_anzeigenamen_auf():
    """Eine Relation (Objekt) wird auf ihren Namen/Label aufgelöst statt als
    „[object Object]" zu landen; eine Liste wird verbunden."""
    d = _kst_defn("cost_center")
    obj = {"id": "a@b.de", "email": "a@b.de", "employee": {"cost_center": {"id": "7", "name": "IT, EDV"}}}
    assert apply_prefill(d, {}, obj)["b.kst"] == "IT, EDV"

    lst = {"id": "a@b.de", "email": "a@b.de", "employee": {"cost_center": [{"name": "IT"}, {"name": "EDV"}]}}
    assert apply_prefill(d, {}, lst)["b.kst"] == "IT, EDV"


def test_prefill_ueberspringt_objekt_ohne_anzeigefeld():
    d = _kst_defn("cost_center")
    obj = {"id": "a@b.de", "email": "a@b.de", "employee": {"cost_center": {"foo": "bar"}}}
    assert "b.kst" not in apply_prefill(d, {}, obj)   # kein Anzeigefeld -> nichts gesetzt


def test_prefill_source_unbekannt_wird_abgewiesen():
    with pytest.raises(ValueError):
        ProcessDefinition.model_validate({
            "schemaVersion": 1, "key": "k", "name": "N",
            "fields": [{"key": "b.x", "widget": "text",
                        "prefill": {"source": "quatsch", "field": "x"}}],
            "phases": [{"key": "start", "kind": "start", "responsibility": {"kind": "owner"},
                        "fields": [{"ref": "b.x"}]}],
        })
