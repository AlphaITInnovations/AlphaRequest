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

#: Ein Marker-Name: Wortzeichen (inkl. Umlaute/ß dank Unicode-`\w`) plus ._-,
#: optional Leerraum in den Klammern.
_TOKEN = re.compile(r"\{\{\s*([\w.\-]+)\s*\}\}", re.UNICODE)
#: Bedingte Abschnitte: `{{#if:NAME}} … {{/if}}`. `#`/`:`/`/` sind KEINE
#: `_TOKEN`-Zeichen → diese Steuer-Marken tauchen weder in der Zuordnungs-
#: Oberfläche auf noch werden sie versehentlich zur „Lücke". NAME entscheidet über
#: Anzeige/Ausblenden eines ganzen Absatzes (siehe `_apply_conditions`).
_IF_OPEN = re.compile(r"\{\{\s*#if:([\w.\-]+)\s*\}\}", re.UNICODE)
_IF_CLOSE = re.compile(r"\{\{\s*/if\s*\}\}")
#: Absatz-Grenzen (für das Entfernen eines ganzen Passus). `<w:p ...>` bzw.
#: `<w:p>` – NICHT `<w:pPr>`/`<w:pStyle>` (danach folgt „P", kein `>`/Leerraum).
_P_OPEN = re.compile(r"<w:p(?:\s[^>]*)?>")
_P_CLOSE = re.compile(r"</w:p>")
#: `{{ … }}` inkl. etwaiger Run-/Tag-Grenzen dazwischen – bewusst längenbegrenzt,
#: damit ein verwaistes `{{` nicht über das halbe Dokument „frisst".
_SPLIT = re.compile(r"\{\{(?:(?!\}\})[\s\S]){0,800}?\}\}")
_TAG = re.compile(r"<[^>]*>")
#: Block-Ebene: ein echter, nur über RUNS zerlegter Marker überschreitet diese
#: Grenzen nie (ein `{{` und `}}` in verschiedenen Absätzen/Zellen ist kein
#: Marker). Taucht so ein Tag im `{{…}}`-Fenster auf, stammt das schließende `}}`
#: von einem SPÄTEREN echten Marker (verwaistes `{{`) – dann NICHT ent-splitten,
#: sonst würden Struktur-Tags gelöscht und das OOXML zerstört.
_BLOCK_TAG = re.compile(r"</?w:(p|tbl|tr|tc|sdt|sdtContent|sectPr|tblGrid|gridCol|body)\b")
#: Text-tragende Teile eines .docx (auch Fuß-/Endnoten und Kommentare).
_TEXT_PART = re.compile(
    r"^word/(document|header\d*|footer\d*|footnotes|endnotes|comments)\.xml$")

#: Standard-Füllung für Marker OHNE Zuordnung – eine Lücke wie im Ausgangsvertrag.
GAP = "…………………………"

#: NUR für die Vorschau (mark=True): unsichtbare Private-Use-Marken um jeden
#: EINGESETZTEN Wert. Das Frontend ersetzt sie beim Rendern durch eine
#: Hervorhebung; im normalen Export (mark=False) tauchen sie nie auf.
MARK_OPEN = "\ue000"
MARK_CLOSE = "\ue001"


def _desplit(xml: str) -> str:
    """Tag-Grenzen INNERHALB eines `{{…}}` entfernen (über Runs zerlegte Marker
    wieder zusammenführen). Marker ohne Tags dazwischen bleiben unverändert;
    Spannen, die eine Block-Grenze überqueren, ebenfalls (verwaistes `{{`)."""
    def _merge(m: "re.Match[str]") -> str:
        span = m.group(0)
        if _BLOCK_TAG.search(span):
            return span   # überspannt eine Block-Grenze → kein echter Marker
        return _TAG.sub("", span)
    return _SPLIT.sub(_merge, xml)


#: In XML 1.0 verbotene C0-Steuerzeichen (Tab/LF/CR sind erlaubt). Ein solcher
#: Wert – etwa aus einem overrides-Feld kopiert – würde sonst roh ins document.xml
#: wandern und das .docx unöffenbar machen.
_XML_FORBIDDEN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _xml_escape(s: str) -> str:
    s = _XML_FORBIDDEN.sub("", s)
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _apply_conditions(xml: str, conditions: dict) -> str:
    """`{{#if:NAME}} … {{/if}}`-Blöcke auflösen.

    `NAME → bool` aus `conditions`: fehlt NAME oder ist er WAHR, bleibt der Text –
    nur die beiden Steuer-Marken fallen weg. Ist NAME FALSCH, wird der GESAMTE
    umschließende Absatzbereich `<w:p …>…</w:p>` entfernt (der Passus verschwindet
    inkl. seiner inneren `{{marker}}`, es bleibt keine „…"-Lücke).

    Verträge/Vorlagen OHNE `#if:` bleiben unberührt (früher Ausstieg). Blöcke sind
    NICHT verschachtelt; sie werden von links nach rechts aufgelöst. Der Aufrufer
    setzt den Marker an den Anfang des ersten und `{{/if}}` an das Ende des letzten
    Absatzes des Passus.
    """
    if "#if:" not in xml:
        return xml
    guard = 0
    while True:
        guard += 1
        if guard > 2000:            # Sicherung gegen einen pathologischen Endlos-Fall
            break
        mo = _IF_OPEN.search(xml)
        if not mo:
            break
        mc = _IF_CLOSE.search(xml, mo.end())
        if not mc:
            # Verwaistes `{{#if:…}}` ohne Abschluss: nur die Marke entfernen.
            xml = xml[:mo.start()] + xml[mo.end():]
            continue
        if bool(conditions.get(mo.group(1), True)):
            # Behalten: nur die beiden Steuer-Marken entfernen (hinten zuerst, damit
            # die vorderen Indizes gültig bleiben) – der Text bleibt.
            xml = xml[:mc.start()] + xml[mc.end():]
            xml = xml[:mo.start()] + xml[mo.end():]
            continue
        # Ausblenden: den umschließenden Absatzbereich löschen.
        opens = list(_P_OPEN.finditer(xml, 0, mo.start()))
        p_close = _P_CLOSE.search(xml, mc.end())
        if opens and p_close:
            xml = xml[:opens[-1].start()] + xml[p_close.end():]
        else:
            # Kein umschließender Absatz gefunden (untypische Platzierung) → nur den
            # Block-Text zwischen den Marken entfernen, statt Struktur zu zerstören.
            xml = xml[:mo.start()] + xml[mc.end():]
    return xml


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
              *, gap: str = GAP, mark: bool = False,
              conditions: Optional[dict] = None) -> bytes:
    """Die Vorlage füllen: `{{token}}` → values[token] (XML-escaped), fehlt der
    Token in `values`, kommt `gap` (Word-Lücke). Alle Nicht-Text-Teile werden
    unverändert übernommen.

    `conditions` (NAME→bool) steuert `{{#if:NAME}} … {{/if}}`-Passagen: ein
    falscher Abschnitt wird als ganzer Absatz entfernt, ein wahrer/fehlender behält
    den Text (ohne Steuer-Marken). Ohne `#if:` in der Vorlage ein No-Op.

    `mark=True` klammert jeden EINGESETZTEN Wert in unsichtbare Marken
    (MARK_OPEN/MARK_CLOSE) – nur für die Frontend-Vorschau (Hervorhebung), NICHT
    für den echten Export."""
    src = io.BytesIO(template_bytes)
    out = io.BytesIO()
    with zipfile.ZipFile(src) as zin, \
            zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if _TEXT_PART.match(item.filename):
                xml = _desplit(data.decode("utf-8"))
                # Bedingte Passagen VOR dem Ersetzen auflösen – ein ausgeblendeter
                # Absatz nimmt seine inneren {{marker}} mit (keine Lücke bleibt).
                xml = _apply_conditions(xml, conditions or {})

                def _repl(m: "re.Match[str]") -> str:
                    name = m.group(1)
                    if name in values:
                        val = values[name]
                        esc = _xml_escape("" if val is None else str(val))
                        return f"{MARK_OPEN}{esc}{MARK_CLOSE}" if (mark and esc) else esc
                    return _xml_escape(gap)   # ohne Zuordnung → Lücke, nie markiert

                data = _TOKEN.sub(_repl, xml).encode("utf-8")
            # ZipInfo mitgeben → Name/Modus bleiben; Nicht-Text-Teile sind inhaltlich
            # unverändert.
            zout.writestr(item, data)
    return out.getvalue()
