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

    add("Miete")
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
            "status": PHASE_STATUS_IN_PROGRESS if i == 0 else PHASE_STATUS_PENDING,
        }
        if phase_def.type == PhaseType.department_review:
            builder = DEPARTMENT_BUILDERS.get(ticket.ticket_type)
            phase["departments"] = builder(description) if builder else {}
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


def _ticket_to_department_item(ticket: Ticket) -> dict:
    return {
        "id": ticket.id,
        "title": ticket.title,
        "type_key": ticket.ticket_type.value,
        "status": ticket.status.value,
        "priority": ticket.priority.value,
        "created_at": ticket.created_at.isoformat() if ticket.created_at else None,
    }


def get_department_requests_for_user(user_id: str) -> list[dict]:
    group_ids = get_group_ids_for_user(user_id)
    if not group_ids:
        return []

    tickets = list_all_tickets()
    result: list[dict] = []

    for group_id in group_ids:
        group_tickets: list[dict] = []

        for ticket in tickets:
            if ticket.status != RequestStatus.in_request:
                continue
            departments = _get_departments_from_workflow(ticket.workflow_state_parsed)
            dept = departments.get(group_id)
            if dept and dept.get("required") and dept.get("status") != DEPARTMENT_STATUS_DONE:
                group_tickets.append(_ticket_to_department_item(ticket))

        if group_tickets:
            result.append({
                "group_id": group_id,
                "group_name": get_group_name_from_id(group_id),
                "tickets": group_tickets,
            })

    return result
