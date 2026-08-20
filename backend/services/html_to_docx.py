"""HTML → Word (.docx) OHNE externe Bibliothek.

Ein .docx ist ein ZIP aus OOXML-XML-Teilen. Für ein Textdokument (Vertrag)
reichen Überschriften, Absätze, Fett/Kursiv/Unterstrichen, Zeilenumbrüche und
einfache Listen – die erzeugen wir hier aus einem BEGRENZTEN HTML-Subset direkt
als WordprocessingML und packen sie mit der Standardbibliothek (`zipfile`) in
ein gültiges .docx. Bewusst kein python-docx/pandoc: keine neue Abhängigkeit,
kein Offline-Install-Risiko, im Test lauffähig.

Unterstützt: h1–h3 (Überschrift-Stile), p/div (Absatz), br (Zeilenumbruch),
strong/b, em/i, u, ul/ol/li (als Aufzählungs-/Nummern-Absätze). Alles andere
wird zu reinem Text – der Inhalt geht nie verloren.
"""
from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field
from html.parser import HTMLParser
from xml.sax.saxutils import escape

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


# ── Zwischenmodell: Absätze mit formatierten Text-Läufen ─────────────────────

@dataclass
class Run:
    text: str
    bold: bool = False
    italic: bool = False
    underline: bool = False
    br_after: bool = False        # harter Zeilenumbruch NACH diesem Lauf


@dataclass
class Para:
    style: str = "Normal"         # Normal | Heading1 | Heading2 | Heading3 | ListBullet | ListNumber
    runs: list[Run] = field(default_factory=list)

    def text_len(self) -> int:
        return sum(len(r.text) for r in self.runs)


_HEADING = {"h1": "Heading1", "h2": "Heading2", "h3": "Heading3"}
_BLOCK = {"p", "div", "h1", "h2", "h3", "li"}


class _Parser(HTMLParser):
    """Sammelt aus dem HTML eine flache Absatzliste (kein DOM nötig)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.paras: list[Para] = []
        self._cur: Para | None = None
        self._bold = 0
        self._italic = 0
        self._underline = 0
        self._list: list[str] = []          # Stack: 'ul' | 'ol'

    def _ensure(self, style: str = "Normal") -> Para:
        if self._cur is None:
            self._cur = Para(style=style)
        return self._cur

    def _flush(self) -> None:
        if self._cur is not None and self._cur.text_len() > 0:
            self.paras.append(self._cur)
        self._cur = None

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in ("strong", "b"):
            self._bold += 1
        elif tag in ("em", "i"):
            self._italic += 1
        elif tag == "u":
            self._underline += 1
        elif tag == "br":
            if self._cur and self._cur.runs:
                self._cur.runs[-1].br_after = True
        elif tag in ("ul", "ol"):
            self._flush()
            self._list.append(tag)
        elif tag == "li":
            self._flush()
            style = "ListNumber" if (self._list and self._list[-1] == "ol") else "ListBullet"
            self._cur = Para(style=style)
        elif tag in _BLOCK:
            self._flush()
            self._cur = Para(style=_HEADING.get(tag, "Normal"))

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in ("strong", "b"):
            self._bold = max(0, self._bold - 1)
        elif tag in ("em", "i"):
            self._italic = max(0, self._italic - 1)
        elif tag == "u":
            self._underline = max(0, self._underline - 1)
        elif tag in ("ul", "ol"):
            if self._list:
                self._list.pop()
        elif tag in _BLOCK:
            self._flush()

    def handle_data(self, data):
        if not data:
            return
        # Whitespace glätten: HTML-Quelltext bringt viele Umbrüche/Einrückungen mit,
        # die im Dokument nichts zu suchen haben.
        text = " ".join(data.split())
        if not text:
            # Reiner Whitespace zwischen Tags – aber ein Leerzeichen zwischen zwei
            # Inline-Läufen (z. B. „<b>a</b> <b>b</b>") muss erhalten bleiben.
            if data.strip() == "" and self._cur and self._cur.runs and not self._cur.runs[-1].text.endswith(" "):
                self._cur.runs[-1].text += " "
            return
        if data[:1].isspace() and self._cur and self._cur.runs and not self._cur.runs[-1].text.endswith(" "):
            text = " " + text
        if data[-1:].isspace():
            text = text + " "
        p = self._ensure()
        p.runs.append(Run(text=text, bold=bool(self._bold),
                          italic=bool(self._italic), underline=bool(self._underline)))


def parse_html(html: str) -> list[Para]:
    p = _Parser()
    p.feed(html or "")
    p.close()
    p._flush()
    return p.paras


# ── OOXML erzeugen ───────────────────────────────────────────────────────────

def _run_xml(r: Run) -> str:
    props = []
    if r.bold:
        props.append("<w:b/>")
    if r.italic:
        props.append("<w:i/>")
    if r.underline:
        props.append('<w:u w:val="single"/>')
    rpr = f"<w:rPr>{''.join(props)}</w:rPr>" if props else ""
    # xml:space=preserve, damit führende/abschließende Leerzeichen bleiben.
    text = f'<w:t xml:space="preserve">{escape(r.text)}</w:t>'
    br = "<w:br/>" if r.br_after else ""
    return f"<w:r>{rpr}{text}{br}</w:r>"


def _para_xml(p: Para) -> str:
    ppr = f'<w:pPr><w:pStyle w:val="{p.style}"/></w:pPr>' if p.style != "Normal" else ""
    runs = "".join(_run_xml(r) for r in p.runs)
    return f"<w:p>{ppr}{runs}</w:p>"


def _document_xml(paras: list[Para]) -> str:
    body = "".join(_para_xml(p) for p in paras) or "<w:p/>"
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{W}"><w:body>{body}'
        '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
        '<w:pgMar w:top="1417" w:right="1417" w:bottom="1134" w:left="1417"/>'
        '</w:sectPr></w:body></w:document>'
    )


_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    '<Override PartName="/word/styles.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
    '</Types>'
)

_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" '
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
    'Target="word/document.xml"/></Relationships>'
)

_DOC_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" '
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
    'Target="styles.xml"/></Relationships>'
)


def _style(style_id: str, name: str, size_half_pt: int, bold: bool) -> str:
    b = "<w:b/>" if bold else ""
    return (
        f'<w:style w:type="paragraph" w:styleId="{style_id}"><w:name w:val="{name}"/>'
        f'<w:pPr><w:spacing w:before="{120 if bold else 0}" w:after="120"/></w:pPr>'
        f'<w:rPr>{b}<w:sz w:val="{size_half_pt}"/></w:rPr></w:style>'
    )


_STYLES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    f'<w:styles xmlns:w="{W}">'
    '<w:docDefaults><w:rPrDefault><w:rPr><w:sz w:val="22"/></w:rPr></w:rPrDefault></w:docDefaults>'
    + _style("Normal", "Normal", 22, False)
    + _style("Heading1", "heading 1", 32, True)
    + _style("Heading2", "heading 2", 28, True)
    + _style("Heading3", "heading 3", 24, True)
    + _style("ListBullet", "List Bullet", 22, False)
    + _style("ListNumber", "List Number", 22, False)
    + '</w:styles>'
)


def html_to_docx(html: str) -> bytes:
    """Rendert ein begrenztes HTML-Subset in ein gültiges .docx (Bytes)."""
    paras = parse_html(html)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _CONTENT_TYPES)
        z.writestr("_rels/.rels", _RELS)
        z.writestr("word/_rels/document.xml.rels", _DOC_RELS)
        z.writestr("word/styles.xml", _STYLES)
        z.writestr("word/document.xml", _document_xml(paras))
    return buf.getvalue()
