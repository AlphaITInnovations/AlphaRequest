"""
REST-API für definitions-getriebene Tickets (Prozess-Instanzen, Stufe 2).

Neues, sauberes Schema (ersetzt später `view`/`overview`); während des Umbaus
unter /process-tickets parallel zum Alt-System.

Zugriff (nicht mehr admin-only): `_assert_view` lässt Aufsicht, Ersteller:in,
aktuell Zuständige und Beobachter:innen herein – und liefert nur die Feldwerte
aus, die der Sichtbarkeits-Filter freigibt. `_assert_edit` verlangt zusätzlich
die Zuständigkeit für die AKTUELLE Phase.

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
from backend.database import process_ticket_watchers as watchers
from backend.database.audit_log import record_audit
from backend.database.groups import get_group_ids_for_user
from backend.database.users import PERM_ADMIN
from backend.schemas.process_definition import ProcessDefinition
from backend.schemas.responses import (
    DataResponse, ListResponse, Meta, api_error, ErrorCode,
)
from backend.services import process_access as acc
from backend.services import process_actions as pactions
from backend.services import process_compute as compute
from backend.services import process_engine as engine
from backend.services import process_events as events
from backend.services import process_permissions as perms
from backend.services import process_runtime as pr
from backend.services import process_sequences as seq
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


class TicketAbilities(BaseModel):
    """Was DIESE Person mit DIESEM Auftrag darf.

    Damit muss die Oberfläche die Rechte nicht nachbauen (sie kennt die
    Gruppen-Mitgliedschaft gar nicht) und zeigt keine Schaltflächen, die der
    Server anschließend mit 403 abweist. Verbindlich bleiben die Endpunkte.
    """
    edit: bool = False
    internal_comment: bool = False
    manage_watchers: bool = False
    reopen: bool = False
    #: Notfalleingriffe (Admin): hängenden Auftrag zwangsweise abschließen bzw. löschen.
    archive: bool = False
    delete: bool = False


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
    abilities: TicketAbilities = TicketAbilities()
    #: Welche Felder diese Person SEHEN bzw. in der aktuellen Phase BEARBEITEN darf.
    #: Das Formular richtet sich danach, statt die Gruppen-Logik nachzubauen – es
    #: kennt die Gruppen-Mitgliedschaft gar nicht.
    visible_fields: list[str] = []
    editable_fields: list[str] = []


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


def _abilities(row: dict, defn: Optional[ProcessDefinition], user: Optional[dict],
               group_ids) -> TicketAbilities:
    if not user:
        return TicketAbilities()
    gids = set(group_ids or ())
    darf_bearbeiten = acc.may_edit(defn, row, user, gids) and not _is_terminal(row)
    return TicketAbilities(
        edit=darf_bearbeiten,
        internal_comment=acc.is_process_staff(defn, user, gids),
        manage_watchers=acc.may_edit(defn, row, user, gids),
        # Wiederaufnahme greift in einen FERTIGEN Auftrag ein – nur Admin.
        reopen=acc.is_admin(user) and _is_terminal(row),
        archive=acc.is_admin(user) and not _is_terminal(row),
        delete=acc.is_admin(user),
    )


def _field_access(row: dict, defn: Optional[ProcessDefinition], phase, ctx: vis.ViewerCtx
                  ) -> tuple[list, list]:
    """Sichtbare und (in dieser Phase) bearbeitbare Feld-Schlüssel.

    `visible_field_keys` verträgt `defn=None` (default-deny), `editable_field_keys`
    NICHT – und `_out` wird mit None aufgerufen, wenn die gepinnte Definition fehlt.
    Daher der frühe Ausstieg.
    """
    if defn is None:
        return [], []
    sichtbar = sorted(vis.visible_field_keys(defn, ctx))
    if phase is None or _is_terminal(row):
        return sichtbar, []
    # ignore_conditions: die bedingte Anzeige (visibleWhen) wertet das Formular
    # live gegen den Tippstand aus – hier geht es nur um das Rollen-Gate.
    bearbeitbar = sorted(vis.editable_field_keys(
        defn, phase, ctx, row.get("values") or {}, ignore_conditions=True))
    return sichtbar, bearbeitbar


def _out(row: dict, defn: Optional[ProcessDefinition], ctx: vis.ViewerCtx,
         user: Optional[dict] = None, group_ids=()) -> ProcessTicketOut:
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
    data["abilities"] = _abilities(row, defn, user, group_ids)
    data["visible_fields"], data["editable_fields"] = _field_access(row, defn, cur, ctx)
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


def _sequence_error(exc: "seq.SequenceError"):
    """Vergabe-Fehler → HTTP. Ein erschöpfter Nummernkreis ist ein fachlicher
    Konflikt (409), kein Serverfehler; eine Kollision zwischen Anspruchs-Ledger und
    Zählerstand dagegen schon – die muss jemand ansehen. Die Codes sind bewusst
    dieselben wie im Alt-System, damit die Meldung im Frontend gleich bleibt."""
    if isinstance(exc, seq.SequenceExhausted):
        return api_error(409, "PERSONALNUMMER_FAILED", str(exc))
    if isinstance(exc, seq.SequenceNotConfigured):
        return api_error(400, "PERSONALNUMMER_FAILED", str(exc))
    if isinstance(exc, seq.SequenceWriteConflict):
        return api_error(409, "TICKET_CONFLICT", str(exc))
    logger.error("Nummernkreis-Kollision bei der Vergabe: %s", exc)
    return api_error(500, "PERSONALNUMMER_FAILED", str(exc))


def _watcher_ids(ticket_id) -> set:
    """Beobachter-IDs – fail-closed: nicht ladbar heißt „keine Beobachter“, also
    kein Zugriff über diesen Weg (statt versehentlich allen Zugriff zu geben)."""
    try:
        return watchers.watcher_ids(int(ticket_id))
    except Exception:
        logger.warning("Beobachter für Ticket #%s nicht ladbar – fail-closed", ticket_id)
        return set()


def _assert_view(row: dict, defn, user: dict) -> list:
    """Zugriff prüfen und die Gruppen-Mitgliedschaft zurückgeben (einmal geladen)."""
    gids = vis.user_group_ids(user)
    if not acc.may_view(defn, row, user, gids, _watcher_ids(row["id"])):
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
    # Beobachter aller Zeilen in EINER Abfrage (ohne Aufsichtsrechte relevant für
    # die Sichtbarkeit) – je Zeile einzeln wäre das ein N+1.
    watch_map: dict = {}
    if not oversight and rows:
        try:
            watch_map = watchers.watcher_ids_for_tickets([r["id"] for r in rows])
        except Exception:
            logger.warning("Beobachter-Liste nicht ladbar – fail-closed")
    out = []
    hidden = 0
    for r in rows:
        try:
            d = _load_pinned_defn(r, defn_cache)
        except Exception:
            d = None
        if not oversight and not acc.may_view(d, r, user, gids, watch_map.get(r["id"], ())):
            hidden += 1
            continue
        out.append(_out(r, d, vis.build_viewer_ctx(user, r, d, group_ids=gids),
                        user, gids))
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
        # Fachabteilungen (interne Gruppen) UND AD-Gruppen aus dem Login-Token:
        # das Alt-System berechtigte über beides, createPermissions.groups mischt
        # sie ebenfalls. Ohne die AD-Gruppen verlöre jede Person das Anlegerecht,
        # die es heute nur über eine AD-Gruppe hat.
        gids = get_group_ids_for_user(user.get("id")) if user.get("id") else []
        group_ids = list(gids) + [g for g in (user.get("groups") or []) if g]
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
    # Ersteller:in beobachtet den eigenen Auftrag automatisch (wie im Alt-System) –
    # so bekommt sie die Fortschritts-Mails, ohne zuständig zu sein.
    try:
        watchers.add_watcher(row["id"], user.get("id"),
                             user.get("displayName") or user.get("email"),
                             added_by=user.get("id"))
    except Exception:
        logger.warning("Ersteller:in konnte für #%s nicht als Beobachter eingetragen werden",
                       row["id"])
    events.record(row, events.CREATED, actor_id=user.get("id"), actor_name=_actor_name(user),
                  details={"process_key": defn.key, "version": pub["version"]})
    engine.run_inline(row, defn, pr.current_phase(defn, row["runtime"]), {TriggerType.on_enter})
    _safe_restamp(row, defn)
    return DataResponse(data=_out(row, defn, vis.build_viewer_ctx(user, row, defn),
                                  user, group_ids))


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
                                  vis.build_viewer_ctx(user, row, defn, group_ids=gids),
                                  user, gids))


@router.get("/process-tickets/{ticket_id}/definition")
def get_pinned_definition(ticket_id: int, user: dict = Depends(get_current_user)):
    """Die GEPINNTE Definition dieses Auftrags – Grundlage für Formular und Anzeige.

    Eigener Endpunkt, weil `GET /processes/{key}/versions/{v}` Verwaltungsrechte
    verlangt (dort kommt man auch an unveröffentlichte Entwürfe). Hier entscheidet
    ausschließlich der Zugriff auf den AUFTRAG: wer ihn sehen darf, darf auch
    wissen, wie er aufgebaut ist. Feldwerte stehen hier keine drin.
    """
    row = store.get(ticket_id)
    if not row:
        raise api_error(404, "TICKET_NOT_FOUND", "Ticket nicht gefunden")
    try:
        defn = _load_pinned_defn(row)
    except Exception:
        defn = None
    _assert_view(row, defn, user)
    if defn is None:
        raise api_error(500, "PROCESS_DEFINITION_MISSING",
                        f"Gepinnte Definition {row['process_key']} "
                        f"v{row['process_version']} fehlt")
    return DataResponse(data=defn.model_dump(mode="json", by_alias=True, exclude_none=True))


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
    if to_apply:
        # Verlauf: NUR die Feld-Schlüssel, nie die Werte. Wer ein Feld nicht sehen
        # darf, sieht den Eintrag auch nicht (Redaktion in process_events.redact).
        events.record(row, events.UPDATED, actor_id=user.get("id"),
                      actor_name=_actor_name(user),
                      details={"fields": sorted(to_apply.keys())})
        wants_advance = engine.run_inline(row, defn, phase, {TriggerType.on_field_change},
                                          changed_fields=set(to_apply.keys()))
        if wants_advance:
            try:
                engine.transition(row, defn)
            except seq.SequenceError as exc:
                raise _sequence_error(exc)
        else:
            _safe_restamp(row, defn)
    return DataResponse(data=_out(row, defn, ctx, user, gids))


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
    # Den Verlaufs-Eintrag schreibt die Engine (mit `actor`) – nur so ist er auch
    # bei verketteten auto_advance und beim Scheduler garantiert dabei.
    try:
        engine.transition(row, defn, expected_rev=row.get("rev"), actor=user)
    except store.ProcessTicketConflict as exc:
        raise api_error(409, "TICKET_CONFLICT", str(exc))
    except seq.SequenceError as exc:
        raise _sequence_error(exc)
    gids = vis.user_group_ids(user)
    return DataResponse(data=_out(row, defn,
                                  vis.build_viewer_ctx(user, row, defn, group_ids=gids),
                                  user, gids))


class RejectRequest(BaseModel):
    reason: str


def _melde_ablehnung(row: dict, defn, reason: str, by_name: str) -> None:
    """Ersteller:in über die Ablehnung informieren.

    Die Ablehnung ist zu diesem Zeitpunkt schon gespeichert – ein Mail-Fehler darf
    sie nicht kippen, muss aber sichtbar im Log landen (das Alt-System hat hier
    immer gemailt; stillschweigend nichts zu tun wäre die schlechteste Variante).
    """
    try:
        pactions.notify_rejection(row, defn, reason=reason, by_name=by_name)
    except Exception:
        logger.exception("Ablehnungs-Mail für #%s fehlgeschlagen", row.get("id"))


MAX_REASON_LEN = 2000


def _pflicht_begruendung(reason: Optional[str], pfad: str = "reason") -> str:
    """Begründung prüfen. Eine Ablehnung ohne Grund ist im Verlauf nicht erklärbar
    und die antragstellende Person erfährt nie, was zu ändern wäre – das Alt-System
    hat sie deshalb erzwungen."""
    text = (reason or "").strip()
    if not text:
        raise api_error(422, ErrorCode.VALIDATION_FAILED, "Begründung fehlt",
                        fields=[{"path": pfad, "code": "REQUIRED",
                                 "message": "Bitte begründen, warum abgelehnt wird"}])
    if len(text) > MAX_REASON_LEN:
        raise api_error(422, ErrorCode.VALIDATION_FAILED, "Begründung zu lang",
                        fields=[{"path": pfad, "code": "TOO_LONG",
                                 "message": f"Maximal {MAX_REASON_LEN} Zeichen"}])
    return text


@router.post("/process-tickets/{ticket_id}:reject", response_model=DataResponse[ProcessTicketOut])
def reject_process_ticket(ticket_id: int, body: RejectRequest,
                          user: dict = Depends(get_current_user)):
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
    grund = _pflicht_begruendung(body.reason)
    runtime = pr.reject(row["runtime"])
    try:
        row = store.update_runtime(ticket_id, runtime_json=json.dumps(runtime, ensure_ascii=False),
                                   status="rejected", expected_rev=row.get("rev"))
    except store.ProcessTicketConflict as exc:
        raise api_error(409, "TICKET_CONFLICT", str(exc))
    from backend.metrics.process_metrics import record_process_terminal
    record_process_terminal("rejected")
    events.record(row, events.REJECTED, actor_id=user.get("id"),
                  actor_name=_actor_name(user), body=grund)
    try:
        defn = _load_pinned_defn(row)
    except Exception:
        defn = None
    _melde_ablehnung(row, defn, grund, _actor_name(user))
    gids = vis.user_group_ids(user)
    return DataResponse(data=_out(row, defn,
                                  vis.build_viewer_ctx(user, row, defn, group_ids=gids),
                                  user, gids))


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
    if status == "rejected":
        note = _pflicht_begruendung(note, "note")

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

    # Bei Ablehnung wird der ganze Auftrag abgelehnt (wie im Alt-System) – deshalb
    # gilt hier derselbe Begründungszwang wie bei :reject.
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

    if status == "rejected":
        from backend.metrics.process_metrics import record_process_terminal
        record_process_terminal("rejected")
    events.record(row, {"done": events.DEPARTMENT_DONE,
                        "skipped": events.DEPARTMENT_SKIPPED,
                        "rejected": events.DEPARTMENT_REJECTED}[status],
                  actor_id=user.get("id"), actor_name=_actor_name(user),
                  body=note, details={"group": group_id})
    if status == "rejected":
        _melde_ablehnung(row, defn, note or "", _actor_name(user))
    return _out(row, defn, vis.build_viewer_ctx(user, row, defn, group_ids=gids),
                user, gids)


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


# ── Verlauf & Nachträge ──────────────────────────────────────────────────────

MAX_COMMENT_LEN = 5000


class EventOut(BaseModel):
    id: int
    action: str
    phase_key: Optional[str] = None
    epoch: int = 0
    actor_id: Optional[str] = None
    actor_name: Optional[str] = None
    actor_type: str = "user"
    internal: bool = False
    body: Optional[str] = None
    details: dict = {}
    created_at: Optional[str] = None


class CommentRequest(BaseModel):
    body: str
    internal: bool = False


def _load_for_view(ticket_id: int, user: dict) -> tuple[dict, Optional[ProcessDefinition], list]:
    """Ticket + gepinnte Definition laden und Leserecht prüfen."""
    row = store.get(ticket_id)
    if not row:
        raise api_error(404, "TICKET_NOT_FOUND", "Ticket nicht gefunden")
    try:
        defn = _load_pinned_defn(row)
    except Exception:
        defn = None
    return row, defn, _assert_view(row, defn, user)


@router.get("/process-tickets/{ticket_id}/events", response_model=ListResponse[EventOut])
def list_ticket_events(ticket_id: int, user: dict = Depends(get_current_user),
                       limit: int = Query(200, ge=1, le=500),
                       offset: int = Query(0, ge=0)):
    """Verlauf eines Auftrags – redigiert: Einträge über nicht sichtbare Felder
    entfallen, interne Nachträge sieht nur die bearbeitende Seite."""
    row, defn, gids = _load_for_view(ticket_id, user)
    evs, total = events.for_viewer(row, defn, user, gids, limit=limit, offset=offset)
    return ListResponse(data=[EventOut(**e) for e in evs],
                        meta=Meta(total=total, limit=limit, offset=offset))


@router.post("/process-tickets/{ticket_id}/comments", response_model=DataResponse[EventOut])
def add_ticket_comment(ticket_id: int, body: CommentRequest,
                       user: dict = Depends(get_current_user)):
    """Nachtrag schreiben. Jede Person mit Leserecht darf – ein interner Nachtrag
    nur die bearbeitende Seite (sonst könnte die antragstellende Person Text
    hinterlegen, den sie selbst anschließend nicht mehr sieht)."""
    row, defn, gids = _load_for_view(ticket_id, user)
    text = (body.body or "").strip()
    if not text:
        raise api_error(422, ErrorCode.VALIDATION_FAILED, "Nachtrag ist leer",
                        fields=[{"path": "body", "code": "REQUIRED",
                                 "message": "Bitte einen Text eingeben"}])
    if len(text) > MAX_COMMENT_LEN:
        raise api_error(422, ErrorCode.VALIDATION_FAILED, "Nachtrag zu lang",
                        fields=[{"path": "body", "code": "TOO_LONG",
                                 "message": f"Maximal {MAX_COMMENT_LEN} Zeichen"}])
    if body.internal and not acc.is_process_staff(defn, user, gids):
        raise api_error(403, ErrorCode.PERMISSION_DENIED,
                        "Interne Nachträge kann nur die bearbeitende Seite schreiben")

    # Bewusst `write` (nicht `record`): geht der Nachtrag verloren, muss der
    # Aufrufer einen Fehler sehen und nicht ein stilles „gespeichert".
    ev = events.write(row, events.COMMENT, actor_id=user.get("id"),
                      actor_name=_actor_name(user), internal=body.internal, body=text)
    try:
        recips = pactions.notify_comment(
            row, pr.current_phase(defn, row["runtime"]) if defn else None,
            author_name=_actor_name(user), body_text=text, internal=body.internal,
            actor_email=user.get("email") or user.get("mail"))
        if recips:
            logger.info("Nachtrag zu #%s an %s Empfänger", ticket_id, len(recips))
    except Exception:
        logger.exception("Nachtrags-Mail für #%s fehlgeschlagen", ticket_id)
    return DataResponse(data=EventOut(**ev))


# ── Wiederaufnahme ───────────────────────────────────────────────────────────

class ReopenRequest(BaseModel):
    reason: str
    phase: Optional[str] = None


@router.post("/process-tickets/{ticket_id}:archive", response_model=DataResponse[ProcessTicketOut])
def archive_process_ticket(ticket_id: int, body: RejectRequest,
                           user: dict = Depends(get_current_user)):
    """Auftrag zwangsweise abschließen (Admin-Notfalleingriff).

    Für Fälle, in denen ein Auftrag hängt, den niemand mehr weiterschalten kann –
    etwa weil die zuständige Gruppe aufgelöst wurde. Der Grund ist Pflicht, sonst
    steht im Verlauf ein Abschluss ohne Erklärung. Rückholbar über :reopen.
    """
    row = store.get(ticket_id)
    if not row:
        raise api_error(404, "TICKET_NOT_FOUND", "Ticket nicht gefunden")
    if not acc.is_admin(user):
        raise api_error(403, ErrorCode.ADMIN_REQUIRED,
                        "Nur Admins können einen Auftrag zwangsweise abschließen")
    if _is_terminal(row):
        raise api_error(409, ErrorCode.PROCESS_INVALID_STATE,
                        "Der Auftrag ist bereits abgeschlossen/abgelehnt")
    grund = _pflicht_begruendung(body.reason)
    runtime = pr.force_archive(row["runtime"])
    try:
        row = store.update_runtime(ticket_id, runtime_json=json.dumps(runtime, ensure_ascii=False),
                                   status="archived", expected_rev=row.get("rev"))
    except store.ProcessTicketConflict as exc:
        raise api_error(409, "TICKET_CONFLICT", str(exc))
    from backend.metrics.process_metrics import record_process_terminal
    record_process_terminal("archived")
    try:
        defn = _load_pinned_defn(row)
    except Exception:
        defn = None
    events.record(row, events.ADVANCED, actor_id=user.get("id"), actor_name=_actor_name(user),
                  body=grund, details={"from_phase": None, "to_phase": None,
                                       "status": "archived", "forced": True})
    _safe_restamp(row, defn) if defn else store.set_next_timer(ticket_id, None)
    gids = vis.user_group_ids(user)
    return DataResponse(data=_out(row, defn,
                                  vis.build_viewer_ctx(user, row, defn, group_ids=gids),
                                  user, gids))


@router.delete("/process-tickets/{ticket_id}")
def delete_process_ticket(ticket_id: int, user: dict = Depends(get_current_user)):
    """Auftrag endgültig löschen (Admin).

    Vor der Löschung wird auditiert – der Audit-Eintrag überlebt sie bewusst,
    sonst wäre nicht mehr nachvollziehbar, dass es den Auftrag je gab. Die
    vergebenen Nummern-Ansprüche bleiben stehen: eine ausgegebene Personalnummer
    darf nicht erneut vergeben werden.
    """
    row = store.get(ticket_id)
    if not row:
        raise api_error(404, "TICKET_NOT_FOUND", "Ticket nicht gefunden")
    if not acc.is_admin(user):
        raise api_error(403, ErrorCode.ADMIN_REQUIRED, "Nur Admins können Aufträge löschen")
    record_audit(
        action="process_ticket_deleted", actor_id=user.get("id"),
        actor_name=_actor_name(user), entity_type="process_ticket", entity_id=str(ticket_id),
        summary=f"Prozess-Ticket #{ticket_id} gelöscht: {row.get('title')}",
        details={"process_key": row.get("process_key"), "status": row.get("status"),
                 "owner_id": row.get("owner_id")},
    )
    store.delete(ticket_id)
    return DataResponse(data={"deleted": ticket_id})


@router.post("/process-tickets/{ticket_id}:reopen", response_model=DataResponse[ProcessTicketOut])
def reopen_process_ticket(ticket_id: int, body: ReopenRequest,
                          user: dict = Depends(get_current_user)):
    """Abgeschlossenen/abgelehnten Auftrag wieder aufnehmen.

    Nur Admin (Notfall-Eingriff in einen fertigen Auftrag). Ein Grund ist Pflicht –
    ohne ihn wäre im Verlauf nicht nachvollziehbar, warum ein fertiger Auftrag
    wieder offen ist. Nicht für aktive Aufträge: „zurück zu Phase X" ist eine
    andere Aktion und hat hier absichtlich keinen Einstieg.
    """
    row = store.get(ticket_id)
    if not row:
        raise api_error(404, "TICKET_NOT_FOUND", "Ticket nicht gefunden")
    if not acc.is_admin(user):
        raise api_error(403, ErrorCode.ADMIN_REQUIRED,
                        "Nur Admins können einen abgeschlossenen Auftrag wieder aufnehmen")
    defn = _load_pinned_defn(row)
    if not _is_terminal(row):
        raise api_error(409, ErrorCode.PROCESS_INVALID_STATE,
                        "Der Auftrag ist noch aktiv – hier gibt es nichts wieder aufzunehmen")
    reason = (body.reason or "").strip()
    if not reason:
        raise api_error(422, ErrorCode.VALIDATION_FAILED, "Grund fehlt",
                        fields=[{"path": "reason", "code": "REQUIRED",
                                 "message": "Bitte begründen, warum der Auftrag wieder aufgenommen wird"}])

    try:
        runtime, status = pr.reopen(defn, row["runtime"], utcnow_iso(),
                                    phase_key=body.phase, values=row.get("values") or {})
    except ValueError as exc:
        raise api_error(422, ErrorCode.VALIDATION_FAILED, str(exc),
                        fields=[{"path": "phase", "code": "UNKNOWN_REF", "message": str(exc)}])
    try:
        row = store.update_runtime(ticket_id, runtime_json=json.dumps(runtime, ensure_ascii=False),
                                   status=status, expected_rev=row.get("rev"))
    except store.ProcessTicketConflict as exc:
        raise api_error(409, "TICKET_CONFLICT", str(exc))

    phase = pr.current_phase(defn, row["runtime"])
    events.write(row, events.REOPENED, actor_id=user.get("id"), actor_name=_actor_name(user),
                 body=reason, details={"phase": phase.key if phase else None,
                                       "epoch": runtime.get("epoch")})
    # Die Phase wird ERNEUT betreten: on_enter-Automationen und die
    # Zuständigkeits-Mail müssen laufen, sonst wartet die Stelle auf nichts.
    engine.run_inline(row, defn, phase, {TriggerType.on_enter})
    try:
        pactions.notify_phase_entry(row, defn, phase)
    except Exception:
        logger.exception("Benachrichtigung nach Wiederaufnahme von #%s fehlgeschlagen", ticket_id)
    _safe_restamp(row, defn)
    gids = vis.user_group_ids(user)
    return DataResponse(data=_out(row, defn,
                                  vis.build_viewer_ctx(user, row, defn, group_ids=gids),
                                  user, gids))


# ── Beobachter:innen ─────────────────────────────────────────────────────────

class WatcherOut(BaseModel):
    id: str
    name: Optional[str] = None
    added_by: Optional[str] = None
    created_at: Optional[str] = None


class WatcherRequest(BaseModel):
    userId: Optional[str] = None      # leer = sich selbst eintragen


def _display_name(user_id: str) -> Optional[str]:
    """Anzeigename einer Person (denormalisiert in der Watcher-Zeile).

    `get_user` liefert eine Dataclass, kein dict – deshalb getattr.
    """
    try:
        from backend.database.users import get_user
        row = get_user(user_id)
        if row is None:
            return None
        if isinstance(row, dict):
            return row.get("displayName") or row.get("display_name") or row.get("email")
        return getattr(row, "display_name", None) or getattr(row, "email", None)
    except Exception:
        logger.warning("Anzeigename für %s nicht auflösbar", user_id)
        return None


@router.get("/process-tickets/{ticket_id}/watchers", response_model=ListResponse[WatcherOut])
def list_ticket_watchers(ticket_id: int, user: dict = Depends(get_current_user)):
    row, _defn, _gids = _load_for_view(ticket_id, user)
    rows = watchers.list_watchers(row["id"])
    return ListResponse(data=[WatcherOut(**w) for w in rows],
                        meta=Meta(total=len(rows), limit=len(rows), offset=0))


@router.post("/process-tickets/{ticket_id}/watchers", response_model=ListResponse[WatcherOut])
def add_ticket_watcher(ticket_id: int, body: Optional[WatcherRequest] = None,
                       user: dict = Depends(get_current_user)):
    """Beobachter:in eintragen.

    Sich selbst darf jede Person mit Leserecht. FREMDE einzutragen ist eine
    Rechte-Vergabe (der/die Eingetragene darf den Auftrag danach lesen) – das
    dürfen nur die zuständige Stelle und Admins.
    """
    row, defn, gids = _load_for_view(ticket_id, user)
    target = (body.userId if body else None) or user.get("id")
    if not target:
        raise api_error(422, ErrorCode.VALIDATION_FAILED, "Keine Person angegeben",
                        fields=[{"path": "userId", "code": "REQUIRED", "message": "Pflichtfeld"}])
    if target != user.get("id") and not acc.may_edit(defn, row, user, gids):
        raise api_error(403, ErrorCode.TICKET_FORBIDDEN,
                        "Nur die zuständige Stelle kann andere Personen als Beobachter eintragen")

    name = (_actor_name(user) if target == user.get("id") else _display_name(target))
    if watchers.add_watcher(row["id"], target, name, added_by=user.get("id")):
        events.record(row, events.WATCHER_ADDED, actor_id=user.get("id"),
                      actor_name=_actor_name(user),
                      details={"watcher": target, "watcher_name": name})
    rows = watchers.list_watchers(row["id"])
    return ListResponse(data=[WatcherOut(**w) for w in rows],
                        meta=Meta(total=len(rows), limit=len(rows), offset=0))


@router.delete("/process-tickets/{ticket_id}/watchers/{watcher_id}",
               response_model=ListResponse[WatcherOut])
def remove_ticket_watcher(ticket_id: int, watcher_id: str,
                          user: dict = Depends(get_current_user)):
    """Beobachtung beenden. Sich selbst immer; andere nur die zuständige Stelle."""
    row, defn, gids = _load_for_view(ticket_id, user)
    if watcher_id != user.get("id") and not acc.may_edit(defn, row, user, gids):
        raise api_error(403, ErrorCode.TICKET_FORBIDDEN,
                        "Nur die zuständige Stelle kann andere Beobachter:innen entfernen")
    if watchers.remove_watcher(row["id"], watcher_id):
        events.record(row, events.WATCHER_REMOVED, actor_id=user.get("id"),
                      actor_name=_actor_name(user), details={"watcher": watcher_id})
    rows = watchers.list_watchers(row["id"])
    return ListResponse(data=[WatcherOut(**w) for w in rows],
                        meta=Meta(total=len(rows), limit=len(rows), offset=0))
