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
from backend.database.groups import get_group_ids_for_user
from backend.database.users import PERM_ADMIN, PERM_MANAGE
from backend.schemas.process_definition import ProcessDefinition
from backend.schemas.responses import DataResponse, api_error, ErrorCode
from backend.services import process_permissions as perms
from backend.services import process_runtime as pr
from backend.services import process_visibility as vis
from backend.utils.logger import logger
from backend.utils.timeutil import utcnow_iso

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
    #: Darf der/die Aufrufende einen Auftrag dieses Prozesses anlegen?
    #: Nur auf dem Katalog (GET /processes) gefüllt, damit die Anlage-Seite
    #: filtern kann, ohne jede Definition einzeln zu laden.
    may_create: Optional[bool] = None
    #: Symbol aus der Definition – Listen-Routen liefern `definition` nicht mit.
    icon: Optional[str] = None
    #: Kurzbeschreibung aus der Definition. Wie `icon` nur im Katalog gefüllt: die
    #: Kacheln der Anlage-Seite brauchen sie, damit erkennbar bleibt, wofür ein
    #: Prozess da ist (die Alt-Seite hatte diesen Satz je Kachel hartcodiert).
    description: Optional[str] = None
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
    """Veröffentlichter Prozess-Katalog (für alle Authentifizierten).

    Liefert je Prozess `may_create` und `icon`. Die vollständige Definition wird
    dafür gelesen, aber NICHT mitgesendet – sie gehört nicht in eine Liste.
    """
    rows = db.list_published_catalog(include_definition=True)
    try:
        # Fachabteilungen (interne Gruppen) UND AD-Gruppen aus dem Login-Token:
        # das Alt-System berechtigte über beides. Katalog und Anlegen müssen
        # dieselbe Menge sehen, sonst zeigt die Oberfläche einen Prozess an,
        # dessen Anlegen dann 403 liefert.
        gids = get_group_ids_for_user(user.get("id")) if user.get("id") else []
        group_ids = list(gids) + [g for g in (user.get("groups") or []) if g]
    except Exception:
        logger.warning("Gruppen für Erstellrechte nicht ladbar – nur Admin darf anlegen")
        group_ids = []

    out: list[ProcessOut] = []
    for r in rows:
        item = _out(r)
        item.definition = None          # Blob nicht in der Liste ausliefern
        raw = r.get("definition") or {}
        item.icon = raw.get("icon")
        item.description = raw.get("description")
        try:
            defn = ProcessDefinition.model_validate(raw)
            item.may_create = perms.may_create(defn, user, group_ids)
        except Exception:
            # Kaputte Definition darf den Katalog nicht sprengen – fail-closed.
            logger.exception("Definition %s v%s nicht lesbar", r.get("key"), r.get("version"))
            item.may_create = False
        out.append(item)
    return DataResponse(data=out)


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


class FieldAccessOut(BaseModel):
    """Welche Felder diese Person beim ANLEGEN sehen und ausfüllen darf."""
    visible_fields: list[str] = []
    editable_fields: list[str] = []


@router.get("/processes/{key}/field-access", response_model=DataResponse[FieldAccessOut])
def get_create_field_access(key: str, user: dict = Depends(get_current_user)):
    """Feld-Auskunft für den Anlege-Dialog.

    Beim Anlegen gibt es noch kein Ticket, also auch keine Ticket-Antwort mit
    `visible_fields`/`editable_fields`. Ohne diese Auskunft müsste das Formular die
    Sichtbarkeit raten – es kennt die Gruppen-Mitgliedschaft aber gar nicht und
    würde Eingabefelder für Daten anbieten, die der Server anschließend verwirft.

    Gerechnet wird gegen die START-Phase und mit der anfragenden Person als
    künftiger Ersteller:in – genau die Rolle, die sie beim Anlegen hätte.
    """
    row = db.get_published(key)
    if not row or not row.get("definition"):
        raise api_error(404, ErrorCode.PROCESS_NOT_FOUND, f"Kein veröffentlichter Prozess: {key}")
    defn = ProcessDefinition.model_validate(row["definition"])
    start = defn.phases[0]
    provisorisch = {"owner_id": user.get("id"), "status": "in_progress",
                    "runtime": pr.initial_runtime(defn, utcnow_iso()), "values": {}}
    gids = vis.user_group_ids(user)
    ctx = vis.build_viewer_ctx(user, provisorisch, defn, group_ids=gids)
    return DataResponse(data=FieldAccessOut(
        visible_fields=sorted(vis.visible_field_keys(defn, ctx)),
        # ignore_conditions: die bedingte Anzeige wertet das Formular live aus.
        editable_fields=sorted(vis.editable_field_keys(defn, start, ctx, {},
                                                       ignore_conditions=True)),
    ))


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
