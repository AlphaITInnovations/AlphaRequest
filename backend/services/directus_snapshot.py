"""Server-seitiger Auto-Fill (Snapshot) für directus-Felder.

Wenn ein `directus`-Feld beim Speichern einen NEUEN Wert trägt, holt der Server
den zugehörigen Datensatz autoritativ aus Directus (anhand des Wert-Felds) und
schreibt die gemappten Zielfelder – unabhängig davon, ob diese in der Phase
bearbeitbar sind. Damit dürfen Zielfelder read-only/manipulationssicher sein.

„Snapshot beim Auswählen": neu abgeholt wird NUR, wenn sich der Feldwert
gegenüber dem gespeicherten Stand geändert hat (bzw. beim Anlegen). Bleibt der
Wert gleich, bleiben die Zielfelder eingefroren. Wird das Feld geleert, werden
die Ziele geleert.

Best-effort: ist Directus beim Speichern nicht erreichbar, bleiben die Zielfelder
unverändert (Log-Warnung) – ein Stammdaten-Ausfall darf das Speichern nicht kippen.
Directus-Zugriff ist injizierbar (Testbarkeit).
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from backend.database import directus_sources as sources_db
from backend.schemas.process_definition import ProcessDefinition, Widget
from backend.services import directus_client as dc
from backend.utils.logger import logger


def _coerce(value: Any, widget: Optional[Widget]) -> Any:
    """Directus-Wert an das Ziel-Widget anpassen: Zahl-Felder → Zahl, sonst String
    (wie der Options-Wert). Nicht-Skalare → None."""
    if value is None:
        return None
    if isinstance(value, bool):
        value = "Ja" if value else "Nein"
    if isinstance(value, (list, dict)):
        return None
    if widget == Widget.number:
        try:
            f = float(value)
            return int(f) if f.is_integer() else f
        except (TypeError, ValueError):
            return None
    return str(value)


def apply_snapshots(defn: ProcessDefinition, values: dict, stored: Optional[dict], *,
                    get_source: Callable[[str], Optional[dict]] = sources_db.get,
                    query: Callable[..., list] = dc.query_items) -> dict:
    """Gibt `values` mit aktualisierten Auto-Fill-Zielen zurück (neue Kopie)."""
    fields = [f for f in defn.fields if f.widget == Widget.directus and f.directusFieldMap]
    if not fields:
        return values
    stored = stored or {}
    widget_by_key = {f.key: f.widget for f in defn.fields}
    out = dict(values)

    for f in fields:
        cur = out.get(f.key)
        if cur == stored.get(f.key):
            continue                                    # unverändert → Snapshot bleibt eingefroren
        if cur in (None, ""):
            for b in f.directusFieldMap:                # geleert → Ziele leeren
                out[b.target] = None
            continue

        src = get_source(f.directusSource or "")
        if not src:
            logger.warning("Directus-Snapshot: Quelle „%s“ (Feld %s) nicht gefunden",
                           f.directusSource, f.key)
            continue

        base = sources_db.query_fields(src)
        want = base + [b.source for b in f.directusFieldMap if b.source not in base]
        eq = {src["valueField"]: {"_eq": cur}}
        flt = {"_and": [src["filter"], eq]} if src.get("filter") else eq
        try:
            recs = query(src["collection"], fields=want, filter=flt, limit=1)
        except dc.DirectusError as exc:
            logger.warning("Directus-Snapshot für %s=%r fehlgeschlagen: %s", f.key, cur, exc)
            continue

        rec = recs[0] if recs else None
        for b in f.directusFieldMap:
            val = sources_db.resolve_path(rec, b.source) if rec else None
            out[b.target] = _coerce(val, widget_by_key.get(b.target))
    return out
