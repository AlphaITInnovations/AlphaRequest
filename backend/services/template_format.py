"""Format einer Dokument-Vorlage anhand der Magic-Bytes bestimmen.

Die Vorlage liegt je (process_key, phase_key, document_key) als Datei; ob es eine
Word- oder PDF-Vorlage ist, hängt NICHT an einer Definition (die könnte
auseinanderlaufen), sondern an den tatsächlichen Bytes: `%PDF-` = PDF, ein ZIP
(`PK\\x03\\x04`) = .docx. So verzweigen Marker-Extraktion, Füllung und Ausgabe
zuverlässig, egal wie zuverlässig der Upload den content_type gesetzt hat.
"""
from __future__ import annotations

PDF = "pdf"
DOCX = "docx"


def detect(data: bytes | None) -> str:
    """`"pdf"` bei `%PDF-`-Signatur, sonst `"docx"` (ZIP-basiert). Leere/kaputte
    Bytes fallen auf docx zurück – der nachgelagerte Fill/Placeholder-Scan lehnt
    inhaltlich ungültige Dateien ohnehin ab."""
    if data and data[:5] == b"%PDF-":
        return PDF
    return DOCX


def is_pdf(data: bytes | None) -> bool:
    return detect(data) == PDF
