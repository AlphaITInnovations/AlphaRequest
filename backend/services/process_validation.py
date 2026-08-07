"""
Server-seitige Validierung von Ticket-Eingaben gegen eine ProcessDefinition (§9).

Zwei getrennte Pässe:
  1. validate_values()  – bei POST/PATCH, über die GESENDETEN Felder: existiert
     das Feld im Katalog (sonst 422), passt der Typ zum Widget, halten Options
     und Constraints? Blockiert NICHT das Speichern eines halbfertigen Entwurfs.
  2. validate_phase_completion() – bei :advance: für die Felder der aktuellen
     Phase required + requiredWhen (DSL) + Phase-Constraints.

Beide geben eine Liste von Feld-Fehlern als dicts zurück
({path, code, message}) – direkt für api_error(..., fields=[...]) nutzbar.
"""
from typing import Any

from backend.schemas.process_definition import (
    ProcessDefinition, PhaseDef, FieldDef, FieldMode, Widget,
)
from backend.services.condition_dsl import evaluate


def _field_map(defn: ProcessDefinition) -> dict[str, FieldDef]:
    return {f.key: f for f in defn.fields}


def _is_empty(v: Any) -> bool:
    return v is None or v == "" or v == [] or v == {}


def _err(path: str, code: str, message: str) -> dict:
    return {"path": path, "code": code, "message": message}


# ── Pass 1: Wert-Form ─────────────────────────────────────────────────────────

_SCALAR_TEXT = {Widget.text, Widget.textarea, Widget.date, Widget.select,
                Widget.user, Widget.company, Widget.group, Widget.server_generated}
_LIST_WIDGETS = {Widget.multiselect, Widget.checkbox_group, Widget.collection}


def validate_values(defn: ProcessDefinition, submitted: dict) -> list[dict]:
    errors: list[dict] = []
    fmap = _field_map(defn)
    for key, val in submitted.items():
        f = fmap.get(key)
        if f is None:
            errors.append(_err(key, "UNKNOWN_FIELD", f"Unbekanntes Feld „{key}“"))
            continue
        if val is None:
            continue  # explizites Leeren ist erlaubt (Pflicht greift erst in Pass 2)
        errors.extend(_check_field(f, val))
    return errors


def _check_field(f: FieldDef, val: Any) -> list[dict]:
    e: list[dict] = []
    w = f.widget
    if w == Widget.number:
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            return [_err(f.key, "TYPE", "Zahl erwartet")]
    elif w == Widget.checkbox:
        if not isinstance(val, bool):
            return [_err(f.key, "TYPE", "Ja/Nein (bool) erwartet")]
    elif w == Widget.collection:
        if not isinstance(val, list):
            return [_err(f.key, "TYPE", "Liste erwartet")]
        return _check_collection(f, val)
    elif w in _LIST_WIDGETS:
        if not isinstance(val, list):
            return [_err(f.key, "TYPE", "Liste erwartet")]
    elif w in _SCALAR_TEXT:
        if not isinstance(val, str):
            return [_err(f.key, "TYPE", "Text erwartet")]
    # Optionen (statische select/multiselect)
    if f.options and w in (Widget.select, Widget.multiselect, Widget.checkbox_group):
        allowed = {o.value for o in f.options}
        picked = val if isinstance(val, list) else [val]
        bad = [p for p in picked if p not in allowed]
        if bad and not f.allowOther:
            e.append(_err(f.key, "OPTION", f"Ungültige Auswahl: {', '.join(map(str, bad))}"))
    # Constraints
    if f.constraints:
        e.extend(_check_constraints(f, val))
    return e


_SUB_SCALAR_TEXT = {Widget.text, Widget.textarea, Widget.date, Widget.select}


def _check_collection(f: FieldDef, val: list) -> list[dict]:
    """Validiert collection-Einträge gegen die deklarierten Sub-Felder. server_stamped
    ist serverseitig gesetzt und wird nicht vom Client geprüft."""
    e: list[dict] = []
    submap = {sf.key: sf for sf in f.item}
    for idx, entry in enumerate(val):
        if not isinstance(entry, dict):
            e.append(_err(f"{f.key}[{idx}]", "TYPE", "Objekt erwartet"))
            continue
        for k, v in entry.items():
            sf = submap.get(k)
            if sf is None:
                e.append(_err(f"{f.key}[{idx}].{k}", "UNKNOWN_FIELD", f"Unbekanntes Unterfeld „{k}“"))
                continue
            if sf.widget == Widget.server_stamped or v is None:
                continue
            if sf.widget == Widget.number:
                if isinstance(v, bool) or not isinstance(v, (int, float)):
                    e.append(_err(f"{f.key}[{idx}].{k}", "TYPE", "Zahl erwartet"))
            elif sf.widget == Widget.checkbox:
                if not isinstance(v, bool):
                    e.append(_err(f"{f.key}[{idx}].{k}", "TYPE", "Ja/Nein erwartet"))
            elif sf.widget in _SUB_SCALAR_TEXT:
                if not isinstance(v, str):
                    e.append(_err(f"{f.key}[{idx}].{k}", "TYPE", "Text erwartet"))
    return e


def _check_constraints(f: FieldDef, val: Any) -> list[dict]:
    import re
    c = f.constraints
    e: list[dict] = []
    if isinstance(val, str):
        if c.minLength is not None and len(val) < c.minLength:
            e.append(_err(f.key, "MIN_LENGTH", f"mindestens {c.minLength} Zeichen"))
        if c.maxLength is not None and len(val) > c.maxLength:
            e.append(_err(f.key, "MAX_LENGTH", f"höchstens {c.maxLength} Zeichen"))
        if c.pattern is not None:
            try:
                if not re.fullmatch(c.pattern, val):
                    e.append(_err(f.key, "PATTERN", "Format ungültig"))
            except re.error:
                pass  # ungültiges Pattern wurde bei der Definition schon geprüft
        if c.minDate is not None and val < c.minDate:
            e.append(_err(f.key, "MIN_DATE", f"nicht vor {c.minDate}"))
        if c.maxDate is not None and val > c.maxDate:
            e.append(_err(f.key, "MAX_DATE", f"nicht nach {c.maxDate}"))
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        if c.min is not None and val < c.min:
            e.append(_err(f.key, "MIN", f"mindestens {c.min}"))
        if c.max is not None and val > c.max:
            e.append(_err(f.key, "MAX", f"höchstens {c.max}"))
    return e


# ── Pass 2: Phasen-Abschluss ──────────────────────────────────────────────────

def validate_phase_completion(defn: ProcessDefinition, phase: PhaseDef, values: dict) -> list[dict]:
    errors: list[dict] = []
    for fr in phase.fields:
        if fr.mode == FieldMode.hidden:
            continue
        if fr.visibleWhen is not None and not evaluate(fr.visibleWhen, values):
            continue  # nicht sichtbar → nicht pflicht
        required = fr.required or (fr.requiredWhen is not None and evaluate(fr.requiredWhen, values))
        if required and _is_empty(values.get(fr.ref)):
            errors.append(_err(fr.ref, "REQUIRED", "Pflichtfeld"))
    for i, c in enumerate(phase.constraints):
        if not evaluate(c["when"], values):
            errors.append(_err(f"{phase.key}.constraints[{i}]", "CONSTRAINT", c.get("message", "ungültig")))
    return errors
