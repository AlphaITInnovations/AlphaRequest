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


def _rel_defn(widget, source_field, directus_source=None):
    fld = {"key": "b.x", "widget": widget, "prefill": {"source": "employee", "field": source_field}}
    if directus_source:
        fld["directusSource"] = directus_source
    return ProcessDefinition.model_validate({
        "schemaVersion": 1, "key": "k", "name": "N", "fields": [fld],
        "phases": [{"key": "start", "kind": "start", "responsibility": {"kind": "owner"},
                    "fields": [{"ref": "b.x", "mode": "editable"}]}],
    })


def test_prefill_directus_widget_nimmt_rohe_id():
    """Ein directus-Dropdown braucht die ID (nicht den Anzeigenamen), damit die
    Auswahl passt und beim Zurückschreiben die ID landet."""
    d = _rel_defn("directus", "location", "niederlassung")
    # fields=* liefert den FK skalar
    assert apply_prefill(d, {}, {"id": "a@b", "email": "a@b",
                                 "employee": {"location": "42"}})["b.x"] == "42"
    # als Objekt geliefert -> dessen id
    assert apply_prefill(d, {}, {"id": "a@b", "email": "a@b",
                                 "employee": {"location": {"id": "42", "name": "Berlin"}}})["b.x"] == "42"


def test_prefill_directus_id_wird_string():
    """Directus liefert den Fremdschlüssel evtl. als Zahl – ein directus-Feld
    braucht aber eine Text-ID (validate_values: „Text erwartet"), also normalisieren."""
    d = _rel_defn("directus", "location", "niederlassung")
    out_num = apply_prefill(d, {}, {"id": "a@b", "email": "a@b", "employee": {"location": 8080}})
    assert out_num["b.x"] == "8080" and isinstance(out_num["b.x"], str)
    out_obj = apply_prefill(d, {}, {"id": "a@b", "email": "a@b",
                                    "employee": {"location": {"id": 42, "name": "Berlin"}}})
    assert out_obj["b.x"] == "42" and isinstance(out_obj["b.x"], str)


def test_prefill_company_id_wird_zu_firmenname(monkeypatch):
    """company-Widget: Directus-Firmen-ID → System-Firmenname (Umkehr von
    company_directus_id über die je Firma hinterlegte directus_firma_id)."""
    from backend.database import settings as st
    monkeypatch.setattr(st, "get_companies_full", lambda: [
        {"name": "Alpha GmbH", "directus_firma_id": "7"},
        {"name": "Beta AG", "directus_firma_id": "9"}])
    d = _rel_defn("company", "company")
    assert apply_prefill(d, {}, {"id": "a@b", "email": "a@b",
                                 "employee": {"company": "9"}})["b.x"] == "Beta AG"
    # unbekannte id -> Feld bleibt leer (kein falscher Wert)
    assert "b.x" not in apply_prefill(d, {}, {"id": "a@b", "email": "a@b",
                                              "employee": {"company": "999"}})


def test_prefill_editierbares_feld_bleibt_erhalten():
    """Self-Service: ein EDITIERBARES prefill-Feld behält den bearbeiteten Wert;
    nur read-only wird autoritativ überschrieben. Leeres editierbares Feld wird
    trotzdem vorbelegt."""
    d = ProcessDefinition.model_validate({
        "schemaVersion": 1, "key": "k", "name": "N",
        "fields": [
            {"key": "b.vorname", "widget": "text", "prefill": {"source": "employee", "field": "first_name"}},
            {"key": "b.nachname", "widget": "text", "prefill": {"source": "employee", "field": "last_name"}},
        ],
        "phases": [{"key": "start", "kind": "start", "responsibility": {"kind": "owner"},
                    "fields": [{"ref": "b.vorname", "mode": "editable"},
                               {"ref": "b.nachname", "mode": "readonly"}]}],
    })
    user = {"id": "a@b", "email": "a@b", "employee": {"first_name": "Helmut", "last_name": "Popp"}}
    out = apply_prefill(d, {"b.vorname": "Heinz", "b.nachname": "Faelschung"}, user)
    assert out["b.vorname"] == "Heinz"    # Bearbeitung des editierbaren Felds bleibt
    assert out["b.nachname"] == "Popp"    # read-only bleibt autoritativ
    assert apply_prefill(d, {}, user)["b.vorname"] == "Helmut"   # leer -> vorbelegt


def _select_defn():
    return ProcessDefinition.model_validate({
        "schemaVersion": 1, "key": "k", "name": "N",
        "fields": [{"key": "b.anrede", "widget": "select",
                    "options": [{"value": "Herr"}, {"value": "Frau"}, {"value": "Divers"}],
                    "prefill": {"source": "employee", "field": "salutation"}}],
        "phases": [{"key": "start", "kind": "start", "responsibility": {"kind": "owner"},
                    "fields": [{"ref": "b.anrede", "mode": "editable"}]}],
    })


def test_prefill_select_trifft_option_case_insensitive():
    """Directus liefert die Anrede evtl. klein/anders geschrieben – sie wird auf den
    Options-Wert normalisiert, damit das Dropdown den Wert vorwählt."""
    d = _select_defn()
    assert apply_prefill(d, {}, {"id": "a@b", "email": "a@b",
                                 "employee": {"salutation": "herr"}})["b.anrede"] == "Herr"
    assert apply_prefill(d, {}, {"id": "a@b", "email": "a@b",
                                 "employee": {"salutation": "FRAU"}})["b.anrede"] == "Frau"


def test_prefill_select_trifft_option_ueber_label():
    d = ProcessDefinition.model_validate({
        "schemaVersion": 1, "key": "k", "name": "N",
        "fields": [{"key": "b.anrede", "widget": "select",
                    "options": [{"value": "m", "label": "Herr"}, {"value": "w", "label": "Frau"}],
                    "prefill": {"source": "employee", "field": "salutation"}}],
        "phases": [{"key": "start", "kind": "start", "responsibility": {"kind": "owner"},
                    "fields": [{"ref": "b.anrede", "mode": "editable"}]}],
    })
    # Directus liefert das Label „Herr" -> auf den Options-Wert „m" abgebildet.
    assert apply_prefill(d, {}, {"id": "a@b", "email": "a@b",
                                 "employee": {"salutation": "Herr"}})["b.anrede"] == "m"


def test_prefill_select_ohne_treffer_bleibt_leer():
    """Kein passender Options-Wert -> Feld NICHT setzen (lieber leer als ungültig)."""
    d = _select_defn()
    assert "b.anrede" not in apply_prefill(
        d, {}, {"id": "a@b", "email": "a@b", "employee": {"salutation": "keine-ahnung"}})


def test_prefill_text_widget_zahl_wird_string():
    """Directus liefert die id/PLZ/Personalnummer evtl. als Zahl – in einem
    Text-Feld wird daraus ein String, sonst verwirft der Client-Check „Text
    erwartet" das Formular (bei einem versteckten Feld sogar unsichtbar)."""
    d = ProcessDefinition.model_validate({
        "schemaVersion": 1, "key": "k", "name": "N",
        "fields": [
            {"key": "b.id", "widget": "text", "prefill": {"source": "employee", "field": "id"}},
            {"key": "b.plz", "widget": "text", "prefill": {"source": "employee", "field": "zip"}},
        ],
        "phases": [{"key": "start", "kind": "start", "responsibility": {"kind": "owner"},
                    "fields": [{"ref": "b.id", "mode": "hidden"},
                               {"ref": "b.plz", "mode": "editable"}]}],
    })
    out = apply_prefill(d, {}, {"id": "a@b", "email": "a@b",
                               "employee": {"id": 42, "zip": 90402}})
    assert out["b.id"] == "42" and isinstance(out["b.id"], str)
    assert out["b.plz"] == "90402" and isinstance(out["b.plz"], str)


def test_prefill_source_unbekannt_wird_abgewiesen():
    with pytest.raises(ValueError):
        ProcessDefinition.model_validate({
            "schemaVersion": 1, "key": "k", "name": "N",
            "fields": [{"key": "b.x", "widget": "text",
                        "prefill": {"source": "quatsch", "field": "x"}}],
            "phases": [{"key": "start", "kind": "start", "responsibility": {"kind": "owner"},
                        "fields": [{"ref": "b.x"}]}],
        })
