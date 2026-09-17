"""Felder beim Anlegen aus den Daten der angemeldeten Person vorbelegen (§ prefill).

Für read-only Antragsteller-Felder: der Wert kommt aus dem Directus-Mitarbeiter-
Datensatz (user["employee"]) bzw. den Session-Feldern und wird serverseitig
AUTORITATIV gesetzt (überschreibt Client-Eingaben – manipulationssicher). Wird nur
beim ANLEGEN angewandt (Momentaufnahme, wer den Antrag gestellt hat); spätere
Änderungen der Stammdaten wirken nicht rückwirkend.
"""
from typing import Any, Optional

from backend.schemas.process_definition import ProcessDefinition


def _resolve_path(obj: Any, path: str) -> Optional[Any]:
    """dot-Pfad in einem (verschachtelten) dict auflösen; Relationen wie
    „location.name". Listen werden nicht durchlaufen."""
    cur = obj
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def apply_prefill(defn: ProcessDefinition, values: dict, user: dict) -> dict:
    """Felder mit `prefill`-Spec aus den Daten der angemeldeten Person füllen.

    source "employee" → user["employee"] (Directus-Stammdaten), source "user" →
    das Session-User-Objekt. Ein leerer/fehlender Quellwert lässt das Feld
    unangetastet (kein Überschreiben mit None).
    """
    out = dict(values)
    employee = user.get("employee") or {}
    for f in defn.fields:
        pf = f.prefill
        if not pf:
            continue
        src = employee if pf.source == "employee" else user
        val = _resolve_path(src, pf.field)
        if val is not None and val != "":
            out[f.key] = val
    return out
