import json
from datetime import datetime

from fastapi import APIRouter, Request, Depends, Query
from typing import Optional
from backend.core.dependencies import get_current_user
from backend.database import tickets as database
from backend.models.models import RequestStatus, TicketType
from backend.services.ticket_history import add_history_event
from backend.services.microsoft_graph import get_cached_user_mail
from backend.services.microsoft_mail import send_newrequest_mail, send_mail_to_all_fachabteilung
from backend.services.ticket_permissions import can_user_create_ticket
from backend.schemas.ticket import (
    TicketOut, TicketCreateRequest, TicketUpdateRequest, UserOut, BasisTicketCreateRequest,
    ResponsibilityOverrideRequest, LockState,
    RawTicketUpdateRequest, BulkTicketActionRequest, BulkActionResult,
)
from backend.schemas.responses import (
    DataResponse, ListResponse, Meta, ErrorCode, api_error,
)
from backend.api.v1.ticket_overview import build_overview_detail, TicketOverviewDetail
from backend.services.bulk_actions import normalize_bulk_action, required_permission_for_bulk
from backend.database.users import PERM_MANAGE, PERM_ADMIN
from backend.database.audit_log import record_audit
from backend.services.workflow_state import (
    build_workflow, set_workflow_state, advance_phase,
    reject_workflow, get_current_phase, all_required_departments_done,
)
from backend.utils.ticket_labels import TICKET_LABELS
from backend.utils.logger import logger
from backend.metrics.ticket_metrics import tickets_created_total
from zoneinfo import ZoneInfo
router = APIRouter()


def _user_can_delete_ticket(user: dict, ticket_id: int) -> bool:
    """Admins oder Besitzer dürfen löschen."""
    if user.get("is_admin", False):
        return True
    try:
        owned = database.list_tickets_by_owner(user["id"])
    except Exception:
        logger.exception("Konnte Tickets des Users nicht laden")
        return False
    return any(t.id == ticket_id for t in owned)


def _onb_field(desc: dict, key: str, default: str = "") -> str:
    """Onboarding-Basisfeld lesen: neu aus 'base', Fallback altes 'personal'
    (Legacy-Tickets vor der Basisdaten-Umstellung). Greift auch fuer
    zugang_sperren, wo Name/Firma weiterhin unter personal liegen."""
    base = desc.get("base") or {}
    val = base.get(key)
    if val not in (None, ""):
        return val
    return (desc.get("personal") or {}).get(key, default)


def generate_title(ticket_type, user, desc):
    now_str = datetime.now(ZoneInfo("Europe/Berlin")).strftime("%Y-%m-%d %H:%M")

    if isinstance(desc, str):
        desc = json.loads(desc)

    name = f"{_onb_field(desc, 'first_name')} {_onb_field(desc, 'last_name')}".strip()

    if ticket_type == TicketType.zugang_beantragen:
        label = f"Onboarding Mitarbeiter:innen – {name}"
    elif ticket_type == TicketType.zugang_sperren:
        label = f"Offboarding Mitarbeiter:innen – {name}"
    elif ticket_type == TicketType.marketing_stellenanzeige:
        stelle = desc.get("stelle", {})

        unit = stelle.get("gesellschaft", "")
        Niederlassung = stelle.get("niederlassung", "")
        Job = stelle.get("berufsbezeichnung", "")

        label = f"{unit}_{Niederlassung}_{Job}"
    elif ticket_type == TicketType.hotelbuchung:
        label = f"Hotelbuchung – {user['displayName']}"
    elif ticket_type == TicketType.basis_ticket:
        ticket_data = desc.get("ticket", {})
        betreff = ticket_data.get("betreff", "").strip()
        label = f"Basis-Ticket – {betreff}" if betreff else f"Basis-Ticket – {user['displayName']}"
    else:
        label = TICKET_LABELS.get(ticket_type, ticket_type.value)

    return f"{label} – {now_str}"


def validate_assignee(user_cache, assignee_id: str) -> bool:
    if not assignee_id:
        return False
    # Platzhalter für Ticket-Typen ohne Bearbeitungsphase (z.B. Marketing,
    # Hotelbuchung) – sie gehen direkt in die Durchführung; die Zuständigkeit
    # steht im workflow_state.departments, nicht im assignee.
    if assignee_id == "fachabteilung":
        return True
    # Check if it's a valid group ID
    from backend.database.groups import get_groups
    group_ids = {g["id"] for g in get_groups()}
    if assignee_id in group_ids:
        return True
    return any(u.get("id") == assignee_id for u in user_cache)


def _build_and_init_workflow(ticket) -> dict:
    """Builds workflow, saves it, advances past the creation phase. Returns updated workflow."""
    workflow = build_workflow(ticket)
    set_workflow_state(ticket.id, workflow)
    return advance_phase(ticket.id)


def notify_phase_entry(request, ticket, phase: Optional[dict]) -> None:
    """
    Benachrichtigt die für die (gerade aktiv gewordene) Phase Zuständigen –
    zentral genutzt von create_ticket und submit_ticket.
      - department_review        → Mail an alle Fachabteilungs-Verteiler
      - assignment + view=approval → Freigabe-Mail (JA/NEIN) an Gruppen-Verteiler
      - assignment + kind=group  → Mail an Gruppen-Verteiler
      - assignment + kind=user   → Mail an die Person
    """
    if not phase:
        return
    from backend.services.phase_definitions import PhaseType, PhaseView
    from backend.database.groups import get_distributions_from_group

    ptype = phase.get("type")
    if ptype == PhaseType.department_review.value:
        send_mail_to_all_fachabteilung(phase.get("departments", {}), ticket)
        return

    resp = phase.get("responsibility") or {}
    kind = resp.get("kind")

    # Freigabe-Phase: Mail mit JA/NEIN-Buttons (signierte Links) an die Verteiler
    if phase.get("view") == PhaseView.approval.value and kind == "group":
        from backend.services.freigabe_token import make_token
        from backend.services.microsoft_mail import send_freigabe_mail
        from backend.utils.config import config
        base = config.FRONTEND_URL.rstrip("/")
        approve_url = f"{base}/api/v1/freigabe?token={make_token(ticket.id, 'approve')}"
        reject_url  = f"{base}/api/v1/freigabe?token={make_token(ticket.id, 'reject')}"
        recipients = [m.strip() for m in get_distributions_from_group(resp.get("id")) if m]
        send_freigabe_mail(ticket, approve_url, reject_url, recipients)
        return

    if kind == "group":
        for mail in get_distributions_from_group(resp.get("id")):
            if mail:
                send_newrequest_mail(mail.strip(), ticket.priority, ticket.title, ticket.ticket_type, ticket.id)
    elif kind == "user":
        mail_to = get_cached_user_mail(request.app, resp.get("id"))
        if mail_to:
            send_newrequest_mail(mail_to, ticket.priority, ticket.title, ticket.ticket_type, ticket.id)


# ── Permission helpers ────────────────────────────────────────────────────────

def _require_admin(user: dict) -> dict:
    if PERM_ADMIN not in user.get("permissions", []):
        raise api_error(403, ErrorCode.ADMIN_REQUIRED, "Admin-Rechte erforderlich")
    return user


def _require_manage(user: dict) -> dict:
    if PERM_MANAGE not in user.get("permissions", []):
        raise api_error(403, ErrorCode.TICKET_FORBIDDEN, "Keine Berechtigung")
    return user


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    return _require_admin(user)


# ── Ticket helpers ─────────────────────────────────────────────────────────────

def _get_ticket_or_404(ticket_id: int):
    ticket = database.get_ticket(ticket_id)
    if not ticket:
        raise api_error(404, ErrorCode.TICKET_NOT_FOUND, "Ticket nicht gefunden")
    return ticket


def _assert_ticket_access(ticket, user: dict):
    """Ersteller, in der aktuellen Phase Zuständige (Person/Gruppe/Reviewing-
    Fachabteilungen), Beobachter oder Manager/Admin dürfen zugreifen.
    Die alten assignee/accountable-Spalten werden NICHT mehr ausgewertet –
    Zuständigkeit kommt aus dem workflow_state."""
    user_id = user["id"]

    if ticket.owner_id == user_id:
        return
    if PERM_MANAGE in user.get("permissions", []):
        return

    from backend.database.groups import get_group_ids_for_user
    user_group_ids = get_group_ids_for_user(user_id)

    # In der aktuellen Phase zuständig (Person, Gruppe oder Reviewing-Fachabteilung)?
    from backend.services.workflow_state import user_is_responsible
    if user_is_responsible(ticket, user_id, user_group_ids):
        return

    # Beobachter dürfen das Ticket sehen
    from backend.database.ticket_watchers import is_watcher
    if is_watcher(ticket.id, user_id):
        return

    raise api_error(403, ErrorCode.TICKET_FORBIDDEN, "Kein Zugriff auf dieses Ticket")


def _assert_not_locked_by_other(ticket_id: int, user: dict) -> None:
    """Schreibzugriff verweigern, wenn ein ANDERER Nutzer den Edit-Lock hält.
    Admins umgehen den Lock (können ihn per Force-Unlock ohnehin aufheben)."""
    if PERM_ADMIN in user.get("permissions", []):
        return
    from backend.database.ticket_locks import get_active_lock
    lock = get_active_lock(ticket_id)
    if lock and lock["holder_id"] != user["id"]:
        raise api_error(
            423, ErrorCode.TICKET_LOCKED,
            f"Ticket wird gerade von {lock['holder_name'] or 'einer anderen Person'} bearbeitet.",
        )


# ══════════════════════════════════════════════════════════════════════════════
# AUTH
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/auth/me", response_model=DataResponse[UserOut])
def get_me(user: dict = Depends(get_current_user)):
    return DataResponse(data=UserOut(
        id=user["id"],
        displayName=user["displayName"],
        mail=user.get("mail") or user.get("email"),
        permissions=user.get("permissions", []),
    ))


# ══════════════════════════════════════════════════════════════════════════════
# TICKETS – User
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/tickets", response_model=ListResponse[TicketOut])
def list_my_tickets(user: dict = Depends(get_current_user)):
    items = database.list_tickets_by_owner(user["id"])
    return ListResponse(
        data=[TicketOut.from_ticket(t, user=user) for t in items],
        meta=Meta(total=len(items), limit=len(items), offset=0),
    )


@router.get("/tickets/{ticket_id}", response_model=DataResponse[TicketOut])
def get_ticket(ticket_id: int, user: dict = Depends(get_current_user)):
    ticket = _get_ticket_or_404(ticket_id)
    _assert_ticket_access(ticket, user)
    from backend.database.ticket_watchers import list_watchers
    return DataResponse(data=TicketOut.from_ticket(ticket, watchers=list_watchers(ticket_id), user=user))


# ── Beobachter (Watcher) ──────────────────────────────────────────────────────
# Jeder mit Ticket-Zugriff darf die Beobachterliste lesen und ändern.

@router.get("/tickets/{ticket_id}/watchers")
def get_ticket_watchers(ticket_id: int, user: dict = Depends(get_current_user)):
    ticket = _get_ticket_or_404(ticket_id)
    _assert_ticket_access(ticket, user)
    from backend.database.ticket_watchers import list_watchers
    return DataResponse(data={"watchers": list_watchers(ticket_id)})


@router.post("/tickets/{ticket_id}/watchers", status_code=201)
async def add_ticket_watcher(ticket_id: int, request: Request, user: dict = Depends(get_current_user)):
    ticket = _get_ticket_or_404(ticket_id)
    _assert_ticket_access(ticket, user)
    body = await request.json()
    watcher_id = (body.get("user_id") or "").strip()
    watcher_name = (body.get("user_name") or "").strip()
    if not watcher_id:
        raise api_error(400, ErrorCode.INVALID_WATCHER, "user_id ist erforderlich")
    from backend.database.ticket_watchers import add_watcher, list_watchers
    add_watcher(ticket_id, watcher_id, watcher_name or None)
    return DataResponse(data={"watchers": list_watchers(ticket_id)})


@router.delete("/tickets/{ticket_id}/watchers/{watcher_id}")
def remove_ticket_watcher(ticket_id: int, watcher_id: str, user: dict = Depends(get_current_user)):
    ticket = _get_ticket_or_404(ticket_id)
    _assert_ticket_access(ticket, user)
    from backend.database.ticket_watchers import remove_watcher, list_watchers
    remove_watcher(ticket_id, watcher_id)
    return DataResponse(data={"watchers": list_watchers(ticket_id)})


@router.get("/ticket-phases/{ticket_type}")
def get_ticket_phases(ticket_type: TicketType, user: dict = Depends(get_current_user)):
    """
    Phasen-Vorschau für einen Tickettyp (statische Definition aus TICKET_PHASES,
    ohne dass ein Ticket existiert) – für die Ablauf-Anzeige beim Erstellen.
    """
    from backend.services.phase_definitions import TICKET_PHASES
    defs = TICKET_PHASES.get(ticket_type, [])
    return DataResponse(data=[
        {"key": p.key, "label": p.label, "type": p.type.value} for p in defs
    ])


@router.post("/tickets", response_model=DataResponse[TicketOut], status_code=201)
async def create_ticket(
    data: TicketCreateRequest,
    request: Request,
    user: dict = Depends(get_current_user),
):
    # Basis-Tickets haben einen eigenen Endpoint
    if data.ticket_type == TicketType.basis_ticket:
        raise api_error(400, ErrorCode.INVALID_DESCRIPTION,
                        "Basis-Tickets bitte über POST /tickets/basis erstellen")

    if not can_user_create_ticket(data.ticket_type.value, user["id"], user.get("groups")):
        raise api_error(403, ErrorCode.TICKET_FORBIDDEN,
                        f"Kein Recht zum Erstellen von '{data.ticket_type.value}'-Tickets")
    # Assignee wird erst geprüft, wenn die erste Phase nach der Erstellung wirklich
    # einen frei wählbaren Bearbeiter braucht (siehe unten). Tickettypen mit fester
    # Zuständigkeit der ersten Phase (assign_group/Freigabe/Fachabteilungen) kommen
    # ohne Assignee aus.
    try:
        json.loads(data.description)   # nur Validierung: muss gültiges JSON sein
    except Exception:
        raise api_error(400, ErrorCode.INVALID_DESCRIPTION,
                        "description muss gültiges JSON sein")

    description = data.description
    # Hinweis: Die Personalnummer wird NICHT bei der Erstellung vergeben, sondern
    # erst beim Abschluss der BackOffice-Phase (endgültige „Firma lt. Arbeitsvertrag“)
    # – siehe _assign_onboarding_personalnummer() in submit_ticket.

    title = generate_title(data.ticket_type, user, description)
    ticket_id = request.app.state.manager.create_ticket(
        title=title,
        ticket_type=data.ticket_type,
        description=description,
        owner_id=user["id"],
        owner_name=user["displayName"],
        owner_info=json.dumps(user, ensure_ascii=False),
        comment=data.comment,
        priority=data.priority,
    )
    add_history_event(
        ticket_id,
        actor_id=user["id"],
        actor_name=user["displayName"],
        action="ticket_created",
        details={"priority": data.priority.value, "ticket_type": data.ticket_type.value},
    )
    tickets_created_total.labels(type=data.ticket_type.value).inc()

    # Beobachter: vom Client übergebene Liste (inkl. Ersteller), sonst nur Ersteller
    from backend.database.ticket_watchers import add_watcher
    if data.watchers:
        for w in data.watchers:
            add_watcher(ticket_id, w.id, w.name)
    else:
        add_watcher(ticket_id, user["id"], user["displayName"])

    ticket = database.get_ticket(ticket_id)
    updated_workflow = _build_and_init_workflow(ticket)
    ticket = database.get_ticket(ticket_id)

    # Phase nach dem Vorbei-Advancen der Erstellung
    from backend.services.workflow_state import PhaseType as WfPhaseType, set_phase_responsibility
    phases = updated_workflow.get("phases", [])
    current_idx = updated_workflow.get("current_phase_index", 0)
    current_phase = phases[current_idx] if current_idx < len(phases) else None

    # Nur wenn die erste Phase eine assignment-Phase OHNE feste Zuständigkeit ist
    # (kein assign_group), muss der Client einen Bearbeiter mitliefern.
    needs_assignee = (
        current_phase is not None
        and current_phase.get("type") == WfPhaseType.assignment.value
        and not (current_phase.get("responsibility") or {}).get("kind")
    )
    if needs_assignee:
        if not validate_assignee(request.app.state.user_cache, data.assignee_id):
            raise api_error(400, ErrorCode.INVALID_ASSIGNEE,
                            f"Unbekannter Assignee '{data.assignee_id}'")
        from backend.database.groups import get_groups
        group_map = {g["id"]: g["name"] for g in get_groups()}
        if data.assignee_id in group_map:
            set_phase_responsibility(ticket_id, current_idx,
                {"kind": "group", "id": data.assignee_id, "name": group_map[data.assignee_id]})
        else:
            set_phase_responsibility(ticket_id, current_idx,
                {"kind": "user", "id": data.assignee_id, "name": data.assignee_name})
        ticket = database.get_ticket(ticket_id)
        current_phase = ticket.workflow_state_parsed.get("phases", [])[current_idx]

    if current_phase and current_phase.get("type") == WfPhaseType.department_review.value:
        add_history_event(
            ticket_id,
            actor_id=user["id"],
            actor_name=user["displayName"],
            action="ticket_submitted",
            details={"status_new": RequestStatus.in_request.value},
        )

    notify_phase_entry(request, ticket, current_phase)

    return DataResponse(data=TicketOut.from_ticket(database.get_ticket(ticket_id), user=user))


# ── Basis-Ticket (eigener Endpoint, keine Permission-Prüfung) ─────────────────




@router.post("/tickets/basis", response_model=DataResponse[TicketOut], status_code=201)
async def create_basis_ticket(
    data: BasisTicketCreateRequest,
    request: Request,
    user: dict = Depends(get_current_user),
):
    # Keine Permission-Prüfung – jeder eingeloggte User darf Basis-Tickets erstellen

    if not validate_assignee(request.app.state.user_cache, data.assignee_id):
        raise api_error(400, ErrorCode.INVALID_ASSIGNEE,
                        f"Unbekannter Assignee '{data.assignee_id}'")
    try:
        json.loads(data.description)
    except Exception:
        raise api_error(400, ErrorCode.INVALID_DESCRIPTION,
                        "description muss gültiges JSON sein")

    # Basis-Tickets sind ausschließlich Fachabteilungen zuweisbar (keine Personen).
    from backend.database.groups import get_groups
    group_map = {g["id"]: g["name"] for g in get_groups()}
    if data.assignee_id not in group_map:
        raise api_error(400, ErrorCode.INVALID_ASSIGNEE,
                        "Basis-Tickets können nur einer Fachabteilung zugewiesen werden")

    now_str = datetime.now(ZoneInfo("Europe/Berlin")).strftime("%Y-%m-%d %H:%M")
    title = f"{data.title.strip()} – {now_str}" if data.title.strip() else f"Basis-Ticket – {user['displayName']} – {now_str}"

    ticket_id = request.app.state.manager.create_ticket(
        title=title,
        ticket_type=TicketType.basis_ticket,
        description=data.description,
        owner_id=user["id"],
        owner_name=user["displayName"],
        owner_info=json.dumps(user, ensure_ascii=False),
        comment=data.comment or "",
        priority=data.priority or "medium",
    )
    add_history_event(
        ticket_id,
        actor_id=user["id"],
        actor_name=user["displayName"],
        action="ticket_created",
        details={"priority": data.priority, "ticket_type": "basis-ticket"},
    )
    tickets_created_total.labels(type=TicketType.basis_ticket.value).inc()

    # Beobachter: vom Client übergebene Liste (inkl. Ersteller), sonst nur Ersteller
    from backend.database.ticket_watchers import add_watcher
    if data.watchers:
        for w in data.watchers:
            add_watcher(ticket_id, w.id, w.name)
    else:
        add_watcher(ticket_id, user["id"], user["displayName"])

    # Workflow aufbauen und an der Erstellungsphase vorbei in die Bearbeitung schieben.
    # Basis-Tickets haben Phasen [creation, assignment] – danach immer Assignment-Phase.
    ticket = database.get_ticket(ticket_id)
    updated_workflow = _build_and_init_workflow(ticket)
    current_idx = updated_workflow.get("current_phase_index", 0)

    # Zuständigkeit der Bearbeitungsphase (immer eine Fachabteilung) in den
    # Workflow schreiben + Verteiler der Gruppe benachrichtigen.
    from backend.services.workflow_state import set_phase_responsibility
    set_phase_responsibility(ticket_id, current_idx,
        {"kind": "group", "id": data.assignee_id, "name": group_map[data.assignee_id]})
    for g in get_groups():
        if g["id"] == data.assignee_id:
            for mail in g.get("distributions", []):
                if mail:
                    send_newrequest_mail(mail.strip(), data.priority, title, TicketType.basis_ticket, ticket_id)
            break

    return DataResponse(data=TicketOut.from_ticket(database.get_ticket(ticket_id), user=user))


@router.patch("/tickets/{ticket_id}", response_model=DataResponse[TicketOut])
async def update_ticket(
    ticket_id: int,
    data: TicketUpdateRequest,
    request: Request,
    user: dict = Depends(get_current_user),
):
    ticket = _get_ticket_or_404(ticket_id)
    _assert_ticket_access(ticket, user)
    _assert_not_locked_by_other(ticket_id, user)

    # Eingeschränkte Fachabteilungen sehen die Beschreibung nur gefiltert und dürfen
    # sie daher nicht speichern – ihr Client kennt die versteckten Abschnitte nicht
    # und würde sie sonst überschreiben. Sie steuern nur ihren Fachabteilungs-Status.
    from backend.services.ticket_visibility import is_restricted_viewer
    if is_restricted_viewer(ticket, user):
        raise api_error(403, ErrorCode.TICKET_FORBIDDEN,
                        "Kein Schreibzugriff auf die Beschreibung dieses Tickets")

    # assignee_id/assignee_name werden beim PATCH ignoriert (siehe unten) – daher
    # hier auch keine Assignee-Validierung mehr.

    # --- Änderungen tracken (old → new) ---
    changes = {}

    if data.priority is not None and data.priority != ticket.priority:
        changes["priority"] = {"old": ticket.priority.value, "new": data.priority.value}

    if data.comment is not None:
        stripped = data.comment.strip()
        if stripped != ticket.comment:
            changes["comment"] = {"old": ticket.comment, "new": stripped}

    if data.description is not None and data.description != ticket.description:
        try:
            old_desc = json.loads(ticket.description) if ticket.description else {}
            new_desc = json.loads(data.description)
        except Exception:
            old_desc, new_desc = ticket.description, data.description
        changes["description"] = {"old": old_desc, "new": new_desc}

    # --- DB Update ---
    updates = {k: v for k, v in {
        "description": data.description,
        "comment":     data.comment.strip() if data.comment else None,
        "priority":    data.priority.value if data.priority else None,
    }.items() if v is not None}

    if updates:
        database.update_ticket(ticket_id=ticket_id, **updates)

    # Hinweis: Ein PATCH (Feld-Speichern) ändert BEWUSST NICHT die Zuständigkeit.
    # Die Zuständigkeit wird ausschließlich bei der Erstellung (create_ticket) und
    # beim Weitergeben (submit_ticket, „nächster Bearbeiter") gesetzt. Früher schrieb
    # jedes PATCH das mitgesendete assignee_id als aktuelle Phasen-Zuständigkeit –
    # eine veraltete/falsche Vorbefüllung (z.B. Freigabe-Gruppe beim Onboarding)
    # hat dadurch beim Speichern die echte Zuständigkeit überschrieben. data.assignee_id
    # wird hier deshalb ignoriert.

    # --- Ein gebündeltes History-Event für alle Änderungen ---
    if changes:
        add_history_event(
            ticket_id,
            actor_id=user["id"],
            actor_name=user["displayName"],
            action="ticket_updated",
            details={"changes": changes},
        )

    return DataResponse(data=TicketOut.from_ticket(database.get_ticket(ticket_id), user=user))


# ══════════════════════════════════════════════════════════════════════════════
# EDIT-LOCKS – pessimistisches Sperren der Bearbeitungsansicht
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/tickets/{ticket_id}/lock", response_model=DataResponse[LockState])
def acquire_ticket_lock(ticket_id: int, user: dict = Depends(get_current_user)):
    """
    Sperrt das Ticket für den aufrufenden Nutzer (beim Öffnen der Bearbeitung).
    Erfolgt still, wenn frei/eigener/abgelaufener Lock. Hält jemand anderes einen
    aktiven Lock, kommt is_me=False + holder_* zurück (Frontend zeigt Popup).
    """
    ticket = _get_ticket_or_404(ticket_id)
    _assert_ticket_access(ticket, user)
    from backend.database.ticket_locks import acquire_lock
    state = acquire_lock(ticket_id, user["id"], user["displayName"])
    return DataResponse(data=LockState(**state))


@router.post("/tickets/{ticket_id}/lock/heartbeat", response_model=DataResponse[LockState])
def heartbeat_ticket_lock(ticket_id: int, user: dict = Depends(get_current_user)):
    """Lebenszeichen des Editors – hält den Lock aktiv. is_me=False → Lock verloren."""
    from backend.database.ticket_locks import refresh_lock, get_active_lock
    still_mine = refresh_lock(ticket_id, user["id"])
    if still_mine:
        return DataResponse(data=LockState(locked=True, is_me=True,
                                           holder_id=user["id"], holder_name=user["displayName"]))
    lock = get_active_lock(ticket_id)
    if lock:
        return DataResponse(data=LockState(locked=True, is_me=False,
                                           holder_id=lock["holder_id"], holder_name=lock["holder_name"],
                                           age_seconds=lock["age_seconds"]))
    return DataResponse(data=LockState(locked=False, is_me=False))


@router.delete("/tickets/{ticket_id}/lock", status_code=204)
def release_ticket_lock(ticket_id: int, user: dict = Depends(get_current_user)):
    """Gibt den eigenen Lock frei (beim Verlassen der Bearbeitung)."""
    from backend.database.ticket_locks import release_lock
    release_lock(ticket_id, user["id"])


@router.get("/tickets/{ticket_id}/lock", response_model=DataResponse[LockState])
def get_ticket_lock(ticket_id: int, user: dict = Depends(get_current_user)):
    """Aktuellen Sperr-Status abfragen (z.B. für die read-only Übersicht)."""
    ticket = _get_ticket_or_404(ticket_id)
    _assert_ticket_access(ticket, user)
    from backend.database.ticket_locks import get_active_lock
    lock = get_active_lock(ticket_id)
    if not lock:
        return DataResponse(data=LockState(locked=False, is_me=False))
    return DataResponse(data=LockState(
        locked=True,
        is_me=lock["holder_id"] == user["id"],
        holder_id=lock["holder_id"],
        holder_name=lock["holder_name"],
        age_seconds=lock["age_seconds"],
    ))


def _assign_onboarding_personalnummer(ticket_id: int, user: dict) -> None:
    """
    Vergibt die Personalnummer anhand der aktuellen „Firma lt. Arbeitsvertrag"
    (contract_company), sofern noch keine gesetzt ist. Wird beim Abschluss der
    BackOffice-Phase aufgerufen. Wirft api_error, wenn kein Bereich hinterlegt
    oder erschöpft ist (dann wird die Phase nicht weitergeschaltet).
    """
    ticket = database.get_ticket(ticket_id)
    try:
        desc_obj = json.loads(ticket.description or "{}")
    except Exception:
        desc_obj = {}
    personal = desc_obj.get("personal") or {}
    if str(personal.get("personal_number") or "").strip():
        return  # bereits vergeben – nicht erneut

    company = str(_onb_field(desc_obj, "contract_company") or "").strip()
    if not company:
        raise api_error(400, "PERSONALNUMMER_FAILED",
                        "Bitte zuerst die „Firma lt. Arbeitsvertrag“ auswählen.")

    from backend.database.personalnummer import (
        db_assign_personalnummer_for_company,
        PersonalnummerNotConfigured, PersonalnummerExhausted,
    )
    from backend.utils.config import config
    try:
        result = db_assign_personalnummer_for_company(
            company, warn_remaining=config.PERSONALNUMMER_WARN_REMAINING,
        )
    except PersonalnummerExhausted as e:
        record_audit(
            action="personalnummer_exhausted", actor_id=user.get("id"),
            actor_name=user.get("displayName") or "", entity_type="settings",
            entity_id="personalnummer", summary=f"Firma {company}: Nummernbereich erschöpft",
            details={"company": company},
        )
        raise api_error(409, "PERSONALNUMMER_FAILED", str(e))
    except PersonalnummerNotConfigured as e:
        raise api_error(400, "PERSONALNUMMER_FAILED", str(e))
    except Exception:
        logger.exception("Personalnummer-Vergabe fehlgeschlagen")
        raise api_error(500, "PERSONALNUMMER_FAILED", "Personalnummer konnte nicht vergeben werden")

    personal["personal_number"] = str(result["number"])
    desc_obj["personal"] = personal
    database.update_ticket(ticket_id=ticket_id, description=json.dumps(desc_obj, ensure_ascii=False))

    person_name = f"{_onb_field(desc_obj, 'first_name')} {_onb_field(desc_obj, 'last_name')}".strip()
    record_audit(
        action="personalnummer_assigned", actor_id=user.get("id"),
        actor_name=user.get("displayName") or "", entity_type="ticket", entity_id=str(ticket_id),
        summary=f"Personalnummer {result['number']} – {person_name or company}",
        details={
            "number": str(result["number"]),
            "company": result.get("company_name") or company,
            "mandant": result.get("mandant"),
            "remaining": result.get("remaining"),
            "person": person_name,
        },
    )

    if result.get("should_warn"):
        record_audit(
            action="personalnummer_range_low", actor_type="system", actor_name="System",
            entity_type="settings", entity_id="personalnummer",
            summary=f"Firma {company}: nur noch {result.get('remaining')} Nummern frei",
            details={"company": company, "remaining": result.get("remaining"), "pnr_to": result.get("pnr_to")},
        )
        try:
            from backend.services.microsoft_mail import send_personalnummer_warning_mail
            send_personalnummer_warning_mail(company, result["remaining"], result["pnr_to"])
        except Exception:
            logger.exception("Personalnummern-Warn-Mail fehlgeschlagen (Firma %s)", company)


@router.post("/tickets/{ticket_id}/submit", response_model=DataResponse[TicketOut])
async def submit_ticket(
    ticket_id: int,
    request: Request,
    user: dict = Depends(get_current_user),
):
    ticket = _get_ticket_or_404(ticket_id)
    _assert_ticket_access(ticket, user)
    _assert_not_locked_by_other(ticket_id, user)

    current_phase = get_current_phase(ticket_id)
    if not current_phase:
        raise api_error(400, ErrorCode.INVALID_STATUS, "Ticket hat keine aktive Phase")

    from backend.services.phase_definitions import PhaseType
    if current_phase["type"] != PhaseType.assignment:
        raise api_error(400, ErrorCode.INVALID_STATUS, "Aktuelle Phase kann nicht über Submit abgeschlossen werden")

    # Optionaler „nächster Bearbeiter" (z.B. BackOffice wählt Person/Fachabteilung,
    # Zuständigkeit wird erst beim Abschluss aktiviert).
    try:
        body = await request.json()
    except Exception:
        body = {}
    next_assignee_id   = (body or {}).get("assignee_id")
    next_assignee_name = (body or {}).get("assignee_name")

    completed_key = current_phase["key"]

    # Personalnummer erst beim Abschluss des BackOffice vergeben (endgültige
    # „Firma lt. Arbeitsvertrag"). Schlägt es fehl (kein Bereich / erschöpft),
    # wird NICHT weitergegeben (advance_phase folgt erst danach).
    tt = ticket.ticket_type.value if hasattr(ticket.ticket_type, "value") else ticket.ticket_type
    if tt == TicketType.zugang_beantragen.value and completed_key == "backoffice":
        _assign_onboarding_personalnummer(ticket_id, user)

    updated_workflow = advance_phase(ticket_id)

    phases = updated_workflow.get("phases", [])
    current_idx = updated_workflow.get("current_phase_index", 0)
    next_phase = phases[current_idx] if current_idx < len(phases) else None

    # Nächste assignment-Phase ohne feste Zuständigkeit → gewählten Bearbeiter setzen.
    from backend.services.workflow_state import set_phase_responsibility
    if (next_phase is not None
            and next_phase.get("type") == PhaseType.assignment.value
            and not (next_phase.get("responsibility") or {}).get("kind")
            and next_assignee_id):
        if not validate_assignee(request.app.state.user_cache, next_assignee_id):
            raise api_error(400, ErrorCode.INVALID_ASSIGNEE,
                            f"Unbekannter Assignee '{next_assignee_id}'")
        from backend.database.groups import get_groups
        group_map = {g["id"]: g["name"] for g in get_groups()}
        if next_assignee_id in group_map:
            set_phase_responsibility(ticket_id, current_idx,
                {"kind": "group", "id": next_assignee_id, "name": group_map[next_assignee_id]})
        else:
            set_phase_responsibility(ticket_id, current_idx,
                {"kind": "user", "id": next_assignee_id, "name": next_assignee_name or next_assignee_id})
        next_phase = database.get_ticket(ticket_id).workflow_state_parsed["phases"][current_idx]

    ticket = database.get_ticket(ticket_id)

    if next_phase and next_phase["type"] == PhaseType.department_review.value:
        add_history_event(
            ticket_id,
            actor_id=user["id"],
            actor_name=user["displayName"],
            action="ticket_submitted",
            details={"status_new": RequestStatus.in_request.value},
        )
    else:
        action = "ticket_archived" if not next_phase else "phase_advanced"
        add_history_event(
            ticket_id,
            actor_id=user["id"],
            actor_name=user["displayName"],
            action=action,
            details={"phase_completed": completed_key},
        )

    notify_phase_entry(request, ticket, next_phase)

    return DataResponse(data=TicketOut.from_ticket(database.get_ticket(ticket_id), user=user))


@router.post("/tickets/{ticket_id}/reject", response_model=DataResponse[TicketOut])
async def reject_ticket(
    ticket_id: int,
    request: Request,
    user: dict = Depends(get_current_user),
):
    ticket = _get_ticket_or_404(ticket_id)
    _assert_ticket_access(ticket, user)

    if ticket.status in (RequestStatus.archived, RequestStatus.rejected):
        raise api_error(400, ErrorCode.INVALID_STATUS, "Ticket ist bereits abgeschlossen")

    body = await request.json()
    message = (body.get("message") or "").strip()
    if not message:
        raise api_error(400, ErrorCode.INVALID_DESCRIPTION, "Ablehnungsgrund (message) ist erforderlich")

    from zoneinfo import ZoneInfo
    rejected_at = datetime.now(ZoneInfo("Europe/Berlin")).isoformat()
    reject_workflow(ticket_id, message=message, rejected_by=user["displayName"], rejected_at=rejected_at)

    add_history_event(
        ticket_id,
        actor_id=user["id"],
        actor_name=user["displayName"],
        action="ticket_rejected",
        details={"message": message},
    )

    # Ersteller über die Ablehnung informieren (Mailfehler darf den Reject nicht kippen).
    try:
        from backend.services.microsoft_mail import send_rejection_mail
        owner_mail = ticket.owner_info_parsed.get("mail") or get_cached_user_mail(request.app, ticket.owner_id)
        send_rejection_mail(ticket, message, owner_mail)
    except Exception:
        logger.exception("Ablehnungs-Mail an Ersteller fehlgeschlagen (Ticket %s)", ticket_id)

    return DataResponse(data=TicketOut.from_ticket(database.get_ticket(ticket_id), user=user))


@router.post("/tickets/{ticket_id}/nachtrag", response_model=DataResponse[TicketOut])
async def add_nachtrag(
    ticket_id: int,
    request: Request,
    user: dict = Depends(get_current_user),
):
    """
    Nachtrag zu einem (i.d.R. archivierten) Ticket: Freitext, wird im Verlauf
    festgehalten und an die Verteiler der beteiligten Fachabteilungen gemailt.
    """
    ticket = _get_ticket_or_404(ticket_id)
    # view/manage/admin dürfen überall; sonst nur Beteiligte (Owner/Beobachter/Zuständige)
    if "view" not in user.get("permissions", []):
        _assert_ticket_access(ticket, user)

    body = await request.json()
    text = (body.get("text") or "").strip()
    if not text:
        raise api_error(400, ErrorCode.INVALID_DESCRIPTION, "Nachtrag-Text ist erforderlich")

    add_history_event(
        ticket_id,
        actor_id=user["id"],
        actor_name=user["displayName"],
        action="nachtrag_added",
        details={"text": text},
    )

    # Beteiligte Fachabteilungen benachrichtigen (Mailfehler darf den Nachtrag nicht kippen).
    try:
        from backend.services.workflow_state import involved_group_ids
        from backend.database.groups import get_distributions_from_group
        from backend.services.microsoft_mail import send_nachtrag_mail
        recipients: set[str] = set()
        for gid in involved_group_ids(ticket):
            for mail in get_distributions_from_group(gid):
                if mail:
                    recipients.add(mail.strip())
        if recipients:
            send_nachtrag_mail(ticket, text, sorted(recipients))
    except Exception:
        logger.exception("Nachtrag-Mail fehlgeschlagen (Ticket %s)", ticket_id)

    return DataResponse(data=TicketOut.from_ticket(database.get_ticket(ticket_id), user=user))


@router.delete("/tickets/{ticket_id}", status_code=204)
def delete_ticket(ticket_id: int, user: dict = Depends(get_current_user)):
    ticket = _get_ticket_or_404(ticket_id)
    ticket_id_val = ticket["id"] if isinstance(ticket, dict) else ticket.id
    if not _user_can_delete_ticket(user, ticket_id_val):
        raise api_error(403, ErrorCode.TICKET_FORBIDDEN, "Kein Zugriff")
    database.delete_ticket(ticket_id)


# ══════════════════════════════════════════════════════════════════════════════
# TICKETS – Admin / Manager
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/admin/tickets", response_model=ListResponse[TicketOut])
def list_all_tickets(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: dict = Depends(get_current_user),
):
    _require_manage(user)
    items = database.list_all_tickets(limit=limit, offset=offset)
    total = database.count_all_tickets()
    return ListResponse(
        data=[TicketOut.from_ticket(t, user=user) for t in items],
        meta=Meta(total=total, limit=limit, offset=offset),
    )


@router.post("/admin/tickets/{ticket_id}/archive", response_model=DataResponse[TicketOut])
def archive_ticket(
    ticket_id: int,
    request: Request,
    user: dict = Depends(get_current_user),
):
    _require_manage(user)
    ticket = _get_ticket_or_404(ticket_id)
    request.app.state.manager.update_ticket(ticket_id=ticket.id, status=RequestStatus.archived)
    add_history_event(
        ticket.id,
        actor_id=user["id"],
        actor_name=user["displayName"],
        action="status_changed",
        details={
            "field": "status",
            "old_value": ticket.status.value,
            "new_value": RequestStatus.archived.value,
        },
    )
    return DataResponse(data=TicketOut.from_ticket(database.get_ticket(ticket_id), user=user))


@router.put("/admin/tickets/{ticket_id}/responsibility", response_model=DataResponse[TicketOut])
def override_responsibility(
    ticket_id: int,
    data: ResponsibilityOverrideRequest,
    request: Request,
    user: dict = Depends(get_current_user),
):
    """
    Admin-Notfall: setzt die Zuständigkeit einer Phase (Standard: aktuelle Phase)
    auf eine Person oder Fachabteilung/Gruppe – unabhängig vom normalen Workflow.
    Funktioniert in jeder Bearbeitungs-(assignment)-Phase. Für die Durchführung
    werden die Fachabteilungen separat verwaltet.
    """
    _require_admin(user)
    _get_ticket_or_404(ticket_id)   # 404, falls es das Ticket nicht gibt

    from backend.services.workflow_state import (
        get_workflow_state, set_phase_responsibility, PhaseType as WfPhaseType,
    )
    wf = get_workflow_state(ticket_id)
    phases = wf.get("phases", [])
    if not phases:
        raise api_error(400, ErrorCode.INVALID_STATUS,
                        "Ticket hat keinen Workflow im neuen Format")

    idx = data.phase_index if data.phase_index is not None else wf.get("current_phase_index", 0)
    if not (0 <= idx < len(phases)):
        raise api_error(400, ErrorCode.INVALID_STATUS,
                        f"Phase-Index {idx} ungültig (erlaubt: 0..{len(phases) - 1})")

    phase = phases[idx]
    if phase.get("type") != WfPhaseType.assignment.value:
        raise api_error(400, ErrorCode.INVALID_STATUS,
                        f"Phase '{phase.get('key')}' ist keine Bearbeitungsphase – "
                        "Zuständigkeit kann hier nicht gesetzt werden "
                        "(Durchführung wird über die Fachabteilungen gesteuert).")

    # Person oder Gruppe/Fachabteilung auflösen
    from backend.database.groups import get_groups
    group_map = {g["id"]: g["name"] for g in get_groups()}
    if data.assignee_id in group_map:
        new_resp = {"kind": "group", "id": data.assignee_id, "name": group_map[data.assignee_id]}
    else:
        if not validate_assignee(request.app.state.user_cache, data.assignee_id):
            raise api_error(400, ErrorCode.INVALID_ASSIGNEE,
                            f"Unbekannte Person/Gruppe '{data.assignee_id}'")
        new_resp = {"kind": "user", "id": data.assignee_id,
                    "name": data.assignee_name or data.assignee_id}

    old_name = (phase.get("responsibility") or {}).get("name")
    set_phase_responsibility(ticket_id, idx, new_resp)

    add_history_event(
        ticket_id,
        actor_id=user["id"],
        actor_name=user["displayName"],
        action="responsibility_overridden",
        details={
            "phase_key": phase.get("key"),
            "phase_label": phase.get("label"),
            "phase_index": idx,
            "old": old_name,
            "new": new_resp["name"],
        },
    )
    return DataResponse(data=TicketOut.from_ticket(database.get_ticket(ticket_id), user=user))


@router.delete("/admin/tickets/{ticket_id}/lock", status_code=204)
def admin_force_unlock(ticket_id: int, user: dict = Depends(get_current_user)):
    """Admin-Notfall: hebt die Bearbeitungs-Sperre eines Tickets auf (verhindert
    dauerhaften Lockout, falls ein Editor den Tab nicht sauber geschlossen hat)."""
    _require_admin(user)
    _get_ticket_or_404(ticket_id)
    from backend.database.ticket_locks import force_release_lock
    force_release_lock(ticket_id)
    add_history_event(
        ticket_id,
        actor_id=user["id"],
        actor_name=user["displayName"],
        action="lock_released",
        details={},
    )


# ── Admin-Detail (inkl. rohem description-JSON) ────────────────────────────────

class AdminTicketDetail(TicketOverviewDetail):
    """Read-only-Detail wie im Overview + roher description-JSON-String für den
    Raw-Editor."""
    description_raw: str = ""


@router.get("/admin/tickets/{ticket_id}/detail", response_model=DataResponse[AdminTicketDetail])
def admin_ticket_detail(ticket_id: int, user: dict = Depends(get_current_user)):
    _require_admin(user)
    ticket = _get_ticket_or_404(ticket_id)
    detail = build_overview_detail(ticket)
    return DataResponse(data=AdminTicketDetail(
        **detail.model_dump(),
        description_raw=ticket.description or "",
    ))


@router.put("/admin/tickets/{ticket_id}/raw", response_model=DataResponse[TicketOut])
def admin_raw_update(
    ticket_id: int,
    data: RawTicketUpdateRequest,
    user: dict = Depends(get_current_user),
):
    """Admin-Notfall: rohe Bearbeitung einzelner Ticket-Felder (Lock wird als
    Admin umgangen). `description` muss gültiges JSON sein."""
    _require_admin(user)
    ticket = _get_ticket_or_404(ticket_id)

    updates: dict = {}
    changes: dict = {}

    if data.description is not None:
        try:
            parsed_new = json.loads(data.description)
        except Exception:
            raise api_error(400, ErrorCode.INVALID_DESCRIPTION, "description ist kein gültiges JSON")
        try:
            parsed_old = json.loads(ticket.description or "{}")
        except Exception:
            parsed_old = {}
        if parsed_new != parsed_old:
            updates["description"] = json.dumps(parsed_new, ensure_ascii=False)
            changes["description"] = {"old": parsed_old, "new": parsed_new}

    if data.title is not None and data.title != ticket.title:
        updates["title"] = data.title
        changes["title"] = {"old": ticket.title, "new": data.title}

    if data.comment is not None and data.comment != (ticket.comment or ""):
        updates["comment"] = data.comment
        changes["comment"] = {"old": ticket.comment or "", "new": data.comment}

    if data.priority is not None:
        old_p = ticket.priority.value if hasattr(ticket.priority, "value") else str(ticket.priority)
        if data.priority.value != old_p:
            updates["priority"] = data.priority.value
            changes["priority"] = {"old": old_p, "new": data.priority.value}

    if data.status is not None:
        old_s = ticket.status.value if hasattr(ticket.status, "value") else str(ticket.status)
        if data.status.value != old_s:
            updates["status"] = data.status.value
            changes["status"] = {"old": old_s, "new": data.status.value}

    if not updates:
        raise api_error(400, ErrorCode.INVALID_STATUS, "Keine Änderungen übermittelt")

    database.update_ticket(ticket_id, **updates)
    add_history_event(
        ticket_id,
        actor_id=user["id"],
        actor_name=user["displayName"],
        action="admin_raw_edited",
        details={"changes": changes},
    )
    return DataResponse(data=TicketOut.from_ticket(database.get_ticket(ticket_id), user=user))


def _client_ip(request) -> str | None:
    try:
        return request.client.host if request and request.client else None
    except Exception:
        return None


def _audit_ticket_deleted(ticket, user: dict, request) -> None:
    """Löschung persistent auditieren – VOR dem Löschen aufrufen, da danach die
    Ticket-Historie weg ist."""
    tt = ticket.ticket_type.value if hasattr(ticket.ticket_type, "value") else str(ticket.ticket_type)
    st = ticket.status.value if hasattr(ticket.status, "value") else str(ticket.status)
    record_audit(
        action="ticket_deleted",
        actor_id=user["id"], actor_name=user["displayName"],
        entity_type="ticket", entity_id=str(ticket.id),
        summary=ticket.title,
        details={"ticket_type": tt, "status": st, "owner_name": ticket.owner_name},
        ip=_client_ip(request),
    )


@router.delete("/admin/tickets/{ticket_id}", status_code=204)
def admin_delete_ticket(ticket_id: int, request: Request, user: dict = Depends(get_current_user)):
    """Admin-Notfall: Ticket endgültig löschen (inkl. Cleanup von Beobachtern/Locks)."""
    _require_admin(user)
    ticket = _get_ticket_or_404(ticket_id)
    _audit_ticket_deleted(ticket, user, request)
    database.delete_ticket(ticket_id)


@router.post("/admin/tickets/bulk", response_model=DataResponse[BulkActionResult])
def admin_bulk_action(
    data: BulkTicketActionRequest,
    request: Request,
    user: dict = Depends(get_current_user),
):
    """Sammelaktion auf mehrere Tickets: 'archive' (ab Manager) oder 'delete' (nur
    Admin). Verarbeitet pro Ticket; Ergebnis mit ok/failed-Listen."""
    action = normalize_bulk_action(data.action)
    if action is None:
        raise api_error(400, ErrorCode.INVALID_STATUS, f"Unbekannte Aktion: {data.action!r}")

    # Rechte je Aktion durchsetzen.
    if required_permission_for_bulk(action) == PERM_ADMIN:
        _require_admin(user)
    else:
        _require_manage(user)

    ok: list[int] = []
    failed: list[dict] = []
    for tid in data.ids:
        try:
            ticket = database.get_ticket(tid)
            if not ticket:
                failed.append({"id": tid, "error": "nicht gefunden"})
                continue
            if action == "archive":
                if ticket.status == RequestStatus.archived:
                    failed.append({"id": tid, "error": "bereits archiviert"})
                    continue
                old_status = ticket.status.value if hasattr(ticket.status, "value") else str(ticket.status)
                database.update_ticket(tid, status=RequestStatus.archived.value)
                add_history_event(
                    tid, actor_id=user["id"], actor_name=user["displayName"],
                    action="ticket_archived_manual",
                    details={"field": "status", "old_value": old_status,
                             "new_value": RequestStatus.archived.value, "bulk": True},
                )
            else:  # delete
                _audit_ticket_deleted(ticket, user, request)
                database.delete_ticket(tid)
            ok.append(tid)
        except Exception:
            logger.exception("Bulk-Aktion %s fehlgeschlagen für Ticket %s", action, tid)
            failed.append({"id": tid, "error": "Fehler bei der Verarbeitung"})

    return DataResponse(data=BulkActionResult(ok=ok, failed=failed))


# ══════════════════════════════════════════════════════════════════════════════
# DEPARTMENTS
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/tickets/{ticket_id}/departments")
def get_my_departments(ticket_id: int, user: dict = Depends(get_current_user)):
    from backend.services.workflow_state import get_departments_for_user
    return DataResponse(data=get_departments_for_user(ticket_id, user["id"]))


@router.get("/tickets/{ticket_id}/departments/all")
def get_all_departments(ticket_id: int, user: dict = Depends(get_current_user)):
    _require_manage(user)
    from backend.services.workflow_state import get_all_department_statuses
    return DataResponse(data=get_all_department_statuses(ticket_id))


@router.patch("/tickets/{ticket_id}/departments/{group_id}")
async def set_department_status(
    ticket_id: int,
    group_id: str,
    request: Request,
    user: dict = Depends(get_current_user),
):
    from backend.services.workflow_state import (
        user_can_complete_department, set_department_status,
    )
    from backend.database.groups import get_group_name_from_id

    body = await request.json()
    status = body.get("status")

    if not user_can_complete_department(ticket_id, user["id"], group_id):
        raise api_error(403, ErrorCode.DEPARTMENT_FORBIDDEN,
                        "Keine Berechtigung für diese Fachabteilung")
    if status not in {"done", "rejected", "skipped"}:
        raise api_error(400, ErrorCode.INVALID_STATUS,
                        "Erlaubte Werte: done, rejected, skipped")

    set_department_status(ticket_id, group_id, status)
    add_history_event(
        ticket_id,
        actor_id=user["id"],
        actor_name=user["displayName"],
        action="department_status_changed",
        details={
            "department_id": group_id,
            "department_name": get_group_name_from_id(group_id),
            "new_value": status,
        },
    )

    if all_required_departments_done(ticket_id):
        updated_workflow = advance_phase(ticket_id)
        phases = updated_workflow.get("phases", [])
        current_idx = updated_workflow.get("current_phase_index", 0)
        next_phase = phases[current_idx] if current_idx < len(phases) else None

        if next_phase:
            add_history_event(
                ticket_id,
                actor_id=None,
                actor_name="System",
                actor_type="system",
                action="phase_advanced",
                details={"new_phase": next_phase["key"]},
            )
            # Zuständige der neu aktiven Phase benachrichtigen (z.B. Reisestelle
            # nach der Durchführung) – analog zu create_ticket/submit_ticket.
            # Status + Advance sind bereits persistiert, ein Mailfehler darf
            # die Antwort nicht kippen.
            try:
                notify_phase_entry(request, database.get_ticket(ticket_id), next_phase)
            except Exception:
                logger.exception("Phasen-Benachrichtigung nach Fachabteilungs-Abschluss fehlgeschlagen (Ticket %s)", ticket_id)
        else:
            add_history_event(
                ticket_id,
                actor_id=None,
                actor_name="System",
                actor_type="system",
                action="status_changed",
                details={
                    "field": "status",
                    "old_value": RequestStatus.in_request.value,
                    "new_value": RequestStatus.archived.value,
                },
            )

    return {"ok": True}