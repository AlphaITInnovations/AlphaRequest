"""
REST-API für definitions-getriebene Tickets (Prozess-Instanzen, Stufe 2).

Neues, sauberes Schema (ersetzt später `view`/`overview`); während des Umbaus
unter /process-tickets parallel zum Alt-System. Bis Stufe 3 (Sichtbarkeit) sind
die Endpunkte admin-gated, damit ungefilterte Feldwerte nicht an Unbefugte gehen.

Jedes Ticket wird gegen seine GEPINNTE Definition validiert/abgewickelt.
Server-Validierung in zwei Pässen (§9): Wert-Form bei POST/PATCH,
Phasen-Abschluss bei :advance.
"""
import json
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from backend.core.dependencies import get_current_user
from backend.database import process_tickets as store
from backend.database import process_definitions as defstore
from backend.database.audit_log import record_audit
from backend.database.users import PERM_ADMIN
from backend.schemas.process_definition import ProcessDefinition
from backend.schemas.responses import (
    DataResponse, ListResponse, Meta, api_error, ErrorCode,
)
from backend.services import process_runtime as pr
from backend.services import process_validation as pv
from backend.utils.timeutil import utcnow_iso

router = APIRouter()


def _require_admin(user: dict) -> None:
    if PERM_ADMIN not in (user.get("permissions", []) or []):
        raise api_error(403, ErrorCode.ADMIN_REQUIRED, "Admin-Rechte erforderlich")


# ── Schemas ──────────────────────────────────────────────────────────────────

class CreateTicketRequest(BaseModel):
    processKey: str
    title: Optional[str] = None
    priority: Optional[str] = None
    values: Optional[dict] = None


class PatchTicketRequest(BaseModel):
    title: Optional[str] = None
    values: Optional[dict] = None


class ProcessTicketOut(BaseModel):
    id: int
    process_key: str
    process_version: int
    title: str
    status: str
    priority: str
    owner_id: Optional[str] = None
    owner_name: Optional[str] = None
    values: dict = {}
    runtime: dict = {}
    current_phase: Optional[str] = None
    current_phase_label: Optional[str] = None
    responsibility: Optional[dict] = None
    next_timer_due_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


# ── Helfer ─────────────────────────────────────────────────────────────────

def _load_pinned_defn(row: dict) -> ProcessDefinition:
    d = defstore.get_definition(row["process_key"], row["process_version"])
    if not d or not d.get("definition"):
        raise api_error(500, "PROCESS_DEFINITION_MISSING",
                        f"Gepinnte Definition {row['process_key']} v{row['process_version']} fehlt")
    return ProcessDefinition.model_validate(d["definition"])


def _is_terminal(row: dict) -> bool:
    return row["status"] in ("archived", "rejected") or bool((row.get("runtime") or {}).get("rejected"))


def _out(row: dict, defn: Optional[ProcessDefinition] = None) -> ProcessTicketOut:
    if defn is None:
        try:
            defn = _load_pinned_defn(row)
        except Exception:
            defn = None
    cur = pr.current_phase(defn, row["runtime"]) if defn else None
    resp = pr.resolve_responsibility(cur, row.get("values") or {}) if cur else None
    data = {k: row.get(k) for k in (
        "id", "process_key", "process_version", "title", "status", "priority",
        "owner_id", "owner_name", "values", "runtime", "next_timer_due_at",
        "created_at", "updated_at")}
    data["current_phase"] = cur.key if cur else None
    data["current_phase_label"] = (cur.label or cur.key) if cur else None
    data["responsibility"] = resp
    return ProcessTicketOut(**data)


def _audit(user: dict, action: str, ticket_id, **details) -> None:
    record_audit(
        action=action,
        actor_id=user.get("id"),
        actor_name=user.get("displayName") or user.get("email") or "",
        entity_type="process_ticket",
        entity_id=str(ticket_id),
        summary=f"Prozess-Ticket #{ticket_id}: {action}",
        details=details,
    )


# ── Endpunkte ────────────────────────────────────────────────────────────────

@router.get("/process-tickets", response_model=ListResponse[ProcessTicketOut])
def list_process_tickets(
    user: dict = Depends(get_current_user),
    status: Optional[str] = None,
    process_key: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    _require_admin(user)
    rows, total = store.list_tickets(status=status, process_key=process_key, q=q,
                                     limit=limit, offset=offset)
    return ListResponse(data=[_out(r) for r in rows], meta=Meta(total=total, limit=limit, offset=offset))


@router.post("/process-tickets", response_model=DataResponse[ProcessTicketOut])
def create_process_ticket(body: CreateTicketRequest, user: dict = Depends(get_current_user)):
    _require_admin(user)
    pub = defstore.get_published(body.processKey)
    if not pub or not pub.get("definition"):
        raise api_error(404, ErrorCode.PROCESS_NOT_FOUND, f"Kein veröffentlichter Prozess: {body.processKey}")
    defn = ProcessDefinition.model_validate(pub["definition"])

    values = body.values or {}
    errs = pv.validate_values(defn, values)
    if errs:
        raise api_error(422, ErrorCode.VALIDATION_FAILED, "Eingaben ungültig", fields=errs)

    runtime = pr.initial_runtime(defn, utcnow_iso())
    status = pr.enter_status_for(defn.phases[0])
    row = store.create(
        process_key=defn.key, process_version=pub["version"],
        title=body.title or defn.name, status=status, priority=(body.priority or "normal"),
        owner_id=user.get("id"), owner_name=user.get("displayName") or user.get("email"),
        values_json=json.dumps(values, ensure_ascii=False),
        runtime_json=json.dumps(runtime, ensure_ascii=False),
    )
    _audit(user, "process_ticket_created", row["id"], process_key=defn.key, version=pub["version"])
    return DataResponse(data=_out(row, defn))


@router.get("/process-tickets/{ticket_id}", response_model=DataResponse[ProcessTicketOut])
def get_process_ticket(ticket_id: int, user: dict = Depends(get_current_user)):
    _require_admin(user)
    row = store.get(ticket_id)
    if not row:
        raise api_error(404, "TICKET_NOT_FOUND", "Ticket nicht gefunden")
    return DataResponse(data=_out(row))


@router.patch("/process-tickets/{ticket_id}", response_model=DataResponse[ProcessTicketOut])
def patch_process_ticket(ticket_id: int, body: PatchTicketRequest, user: dict = Depends(get_current_user)):
    _require_admin(user)
    row = store.get(ticket_id)
    if not row:
        raise api_error(404, "TICKET_NOT_FOUND", "Ticket nicht gefunden")
    if _is_terminal(row):
        raise api_error(409, ErrorCode.PROCESS_INVALID_STATE, "Ticket ist abgeschlossen/abgelehnt")
    defn = _load_pinned_defn(row)

    submitted = body.values or {}
    errs = pv.validate_values(defn, submitted)
    if errs:
        raise api_error(422, ErrorCode.VALIDATION_FAILED, "Eingaben ungültig", fields=errs)

    merged = {**(row.get("values") or {}), **submitted}
    row = store.update_values(ticket_id, json.dumps(merged, ensure_ascii=False), title=body.title)
    _audit(user, "process_ticket_updated", ticket_id, fields=list(submitted.keys()))
    return DataResponse(data=_out(row, defn))


@router.post("/process-tickets/{ticket_id}:advance", response_model=DataResponse[ProcessTicketOut])
def advance_process_ticket(ticket_id: int, user: dict = Depends(get_current_user)):
    _require_admin(user)
    row = store.get(ticket_id)
    if not row:
        raise api_error(404, "TICKET_NOT_FOUND", "Ticket nicht gefunden")
    if _is_terminal(row):
        raise api_error(409, ErrorCode.PROCESS_INVALID_STATE, "Ticket ist abgeschlossen/abgelehnt")
    defn = _load_pinned_defn(row)
    runtime = row["runtime"]
    values = row.get("values") or {}
    phase = pr.current_phase(defn, runtime)
    if phase is None:
        raise api_error(409, ErrorCode.PROCESS_INVALID_STATE, "Keine aktive Phase")

    errs = pv.validate_phase_completion(defn, phase, values)
    if errs:
        raise api_error(422, ErrorCode.VALIDATION_FAILED, "Phase kann nicht abgeschlossen werden", fields=errs)

    runtime, status = pr.advance(defn, runtime, utcnow_iso())
    row = store.update_runtime(ticket_id, runtime_json=json.dumps(runtime, ensure_ascii=False), status=status)
    _audit(user, "process_ticket_advanced", ticket_id, from_phase=phase.key, status=status)
    return DataResponse(data=_out(row, defn))


@router.post("/process-tickets/{ticket_id}:reject", response_model=DataResponse[ProcessTicketOut])
def reject_process_ticket(ticket_id: int, user: dict = Depends(get_current_user)):
    _require_admin(user)
    row = store.get(ticket_id)
    if not row:
        raise api_error(404, "TICKET_NOT_FOUND", "Ticket nicht gefunden")
    if _is_terminal(row):
        raise api_error(409, ErrorCode.PROCESS_INVALID_STATE, "Ticket ist bereits abgeschlossen/abgelehnt")
    runtime = pr.reject(row["runtime"])
    row = store.update_runtime(ticket_id, runtime_json=json.dumps(runtime, ensure_ascii=False), status="rejected")
    _audit(user, "process_ticket_rejected", ticket_id)
    return DataResponse(data=_out(row))
