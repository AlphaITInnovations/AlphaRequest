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


def test_fill_strippt_xml_verbotene_steuerzeichen():
    """Ein in XML 1.0 unzulässiges Steuerzeichen (z. B. aus einem Editor-Feld
    kopiert) darf die .docx nicht unöffenbar machen – es wird entfernt."""
    import xml.dom.minidom as minidom
    filled = fill_docx(_template(), {"firma": "a\x0bb\x0cc"})
    xml = zipfile.ZipFile(io.BytesIO(filled)).read("word/document.xml").decode("utf-8")
    assert "\x0b" not in xml and "\x0c" not in xml
    minidom.parseString(xml)                      # bleibt wohlgeformt
    assert "abc" in _doc_text(filled)             # Steuerzeichen raus, Text bleibt


def test_fill_mark_klammert_nur_eingesetzte_werte():
    """mark=True umschließt EINGESETZTE Werte mit Marken (Vorschau-Hervorhebung),
    Lücken bleiben unmarkiert; ohne mark gibt es keine Marken (echter Export)."""
    from backend.services.docx_fill import MARK_CLOSE, MARK_OPEN
    marked = fill_docx(_template(), {"arbeitsbeginn": "01.09.2026"}, mark=True)
    xml = zipfile.ZipFile(io.BytesIO(marked)).read("word/document.xml").decode("utf-8")
    assert f"{MARK_OPEN}01.09.2026{MARK_CLOSE}" in xml          # eingesetzt → markiert
    assert xml.count(MARK_OPEN) == 1                            # Lücken NICHT markiert

    plain = fill_docx(_template(), {"arbeitsbeginn": "01.09.2026"})
    plain_xml = zipfile.ZipFile(io.BytesIO(plain)).read("word/document.xml").decode("utf-8")
    assert MARK_OPEN not in plain_xml and MARK_CLOSE not in plain_xml


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


def test_umlaut_marker_wird_erkannt_und_gefuellt():
    """Marker-Namen mit Umlaut/ß (deutsche Verträge) müssen erkannt UND gefüllt
    werden – sonst stünde roh {{tätigkeit}} im unterschriebenen Vertrag."""
    tpl = html_to_docx("<p>Tätigkeit: {{tätigkeit}}, Straße {{straße}}.</p>")
    assert find_placeholders(tpl) == ["tätigkeit", "straße"]
    txt = _doc_text(fill_docx(tpl, {"tätigkeit": "Entwicklung", "straße": "Hauptweg 1"}))
    assert "Entwicklung" in txt and "Hauptweg 1" in txt
    assert "{{" not in txt


def test_marker_in_fussnote_wird_erkannt_und_gefuellt():
    """Text-Teile jenseits von document/header/footer (Fußnoten) müssen ebenfalls
    gefüllt werden – sonst bliebe {{marker}} roh in der Fußnote stehen."""
    ns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    buf = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(_template())) as zin, \
            zipfile.ZipFile(buf, "w") as zout:
        for it in zin.infolist():
            zout.writestr(it, zin.read(it.filename))
        zout.writestr("word/footnotes.xml",
                      f'<?xml version="1.0"?><w:footnotes {ns}><w:t>Ref {{{{fn}}}}</w:t></w:footnotes>')
    tpl = buf.getvalue()
    assert "fn" in find_placeholders(tpl)
    filled = fill_docx(tpl, {"fn": "42"})
    footnote = zipfile.ZipFile(io.BytesIO(filled)).read("word/footnotes.xml").decode("utf-8")
    assert "Ref 42" in footnote and "{{" not in footnote


def test_desplit_zerstoert_keine_struktur_bei_verwaistem_marker():
    """Ein verwaistes `{{` VOR einem echten Marker über eine Block-Grenze (Tabelle)
    darf keine Struktur-Tags löschen – sonst entstünde kaputtes OOXML, das Word
    nicht öffnet. Der echte Marker bleibt trotzdem erkennbar."""
    from backend.services.docx_fill import _desplit
    xml = ("<w:p><w:r><w:t>{{ offen</w:t></w:r></w:p>"
           "<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Gehalt {{gehalt}}</w:t></w:r></w:p>"
           "</w:tc></w:tr></w:tbl>")
    out = _desplit(xml)
    # Struktur-Tags erhalten (Fenster über Block-Grenze → NICHT ent-splittet).
    assert "<w:tbl>" in out and "<w:tc>" in out and "</w:tbl>" in out
    # Der echte Marker ist weiterhin ersetzbar.
    assert re.search(r"\{\{\s*gehalt\s*\}\}", out)
