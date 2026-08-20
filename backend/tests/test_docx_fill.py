"""Ebene-1: .docx-Platzhalter füllen (services/docx_fill) – reine Byte-Arithmetik,
kein DB-/Netz-Zugriff. Als Vorlage bauen wir eine kleine .docx über html_to_docx
(erzeugt gültiges OOXML mit den Markern als Text)."""
import io
import re
import zipfile

from backend.services.docx_fill import GAP, fill_docx, find_placeholders
from backend.services.html_to_docx import html_to_docx


def _doc_text(docx_bytes: bytes) -> str:
    """Sichtbarer Text aus word/document.xml (nur die <w:t>-Inhalte)."""
    xml = zipfile.ZipFile(io.BytesIO(docx_bytes)).read("word/document.xml").decode("utf-8")
    return "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", xml, re.DOTALL))


def _template() -> bytes:
    return html_to_docx(
        "<p>Beginn am {{arbeitsbeginn}} als {{position}} in {{ort}}. "
        "Firma {{firma}}.</p>")


def test_find_placeholders_listet_alle_marker_in_reihenfolge():
    assert find_placeholders(_template()) == ["arbeitsbeginn", "position", "ort", "firma"]


def test_fill_ersetzt_zugeordnete_und_laesst_rest_als_luecke():
    filled = fill_docx(_template(), {"arbeitsbeginn": "01.09.2026", "ort": "Nürnberg"})
    txt = _doc_text(filled)
    assert "01.09.2026" in txt and "Nürnberg" in txt      # zugeordnet → Wert
    assert GAP in txt                                       # position/firma → Lücke
    assert "{{" not in txt and "}}" not in txt             # keine rohen Marker mehr


def test_fill_escaped_sonderzeichen():
    filled = fill_docx(_template(), {"firma": "Overmann, Loh & Co. <KG>"})
    xml = zipfile.ZipFile(io.BytesIO(filled)).read("word/document.xml").decode("utf-8")
    assert "Overmann, Loh &amp; Co. &lt;KG&gt;" in xml     # XML-escaped, nicht roh


def test_nicht_text_teile_bleiben_byte_identisch():
    tpl = _template()
    filled = fill_docx(tpl, {"arbeitsbeginn": "X"})
    a = zipfile.ZipFile(io.BytesIO(tpl))
    b = zipfile.ZipFile(io.BytesIO(filled))
    # [Content_Types].xml ist kein Text-Teil → unverändert übernommen.
    assert a.read("[Content_Types].xml") == b.read("[Content_Types].xml")


def test_fill_ohne_zuordnung_macht_alles_zu_luecken():
    txt = _doc_text(fill_docx(_template(), {}))
    assert "{{" not in txt and GAP in txt


def test_desplit_fuehrt_ueber_runs_zerlegten_marker_zusammen():
    from backend.services.docx_fill import _desplit
    # Word hat den Marker mitten im Wort auf zwei Runs verteilt.
    split = ("<w:r><w:t>geb. {{geb</w:t></w:r>"
             "<w:r><w:rPr><w:b/></w:rPr><w:t>datum}} in</w:t></w:r>")
    zusammengefuehrt = _desplit(split)
    assert "{{gebdatum}}" in zusammengefuehrt
    # und der Marker ist danach normal ersetzbar
    assert re.search(r"\{\{\s*gebdatum\s*\}\}", zusammengefuehrt)


def test_verwaiste_klammern_fressen_nicht_das_ganze_dokument():
    from backend.services.docx_fill import _desplit
    # Ein einzelnes {{ ohne passendes }} in erreichbarer Nähe bleibt unangetastet.
    xml = "{{ " + ("<w:t>Text</w:t>" * 200)
    assert _desplit(xml) == xml
