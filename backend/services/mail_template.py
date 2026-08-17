"""Mail-Text-Vorlagen mit Ticket-Variablen (`{{feld.key}}`).

Eine Freigabe-Mail soll Angaben aus dem Auftrag tragen (z. B. Name und Firma
der einzustellenden Person), damit die entscheidende Person nicht erst ins
System schauen muss. Statt den Text fest zu verdrahten, schreibt die
Prozess-Definition eine Vorlage mit Platzhaltern; hier steht die (reine, damit
testbare) Logik, sie aufzulösen.

Bewusst KEIN HTML in der Vorlage: `substitute` liefert reinen Text, den der
Aufrufer escaped (Werte kommen aus Nutzereingaben – roh eingesetzt wäre das
eine HTML-Injektion). Die Ersetzung läuft in EINEM Durchgang über die Vorlage;
ein Wert, der zufällig selbst `{{…}}` enthält, wird deshalb nicht erneut
ersetzt.
"""
from __future__ import annotations

import re
from typing import Any, Callable

#: `{{ feld.key }}` – Feld-Keys sind a-z0-9_ mit Punkten (base.first_name).
VAR_RE = re.compile(r"\{\{\s*([A-Za-z0-9_.]+)\s*\}\}")

#: Variablen, die KEIN Katalog-Feld sind, aber immer zur Verfügung stehen.
SPECIAL_VARS: tuple[str, ...] = ("title", "id")


def variables(text: str | None) -> list[str]:
    """Alle vorkommenden Variablen (ohne Dopplungen, in Reihenfolge)."""
    seen: dict[str, None] = {}
    for m in VAR_RE.finditer(text or ""):
        seen.setdefault(m.group(1), None)
    return list(seen)


def field_refs(text: str | None) -> list[str]:
    """Nur die Variablen, die ein Katalog-Feld referenzieren (ohne Spezial-Vars)."""
    return [v for v in variables(text) if v not in SPECIAL_VARS]


def format_value(value: Any) -> str:
    """Feldwert für die Mail lesbar machen.

    Leer/None → „—“ (statt einer verwirrend leeren Stelle), Wahrheitswerte →
    Ja/Nein, Listen → kommagetrennt. Alles andere als Text.
    """
    if value is None or value == "":
        return "—"
    if isinstance(value, bool):
        return "Ja" if value else "Nein"
    if isinstance(value, (list, tuple)):
        # Skalare Liste (multiselect) → kommagetrennt. Verschachtelte Strukturen
        # (z. B. Wiederholgruppen) haben in einer Mail nichts zu suchen – die
        # Vorlagen-Validierung verbietet solche Felder; hier nur als Sicherheitsnetz.
        teile = [format_value(v) for v in value if not isinstance(v, (dict, list, tuple))]
        return ", ".join(teile) if teile else "—"
    if isinstance(value, dict):
        return "—"
    return str(value)


def substitute(text: str | None, resolve: Callable[[str], str]) -> str:
    """Vorlage auflösen: jede `{{token}}` wird durch `resolve(token)` ersetzt.

    Liefert REINEN Text – Escaping ist Sache des Aufrufers (die eingesetzten
    Werte stammen aus Nutzereingaben)."""
    if not text:
        return ""
    return VAR_RE.sub(lambda m: resolve(m.group(1)), text)
