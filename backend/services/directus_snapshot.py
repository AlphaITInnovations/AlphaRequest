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
from backend.database.settings import get_companies_full
from backend.schemas.process_definition import ProcessDefinition, Widget
from backend.services import directus_client as dc
# Umkehr-Helfer (Directus-Firmen-ID → System-Firmenname) – EINE Quelle der Wahrheit,
# dieselbe Zuordnung wie beim Onboarding-Prefill.
from backend.services.process_prefill import _company_name_for_directus_id, _rel_id
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


def fetch_source_record(src: dict, key_value: Any, extra_sources: list, *,
                        query: Callable[..., list] = dc.query_items) -> Optional[dict]:
    """Hole EINEN Directus-Datensatz aus der (bereits aufgelösten) Quelle `src`,
    dessen Wert-Feld `key_value` entspricht. Gibt den Datensatz oder None zurück
    (None = kein Treffer). `extra_sources` sind zusätzlich benötigte Feldpfade
    (z. B. Snapshot-/Fill-Quellen) über die Standard-Felder der Quelle hinaus.

    `_in` statt `_eq`: der Wert wird IMMER als String gespeichert; ein `_eq`
    gegen einen numerischen Primärschlüssel (id) trifft je nach Directus/
    Spaltentyp nicht, während `_in` (genau wie das funktionierende Label-
    Auflösen) den Wert zuverlässig matcht. Wirft dc.DirectusError, wenn Directus
    nicht erreichbar ist – der Aufrufer behandelt das best-effort."""
    base = sources_db.query_fields(src)
    want = base + [s for s in extra_sources if s not in base]
    eq = {src["valueField"]: {"_in": [key_value]}}
    flt = {"_and": [src["filter"], eq]} if src.get("filter") else eq
    recs = query(src["collection"], fields=want, filter=flt, limit=1)
    return recs[0] if recs else None


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

    # Firmen-Felder (widget=company) als Snapshot-Ziel: Directus liefert die Firmen-ID,
    # die über das in den Settings hinterlegte directus_firma_id auf den System-
    # Firmennamen gemappt werden muss (Umkehr des Onboarding-Mappings) – nicht-Admins
    # kommen clientseitig nicht an diese Zuordnung, daher serverseitig hier.
    _company_targets = any(widget_by_key.get(b.target) == Widget.company
                           for f in fields for b in f.directusFieldMap)
    companies = get_companies_full() if _company_targets else []

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

        try:
            rec = fetch_source_record(src, cur, [b.source for b in f.directusFieldMap],
                                      query=query)
        except dc.DirectusError as exc:
            logger.warning("Directus-Snapshot für %s=%r fehlgeschlagen: %s", f.key, cur, exc)
            continue

        if rec is None:
            # Schlüssel gesetzt, aber KEIN Datensatz gefunden (z. B. Typ-/Quelle-
            # Mismatch beim valueField oder ein Directus-Hänger). Die Zielfelder
            # NICHT leeren – die im Formular gezeigten Werte bleiben stehen; ein
            # späterer erfolgreicher Snapshot überschreibt sie autoritativ. Ohne das
            # stünde nach dem Anlegen alles leer (inkl. Titel-Vorlage).
            logger.warning("Directus-Snapshot: kein Datensatz für %s=%r in „%s“ – "
                           "Zielfelder unverändert gelassen", f.key, cur, src.get("collection"))
            continue
        for b in f.directusFieldMap:
            raw = sources_db.resolve_path(rec, b.source)
            if widget_by_key.get(b.target) == Widget.company:
                # Directus-Firmen-ID (skalar ODER Relation {id,…}) → System-Firmenname.
                out[b.target] = _company_name_for_directus_id(_rel_id(raw), companies)
            else:
                out[b.target] = _coerce(raw, widget_by_key.get(b.target))
    return out


def snapshot_target_keys(defn: ProcessDefinition) -> set:
    """Alle Prozess-Felder, die Ziel eines directus-Auto-Fills sind."""
    return {b.target for f in defn.fields
            if f.widget == Widget.directus and f.directusFieldMap
            for b in f.directusFieldMap}


def seed_snapshot_targets(defn: ProcessDefinition, values: dict, submitted: dict) -> dict:
    """Read-only Snapshot-Ziele mit den im Formular live gefüllten Werten vorbelegen,
    wo noch nichts steht (neue Kopie).

    Hintergrund: Die Zielfelder sind read-only und werden vom Schreibschutz beim
    Anlegen verworfen. Findet der autoritative Re-Fetch den Datensatz, überschreibt
    er diese Vorbelegung ohnehin; scheitert er, bleiben wenigstens die gezeigten
    Werte erhalten statt leer. Es werden NUR Ziele gefüllt, die die Auswahl schon
    mitgeschickt hat – vertrauliche Ziele stehen dort nicht (sie werden clientseitig
    gar nicht live gefüllt) und bleiben damit dem autoritativen Snapshot vorbehalten."""
    targets = snapshot_target_keys(defn)
    out = dict(values)
    for t in targets:
        if out.get(t) in (None, "") and submitted.get(t) not in (None, ""):
            out[t] = submitted[t]
    return out
