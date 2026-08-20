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

from backend.schemas.process_definition import ProcessDefinition, Widget


def _is_empty(v: Any) -> bool:
    return v is None or v == "" or v == [] or v == {}


def stamp_server_fields(defn: ProcessDefinition, values: dict, stored: dict, *,
                        actor: str, now_iso: str) -> dict:
    """Setzt server_stamped-Unterfelder in collection-Einträgen serverseitig.

    NEUE Einträge (Index >= Anzahl der gespeicherten) bekommen Autor/Zeitstempel
    IMMER vom Server – ein mitgeschickter Wert wird überschrieben, Fälschung ist
    damit ausgeschlossen. BESTEHENDE Einträge behalten ihre Stempel unverändert.
    """
    out = dict(values)
    for f in defn.fields:
        if f.widget != Widget.collection or not f.item:
            continue
        stamped = [(sf.key, sf.value) for sf in f.item if sf.widget == Widget.server_stamped]
        if not stamped:
            continue
        entries = out.get(f.key)
        if not isinstance(entries, list):
            continue
        old = stored.get(f.key) if isinstance(stored.get(f.key), list) else []
        new_entries = []
        for i, entry in enumerate(entries):
            if not isinstance(entry, dict):
                new_entries.append(entry)
                continue
            if i < len(old) and isinstance(old[i], dict):
                e = dict(entry)
                for key, _spec in stamped:      # Bestand: Original-Stempel gewinnt
                    e[key] = old[i].get(key)
            else:
                e = dict(entry)
                for key, spec in stamped:       # neu: Server stempelt, immer
                    e[key] = actor if spec == "actor" else (now_iso if spec == "now" else None)
            new_entries.append(e)
        out[f.key] = new_entries
    return out


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
            # Mit `map` wird der Quellwert übersetzt (z. B. Position →
            # Fahrzeuggruppe); ohne `map` 1:1 kopiert. Fehlt der Quellwert in der
            # Map, ist das Ergebnis leer (None).
            derived = f.computed.map.get(src_val) if f.computed.map is not None else src_val
            if f.overridable:
                if _is_empty(out.get(f.key)) and not _is_empty(derived):
                    out[f.key] = derived
                    changed = True
            else:
                if out.get(f.key) != derived:
                    out[f.key] = derived
                    changed = True
        if not changed:
            break
    return out
