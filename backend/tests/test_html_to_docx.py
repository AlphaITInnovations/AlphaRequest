"""Ebene-1: HTML → .docx ohne externe Bibliothek (stdlib-ZIP + OOXML)."""
import io
import zipfile
from xml.dom import minidom

from backend.services.html_to_docx import Run, html_to_docx, parse_html


def _docx_parts(data: bytes) -> dict[str, str]:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return {n: z.read(n).decode("utf-8") for n in z.namelist()}


def test_erzeugt_gueltiges_docx_zip_mit_pflichtteilen():
    parts = _docx_parts(html_to_docx("<p>Hallo</p>"))
    for pflicht in ("[Content_Types].xml", "_rels/.rels",
                    "word/document.xml", "word/styles.xml",
                    "word/_rels/document.xml.rels"):
        assert pflicht in parts
    # document.xml ist wohlgeformtes XML (parst ohne Fehler).
    minidom.parseString(parts["word/document.xml"])


def test_ueberschriften_und_absaetze():
    paras = parse_html("<h1>Vertrag</h1><p>Zwischen A und B.</p><h2>§1</h2>")
    assert [(p.style, p.runs[0].text) for p in paras] == [
        ("Heading1", "Vertrag"), ("Normal", "Zwischen A und B."), ("Heading2", "§1")]


def test_formatierung_fett_kursiv_unterstrichen():
    [p] = parse_html("<p><b>Max</b> ist <i>hier</i> und <u>da</u></p>")
    fett = next(r for r in p.runs if r.text.strip() == "Max")
    kursiv = next(r for r in p.runs if r.text.strip() == "hier")
    unter = next(r for r in p.runs if r.text.strip() == "da")
    assert fett.bold and kursiv.italic and unter.underline
    # Das Leerzeichen zwischen zwei formatierten Läufen bleibt erhalten.
    assert "".join(r.text for r in p.runs).strip() == "Max ist hier und da"


def test_listen_werden_zu_absaetzen():
    paras = parse_html("<ul><li>eins</li><li>zwei</li></ul><ol><li>a</li></ol>")
    assert [(p.style, p.runs[0].text) for p in paras] == [
        ("ListBullet", "eins"), ("ListBullet", "zwei"), ("ListNumber", "a")]


def test_xml_escaping_verhindert_injektion():
    doc = _docx_parts(html_to_docx("<p>A &amp; B &lt;x&gt;</p>"))["word/document.xml"]
    # Der Wert steht escaped im XML, nicht als rohes Markup.
    assert "A &amp; B &lt;x&gt;" in doc
    minidom.parseString(doc)   # trotzdem wohlgeformt


def test_leeres_html_ergibt_leeres_aber_gueltiges_dokument():
    doc = _docx_parts(html_to_docx(""))["word/document.xml"]
    minidom.parseString(doc)


def test_run_dataclass_defaults():
    r = Run(text="x")
    assert not (r.bold or r.italic or r.underline or r.br_after)
