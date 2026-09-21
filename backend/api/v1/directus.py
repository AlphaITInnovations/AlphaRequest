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
from backend.database import process_definitions as defs_db
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

def _live_fill_fields(source_key: str, process: Optional[str], field: Optional[str],
                      phase: Optional[str]) -> list[str]:
    """Zusätzliche Directus-Quellpfade, damit ein directus-Feld seine Snapshot-
    Zielfelder schon BEI DER AUSWAHL (live) füllen kann – statt erst beim Speichern.

    Serverseitig aus der VERÖFFENTLICHTEN Definition hergeleitet, nicht vom Client:
    so lässt sich kein beliebiges Directus-Feld abfragen. Zusätzlich auf die in
    dieser Phase SICHTBAREN (nicht-hidden, nicht-confidential) Zielfelder
    beschränkt – damit verdeckte Snapshot-Ziele (z. B. Privatadresse) NICHT in die
    Options-Liste gelangen. Fehlt Prozess/Feld/Phase → leer (kein Live-Fill)."""
    if not (process and field and phase):
        return []
    raw = (defs_db.get_published(process) or {}).get("definition") or {}
    fdef = next((f for f in raw.get("fields", [])
                 if f.get("key") == field and f.get("directusSource") == source_key), None)
    ph = next((p for p in raw.get("phases", []) if p.get("key") == phase), None)
    if not fdef or not ph:
        return []
    visible = {r.get("ref") for r in ph.get("fields", []) if r.get("mode") != "hidden"}
    confidential = {f.get("key") for f in raw.get("fields", [])
                    if (f.get("visibility") or {}).get("confidential")}
    out: list[str] = []
    for b in (fdef.get("directusFieldMap") or []):
        tgt, srcpath = b.get("target"), b.get("source")
        if srcpath and tgt in visible and tgt not in confidential and srcpath not in out:
            out.append(srcpath)
    return out


@router.get("/directus/sources/{key}/options")
def source_options(key: str, search: Optional[str] = None, limit: int = 50,
                   process: Optional[str] = None, field: Optional[str] = None,
                   phase: Optional[str] = None,
                   user: dict = Depends(get_current_user)):
    """Optionen einer gespeicherten Quelle – fail-soft: bei fehlender Konfiguration
    oder Directus-Fehler eine leere Liste + Hinweis, damit das Formular nutzbar
    bleibt (die Auswahl ist dann eben leer).

    process/field/phase (optional): lädt zusätzlich die directusFieldMap-Quellfelder
    dieses Feldes mit, damit die Snapshot-Zielfelder live gefüllt werden können
    (siehe _live_fill_fields)."""
    src = store.get(key)
    if not src:
        raise api_error(404, "DIRECTUS_SOURCE_UNKNOWN", f"Quelle „{key}“ nicht gefunden")
    if not dc.is_configured():
        return DataResponse(data={"options": [], "error": "Directus ist nicht konfiguriert"})
    eff_limit = max(1, min(src["limit"], limit))
    want = store.query_fields(src)
    want = want + [p for p in _live_fill_fields(key, process, field, phase) if p not in want]
    try:
        records = dc.query_items(src["collection"], fields=want,
                                 filter=src["filter"], sort=src["sort"] or None,
                                 limit=eff_limit, search=search or None)
    except dc.DirectusError as exc:
        # Details nur ins Log; nach außen eine neutrale Meldung (keine internen
        # Directus-/Schema-Texte an Endnutzer:innen).
        logger.warning("Directus-Optionen „%s“: %s", key, exc)
        return DataResponse(data={"options": [], "error": "Directus ist derzeit nicht erreichbar."})
    return DataResponse(data={"options": store.build_options(records, src), "error": None})


@router.get("/directus/sources/{key}/resolve")
def resolve_labels(key: str, values: str = "", user: dict = Depends(get_current_user)):
    """Labels zu bereits GESPEICHERTEN Werten (IDs) auflösen – für die Lese-/
    Druckansicht, die nur die ID kennt (das Directus-Feld speichert `valueField`,
    das Label lebt live in Directus). `values` ist eine komma-separierte ID-Liste;
    Antwort ist eine Map {id: label}. fail-soft: leere Map, wenn nicht konfiguriert,
    nicht erreichbar oder nichts gefunden – dann zeigt die Ansicht eben die ID."""
    src = store.get(key)
    if not src:
        raise api_error(404, "DIRECTUS_SOURCE_UNKNOWN", f"Quelle „{key}“ nicht gefunden")
    ids = [v.strip() for v in values.split(",") if v.strip()]
    if not ids or not dc.is_configured():
        return DataResponse(data={"labels": {}})
    in_filter = {src["valueField"]: {"_in": ids}}
    base = src.get("filter")
    flt = {"_and": [base, in_filter]} if base else in_filter
    try:
        records = dc.query_items(src["collection"], fields=store.query_fields(src),
                                 filter=flt, limit=max(1, min(len(ids), 200)))
    except dc.DirectusError as exc:
        logger.warning("Directus-Label-Auflösung „%s“: %s", key, exc)
        return DataResponse(data={"labels": {}})
    labels = {str(o["value"]): o["label"] for o in store.build_options(records, src)}
    return DataResponse(data={"labels": labels})
