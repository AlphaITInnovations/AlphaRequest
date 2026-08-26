"""Ebene-1: Mail-Vorlagen mit Ticket-Variablen ({{feld.key}}).

Deckt drei Ebenen ab: das reine Template-Modul, die Schema-Validierung der
Variablen (unbekannte Felder blockieren das Veröffentlichen) und das fertig
gerenderte Freigabe-Mail-Fragment (Werte werden escaped – Injektionsschutz).
"""
import pytest
from pydantic import ValidationError

from backend.schemas.process_definition import ProcessDefinition
from backend.services import mail_template as mt
from backend.services import process_actions as pa
from backend.utils.mail_templates import render_corporate_email


# ── reines Modul ───────────────────────────────────────────────────────────────

def test_variables_und_field_refs():
    tpl = "Hallo {{title}} / {{base.first_name}} {{ base.last_name }} #{{id}} {{base.first_name}}"
    # Ohne Dopplung, in Reihenfolge.
    assert mt.variables(tpl) == ["title", "base.first_name", "base.last_name", "id"]
    # Spezial-Variablen zählen nicht als Feld-Referenz.
    assert mt.field_refs(tpl) == ["base.first_name", "base.last_name"]


def test_format_value():
    assert mt.format_value(None) == "—"
    assert mt.format_value("") == "—"
    assert mt.format_value(True) == "Ja"
    assert mt.format_value(False) == "Nein"
    assert mt.format_value(["a", "b"]) == "a, b"
    assert mt.format_value([]) == "—"
    assert mt.format_value("Max") == "Max"
    # ISO-Datum → deutsches Format (auch in Mail/Titel/Vertrag).
    assert mt.format_value("2026-08-24") == "24.08.2026"
    # Kein roher Python-Repr für verschachtelte Strukturen (Sicherheitsnetz).
    assert mt.format_value({"a": 1}) == "—"
    assert mt.format_value([{"nr": "DL-1"}, {"nr": "DL-2"}]) == "—"


def test_de_date():
    assert mt.de_date("2026-08-24") == "24.08.2026"
    assert mt.de_date("2026-08-24T09:05") == "24.08.2026 09:05"
    assert mt.de_date("2026-08-24 09:05:00") == "24.08.2026 09:05"
    assert mt.de_date("Nürnberg") == "Nürnberg"      # kein Datum → unverändert
    assert mt.de_date("2026") == "2026"


def test_substitute_ersetzt_nur_die_vorlage_nicht_die_werte():
    # Ein Wert, der selbst wie eine Variable aussieht, wird NICHT erneut ersetzt.
    out = mt.substitute("{{a}} und {{b}}", lambda t: {"a": "{{b}}", "b": "X"}[t])
    assert out == "{{b}} und X"


# ── Schema-Validierung ───────────────────────────────────────────────────────

def _defn_with_body(body: str) -> dict:
    return {
        "schemaVersion": 1, "key": "p", "name": "P",
        "fields": [{"key": "base.name", "widget": "text"}],
        "phases": [
            {"key": "start", "kind": "start", "responsibility": {"kind": "owner"},
             "fields": [{"ref": "base.name", "required": True}]},
            {"key": "freigabe", "kind": "approval", "view": "approval",
             "responsibility": {"kind": "group", "group": "g1"},
             "approval": {"question": "OK?", "emailBody": body}},
        ],
    }


def test_bekannte_variable_validiert():
    d = ProcessDefinition.model_validate(_defn_with_body("Name: {{base.name}} (#{{id}})"))
    assert d.phases[1].approval.emailBody


def test_unbekannte_variable_blockiert():
    with pytest.raises(ValidationError, match="emailBody"):
        ProcessDefinition.model_validate(_defn_with_body("Firma: {{base.firma}}"))


def _defn_mit_feld(feld: dict, body: str) -> dict:
    d = _defn_with_body(body)
    d["fields"].append(feld)
    d["phases"][0]["fields"].append({"ref": feld["key"]})
    return d


def test_nicht_skalares_feld_blockiert():
    # Eine Wiederholgruppe (collection) darf nicht als Mail-Variable stehen.
    coll = {"key": "geraete", "widget": "collection",
            "item": [{"key": "nr", "widget": "text"}]}
    with pytest.raises(ValidationError, match="collection|einsetzen"):
        ProcessDefinition.model_validate(_defn_mit_feld(coll, "Geräte: {{geraete}}"))


def test_feldkey_kollision_mit_spezialvariable_blockiert():
    # Ein Feld namens „title" würde die Mail-Variable {{title}} still verdrängen.
    feld = {"key": "title", "widget": "text"}
    with pytest.raises(ValidationError, match="reserviert"):
        ProcessDefinition.model_validate(_defn_mit_feld(feld, "Titel: {{title}}"))


# ── gerenderte Freigabe-Mail ─────────────────────────────────────────────────

def test_freigabe_mail_setzt_werte_ein_und_escaped():
    d = ProcessDefinition.model_validate(_defn_with_body("Name: {{base.name}}\nNr: {{id}}"))
    phase = d.phases[1]
    row = {"id": 7, "title": "T", "values": {"base.name": "<b>Max</b>"}}
    _subject, body = pa._approval_message(row, phase, "T")
    assert "&lt;b&gt;Max&lt;/b&gt;" in body      # Wert escaped
    assert "<b>Max</b>" not in body              # kein roher HTML-Durchgriff
    assert "<br>" in body                        # Zeilenumbruch übernommen
    assert "Nr: 7" in body
    assert "OK?" in body                         # die Freigabe-Frage steht drin


def test_freigabe_mail_ohne_vorlage_rendert_trotzdem():
    d = ProcessDefinition.model_validate({
        "schemaVersion": 1, "key": "p", "name": "P",
        "fields": [{"key": "base.name", "widget": "text"}],
        "phases": [
            {"key": "start", "kind": "start", "responsibility": {"kind": "owner"},
             "fields": [{"ref": "base.name", "required": True}]},
            {"key": "freigabe", "kind": "approval", "view": "approval",
             "responsibility": {"kind": "group", "group": "g1"},
             "approval": {"question": "OK?"}},
        ],
    })
    _subject, body = pa._approval_message({"id": 1, "title": "T", "values": {}},
                                          d.phases[1], "T")
    assert "OK?" in body            # Frage vorhanden
    assert "{{" not in body         # keine unaufgelöste Vorlage im Text


# ── Corporate-Template ───────────────────────────────────────────────────────

def test_corporate_headline_ist_ohne_url_kein_link():
    mit = render_corporate_email(subject="s", headline="Titel", intro="hi",
                                 info_box_url="https://x/dashboard")
    ohne = render_corporate_email(subject="s", headline="Titel", intro="hi")
    assert 'href="https://x/dashboard"' in mit          # klickbare Headline
    assert "href=" not in ohne                          # reine Text-Headline
    assert "Titel" in ohne


def test_corporate_info_rows_werden_escaped():
    body = render_corporate_email(
        subject="s", headline="H", info_box_url="https://x",
        info_rows=[("Auftrag", "#7"), ("Wert", "<b>Max</b>")])
    assert "Auftrag" in body and "#7" in body
    assert "&lt;b&gt;Max&lt;/b&gt;" in body and "<b>Max</b>" not in body


def test_corporate_bindet_logo_cid_ein():
    body = render_corporate_email(subject="s", headline="H", info_box_url="https://x")
    assert "cid:alpha_logo" in body
