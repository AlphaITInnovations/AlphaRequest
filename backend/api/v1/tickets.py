import json
from datetime import datetime

from fastapi import APIRouter, Request, Depends, Query, HTTPException
from pydantic import BaseModel
from typing import Optional
from backend.core.dependencies import get_current_user
from backend.database import tickets as database
from backend.models.models import RequestStatus, TicketType
from backend.services.ticket_history import add_history_event, add_field_change_events
from backend.services.microsoft_graph import get_cached_user_mail
from backend.services.microsoft_mail import send_newrequest_mail, send_mail_to_all_fachabteilung
from backend.services.ticket_permissions import can_user_create_ticket
from backend.schemas.ticket import (
    TicketOut, TicketCreateRequest, TicketUpdateRequest, UserOut, BasisTicketCreateRequest,
)
from backend.schemas.responses import (
    DataResponse, ListResponse, Meta, ErrorCode, api_error,
)
from backend.database.users import PERM_MANAGE, PERM_ADMIN
from backend.services.workflow_state import (
    build_workflow, set_workflow_state, advance_phase,
    reject_workflow, get_current_phase, all_required_departments_done,
)
from backend.utils.ticket_labels import TICKET_LABELS
from backend.utils.logger import logger
from backend.metrics.ticket_metrics import tickets_created_total
from datetime import datetime
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


def generate_title(ticket_type, user, desc):
    now_str = datetime.now(ZoneInfo("Europe/Berlin")).strftime("%Y-%m-%d %H:%M")

    if isinstance(desc, str):
        desc = json.loads(desc)

    personal = desc.get("personal", {})
    first_name = personal.get("first_name", "")
    last_name = personal.get("last_name", "")
    name = f"{first_name} {last_name}".strip()

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
        data=[TicketOut.from_ticket(t) for t in items],
        meta=Meta(total=len(items), limit=len(items), offset=0),
    )


@router.get("/tickets/{ticket_id}", response_model=DataResponse[TicketOut])
def get_ticket(ticket_id: int, user: dict = Depends(get_current_user)):
    ticket = _get_ticket_or_404(ticket_id)
    _assert_ticket_access(ticket, user)
    from backend.database.ticket_watchers import list_watchers
    return DataResponse(data=TicketOut.from_ticket(ticket, watchers=list_watchers(ticket_id)))


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
        desc_obj = json.loads(data.description)
    except Exception:
        raise api_error(400, ErrorCode.INVALID_DESCRIPTION,
                        "description muss gültiges JSON sein")

    description = data.description
    # Onboarding: Personalnummer wird automatisch bei der Auftragserstellung
    # vergeben (kein manueller Button mehr im Formular). Erst hier verbrauchen,
    # damit abgebrochene Formulare keine Nummern „verbrennen". Nur wenn noch
    # keine gesetzt ist.
    if data.ticket_type == TicketType.zugang_beantragen:
        personal = desc_obj.get("personal") or {}
        if not str(personal.get("personal_number") or "").strip():
            from backend.services.personalnummer_generator import next_personalnummer
            try:
                personal["personal_number"] = str(next_personalnummer())
            except RuntimeError as e:
                raise api_error(409, "PERSONALNUMMER_FAILED", str(e))
            except Exception:
                logger.exception("Personalnummer-Vergabe fehlgeschlagen")
                raise api_error(500, "PERSONALNUMMER_FAILED",
                                "Personalnummer konnte nicht vergeben werden")
            desc_obj["personal"] = personal
            description = json.dumps(desc_obj, ensure_ascii=False)

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

    return DataResponse(data=TicketOut.from_ticket(database.get_ticket(ticket_id)))


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
    tickets_created_total.labels(type="basis-ticket").inc()

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

    return DataResponse(data=TicketOut.from_ticket(database.get_ticket(ticket_id)))


@router.patch("/tickets/{ticket_id}", response_model=DataResponse[TicketOut])
async def update_ticket(
    ticket_id: int,
    data: TicketUpdateRequest,
    request: Request,
    user: dict = Depends(get_current_user),
):
    ticket = _get_ticket_or_404(ticket_id)
    _assert_ticket_access(ticket, user)

    if data.assignee_id and not validate_assignee(request.app.state.user_cache, data.assignee_id):
        raise api_error(400, ErrorCode.INVALID_ASSIGNEE, "Unbekannter Assignee")

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

    # --- Zuweisung der Bearbeitungsphase: nur in der assignment-Phase änderbar ---
    # Schreibt die responsibility in den Workflow (Person/Gruppe), nicht in die
    # alten assignee/accountable-Spalten.
    if data.assignee_id:
        from backend.database.groups import get_groups
        from backend.services.workflow_state import (
            get_workflow_state, current_responsibility, set_phase_responsibility,
            PhaseType as WfPhaseType,
        )
        wf = get_workflow_state(ticket_id)
        phases = wf.get("phases", [])
        idx = wf.get("current_phase_index", 0)
        if 0 <= idx < len(phases) and phases[idx].get("type") == WfPhaseType.assignment.value:
            group_map = {g["id"]: g["name"] for g in get_groups()}
            if data.assignee_id in group_map:
                new_resp = {"kind": "group", "id": data.assignee_id, "name": group_map[data.assignee_id]}
            else:
                new_resp = {"kind": "user", "id": data.assignee_id, "name": data.assignee_name or data.assignee_id}
            old = current_responsibility(ticket)
            if old.get("id") != new_resp["id"]:
                changes["assignee"] = {"old": old.get("name"), "new": new_resp["name"]}
                set_phase_responsibility(ticket_id, idx, new_resp)

    # --- Ein gebündeltes History-Event für alle Änderungen ---
    if changes:
        add_history_event(
            ticket_id,
            actor_id=user["id"],
            actor_name=user["displayName"],
            action="ticket_updated",
            details={"changes": changes},
        )

    return DataResponse(data=TicketOut.from_ticket(database.get_ticket(ticket_id)))


@router.post("/tickets/{ticket_id}/submit", response_model=DataResponse[TicketOut])
async def submit_ticket(
    ticket_id: int,
    request: Request,
    user: dict = Depends(get_current_user),
):
    ticket = _get_ticket_or_404(ticket_id)
    _assert_ticket_access(ticket, user)

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

    return DataResponse(data=TicketOut.from_ticket(database.get_ticket(ticket_id)))


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

    return DataResponse(data=TicketOut.from_ticket(database.get_ticket(ticket_id)))


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
        data=[TicketOut.from_ticket(t) for t in items],
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
    return DataResponse(data=TicketOut.from_ticket(database.get_ticket(ticket_id)))


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
        user_can_complete_department, set_department_status, can_archive_ticket,
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