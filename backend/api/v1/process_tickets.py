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
from backend.database.groups import get_group_ids_for_user
from backend.database.users import PERM_ADMIN
from backend.schemas.process_definition import ProcessDefinition
from backend.schemas.responses import (
    DataResponse, ListResponse, Meta, api_error, ErrorCode,
)
from backend.services import process_access as acc
from backend.services import process_compute as compute
from backend.services import process_engine as engine
from backend.services import process_permissions as perms
from backend.services import process_runtime as pr
from backend.services import process_validation as pv
from backend.services import process_visibility as vis
from backend.schemas.process_definition import TriggerType
from backend.utils.logger import logger
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

def _load_pinned_defn(row: dict, cache: Optional[dict] = None) -> ProcessDefinition:
    """Gepinnte Definition laden und parsen.

    `cache` (pro Request) verhindert das N+1-Muster in Listen: ohne ihn würde je
    Zeile eine DB-Abfrage UND eine vollständige Pydantic-Validierung derselben
    Definition laufen. Gepinnte (key, version) sind unveränderlich (§4), das
    Ergebnis ist also innerhalb eines Requests sicher wiederverwendbar."""
    pin = (row["process_key"], row["process_version"])
    if cache is not None and pin in cache:
        return cache[pin]
    d = defstore.get_definition(*pin)
    if not d or not d.get("definition"):
        raise api_error(500, "PROCESS_DEFINITION_MISSING",
                        f"Gepinnte Definition {pin[0]} v{pin[1]} fehlt")
    defn = ProcessDefinition.model_validate(d["definition"])
    if cache is not None:
        cache[pin] = defn
    return defn


def _is_terminal(row: dict) -> bool:
    return row["status"] in ("archived", "rejected") or bool((row.get("runtime") or {}).get("rejected"))


def _out(row: dict, defn: Optional[ProcessDefinition], ctx: vis.ViewerCtx) -> ProcessTicketOut:
    cur = pr.current_phase(defn, row["runtime"]) if defn else None
    # Zuständigkeit wird server-seitig (ungefiltert) aufgelöst; die Feldwerte im
    # Output werden nach Sichtbarkeit gefiltert (§5.1: einzige wertetragende Naht).
    resp = pr.resolve_responsibility(cur, row.get("values") or {}) if cur else None
    # Bei Fachabteilungen den LIVE-Stand aus dem Runtime zeigen (wer hat schon
    # abgeschlossen?) – resolve_responsibility kennt nur die Definition.
    if resp and resp.get("kind") == "departments":
        live = pr.current_departments(row.get("runtime") or {})
        if live:
            resp = {**resp, "departments": live}
    data = {k: row.get(k) for k in (
        "id", "process_key", "process_version", "title", "status", "priority",
        "owner_id", "owner_name", "runtime", "next_timer_due_at",
        "created_at", "updated_at")}
    data["values"] = vis.filter_values(defn, row.get("values") or {}, ctx)
    data["current_phase"] = cur.key if cur else None
    data["current_phase_label"] = (cur.label or cur.key) if cur else None
    data["responsibility"] = resp
    return ProcessTicketOut(**data)


def _actor_name(user: dict) -> str:
    return user.get("displayName") or user.get("email") or user.get("id") or "System"


def _safe_restamp(row: dict, defn: ProcessDefinition) -> None:
    """Timer neu stempeln, ohne den Request zu kippen – aber NIEMALS stillschweigend:
    ein Fehlschlag wird als ERROR geloggt UND auditiert, sonst sähe ein toter Timer
    aus wie „keine Timer konfiguriert" (Review-Blocker)."""
    try:
        engine.restamp(row, defn)
    except Exception as exc:
        logger.error("Timer-Stempel für Ticket #%s fehlgeschlagen: %s", row.get("id"), exc,
                     exc_info=True)
        record_audit(
            action="process_timer_stamp_failed", actor_id=None, actor_name="System",
            actor_type="system", entity_type="process_ticket", entity_id=str(row.get("id")),
            summary=f"Timer konnte nicht gesetzt werden: {type(exc).__name__}",
            details={"error": str(exc)[:500]},
        )


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


def _assert_view(row: dict, defn, user: dict) -> list:
    """Zugriff prüfen und die Gruppen-Mitgliedschaft zurückgeben (einmal geladen)."""
    gids = vis.user_group_ids(user)
    if not acc.may_view(defn, row, user, gids):
        # Bewusst 404: nicht verraten, dass es den Auftrag gibt.
        raise api_error(404, "TICKET_NOT_FOUND", "Ticket nicht gefunden")
    return gids


def _assert_edit(row: dict, defn, user: dict) -> list:
    """Zusätzlich: nur die aktuell zuständige Stelle (und Admin) darf eingreifen."""
    gids = _assert_view(row, defn, user)
    if not acc.may_edit(defn, row, user, gids):
        raise api_error(403, ErrorCode.TICKET_FORBIDDEN,
                        "Nur die aktuell zuständige Stelle kann diesen Auftrag bearbeiten")
    return gids


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
    rows, total = store.list_tickets(status=status, process_key=process_key, q=q,
                                     limit=limit, offset=offset)
    # Definitionen je (key, version) nur EINMAL laden/parsen und die Gruppen-
    # Mitgliedschaft einmal abfragen – sonst 2 DB-Abfragen + 1 Validierung pro Zeile.
    defn_cache: dict = {}
    gids = vis.user_group_ids(user)
    # Ohne Aufsichtsrechte nur eigene/zugewiesene Auftraege zeigen. Die Gesamtzahl
    # wird um die ausgefilterten korrigiert, damit die Blaetterung stimmt.
    oversight = acc.has_oversight(user)
    out = []
    hidden = 0
    for r in rows:
        try:
            d = _load_pinned_defn(r, defn_cache)
        except Exception:
            d = None
        if not oversight and not acc.may_view(d, r, user, gids):
            hidden += 1
            continue
        out.append(_out(r, d, vis.build_viewer_ctx(user, r, d, group_ids=gids)))
    return ListResponse(data=out,
                        meta=Meta(total=max(0, total - hidden), limit=limit, offset=offset))


@router.post("/process-tickets", response_model=DataResponse[ProcessTicketOut])
def create_process_ticket(body: CreateTicketRequest, user: dict = Depends(get_current_user)):
    pub = defstore.get_published(body.processKey)
    if not pub or not pub.get("definition"):
        raise api_error(404, ErrorCode.PROCESS_NOT_FOUND, f"Kein veröffentlichter Prozess: {body.processKey}")
    defn = ProcessDefinition.model_validate(pub["definition"])

    # Erstellrechte kommen aus der Definition (createPermissions). Admins dürfen
    # immer; für alle anderen greift das erst, wenn die Endpunkte über Admin
    # hinaus geöffnet werden – die Prüfung sitzt schon an der richtigen Stelle.
    try:
        group_ids = get_group_ids_for_user(user.get("id")) if user.get("id") else []
    except Exception:
        logger.warning("Gruppen für Erstellrechte nicht ladbar – fail-closed")
        group_ids = []
    if not perms.may_create(defn, user, group_ids):
        raise api_error(403, ErrorCode.PERMISSION_DENIED,
                        f"Keine Berechtigung, Aufträge des Prozesses „{defn.name}“ anzulegen")

    submitted = body.values or {}
    catalog = {f.key for f in defn.fields}
    unknown = [k for k in submitted if k not in catalog]
    if unknown:
        raise api_error(422, ErrorCode.VALIDATION_FAILED, "Unbekannte Felder",
                        fields=[{"path": k, "code": "UNKNOWN_FIELD", "message": f"Unbekanntes Feld „{k}“"}
                                for k in unknown])

    now = utcnow_iso()
    start_phase = defn.phases[0]
    # Provisorischer Kontext (Ersteller:in = Owner → Vollsicht); Schreibschutz auf
    # die editierbaren Felder der Start-Phase anwenden. Der endgültige Runtime
    # entsteht erst UNTEN mit den fertigen Werten – nur so kann die Start-Phase
    # ihre bedingten Fachabteilungen korrekt bestimmen.
    provisional = {"owner_id": user.get("id"), "status": "in_progress",
                   "runtime": pr.initial_runtime(defn, now), "values": {}}
    ctx = vis.build_viewer_ctx(user, provisional, defn)
    try:
        values = vis.apply_writes(defn, start_phase, {}, submitted, ctx)
    except vis.AppendOnlyViolation as exc:
        raise api_error(422, ErrorCode.VALIDATION_FAILED, "Eingaben ungültig",
                        fields=[{"path": exc.field_key, "code": "APPEND_ONLY", "message": str(exc)}])

    errs = pv.validate_values(defn, values)
    if errs:
        raise api_error(422, ErrorCode.VALIDATION_FAILED, "Eingaben ungültig", fields=errs)
    # Autor/Zeitstempel serverseitig setzen, dann abgeleitete Felder füllen.
    values = compute.stamp_server_fields(defn, values, {}, actor=_actor_name(user), now_iso=now)
    values = compute.apply_computed(defn, values)

    runtime = pr.initial_runtime(defn, now, values)
    status = pr.enter_status_for(start_phase)
    row = store.create(
        process_key=defn.key, process_version=pub["version"],
        title=body.title or defn.name, status=status, priority=(body.priority or "normal"),
        owner_id=user.get("id"), owner_name=user.get("displayName") or user.get("email"),
        values_json=json.dumps(values, ensure_ascii=False),
        runtime_json=json.dumps(runtime, ensure_ascii=False),
    )
    _audit(user, "process_ticket_created", row["id"], process_key=defn.key, version=pub["version"])
    engine.run_inline(row, defn, pr.current_phase(defn, row["runtime"]), {TriggerType.on_enter})
    _safe_restamp(row, defn)
    return DataResponse(data=_out(row, defn, vis.build_viewer_ctx(user, row, defn)))


@router.get("/process-tickets/{ticket_id}", response_model=DataResponse[ProcessTicketOut])
def get_process_ticket(ticket_id: int, user: dict = Depends(get_current_user)):
    row = store.get(ticket_id)
    if not row:
        raise api_error(404, "TICKET_NOT_FOUND", "Ticket nicht gefunden")
    try:
        defn = _load_pinned_defn(row)
    except Exception:
        defn = None
    gids = _assert_view(row, defn, user)
    return DataResponse(data=_out(row, defn,
                                  vis.build_viewer_ctx(user, row, defn, group_ids=gids)))


@router.patch("/process-tickets/{ticket_id}", response_model=DataResponse[ProcessTicketOut])
def patch_process_ticket(ticket_id: int, body: PatchTicketRequest, user: dict = Depends(get_current_user)):
    row = store.get(ticket_id)
    if not row:
        raise api_error(404, "TICKET_NOT_FOUND", "Ticket nicht gefunden")
    defn = _load_pinned_defn(row)
    gids = _assert_edit(row, defn, user)
    if _is_terminal(row):
        raise api_error(409, ErrorCode.PROCESS_INVALID_STATE, "Ticket ist abgeschlossen/abgelehnt")
    ctx = vis.build_viewer_ctx(user, row, defn, group_ids=gids)
    phase = pr.current_phase(defn, row["runtime"])
    if phase is None:
        raise api_error(409, ErrorCode.PROCESS_INVALID_STATE, "Keine aktive Phase")

    submitted = body.values or {}
    catalog = {f.key for f in defn.fields}
    unknown = [k for k in submitted if k not in catalog]
    if unknown:
        raise api_error(422, ErrorCode.VALIDATION_FAILED, "Unbekannte Felder",
                        fields=[{"path": k, "code": "UNKNOWN_FIELD", "message": f"Unbekanntes Feld „{k}“"}
                                for k in unknown])

    stored = row.get("values") or {}
    # Schreibschutz: nur sichtbare + in dieser Phase editierbare Felder übernehmen;
    # der Rest wird verworfen (verborgene Felder behalten ihren Bestandswert).
    # writable_keys wertet visibleWhen gegen einen sicheren Kontext aus (keine
    # Freischaltung über nicht-editierbare Body-Felder).
    try:
        merged_raw = vis.apply_writes(defn, phase, stored, submitted, ctx)
    except vis.AppendOnlyViolation as exc:
        raise api_error(422, ErrorCode.VALIDATION_FAILED, "Eingaben ungültig",
                        fields=[{"path": exc.field_key, "code": "APPEND_ONLY", "message": str(exc)}])
    allowed = vis.writable_keys(defn, phase, ctx, stored, submitted)
    to_apply = {k: v for k, v in merged_raw.items() if k in allowed and stored.get(k) != v}
    errs = pv.validate_values(defn, to_apply)
    if errs:
        raise api_error(422, ErrorCode.VALIDATION_FAILED, "Eingaben ungültig", fields=errs)

    merged = compute.stamp_server_fields(defn, merged_raw, stored,
                                         actor=_actor_name(user), now_iso=utcnow_iso())
    merged = compute.apply_computed(defn, merged)
    try:
        row = store.update_values(ticket_id, json.dumps(merged, ensure_ascii=False),
                                  title=body.title, expected_rev=row.get("rev"))
    except store.ProcessTicketConflict as exc:
        raise api_error(409, "TICKET_CONFLICT", str(exc))
    _audit(user, "process_ticket_updated", ticket_id, fields=list(to_apply.keys()))
    if to_apply:
        wants_advance = engine.run_inline(row, defn, phase, {TriggerType.on_field_change},
                                          changed_fields=set(to_apply.keys()))
        if wants_advance:
            engine.transition(row, defn)
        else:
            _safe_restamp(row, defn)
    return DataResponse(data=_out(row, defn, ctx))


@router.post("/process-tickets/{ticket_id}:advance", response_model=DataResponse[ProcessTicketOut])
def advance_process_ticket(ticket_id: int, user: dict = Depends(get_current_user)):
    row = store.get(ticket_id)
    if not row:
        raise api_error(404, "TICKET_NOT_FOUND", "Ticket nicht gefunden")
    defn = _load_pinned_defn(row)
    _assert_edit(row, defn, user)
    if _is_terminal(row):
        raise api_error(409, ErrorCode.PROCESS_INVALID_STATE, "Ticket ist abgeschlossen/abgelehnt")
    runtime = row["runtime"]
    values = row.get("values") or {}
    phase = pr.current_phase(defn, runtime)
    if phase is None:
        raise api_error(409, ErrorCode.PROCESS_INVALID_STATE, "Keine aktive Phase")

    errs = pv.validate_phase_completion(defn, phase, values)
    if errs:
        raise api_error(422, ErrorCode.VALIDATION_FAILED, "Phase kann nicht abgeschlossen werden", fields=errs)

    # Fachabteilungs-Phase: erst wenn alle PFLICHT-Abteilungen fertig sind.
    offen = pr.open_required_departments(runtime)
    if offen:
        raise api_error(409, ErrorCode.DEPARTMENT_FORBIDDEN,
                        "Es stehen noch Fachabteilungen aus",
                        fields=[{"path": d["group"], "code": "DEPARTMENT_OPEN",
                                 "message": "Diese Fachabteilung hat noch nicht abgeschlossen"}
                                for d in offen])

    # Phasenübergang zentral in der Engine: on_exit → advance → on_enter → Timer.
    try:
        status = engine.transition(row, defn, expected_rev=row.get("rev"))
    except store.ProcessTicketConflict as exc:
        raise api_error(409, "TICKET_CONFLICT", str(exc))
    _audit(user, "process_ticket_advanced", ticket_id, from_phase=phase.key, status=status)
    return DataResponse(data=_out(row, defn, vis.build_viewer_ctx(user, row, defn)))


@router.post("/process-tickets/{ticket_id}:reject", response_model=DataResponse[ProcessTicketOut])
def reject_process_ticket(ticket_id: int, user: dict = Depends(get_current_user)):
    row = store.get(ticket_id)
    if not row:
        raise api_error(404, "TICKET_NOT_FOUND", "Ticket nicht gefunden")
    try:
        defn_for_acc = _load_pinned_defn(row)
    except Exception:
        defn_for_acc = None
    _assert_edit(row, defn_for_acc, user)
    if _is_terminal(row):
        raise api_error(409, ErrorCode.PROCESS_INVALID_STATE, "Ticket ist bereits abgeschlossen/abgelehnt")
    runtime = pr.reject(row["runtime"])
    try:
        row = store.update_runtime(ticket_id, runtime_json=json.dumps(runtime, ensure_ascii=False),
                                   status="rejected", expected_rev=row.get("rev"))
    except store.ProcessTicketConflict as exc:
        raise api_error(409, "TICKET_CONFLICT", str(exc))
    _audit(user, "process_ticket_rejected", ticket_id)
    try:
        defn = _load_pinned_defn(row)
    except Exception:
        defn = None
    return DataResponse(data=_out(row, defn, vis.build_viewer_ctx(user, row, defn)))


# ── Fachabteilungen einzeln abschließen ──────────────────────────────────────

class DepartmentActionRequest(BaseModel):
    note: Optional[str] = None


def _department_action(ticket_id: int, group_id: str, status: str,
                       note: Optional[str], user: dict) -> ProcessTicketOut:
    """Gemeinsamer Pfad für :complete / :reject / :skip einer Fachabteilung."""
    row = store.get(ticket_id)
    if not row:
        raise api_error(404, "TICKET_NOT_FOUND", "Ticket nicht gefunden")
    defn = _load_pinned_defn(row)
    gids = _assert_view(row, defn, user)
    if _is_terminal(row):
        raise api_error(409, ErrorCode.PROCESS_INVALID_STATE, "Ticket ist abgeschlossen/abgelehnt")

    # Nur Mitglieder GENAU DIESER Abteilung (oder Admin) – sonst könnte die IT
    # für den Fuhrpark quittieren.
    if not acc.may_complete_department(defn, row, user, gids, group_id):
        raise api_error(403, ErrorCode.DEPARTMENT_FORBIDDEN,
                        "Nur Mitglieder dieser Fachabteilung können hier abschließen")

    runtime = row["runtime"]
    if not pr.set_department_status(runtime, group_id, status,
                                   by=user.get("id"), by_name=_actor_name(user),
                                   at=utcnow_iso(), note=note):
        raise api_error(409, ErrorCode.DEPARTMENT_FORBIDDEN,
                        "Diese Fachabteilung ist an der aktuellen Phase nicht beteiligt")

    # Bei Ablehnung wird der ganze Auftrag abgelehnt (wie im Alt-System).
    new_status = row["status"]
    if status == "rejected":
        runtime = pr.reject(runtime)
        new_status = "rejected"
    try:
        row = store.update_runtime(ticket_id, runtime_json=json.dumps(runtime, ensure_ascii=False),
                                   status=new_status, expected_rev=row.get("rev"),
                                   next_timer_due_at=row.get("next_timer_due_at"))
    except store.ProcessTicketConflict as exc:
        raise api_error(409, "TICKET_CONFLICT", str(exc))

    _audit(user, f"process_department_{status}", ticket_id, group=group_id, note=note)
    return _out(row, defn, vis.build_viewer_ctx(user, row, defn, group_ids=gids))


@router.post("/process-tickets/{ticket_id}/departments/{group_id}:complete",
             response_model=DataResponse[ProcessTicketOut])
def complete_department(ticket_id: int, group_id: str,
                        body: Optional[DepartmentActionRequest] = None,
                        user: dict = Depends(get_current_user)):
    return DataResponse(data=_department_action(
        ticket_id, group_id, "done", (body.note if body else None), user))


@router.post("/process-tickets/{ticket_id}/departments/{group_id}:skip",
             response_model=DataResponse[ProcessTicketOut])
def skip_department(ticket_id: int, group_id: str,
                   body: Optional[DepartmentActionRequest] = None,
                   user: dict = Depends(get_current_user)):
    """Nicht zuständig / nichts zu tun – gilt als erledigt, ohne Bearbeitung."""
    return DataResponse(data=_department_action(
        ticket_id, group_id, "skipped", (body.note if body else None), user))


@router.post("/process-tickets/{ticket_id}/departments/{group_id}:reject",
             response_model=DataResponse[ProcessTicketOut])
def reject_department(ticket_id: int, group_id: str,
                     body: Optional[DepartmentActionRequest] = None,
                     user: dict = Depends(get_current_user)):
    """Ablehnung durch eine Fachabteilung lehnt den gesamten Auftrag ab."""
    return DataResponse(data=_department_action(
        ticket_id, group_id, "rejected", (body.note if body else None), user))
