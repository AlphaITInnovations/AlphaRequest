"""Automations-Aktion `directus_write`: Datensatz in Directus anlegen/ändern/löschen.

Payload = Prozesswerte laut Feld-Mapping. Idempotenz + Referenz über ein
Prozess-Feld (`idField`): create schreibt die vergebene Directus-id dorthin
zurück (und überspringt, wenn schon eine id da ist – Doppelanlage-Schutz);
update/delete lesen die id von dort.

Fehler blockieren den Workflow NICHT: sie werden protokolliert, im Auftrags-
Verlauf und im Audit vermerkt und zusätzlich per Mail an BUG_REPORT_MAIL
gemeldet (Entscheidung des Betreibers). `execute` gibt Zustandsänderungen für
`apply_action_changes` zurück (die id landet über `values`).

Directus-Zugriff ist injizierbar (`client`) – testbar ohne Netz.
"""
from __future__ import annotations

from typing import Callable, Optional

from backend.schemas.process_definition import DirectusOperation
from backend.services import directus_client as dc
from backend.utils.logger import logger


def build_payload(spec, values: dict) -> dict:
    """Directus-Payload aus dem Feld-Mapping. Leere Werte (None/"") werden
    ausgelassen – so überschreibt ein leeres Prozess-Feld nichts unbeabsichtigt."""
    out: dict = {}
    for b in spec.fieldMap:
        v = values.get(b.source)
        if v is None or v == "":
            continue
        out[b.target] = v
    return out


def execute(action, row: dict, defn, phase, *, client=dc,
            on_error: Optional[Callable] = None) -> dict:
    """Führt die directus_write-Aktion aus. Wirft nicht. Gibt changes zurück
    (z. B. {"values": {idField: <neue id>}})."""
    spec = getattr(action, "directus", None)
    if spec is None:
        return {}
    values = row.get("values") or {}
    id_field = spec.idField
    current_id = values.get(id_field)
    report = on_error or _report_failure

    try:
        if spec.operation == DirectusOperation.create:
            if current_id:                                # bereits angelegt → nichts tun
                return {}
            created = client.create_item(spec.collection, build_payload(spec, values))
            new_id = created.get("id") if isinstance(created, dict) else None
            if new_id in (None, ""):
                raise dc.DirectusError("Directus lieferte keine id für den angelegten Datensatz")
            return {"values": {id_field: str(new_id)}}

        if spec.operation == DirectusOperation.update:
            if not current_id:
                raise dc.DirectusError(f"Keine Directus-id in „{id_field}“ – Update nicht möglich")
            client.update_item(spec.collection, current_id, build_payload(spec, values))
            return {}

        if spec.operation == DirectusOperation.delete:
            if not current_id:
                raise dc.DirectusError(f"Keine Directus-id in „{id_field}“ – Löschen nicht möglich")
            client.delete_item(spec.collection, current_id)
            return {"values": {id_field: None}}            # id zurücksetzen (Datensatz existiert nicht mehr)
    except dc.DirectusError as exc:
        report(row, phase, spec, exc)
        return {}
    return {}


# ── Fehlermeldung: Verlauf + Audit + Mail an BUG_REPORT_MAIL ──────────────────

def _report_failure(row: dict, phase, spec, exc: Exception) -> None:
    tid = row.get("id")
    logger.error("Directus-Schreiben (%s %s) für #%s fehlgeschlagen: %s",
                 spec.operation.value, spec.collection, tid, exc)
    details = {"operation": spec.operation.value, "collection": spec.collection,
               "error": str(exc)[:500]}
    try:
        from backend.database.audit_log import record_audit
        record_audit(action="process_directus_write_failed", actor_id=None, actor_name="System",
                     actor_type="system", entity_type="process_ticket", entity_id=str(tid),
                     summary=f"Directus-Schreiben fehlgeschlagen ({spec.operation.value} {spec.collection})",
                     details=details)
    except Exception:
        logger.exception("Audit für Directus-Fehler nicht schreibbar (#%s)", tid)
    try:
        from backend.services import process_events as events
        events.system(row, "directus_write_failed",
                      phase_key=(phase.key if phase else None), details=details)
    except Exception:
        logger.exception("Verlaufseintrag für Directus-Fehler nicht schreibbar (#%s)", tid)
    _notify_bug_mail(row, spec, exc)


def _notify_bug_mail(row: dict, spec, exc: Exception) -> None:
    from backend.utils.config import config
    to = (getattr(config, "BUG_REPORT_MAIL", "") or "").strip()
    if not to:
        return
    try:
        from backend.services.microsoft_mail import (
            brand_logo_attachment, render_corporate_email, send_mail_app_only,
        )
        title = str(row.get("title") or f"Auftrag #{row.get('id')}")
        send_mail_app_only(
            sender_upn_or_id="alpharequest@alpha-it-innovations.org",
            subject=f"[AlphaRequest] Directus-Schreiben fehlgeschlagen: {title}",
            kind="directus_write_failed",
            body=render_corporate_email(
                subject="Directus-Schreiben fehlgeschlagen",
                header_subtitle="Automatische Aktion fehlgeschlagen",
                headline=title,
                intro=("Eine Automation konnte den Datensatz nicht nach Directus schreiben. "
                       "Der Auftrag läuft weiter – bitte manuell prüfen und ggf. nachtragen."),
                info_rows=[("Auftrag", f"#{row.get('id')}"), ("Operation", spec.operation.value),
                           ("Collection", spec.collection), ("Fehler", str(exc)[:300])],
                content="",
            ),
            to_recipients=[to],
            body_type="HTML",
            attachments=[a for a in [brand_logo_attachment()] if a],
        )
    except Exception:
        logger.exception("Fehler-Mail (Directus) nicht versendbar (#%s)", row.get("id"))
