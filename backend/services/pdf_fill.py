"""PDF-Vorlagen mit `{{marker}}` füllen – das PDF-Gegenstück zu `docx_fill`.

Die Marker stehen in den WERTEN der AcroForm-Formularfelder (z. B. ein Textfeld
mit dem Wert `{{vorname}} {{nachname}}`), NICHT im Content-Stream – anders als
bei .docx (Zip/XML) lässt sich das nicht mit der stdlib lösen, daher `pypdf`.

Gleiche Schnittstelle/Semantik wie `docx_fill`:
  - `find_placeholders(bytes)` → Marker-Namen in Reihenfolge, ohne Dopplung.
  - `fill_pdf(bytes, values)` → `{{token}}` in den Feldwerten durch `values[token]`
    ersetzt; fehlt der Token, kommt `gap` (sichtbare Lücke). `NeedAppearances`
    sorgt dafür, dass Viewer die eingesetzten Werte anzeigen.

`mark` (Vorschau-Hervorhebung) gibt es bei .docx über Private-Use-Marken; in
PDF-Formularfeldern ist das nicht sinnvoll und wird ignoriert (Signatur bleibt
kompatibel).

Marker-Regex und GAP kommen aus `docx_fill`, damit Editor-Extraktion und Füllung
über beide Formate deckungsgleich bleiben.
"""
from __future__ import annotations

import io
from typing import Optional

from pypdf import PdfReader, PdfWriter

from backend.services.docx_fill import GAP, _TOKEN


def _substitute(text: str, values: dict[str, Optional[str]], gap: str) -> str:
    def _repl(m: "re.Match[str]") -> str:  # noqa: F821 (nur Typkommentar)
        name = m.group(1)
        if name in values:
            val = values[name]
            return "" if val is None else str(val)
        return gap
    return _TOKEN.sub(_repl, text)


def _text_fields(reader: PdfReader) -> dict:
    """Nur AcroForm-Textfelder ({/FT: /Tx}); Checkboxen/Buttons tragen keine
    {{marker}}-Werte und bleiben unangetastet."""
    fields = reader.get_fields() or {}
    return {name: f for name, f in fields.items() if f.get("/FT") == "/Tx"}


def find_placeholders(template_bytes: bytes) -> list[str]:
    """Alle Marker-Namen der Vorlage (in Reihenfolge, ohne Dopplung) – für die
    Zuordnungs-Oberfläche im Editor."""
    order: list[str] = []
    seen: set[str] = set()
    reader = PdfReader(io.BytesIO(template_bytes))
    for _name, f in _text_fields(reader).items():
        v = f.get("/V")
        if v is None:
            continue
        for m in _TOKEN.finditer(str(v)):
            tok = m.group(1)
            if tok not in seen:
                seen.add(tok)
                order.append(tok)
    return order


def fill_pdf(template_bytes: bytes, values: dict[str, Optional[str]],
             *, gap: str = GAP, mark: bool = False) -> bytes:
    """Die PDF-Vorlage füllen: `{{token}}` in den Formularfeld-Werten → values[token]
    (fehlt der Token → `gap`). Nicht betroffene Felder/Inhalte bleiben unverändert.
    `mark` wird für PDF ignoriert (siehe Modul-Docstring)."""
    reader = PdfReader(io.BytesIO(template_bytes))
    writer = PdfWriter()
    writer.append(reader)

    updates: dict[str, str] = {}
    for name, f in _text_fields(reader).items():
        v = f.get("/V")
        if v is None or "{{" not in str(v):
            continue
        updates[name] = _substitute(str(v), values, gap)

    if updates:
        for page in writer.pages:
            # Wendet je Seite nur die dort vorhandenen Felder an – unbekannte
            # Namen ignoriert pypdf. Fehler an einer Seite dürfen den Rest nicht kippen.
            try:
                writer.update_page_form_field_values(page, updates)
            except Exception:
                pass
        # Ohne NeedAppearances zeigen manche Viewer den alten (Marker-)Text.
        try:
            writer.set_need_appearances_writer(True)
        except Exception:
            pass

    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()
