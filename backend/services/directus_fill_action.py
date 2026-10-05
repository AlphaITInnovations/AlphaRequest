"""Automations-Aktion `directus_fill`: Stammdaten aus Directus NACHLADEN.

Holt bei Phaseneintritt (on_enter) EINEN Directus-Datensatz anhand eines
Schlüsselfelds (`keyField` – dessen Wert gegen das Wert-Feld der Quelle gematcht
wird) und füllt die gemappten Zielfelder. Firmen-Ziele (widget=company) werden –
wie beim Snapshot – von der Directus-Firmen-ID auf den System-Firmennamen
aufgelöst.

Warum eine eigene Aktion statt des Snapshots (services/directus_snapshot)? Der
Snapshot läuft beim SPEICHERN eines directus-Felds – also schon beim Anlegen.
Diese Aktion läuft erst, wenn die Phase betreten wird. Damit lassen sich
PERSONENBEZOGENE Daten (z. B. die Privatadresse) datenschutzkonform erst in
einer späteren Phase laden, in der die zuständige Stelle sie sehen DARF, statt
sie schon in Phase 1 für die erstellende Person abzulegen.

Best-effort wie der Snapshot: ist die Quelle/Directus nicht erreichbar oder der
Datensatz nicht auffindbar, bleiben die Zielfelder unverändert (nur Log-Warnung)
– ein Stammdaten-Ausfall darf den Phasenübergang nicht kippen. `execute` gibt
die Änderungen für `apply_action_changes` zurück (die Werte landen über
`values`, serverseitig/autoritativ – unabhängig vom Phasen-mode und von
Feld-Sichtbarkeiten, genau wie beim Snapshot). Directus-Zugriff ist injizierbar
(Testbarkeit).
"""
from __future__ import annotations

from typing import Callable, Optional

from backend.database import directus_sources as sources_db
from backend.schemas.process_definition import ProcessDefinition, Widget
from backend.services import directus_client as dc
from backend.services import directus_snapshot as snapshot
from backend.utils.logger import logger


def execute(action, row: dict, defn: ProcessDefinition, phase, *,
            get_source: Callable[[str], Optional[dict]] = sources_db.get,
            query: Callable[..., list] = dc.query_items) -> dict:
    """Führt die directus_fill-Aktion aus. Wirft nicht nach außen (best-effort):
    gibt im Erfolgsfall {"values": {ziel: wert, …}} zurück, sonst {} (Ziele
    bleiben dann unverändert)."""
    spec = getattr(action, "directusFill", None)
    if spec is None:
        return {}

    values = row.get("values") or {}
    key_value = values.get(spec.keyField)
    if key_value in (None, ""):
        # Kein Schlüssel → nichts zu holen. Die Ziele NICHT leeren: ein später
        # gesetzter Schlüssel füllt sie beim nächsten Eintritt.
        logger.info("directus_fill: kein Wert in Schlüsselfeld „%s“ (#%s) – übersprungen",
                    spec.keyField, row.get("id"))
        return {}

    src = get_source(spec.source or "")
    if not src:
        logger.warning("directus_fill: Quelle „%s“ nicht gefunden (#%s) – Ziele unverändert",
                       spec.source, row.get("id"))
        return {}

    widget_by_key = {f.key: f.widget for f in defn.fields}
    field_by_key = {f.key: f for f in defn.fields}
    _company_targets = any(widget_by_key.get(b.target) == Widget.company for b in spec.fieldMap)
    companies: list = []
    if _company_targets:
        # Nur wenn ein Firmen-Ziel existiert die Firmen-Zuordnung laden. Scheitert
        # das, bleiben die NICHT-Firmen-Ziele (die datenschutzkritische Adresse!)
        # trotzdem füllbar; das Firmen-Ziel bleibt dann leer (Log-Warnung).
        try:
            from backend.database.settings import get_companies_full
            companies = get_companies_full()
        except Exception as exc:
            logger.warning("directus_fill: Firmen nicht lesbar (%s, #%s) – Firmen-Ziel bleibt leer",
                           exc, row.get("id"))
            companies = []

    try:
        rec = snapshot.fetch_source_record(
            src, key_value, [b.source for b in spec.fieldMap], query=query)
    except dc.DirectusError as exc:
        logger.warning("directus_fill für %s=%r fehlgeschlagen: %s (#%s) – Ziele unverändert",
                       spec.keyField, key_value, exc, row.get("id"))
        return {}

    if rec is None:
        logger.warning("directus_fill: kein Datensatz für %s=%r in „%s“ (#%s) – Ziele unverändert",
                       spec.keyField, key_value, src.get("collection"), row.get("id"))
        return {}

    out: dict = {}
    for b in spec.fieldMap:
        raw = sources_db.resolve_path(rec, b.source)
        # Zentrale Abbildung (Firma id→Name, select case-insensitiv, sonst coerce) –
        # identisch zum Snapshot (directus_snapshot.coerce_for_target).
        out[b.target] = snapshot.coerce_for_target(raw, field_by_key.get(b.target),
                                                    companies=companies)
    return {"values": out} if out else {}
