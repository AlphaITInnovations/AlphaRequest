import json
from datetime import datetime
from typing import Optional

from backend.models.models import TicketType, RequestStatus, Ticket
from backend.services.phase_definitions import TICKET_PHASES, PhaseType
from backend.database.tickets import update_ticket, get_ticket, list_all_tickets
from backend.database.groups import (
    get_users_from_group, get_groups, get_group_name_from_id, get_group_ids_for_user,
)


# ============================================================
# Department status constants
# ============================================================

DEPARTMENT_STATUS_OPEN = "open"
DEPARTMENT_STATUS_IN_PROGRESS = "in_progress"
DEPARTMENT_STATUS_DONE = "done"
DEPARTMENT_STATUS_SKIPPED = "skipped"
DEPARTMENT_STATUS_REJECTED = "rejected"

ALLOWED_DEPARTMENT_STATUS = {
    DEPARTMENT_STATUS_OPEN,
    DEPARTMENT_STATUS_IN_PROGRESS,
    DEPARTMENT_STATUS_DONE,
    DEPARTMENT_STATUS_SKIPPED,
    DEPARTMENT_STATUS_REJECTED,
}

PHASE_STATUS_PENDING = "pending"
PHASE_STATUS_IN_PROGRESS = "in_progress"
PHASE_STATUS_DONE = "done"


# ============================================================
# Core helpers
# ============================================================

def set_workflow_state(ticket_id: int, workflow: dict) -> None:
    update_ticket(ticket_id, workflow_state=json.dumps(workflow, ensure_ascii=False))


def get_workflow_state(ticket_id: int) -> dict:
    ticket = get_ticket(ticket_id)
    return ticket.workflow_state_parsed if ticket and ticket.workflow_state else {}


def _require_workflow(ticket_id: int) -> dict:
    workflow = get_workflow_state(ticket_id)
    if "phases" not in workflow:
        raise ValueError("Workflow not initialized for this ticket")
    return workflow


def _is_new_format(workflow: dict) -> bool:
    return "phases" in workflow


def _get_current_dept_phase(workflow: dict) -> Optional[dict]:
    """Returns the currently active department_review phase, or None."""
    if not _is_new_format(workflow):
        return None
    idx = workflow.get("current_phase_index", 0)
    phases = workflow.get("phases", [])
    if idx < len(phases) and phases[idx].get("type") == PhaseType.department_review:
        return phases[idx]
    return None


def _get_departments_from_workflow(workflow: dict) -> dict:
    """Returns departments dict regardless of workflow format."""
    if _is_new_format(workflow):
        phase = _get_current_dept_phase(workflow)
        return phase.get("departments", {}) if phase else {}
    return workflow.get("departments", {})


# ============================================================
# Department builders (per ticket type)
# ============================================================

def _build_departments_it_hr(description: dict) -> dict:
    groups = {g["name"].lower(): g for g in get_groups()}
    departments = {}

    def add(name: str):
        g = groups.get(name.lower())
        if g:
            departments[g["id"]] = {"name": g["name"], "required": True, "status": DEPARTMENT_STATUS_OPEN}

    add("IT")
    add("Personalabteilung")
    if description.get("fuhrpark", {}).get("car") == "Ja":
        add("Fuhrpark")

    return departments


def _build_departments_niederlassung_schliessen(description: dict) -> dict:
    groups = {g["name"].lower(): g for g in get_groups()}
    departments = {}

    def add(name: str):
        g = groups.get(name.lower())
        if g:
            departments[g["id"]] = {"name": g["name"], "required": True, "status": DEPARTMENT_STATUS_OPEN}

    add("IT")
    add("Personalabteilung")
    if description.get("fuhrpark", {}).get("pool_cars") == "Ja":
        add("Fuhrpark")

    return departments


def _build_departments_niederlassung_anmelden(description: dict) -> dict:
    groups = {g["name"].lower(): g for g in get_groups()}
    departments = {}

    def add(name: str):
        g = groups.get(name.lower())
        if g:
            departments[g["id"]] = {"name": g["name"], "required": True, "status": DEPARTMENT_STATUS_OPEN}

    add("Verwaltung")   # ersetzt die frühere Fachabteilung "Miete"
    add("IT")
    add("Marketing")
    if description.get("fuhrpark", {}).get("pool_cars") == "Ja":
        add("Fuhrpark")

    return departments


def _build_departments_single(group_name: str):
    def builder(description: dict) -> dict:
        groups = {g["name"].lower(): g for g in get_groups()}
        g = groups.get(group_name.lower())
        if not g:
            return {}
        return {g["id"]: {"name": g["name"], "required": True, "status": DEPARTMENT_STATUS_OPEN}}
    return builder


DEPARTMENT_BUILDERS = {
    TicketType.zugang_beantragen: _build_departments_it_hr,
    TicketType.zugang_sperren: _build_departments_it_hr,
    TicketType.hardware: _build_departments_single("IT"),
    TicketType.niederlassung_anmelden: _build_departments_niederlassung_anmelden,
    TicketType.niederlassung_umzug: _build_departments_niederlassung_anmelden,
    TicketType.niederlassung_schliessen: _build_departments_niederlassung_schliessen,
    TicketType.marketing_stellenanzeige: _build_departments_single("Marketing"),
    TicketType.hotelbuchung: _build_departments_single("Hotelbuchung"),
}


# Fachabteilungen (Gruppen), die von den Workflow-Definitionen referenziert werden.
# Diese Liste muss mit den oben in den DEPARTMENT_BUILDERS verwendeten Namen
# synchron gehalten werden (die Namen stecken in den Builder-Closures und sind
# nicht automatisch auslesbar). assign_group-Phasen werden dagegen automatisch
# aus TICKET_PHASES ergänzt.
_DEPARTMENT_GROUP_NAMES = [
    "IT", "Personalabteilung", "Fuhrpark", "Verwaltung", "Marketing", "Hotelbuchung",
]


def required_group_names() -> list[str]:
    """
    Namen aller Gruppen, die für die Workflows zwingend existieren müssen:
    die Fachabteilungen aus den DEPARTMENT_BUILDERS plus alle fest zugewiesenen
    Gruppen (assign_group) aus TICKET_PHASES. Diese Gruppen werden beim Start
    angelegt (sofern sie fehlen) und dürfen nicht gelöscht/umbenannt werden –
    unabhängig davon, ob Mitglieder vorhanden sind.
    """
    names = list(_DEPARTMENT_GROUP_NAMES)
    for phase_defs in TICKET_PHASES.values():
        for pd in phase_defs:
            if getattr(pd, "assign_group", None):
                names.append(pd.assign_group)

    seen, out = set(), []
    for n in names:
        if n.lower() not in seen:
            seen.add(n.lower())
            out.append(n)
    return out


def is_required_group_name(name: str) -> bool:
    """True, wenn eine Gruppe mit diesem Namen von den Workflows benötigt wird."""
    if not name:
        return False
    return name.strip().lower() in {n.lower() for n in required_group_names()}


def assign_group_names() -> list[str]:
    """
    Namen aller Gruppen, die einer Phase fest zugewiesen sind (assign_group).
    Diese Gruppen werden nur automatisch über den Workflow zugewiesen und sollen
    daher in Auswahl-Dropdowns nicht auftauchen (hidden).
    """
    seen, out = set(), []
    for phase_defs in TICKET_PHASES.values():
        for pd in phase_defs:
            name = getattr(pd, "assign_group", None)
            if name and name.lower() not in seen:
                seen.add(name.lower())
                out.append(name)
    return out


# ============================================================
# Workflow builder
# ============================================================

def build_workflow(ticket: Ticket) -> dict:
    phase_defs = TICKET_PHASES.get(ticket.ticket_type)
    if not phase_defs:
        raise ValueError(f"No phase definition for ticket type {ticket.ticket_type}")

    try:
        description = json.loads(ticket.description)
    except Exception:
        raise ValueError("Ticket description is not valid JSON")

    phases = []
    for i, phase_def in enumerate(phase_defs):
        phase: dict = {
            "key": phase_def.key,
            "label": phase_def.label,
            "type": phase_def.type.value,
            "view": phase_def.effective_view.value,
            "status": PHASE_STATUS_IN_PROGRESS if i == 0 else PHASE_STATUS_PENDING,
        }
        if phase_def.type == PhaseType.creation:
            # Zuständigkeit der Erstellungsphase ist immer der Ersteller.
            phase["responsibility"] = {"kind": "owner", "id": ticket.owner_id, "name": ticket.owner_name}
        elif phase_def.type == PhaseType.department_review:
            builder = DEPARTMENT_BUILDERS.get(ticket.ticket_type)
            phase["departments"] = builder(description) if builder else {}
            phase["responsibility"] = {"kind": "departments"}
        elif phase_def.assign_group:
            # assignment-Phase mit fester Gruppen-Zuweisung (Name → Gruppe auflösen)
            groups = {g["name"].lower(): g for g in get_groups()}
            g = groups.get(phase_def.assign_group.lower())
            if g:
                phase["responsibility"] = {"kind": "group", "id": g["id"], "name": g["name"]}
        # Sonstige assignment-Phasen: responsibility wird beim Aktivieren gesetzt
        # (set_phase_responsibility / create_ticket).
        phases.append(phase)

    return {
        "current_phase_index": 0,
        "phases": phases,
        "rejected": None,
    }


# ============================================================
# Phase transitions
# ============================================================

def advance_phase(ticket_id: int) -> dict:
    """Completes the current phase and activates the next. Returns updated workflow."""
    workflow = _require_workflow(ticket_id)
    phases = workflow["phases"]
    idx = workflow["current_phase_index"]

    phases[idx]["status"] = PHASE_STATUS_DONE

    next_idx = idx + 1
    if next_idx >= len(phases):
        workflow["current_phase_index"] = next_idx
        set_workflow_state(ticket_id, workflow)
        update_ticket(ticket_id, status=RequestStatus.archived.value)
        return workflow

    phases[next_idx]["status"] = PHASE_STATUS_IN_PROGRESS
    workflow["current_phase_index"] = next_idx

    new_type = phases[next_idx]["type"]
    if new_type == PhaseType.department_review:
        update_ticket(ticket_id, status=RequestStatus.in_request.value)
    else:
        update_ticket(ticket_id, status=RequestStatus.in_progress.value)

    set_workflow_state(ticket_id, workflow)
    return workflow


def reject_workflow(ticket_id: int, message: str, rejected_by: str, rejected_at: str) -> None:
    """Marks the ticket as rejected with a message. Can be called from any active phase."""
    workflow = _require_workflow(ticket_id)

    phases = workflow["phases"]
    idx = workflow["current_phase_index"]
    current_phase = phases[idx] if idx < len(phases) else {}

    workflow["rejected"] = {
        "phase_key": current_phase.get("key"),
        "phase_index": idx,
        "message": message,
        "rejected_by": rejected_by,
        "rejected_at": rejected_at,
    }

    set_workflow_state(ticket_id, workflow)
    update_ticket(ticket_id, status=RequestStatus.rejected.value)


def get_current_phase(ticket_id: int) -> Optional[dict]:
    """Returns the currently active phase dict, or None if all phases are done."""
    workflow = get_workflow_state(ticket_id)
    if not _is_new_format(workflow):
        return None
    phases = workflow.get("phases", [])
    idx = workflow.get("current_phase_index", 0)
    return phases[idx] if idx < len(phases) else None


# ============================================================
# Responsibility & view (single source of truth)
# ============================================================

def set_phase_responsibility(ticket_id: int, phase_index: int, responsibility: dict) -> None:
    """Setzt die Zuständigkeit einer einzelnen Phase im Workflow."""
    workflow = _require_workflow(ticket_id)
    phases = workflow["phases"]
    if 0 <= phase_index < len(phases):
        phases[phase_index]["responsibility"] = responsibility
        set_workflow_state(ticket_id, workflow)


def phase_view(phase: Optional[dict]) -> str:
    """Frontend-Ansicht einer Phase: 'form' | 'readonly' (Fallback aus type)."""
    if not phase:
        return "readonly"
    v = phase.get("view")
    if v in ("form", "readonly"):
        return v
    return "form" if phase.get("type") == PhaseType.assignment.value else "readonly"


def current_responsibility(ticket) -> dict:
    """
    Einheitliche Quelle der Wahrheit: wer ist in der AKTUELLEN Phase zuständig?
    Rückgabe-kinds: owner | user | group | departments | none.

    Liest AUSSCHLIESSLICH aus dem workflow_state (phase.responsibility / departments).
    Die alten assignee/accountable-Spalten werden NICHT mehr ausgewertet – Alt-Tickets
    werden beim Start einmalig in den Workflow migriert (backfill_phase_responsibility).
    """
    workflow = ticket.workflow_state_parsed if hasattr(ticket, "workflow_state_parsed") else (ticket or {})
    phase = _current_phase_of(workflow)
    if not phase:
        return {"kind": "none"}

    ptype = phase.get("type")

    if ptype == PhaseType.department_review.value:
        return {"kind": "departments", "departments": phase.get("departments", {})}

    resp = phase.get("responsibility")
    if isinstance(resp, dict) and resp.get("kind"):
        return resp

    # creation-Phase ohne explizite responsibility → Ersteller (owner_* bleibt in Gebrauch)
    if ptype == PhaseType.creation.value:
        return {"kind": "owner", "id": getattr(ticket, "owner_id", None), "name": getattr(ticket, "owner_name", None)}

    return {"kind": "none"}


def primary_responsibility(ticket) -> Optional[dict]:
    """
    Die „verantwortliche" Person/Gruppe eines Tickets für die Anzeige
    („Verantwortlicher") = responsibility der ersten Bearbeitungs-(assignment)-Phase,
    stabil über alle Phasen. None, wenn der Typ keine Bearbeitungsphase hat.
    """
    workflow = ticket.workflow_state_parsed if hasattr(ticket, "workflow_state_parsed") else (ticket or {})
    if not _is_new_format(workflow):
        return None
    for phase in workflow.get("phases", []):
        if phase.get("type") == PhaseType.assignment.value:
            resp = phase.get("responsibility")
            if isinstance(resp, dict) and resp.get("kind") in ("user", "group"):
                return resp
            return None
    return None


def responsibility_label(ticket) -> str:
    """
    Lesbarer Name der AKTUELL zuständigen Stelle (für Listen/Übersicht):
    Person, Gruppe, Ersteller oder – in der Durchführung – die noch offenen
    Fachabteilungen. '—', wenn niemand (mehr) zuständig ist (z. B. archiviert).
    """
    resp = current_responsibility(ticket)
    kind = resp.get("kind")
    if kind in ("user", "group", "owner"):
        return resp.get("name") or "—"
    if kind == "departments":
        open_names = [
            d.get("name") for d in resp.get("departments", {}).values()
            if d.get("required") and d.get("status") != DEPARTMENT_STATUS_DONE
        ]
        return ", ".join(n for n in open_names if n) or "—"
    return "—"


def backfill_phase_responsibility() -> None:
    """
    Einmalige, idempotente Migration: trägt für bestehende Tickets die
    responsibility der Bearbeitungs-(assignment)-Phase nach, sofern noch nicht
    gesetzt – abgeleitet aus den Alt-Spalten assignee_group_id / assignee_id.
    Danach ist die Zuständigkeit vollständig im workflow_state und die Spalten
    werden nicht mehr gelesen.
    """
    for ticket in list_all_tickets():
        workflow = ticket.workflow_state_parsed
        if not _is_new_format(workflow):
            continue
        changed = False
        for phase in workflow.get("phases", []):
            if phase.get("type") != PhaseType.assignment.value:
                continue
            resp = phase.get("responsibility")
            if isinstance(resp, dict) and resp.get("kind") in ("user", "group"):
                continue  # bereits gesetzt
            gid = getattr(ticket, "assignee_group_id", None)
            aid = getattr(ticket, "assignee_id", None)
            if gid:
                phase["responsibility"] = {"kind": "group", "id": gid,
                                           "name": getattr(ticket, "assignee_group_name", None)}
                changed = True
            elif aid and aid != "fachabteilung":
                phase["responsibility"] = {"kind": "user", "id": aid,
                                           "name": getattr(ticket, "assignee_name", None)}
                changed = True
        if changed:
            set_workflow_state(ticket.id, workflow)


def user_is_responsible(ticket, user_id: str, user_group_ids=None) -> bool:
    """True, wenn der User in der aktuellen Phase handeln muss/darf."""
    group_ids = set(user_group_ids or [])
    resp = current_responsibility(ticket)
    kind = resp.get("kind")
    if kind in ("user", "owner"):
        return resp.get("id") == user_id
    if kind == "group":
        return resp.get("id") in group_ids
    if kind == "departments":
        for gid, dept in resp.get("departments", {}).items():
            if gid in group_ids and dept.get("required") and dept.get("status") != DEPARTMENT_STATUS_DONE:
                return True
    return False


# ============================================================
# Department handling
# ============================================================

def set_department_status(ticket_id: int, group_id: str, status: str) -> None:
    if status not in ALLOWED_DEPARTMENT_STATUS:
        raise ValueError(f"Invalid department status '{status}'")

    workflow = _require_workflow(ticket_id)

    departments = _get_departments_from_workflow(workflow)
    if group_id not in departments:
        raise ValueError("Group not part of workflow")

    departments[group_id]["status"] = status
    set_workflow_state(ticket_id, workflow)


def get_department_status(ticket_id: int, group_id: str) -> Optional[str]:
    workflow = get_workflow_state(ticket_id)
    return _get_departments_from_workflow(workflow).get(group_id, {}).get("status")


def get_department_info(ticket_id: int, group_id: str) -> Optional[dict]:
    workflow = get_workflow_state(ticket_id)
    return _get_departments_from_workflow(workflow).get(group_id)


def get_all_department_statuses(ticket_id: int) -> dict:
    workflow = get_workflow_state(ticket_id)
    return _get_departments_from_workflow(workflow)


def all_required_departments_done(ticket_id: int) -> bool:
    """Returns True if all required departments in the current dept phase are done."""
    workflow = get_workflow_state(ticket_id)
    for dept in _get_departments_from_workflow(workflow).values():
        if dept.get("required") and dept.get("status") != DEPARTMENT_STATUS_DONE:
            return False
    return True


# ============================================================
# Archive logic
# ============================================================

def can_archive_ticket(ticket_id: int) -> bool:
    workflow = get_workflow_state(ticket_id)
    if _is_new_format(workflow):
        return all_required_departments_done(ticket_id)
    # Old format fallback
    for dept in workflow.get("departments", {}).values():
        if dept.get("required") and dept.get("status") != DEPARTMENT_STATUS_DONE:
            return False
    return True


# ============================================================
# Change handling
# ============================================================

def reset_departments_on_description_change(ticket_id: int) -> None:
    workflow = get_workflow_state(ticket_id)

    if _is_new_format(workflow):
        changed = False
        phase = _get_current_dept_phase(workflow)
        if phase:
            for dept in phase.get("departments", {}).values():
                if dept.get("status") == DEPARTMENT_STATUS_DONE:
                    dept["status"] = DEPARTMENT_STATUS_OPEN
                    changed = True
        if changed:
            set_workflow_state(ticket_id, workflow)
        return

    # Old format fallback
    if "departments" not in workflow:
        return
    changed = False
    for dept in workflow["departments"].values():
        if dept.get("status") == DEPARTMENT_STATUS_DONE:
            dept["status"] = DEPARTMENT_STATUS_OPEN
            changed = True
    if changed:
        set_workflow_state(ticket_id, workflow)


# ============================================================
# Permissions
# ============================================================

def get_departments_for_user(ticket_id: int, user_id: str) -> dict:
    workflow = get_workflow_state(ticket_id)
    result = {}
    for group_id, data in _get_departments_from_workflow(workflow).items():
        if user_id in get_users_from_group(group_id):
            result[group_id] = data
    return result


def user_can_complete_department(ticket_id: int, user_id: str, group_id: str) -> bool:
    if user_id not in get_users_from_group(group_id):
        return False
    status = get_department_status(ticket_id, group_id)
    return status in {DEPARTMENT_STATUS_OPEN, DEPARTMENT_STATUS_IN_PROGRESS}


# ============================================================
# Dashboard queries
# ============================================================

def get_tickets_for_department(group_id: str) -> list[Ticket]:
    tickets = list_all_tickets()
    result = []

    for ticket in tickets:
        if ticket.status != RequestStatus.in_request:
            continue
        departments = _get_departments_from_workflow(ticket.workflow_state_parsed)
        dept = departments.get(group_id)
        if dept and dept.get("required") and dept.get("status") != DEPARTMENT_STATUS_DONE:
            result.append(ticket)

    return result


def get_tickets_for_user_departments(user_id: str) -> dict[str, list[Ticket]]:
    group_ids = get_group_ids_for_user(user_id)
    result = {}
    for group_id in group_ids:
        tickets = get_tickets_for_department(group_id)
        if tickets:
            result[group_id] = tickets
    return result


def _current_phase_of(workflow: dict) -> Optional[dict]:
    """Aktuelle Phase aus einem (bereits geparsten) Workflow-Dict, oder None."""
    if not _is_new_format(workflow):
        return None
    phases = workflow.get("phases", [])
    idx = workflow.get("current_phase_index", 0)
    if 0 <= idx < len(phases):
        return phases[idx]
    return None


def _board_item(ticket: Ticket, phase: dict, department_id: Optional[str]) -> dict:
    return {
        "id": ticket.id,
        "title": ticket.title,
        "type_key": ticket.ticket_type.value,
        "status": ticket.status.value,
        "priority": ticket.priority.value,
        "created_at": ticket.created_at.isoformat() if ticket.created_at else None,
        "phase_type": phase.get("type"),
        "phase_label": phase.get("label"),
        # group_id der Reviewing-Abteilung (für ?department=). None in der
        # Assignment-Phase – dort öffnet der Link das Bearbeitungs-Formular.
        "department_id": department_id,
    }


def get_dashboard_work(user_id: str) -> dict:
    """
    Einheitliche Dashboard-Arbeitslisten – ein Durchlauf, basierend auf der
    aktuellen Zuständigkeit (current_responsibility). Jedes Ticket erscheint
    genau einmal in seiner aktuellen Phase.

    Rückgabe:
      {
        "assigned": [ <board_item> ],          # mir PERSÖNLICH zugewiesen (kind=user)
        "departments": [ {group_id, group_name, tickets:[<board_item>]} ]  # meine Abteilungen
      }

    - assignment + kind=user, id=me        -> assigned (Link öffnet Formular)
    - assignment + kind=group (meine)      -> department-board, department_id=None (Formular)
    - department_review (meine als offener required Reviewer) -> department-board,
      department_id=group_id (Durchführungs-Aktionsleiste)
    """
    group_ids = set(get_group_ids_for_user(user_id))

    assigned: list[dict] = []
    boards: dict[str, dict] = {}

    def board_for(gid: str) -> dict:
        if gid not in boards:
            boards[gid] = {
                "group_id": gid,
                "group_name": get_group_name_from_id(gid) or gid,
                "tickets": [],
            }
        return boards[gid]

    for ticket in list_all_tickets():
        if ticket.status in (RequestStatus.archived, RequestStatus.rejected):
            continue

        phase = _current_phase_of(ticket.workflow_state_parsed)
        if not phase:
            continue

        resp = current_responsibility(ticket)
        kind = resp.get("kind")

        if kind == "user":
            if resp.get("id") == user_id:
                assigned.append(_board_item(ticket, phase, None))

        elif kind == "group":
            gid = resp.get("id")
            if gid in group_ids:
                board_for(gid)["tickets"].append(_board_item(ticket, phase, None))

        elif kind == "departments":
            for gid, dept in resp.get("departments", {}).items():
                if gid in group_ids and dept.get("required") and dept.get("status") != DEPARTMENT_STATUS_DONE:
                    board_for(gid)["tickets"].append(_board_item(ticket, phase, gid))

    return {
        "assigned": assigned,
        "departments": [b for b in boards.values() if b["tickets"]],
    }
