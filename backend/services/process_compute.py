"""
Wert-Ausdrücke der DSL: abgeleitete (`computed`) Felder (§3.1 / §11 Stufe 4).

Semantik:
  - non-overridable computed → Wert wird IMMER aus der Quelle abgeleitet
    (faktisch read-only, bei jedem Speichern neu).
  - overridable computed → Ableitung nur als Default, solange das Zielfeld leer
    ist; ein gesetzter Wert (manuelle Eingabe) bleibt erhalten („manuell gewinnt").

Bewusst einfache Ableitung (Kopie von `computed.from`). Komplexere Ausdrücke
(Datumsdifferenz, externe Lookups) sind als Erweiterung vorgesehen; das Format
trägt sie bereits. Der Frontend-Spiegel (lib/conditionDsl.ts) hält dieselbe Logik.
"""
from typing import Any

from backend.schemas.process_definition import ProcessDefinition


def _is_empty(v: Any) -> bool:
    return v is None or v == "" or v == [] or v == {}


def apply_computed(defn: ProcessDefinition, values: dict) -> dict:
    """Löst computed-Felder bis zum Fixpunkt auf (deklarationsreihenfolge-unabhängig,
    auch computed-from-computed). Iterationen durch die Feldanzahl begrenzt (Zyklen
    laufen einfach aus)."""
    out = dict(values)
    computed = [f for f in defn.fields if f.computed]
    for _ in range(len(computed) + 1):
        changed = False
        for f in computed:
            src_val = out.get(f.computed.from_)
            if f.overridable:
                if _is_empty(out.get(f.key)) and not _is_empty(src_val):
                    out[f.key] = src_val
                    changed = True
            else:
                if out.get(f.key) != src_val:
                    out[f.key] = src_val
                    changed = True
        if not changed:
            break
    return out
