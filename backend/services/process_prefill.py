"""Felder beim Anlegen aus den Daten der angemeldeten Person vorbelegen (§ prefill).

Für read-only Antragsteller-Felder: der Wert kommt aus dem Directus-Mitarbeiter-
Datensatz (user["employee"]) bzw. den Session-Feldern und wird serverseitig
AUTORITATIV gesetzt (überschreibt Client-Eingaben – manipulationssicher). Wird nur
beim ANLEGEN angewandt (Momentaufnahme, wer den Antrag gestellt hat); spätere
Änderungen der Stammdaten wirken nicht rückwirkend.
"""
from typing import Any, Optional

from backend.schemas.process_definition import FieldMode, PhaseKind, ProcessDefinition, Widget


#: Felder, aus denen der Anzeigewert einer Directus-Relation gezogen wird
#: (in dieser Reihenfolge) – wie in der Profil-Anzeige (lib/profileFields.fmtValue).
_DISPLAY_FIELDS = ("name", "label", "title", "bezeichnung", "nummer")


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


def _display_value(v: Any) -> Optional[Any]:
    """Einen Feldwert in einen skalaren Anzeigewert überführen: eine Relation
    (dict) → ihr Name/Label; eine Liste → verbundene Anzeigewerte; ein Skalar
    bleibt. So landet nie ein „[object Object]" im Feld, und eine als Objekt
    gelieferte Relation (z. B. cost_center) zeigt trotzdem ihren Namen."""
    if isinstance(v, dict):
        for k in _DISPLAY_FIELDS:
            sv = v.get(k)
            if isinstance(sv, (str, int, float)) and not isinstance(sv, bool):
                return sv
        return None
    if isinstance(v, list):
        parts = [str(_display_value(x)) for x in v if _display_value(x) not in (None, "")]
        return ", ".join(parts) if parts else None
    return v


def _rel_id(v: Any) -> Any:
    """Fremdschlüssel-Wert einer Relation: bei `fields=*` liefert Directus die ID
    skalar; wird die Relation doch als Objekt geliefert, dessen `id` nehmen."""
    return v.get("id") if isinstance(v, dict) else v


_companies_cache: Optional[list] = None


def _companies() -> list:
    """Lokale Firmen (mit `directus_firma_id`) – einmal je Aufruf-Kette geladen."""
    global _companies_cache
    if _companies_cache is None:
        try:
            from backend.database.settings import get_companies_full
            _companies_cache = get_companies_full()
        except Exception:
            _companies_cache = []
    return _companies_cache


def _company_name_for_directus_id(cid: Any, companies: list) -> Optional[str]:
    """Umkehr des Onboarding-Mappings: Directus-Firmen-ID → System-Firmenname
    (über die je Firma hinterlegte `directus_firma_id`)."""
    if cid in (None, ""):
        return None
    s = str(cid)
    for c in companies:
        if str(c.get("directus_firma_id") or "") == s:
            return c.get("name")
    return None


def _match_option(val: Any, field: Any) -> Optional[Any]:
    """Einen Prefill-Wert auf einen Options-Wert eines select-Feldes abbilden.

    Directus liefert für ein Auswahlfeld (z. B. Anrede) evtl. das Label oder eine
    andere Groß-/Kleinschreibung als der im Prozess hinterlegte Options-Wert –
    dann bliebe das Dropdown leer. Hier wird der Wert unempfindlich gegen
    Groß-/Kleinschreibung mit Options-`value` UND `label` verglichen und auf den
    Options-`value` normalisiert. Trifft nichts (und ist kein Freitext erlaubt),
    wird das Feld NICHT gesetzt – lieber leer als ein ungültiger Options-Wert."""
    if val in (None, "") or not field.options:
        return val
    s = str(val).strip().casefold()
    for opt in field.options:
        if str(opt.value).strip().casefold() == s:
            return opt.value
        if opt.label and str(opt.label).strip().casefold() == s:
            return opt.value
    return val if field.allowOther else None


def apply_prefill(defn: ProcessDefinition, values: dict, user: dict) -> dict:
    """Felder mit `prefill`-Spec aus den Daten der angemeldeten Person füllen.

    source "employee" → user["employee"] (Directus-Stammdaten), source "user" →
    das Session-User-Objekt. Ein leerer/fehlender Quellwert lässt das Feld
    unangetastet (kein Überschreiben mit None).

    Relations-Widgets (`directus`) übernehmen die ROH-ID (nicht den Anzeigenamen),
    damit die Auswahl im Dropdown passt und beim Zurückschreiben wieder die ID
    landet. Ein `company`-Widget bekommt aus der Directus-Firmen-ID den System-
    Firmennamen (Umkehr von `company_directus_id`), sonst könnte das Firmen-Dropdown
    den Wert nicht vorwählen.

    **Editierbare Felder** (in der Start-Phase editable/append_only) werden NUR
    vorbelegt, wenn noch kein Wert da ist – so bleibt eine Bearbeitung der Person
    erhalten (Self-Service). Für read-only/hidden-Felder ist die Vorbelegung
    autoritativ (überschreibt), damit sie manipulationssicher bleibt.
    """
    global _companies_cache
    _companies_cache = None
    out = dict(values)
    employee = user.get("employee") or {}
    start = next((p for p in defn.phases if p.kind == PhaseKind.start),
                 defn.phases[0] if defn.phases else None)
    editable = {fr.ref for fr in (start.fields if start else [])
                if fr.mode in (FieldMode.editable, FieldMode.append_only)}
    for f in defn.fields:
        pf = f.prefill
        if not pf:
            continue
        # Editierbares Feld mit bereits gesetztem Wert: nicht überschreiben.
        if f.key in editable and out.get(f.key) not in (None, ""):
            continue
        src = employee if pf.source == "employee" else user
        raw = _resolve_path(src, pf.field)
        if f.widget == Widget.directus:
            val: Any = _rel_id(raw)
        elif f.widget == Widget.company and pf.source == "employee":
            val = _company_name_for_directus_id(_rel_id(raw), _companies())
        else:
            val = _display_value(raw)
            if f.widget == Widget.select:
                val = _match_option(val, f)
        if val is not None and val != "":
            out[f.key] = val
    return out
