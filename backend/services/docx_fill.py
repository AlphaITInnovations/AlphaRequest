"""Platzhalter in einer ECHTEN .docx füllen – ohne externe Bibliothek.

Die Vorlage bleibt die Original-.docx (Recht, Nummerierung, Tabellen, Layout).
Es werden AUSSCHLIESSLICH `{{marker}}`-Tokens ersetzt; alles andere im Dokument
bleibt unverändert – Text ohne Klammern (inkl. „………"-Lücken zum Ausfüllen in
Word), Formatierung und alle übrigen ZIP-Teile (Styles, Nummerierung, Kopf-/
Fußzeilen-Struktur, Bilder) bleiben byte-identisch.

Vorgehen (stdlib, string-basiert auf dem OOXML, damit nichts umserialisiert und
dabei versehentlich verändert wird):
  1. „Ent-Splitten": Word kann einen frisch getippten `{{marker}}` intern über
     mehrere Runs zerlegen (`{{arb</w:t>…<w:t>eitsbeginn}}`). Innerhalb eines
     `{{…}}` werden solche Tag-Grenzen entfernt, sodass der Marker wieder in EINEM
     Textknoten steht. Gebunden auf ein kurzes Fenster → ein einzelnes `{{` ohne
     passendes `}}` bleibt unangetastet.
  2. Ersetzen: `{{token}}` → zugeordneter Wert (XML-escaped), nicht zugeordnete
     Marker → `GAP` („………", als Word-Lücke).

Betroffen sind nur die Text-Teile (word/document.xml, header*/footer*.xml); alle
anderen ZIP-Einträge werden 1:1 übernommen.
"""
from __future__ import annotations

import io
import re
import zipfile
from typing import Optional

#: Ein Marker-Name: Buchstaben/Ziffern/._- , optional Leerraum in den Klammern.
_TOKEN = re.compile(r"\{\{\s*([A-Za-z0-9_.\-]+)\s*\}\}")
#: `{{ … }}` inkl. etwaiger Run-/Tag-Grenzen dazwischen – bewusst längenbegrenzt,
#: damit ein verwaistes `{{` nicht über das halbe Dokument „frisst".
_SPLIT = re.compile(r"\{\{(?:(?!\}\})[\s\S]){0,800}?\}\}")
_TAG = re.compile(r"<[^>]*>")
#: Text-tragende Teile eines .docx.
_TEXT_PART = re.compile(r"^word/(document|header\d*|footer\d*)\.xml$")

#: Standard-Füllung für Marker OHNE Zuordnung – eine Lücke wie im Ausgangsvertrag.
GAP = "…………………………"


def _desplit(xml: str) -> str:
    """Tag-Grenzen INNERHALB eines `{{…}}` entfernen (über Runs zerlegte Marker
    wieder zusammenführen). Marker ohne Tags dazwischen bleiben unverändert."""
    return _SPLIT.sub(lambda m: _TAG.sub("", m.group(0)), xml)


def _xml_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def find_placeholders(template_bytes: bytes) -> list[str]:
    """Alle Marker-Namen der Vorlage (in Reihenfolge, ohne Dopplungen) – für die
    Zuordnungs-Oberfläche im Editor."""
    order: list[str] = []
    seen: set[str] = set()
    with zipfile.ZipFile(io.BytesIO(template_bytes)) as zin:
        for name in zin.namelist():
            if not _TEXT_PART.match(name):
                continue
            xml = _desplit(zin.read(name).decode("utf-8"))
            for m in _TOKEN.finditer(xml):
                tok = m.group(1)
                if tok not in seen:
                    seen.add(tok)
                    order.append(tok)
    return order


def fill_docx(template_bytes: bytes, values: dict[str, Optional[str]],
              *, gap: str = GAP) -> bytes:
    """Die Vorlage füllen: `{{token}}` → values[token] (XML-escaped), fehlt der
    Token in `values`, kommt `gap` (Word-Lücke). Alle Nicht-Text-Teile werden
    unverändert übernommen."""
    src = io.BytesIO(template_bytes)
    out = io.BytesIO()
    with zipfile.ZipFile(src) as zin, \
            zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if _TEXT_PART.match(item.filename):
                xml = _desplit(data.decode("utf-8"))

                def _repl(m: "re.Match[str]") -> str:
                    val = values.get(m.group(1), gap)
                    return _xml_escape("" if val is None else str(val))

                data = _TOKEN.sub(_repl, xml).encode("utf-8")
            # ZipInfo mitgeben → Name/Modus bleiben; Nicht-Text-Teile sind inhaltlich
            # unverändert.
            zout.writestr(item, data)
    return out.getvalue()
