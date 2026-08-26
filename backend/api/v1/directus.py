"""API für die Directus-Anbindung.

Zwei Ebenen:
  * Admin: Verbindungsstatus, Schema-Introspektion (Collections/Felder) und
    Verwaltung der Quellen-Konfigurationen (bulk-replace wie bei Firmen) inkl.
    Vorschau einer (auch ungespeicherten) Quelle.
  * Angemeldete Nutzer:innen: Live-Optionen einer GESPEICHERTEN Quelle für die
    Auswahl-Felder im Formular – fail-soft (leere Liste + Hinweis statt Fehler,
    wenn Directus nicht erreichbar/konfiguriert ist).
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.core.dependencies import get_current_user
from backend.database import directus_sources as store
from backend.database.audit_log import record_audit
from backend.database.users import PERM_ADMIN
from backend.schemas.responses import DataResponse, ErrorCode, api_error
from backend.services import directus_client as dc
from backend.utils.logger import logger

router = APIRouter()

#: String-Code für „Directus antwortet nicht/fehlerhaft" (kein ErrorCode-Enum –
#: es ist ein Zustand des externen Systems, kein interner Fehler).
_DIRECTUS_ERROR = "DIRECTUS_ERROR"


def _require_admin(user: dict) -> None:
    if PERM_ADMIN not in (user.get("permissions", []) or []):
        raise api_error(403, ErrorCode.ADMIN_REQUIRED, "Admin-Rechte erforderlich")


def _audit(user: dict, action: str, **details) -> None:
    record_audit(
        action=action,
        actor_id=user.get("id"),
        actor_name=user.get("displayName") or user.get("email") or "",
        actor_type="user",
        entity_type="directus_source",
        entity_id="*",
        summary=action,
        details=details,
    )


# ── Modelle ───────────────────────────────────────────────────────────────────

class SourceIn(BaseModel):
    key: str
    label: Optional[str] = None
    collection: str
    valueField: str
    labelTemplate: str
    fields: list[str] = []
    filter: Optional[dict] = None
    sort: list[str] = []
    limit: int = 200


class SourcesIn(BaseModel):
    sources: list[SourceIn]


# ── Verbindung / Introspektion (Admin) ────────────────────────────────────────

@router.get("/directus/status")
def directus_status(user: dict = Depends(get_current_user)):
    _require_admin(user)
    return DataResponse(data=dc.status())


@router.get("/directus/collections")
def directus_collections(user: dict = Depends(get_current_user)):
    _require_admin(user)
    try:
        return DataResponse(data=dc.list_collections())
    except dc.DirectusError as exc:
        raise api_error(502, _DIRECTUS_ERROR, str(exc))


@router.get("/directus/collections/{collection}/fields")
def directus_fields(collection: str, user: dict = Depends(get_current_user)):
    _require_admin(user)
    # Erst die echte Schema-Introspektion; wenn sie für das Token nicht verfügbar
    # ist (Fehler ODER leer), Felder aus einem Beispiel-Datensatz ableiten – das
    # braucht nur Leserechte.
    schema_err = None
    try:
        fields = dc.list_fields(collection)
        if fields:
            return DataResponse(data=fields)
    except dc.DirectusError as exc:
        schema_err = str(exc)
    try:
        return DataResponse(data=dc.sample_fields(collection))
    except dc.DirectusError as exc:
        raise api_error(502, _DIRECTUS_ERROR, schema_err or str(exc))


# ── Quellen-Verwaltung (Admin) ────────────────────────────────────────────────

@router.get("/directus/sources")
def list_sources(user: dict = Depends(get_current_user)):
    _require_admin(user)
    return DataResponse(data=store.get_all())


@router.put("/directus/sources")
def replace_sources(body: SourcesIn, user: dict = Depends(get_current_user)):
    _require_admin(user)
    try:
        saved = store.set_all([s.model_dump() for s in body.sources])
    except store.SourceError as exc:
        raise api_error(422, ErrorCode.VALIDATION_FAILED, str(exc))
    _audit(user, "directus_sources_updated", count=len(saved),
           keys=[s["key"] for s in saved])
    return DataResponse(data=saved)


@router.post("/directus/sources:preview")
def preview_source(body: SourceIn, user: dict = Depends(get_current_user)):
    """Eine (auch ungespeicherte) Quelle testen: liefert Beispiel-Optionen und die
    tatsächlich geladene Feldliste – so sieht man vor dem Speichern, was ankommt."""
    _require_admin(user)
    try:
        src = store.normalize_source(body.model_dump())
    except store.SourceError as exc:
        raise api_error(422, ErrorCode.VALIDATION_FAILED, str(exc))
    try:
        records = dc.query_items(src["collection"], fields=store.query_fields(src),
                                 filter=src["filter"], sort=src["sort"] or None,
                                 limit=min(src["limit"], 25))
    except dc.DirectusError as exc:
        raise api_error(502, _DIRECTUS_ERROR, str(exc))
    return DataResponse(data={"options": store.build_options(records, src),
                              "fields": store.query_fields(src)})


# ── Live-Optionen einer gespeicherten Quelle (für Formulare) ──────────────────

@router.get("/directus/sources/{key}/options")
def source_options(key: str, search: Optional[str] = None, limit: int = 50,
                   user: dict = Depends(get_current_user)):
    """Optionen einer gespeicherten Quelle – fail-soft: bei fehlender Konfiguration
    oder Directus-Fehler eine leere Liste + Hinweis, damit das Formular nutzbar
    bleibt (die Auswahl ist dann eben leer)."""
    src = store.get(key)
    if not src:
        raise api_error(404, "DIRECTUS_SOURCE_UNKNOWN", f"Quelle „{key}“ nicht gefunden")
    if not dc.is_configured():
        return DataResponse(data={"options": [], "error": "Directus ist nicht konfiguriert"})
    eff_limit = max(1, min(src["limit"], limit))
    try:
        records = dc.query_items(src["collection"], fields=store.query_fields(src),
                                 filter=src["filter"], sort=src["sort"] or None,
                                 limit=eff_limit, search=search or None)
    except dc.DirectusError as exc:
        # Details nur ins Log; nach außen eine neutrale Meldung (keine internen
        # Directus-/Schema-Texte an Endnutzer:innen).
        logger.warning("Directus-Optionen „%s“: %s", key, exc)
        return DataResponse(data={"options": [], "error": "Directus ist derzeit nicht erreichbar."})
    return DataResponse(data={"options": store.build_options(records, src), "error": None})
