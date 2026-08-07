"""
REST-API für Prozess-Definitionen (data-driven Workflows, Stufe 1).

Ressourcenorientiert; Nicht-CRUD-Aktionen als Custom Method (`:verb`).
Alle Mutationen sind auf Admin (PERM_ADMIN) beschränkt und werden auditiert;
Entwurf-/Versions-Reads erfordern Manage/Admin, der veröffentlichte Katalog ist
für alle Authentifizierten sichtbar.

Definitionen werden beim Anlegen/Bearbeiten/Import gegen das Meta-Schema
(schemas.process_definition.ProcessDefinition) validiert – FastAPI erzeugt bei
Verstößen einen RequestValidationError, den der Handler in main.py in den
einheitlichen Fehler-Envelope { error: { code, message, fields[] } } normalisiert.
"""
import json
from typing import Optional

from fastapi import APIRouter, Depends, Header, Response
from pydantic import BaseModel

from backend.core.dependencies import get_current_user
from backend.database import process_definitions as db
from backend.database.audit_log import record_audit
from backend.database.users import PERM_ADMIN, PERM_MANAGE
from backend.schemas.process_definition import ProcessDefinition
from backend.schemas.responses import DataResponse, api_error, ErrorCode

router = APIRouter()


# ── Auth ────────────────────────────────────────────────────────────────────

def _require_admin(user: dict) -> None:
    if PERM_ADMIN not in (user.get("permissions", []) or []):
        raise api_error(403, ErrorCode.ADMIN_REQUIRED, "Admin-Rechte erforderlich")


def _require_manage(user: dict) -> None:
    perms = user.get("permissions", []) or []
    if PERM_ADMIN not in perms and PERM_MANAGE not in perms:
        raise api_error(403, ErrorCode.PERMISSION_DENIED, "Verwaltungsrechte erforderlich")


def _audit(user: dict, action: str, key: str, **details) -> None:
    record_audit(
        action=action,
        actor_id=user.get("id"),
        actor_name=user.get("displayName") or user.get("email") or "",
        entity_type="process_definition",
        entity_id=key,
        summary=f"Prozess „{key}“: {action}",
        details=details,
    )


# ── Out-Schema ────────────────────────────────────────────────────────────────

class ProcessOut(BaseModel):
    id: int
    key: str
    version: int
    status: str
    name: str
    definition: Optional[dict] = None
    base_version: Optional[int] = None
    created_by: Optional[str] = None
    created_by_name: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    published_at: Optional[str] = None
    etag: Optional[str] = None


def _out(row: dict) -> ProcessOut:
    return ProcessOut(**{k: row.get(k) for k in ProcessOut.model_fields})


def _set_etag(resp: Response, row: dict) -> None:
    if row.get("etag"):
        resp.headers["ETag"] = str(row["etag"])


def _dump(defn: ProcessDefinition) -> str:
    return json.dumps(defn.model_dump(by_alias=True), ensure_ascii=False)


# ── DB-Fehler → HTTP ────────────────────────────────────────────────────────

def _map_db_error(exc: Exception):
    if isinstance(exc, db.ProcessNotFound):
        return api_error(404, ErrorCode.PROCESS_NOT_FOUND, f"Prozess nicht gefunden: {exc}")
    if isinstance(exc, db.ProcessKeyExists):
        return api_error(409, ErrorCode.PROCESS_KEY_EXISTS, f"Prozess-Key existiert bereits: {exc}")
    if isinstance(exc, db.ProcessInvalidState):
        return api_error(409, ErrorCode.PROCESS_INVALID_STATE, str(exc))
    if isinstance(exc, db.ProcessVersionInUse):
        return api_error(409, ErrorCode.PROCESS_VERSION_IN_USE, str(exc))
    if isinstance(exc, db.ProcessVersionConflict):
        return api_error(409, ErrorCode.PROCESS_VERSION_CONFLICT, str(exc))
    return None


# ── Katalog / Read ─────────────────────────────────────────────────────────

@router.get("/processes", response_model=DataResponse[list[ProcessOut]])
def list_processes(user: dict = Depends(get_current_user)):
    """Veröffentlichter Prozess-Katalog (für alle Authentifizierten)."""
    rows = db.list_published_catalog()
    return DataResponse(data=[_out(r) for r in rows])


@router.get("/processes/{key}/versions", response_model=DataResponse[list[ProcessOut]])
def list_process_versions(key: str, user: dict = Depends(get_current_user)):
    _require_manage(user)
    rows = db.list_versions(key)
    if not rows:
        raise api_error(404, ErrorCode.PROCESS_NOT_FOUND, f"Prozess nicht gefunden: {key}")
    return DataResponse(data=[_out(r) for r in rows])


@router.get("/processes/{key}/versions/{version:int}:export")
def export_process_version(key: str, version: int, user: dict = Depends(get_current_user)):
    """Portable JSON-Definition einer Version (Export)."""
    _require_manage(user)
    row = db.get_definition(key, version)
    if not row:
        raise api_error(404, ErrorCode.PROCESS_NOT_FOUND, f"Prozess nicht gefunden: {key} v{version}")
    return DataResponse(data=row.get("definition"))


@router.get("/processes/{key}/versions/{version:int}", response_model=DataResponse[ProcessOut])
def get_process_version(key: str, version: int, response: Response,
                        user: dict = Depends(get_current_user)):
    _require_manage(user)
    row = db.get_definition(key, version)
    if not row:
        raise api_error(404, ErrorCode.PROCESS_NOT_FOUND, f"Prozess nicht gefunden: {key} v{version}")
    _set_etag(response, row)
    return DataResponse(data=_out(row))


@router.get("/processes/{key}", response_model=DataResponse[ProcessOut])
def get_published_process(key: str, user: dict = Depends(get_current_user)):
    """Aktuell veröffentlichte Version (für alle Authentifizierten)."""
    row = db.get_published(key)
    if not row:
        raise api_error(404, ErrorCode.PROCESS_NOT_FOUND, f"Kein veröffentlichter Prozess: {key}")
    return DataResponse(data=_out(row))


# ── Mutationen (Admin) ────────────────────────────────────────────────────────

@router.post("/processes", response_model=DataResponse[ProcessOut])
def create_process(defn: ProcessDefinition, user: dict = Depends(get_current_user)):
    """Neuen Prozess als Draft v1 anlegen (key aus der Definition)."""
    _require_admin(user)
    try:
        row = db.create_process(defn.key, defn.name, _dump(defn), user.get("id"),
                                user.get("displayName") or user.get("email"))
    except Exception as exc:
        mapped = _map_db_error(exc)
        if mapped:
            raise mapped
        raise
    _audit(user, "process_created", defn.key, version=1)
    return DataResponse(data=_out(row))


@router.post("/processes/{key}/versions", response_model=DataResponse[ProcessOut])
def create_draft_version(key: str, user: dict = Depends(get_current_user)):
    """Neuen Bearbeitungs-Draft holen/anlegen (klont die published-Version)."""
    _require_admin(user)
    try:
        row = db.create_or_get_draft(key, user.get("id"),
                                     user.get("displayName") or user.get("email"))
    except Exception as exc:
        mapped = _map_db_error(exc)
        if mapped:
            raise mapped
        raise
    _audit(user, "process_draft_created", key, version=row["version"])
    return DataResponse(data=_out(row))


@router.put("/processes/{key}/versions/{version:int}", response_model=DataResponse[ProcessOut])
def update_process_draft(key: str, version: int, defn: ProcessDefinition, response: Response,
                         if_match: Optional[str] = Header(None, alias="If-Match"),
                         user: dict = Depends(get_current_user)):
    _require_admin(user)
    if defn.key != key:
        raise api_error(422, ErrorCode.VALIDATION_FAILED, "key im Body weicht vom Pfad ab",
                        fields=[{"path": "key", "code": "MISMATCH",
                                 "message": f"Body-key „{defn.key}“ ≠ Pfad-key „{key}“"}])
    try:
        row = db.update_draft(key, version, defn.name, _dump(defn), if_match=if_match)
    except Exception as exc:
        mapped = _map_db_error(exc)
        if mapped:
            raise mapped
        raise
    _audit(user, "process_draft_updated", key, version=version)
    _set_etag(response, row)
    return DataResponse(data=_out(row))


@router.post("/processes/{key}/versions/{version:int}:publish", response_model=DataResponse[ProcessOut])
def publish_process_version(key: str, version: int, user: dict = Depends(get_current_user)):
    _require_admin(user)
    try:
        row = db.publish(key, version)
    except Exception as exc:
        mapped = _map_db_error(exc)
        if mapped:
            raise mapped
        raise
    _audit(user, "process_published", key, version=version)
    return DataResponse(data=_out(row))


class DuplicateRequest(BaseModel):
    newKey: str


@router.post("/processes/{key}:duplicate", response_model=DataResponse[ProcessOut])
def duplicate_process(key: str, body: DuplicateRequest, user: dict = Depends(get_current_user)):
    _require_admin(user)
    # Quelle = published, sonst höchste Version
    src = db.get_published(key)
    if not src:
        versions = db.list_versions(key)
        src = versions[0] if versions else None
    if not src or not src.get("definition"):
        raise api_error(404, ErrorCode.PROCESS_NOT_FOUND, f"Prozess nicht gefunden: {key}")

    raw = dict(src["definition"])
    raw["key"] = body.newKey
    try:
        defn = ProcessDefinition.model_validate(raw)   # validiert den neuen key mit
    except Exception:
        raise api_error(422, ErrorCode.VALIDATION_FAILED, "Kopie ist nicht valide (ungültiger neuer key?)",
                        fields=[{"path": "newKey", "code": "INVALID", "message": body.newKey}])
    try:
        row = db.duplicate(key, body.newKey, _dump(defn), defn.name, user.get("id"),
                           user.get("displayName") or user.get("email"))
    except Exception as exc:
        mapped = _map_db_error(exc)
        if mapped:
            raise mapped
        raise
    _audit(user, "process_duplicated", body.newKey, source=key)
    return DataResponse(data=_out(row))


class ImportRequest(BaseModel):
    targetKey: str
    definition: ProcessDefinition


@router.post("/processes:import", response_model=DataResponse[ProcessOut])
def import_process(body: ImportRequest, user: dict = Depends(get_current_user)):
    """Import: der Ziel-key muss bestätigt werden (nie allein aus dem JSON)."""
    _require_admin(user)
    raw = body.definition.model_dump(by_alias=True)
    raw["key"] = body.targetKey
    try:
        defn = ProcessDefinition.model_validate(raw)
    except Exception:
        raise api_error(422, ErrorCode.VALIDATION_FAILED, "Import ist nicht valide",
                        fields=[{"path": "targetKey", "code": "INVALID", "message": body.targetKey}])
    try:
        row = db.create_process(defn.key, defn.name, _dump(defn), user.get("id"),
                                user.get("displayName") or user.get("email"))
    except Exception as exc:
        mapped = _map_db_error(exc)
        if mapped:
            raise mapped
        raise
    _audit(user, "process_imported", defn.key)
    return DataResponse(data=_out(row))


@router.delete("/processes/{key}/versions/{version:int}")
def delete_process_version(key: str, version: int, user: dict = Depends(get_current_user)):
    _require_admin(user)
    try:
        db.delete_version(key, version)
    except Exception as exc:
        mapped = _map_db_error(exc)
        if mapped:
            raise mapped
        raise
    _audit(user, "process_version_deleted", key, version=version)
    return {"ok": True}
