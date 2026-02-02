import json
from typing import Dict
from alpharequestmanager.models.models import TicketType, RequestStatus

from alpharequestmanager.database.database import (
    update_ticket,
    get_ticket,
    get_users_from_group,
    get_groups, list_all_tickets, get_group_name_from_id,
)
from alpharequestmanager.models.models import Ticket, TicketType

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



# ============================================================
# Core helpers
# ============================================================

def set_workflow_state(ticket_id: int, workflow: dict) -> None:
    print("set_workflow_state", workflow)
    update_ticket(
        ticket_id,
        workflow_state=json.dumps(workflow, ensure_ascii=False)
    )


def get_workflow_state(ticket_id: int) -> dict:
    ticket = get_ticket(ticket_id)
    return ticket.workflow_state_parsed if ticket and ticket.workflow_state else {}


def _require_workflow(ticket_id: int) -> dict:
    workflow = get_workflow_state(ticket_id)
    if "departments" not in workflow:
        raise ValueError("Workflow not initialized for this ticket")
    return workflow


# ============================================================
# Department handling
# ============================================================

def set_department_status(ticket_id: int, group_id: str, status: str):
    if status not in ALLOWED_DEPARTMENT_STATUS:
        raise ValueError(f"Invalid department status '{status}'")

    workflow = _require_workflow(ticket_id)

    if group_id not in workflow["departments"]:
        raise ValueError("Group not part of workflow")

    workflow["departments"][group_id]["status"] = status
    set_workflow_state(ticket_id, workflow)


def get_department_status(ticket_id: int, group_id: str) -> str | None:
    workflow = get_workflow_state(ticket_id)
    return workflow.get("departments", {}).get(group_id, {}).get("status")


def get_department_info(ticket_id: int, group_id: str) -> dict | None:
    workflow = get_workflow_state(ticket_id)
    return workflow.get("departments", {}).get(group_id)


def get_all_department_statuses(ticket_id: int) -> dict:
    workflow = get_workflow_state(ticket_id)
    return workflow.get("departments", {})


# ============================================================
# Archive logic
# ============================================================

def can_archive_ticket(ticket_id: int) -> bool:
    workflow = _require_workflow(ticket_id)

    for dept in workflow["departments"].values():
        if dept.get("required") and dept.get("status") != DEPARTMENT_STATUS_DONE:
            return False

    return True


# ============================================================
# Change handling
# ============================================================

def reset_departments_on_description_change(ticket_id: int) -> None:
    workflow = get_workflow_state(ticket_id)
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

    for group_id, data in workflow.get("departments", {}).items():
        if user_id in get_users_from_group(group_id):
            result[group_id] = data

    return result


def user_can_complete_department(ticket_id: int, user_id: str, group_id: str) -> bool:
    if user_id not in get_users_from_group(group_id):
        return False

    status = get_department_status(ticket_id, group_id)
    return status in {
        DEPARTMENT_STATUS_OPEN,
        DEPARTMENT_STATUS_IN_PROGRESS,
    }


# ============================================================
# Workflow builders
# ============================================================

def build_workflow_zugang_beantragen(description: dict) -> dict:
    groups = {g["name"].lower(): g for g in get_groups()}

    workflow = {"departments": {}}

    def add_group(name: str):
        g = groups.get(name.lower())
        if not g:
            return
        workflow["departments"][g["id"]] = {
            "name": g["name"],
            "required": True,
            "status": DEPARTMENT_STATUS_OPEN,
        }

    add_group("IT")
    add_group("Personalabteilung")

    if description.get("fuhrpark", {}).get("car") == "Ja":
        add_group("Fuhrpark")

    return workflow


def build_workflow_zugang_sperren(description: dict) -> dict:
    return build_workflow_zugang_beantragen(description)

def build_workflow_hardware(description: dict) -> dict:
    groups = {g["name"].lower(): g for g in get_groups()}

    workflow = {"departments": {}}

    def add_group(name: str):
        g = groups.get(name.lower())
        if not g:
            return
        workflow["departments"][g["id"]] = {
            "name": g["name"],
            "required": True,
            "status": DEPARTMENT_STATUS_OPEN,
        }

    add_group("IT")

    return workflow

def build_workflow_niederlassung_schliessen(description: dict) -> dict:
    groups = {g["name"].lower(): g for g in get_groups()}

    workflow = {"departments": {}}

    def add_group(name: str):
        g = groups.get(name.lower())
        if not g:
            return
        workflow["departments"][g["id"]] = {
            "name": g["name"],
            "required": True,
            "status": DEPARTMENT_STATUS_OPEN,
        }

    add_group("IT")
    add_group("Personalabteilung")

    if description.get("fuhrpark", {}).get("pool_cars") == "Ja":
        add_group("Fuhrpark")

    return workflow


def build_workflow_niederlassung_anmelden(description: dict) -> dict:
    groups = {g["name"].lower(): g for g in get_groups()}

    workflow = {"departments": {}}

    def add_group(name: str):
        g = groups.get(name.lower())
        if not g:
            return
        workflow["departments"][g["id"]] = {
            "name": g["name"],
            "required": True,
            "status": DEPARTMENT_STATUS_OPEN,
        }

    add_group("Miete")
    add_group("IT")
    add_group("Marketing")

    if description.get("fuhrpark", {}).get("pool_cars") == "Ja":
        add_group("Fuhrpark")

    return workflow

def build_workflow_niederlassung_umzug(description: dict) -> dict:
    pass

WORKFLOW_BUILDERS = {
    TicketType.zugang_beantragen: build_workflow_zugang_beantragen,
    TicketType.zugang_sperren: build_workflow_zugang_sperren,
    TicketType.hardware: build_workflow_hardware,
    TicketType.niederlassung_anmelden: build_workflow_niederlassung_anmelden,
    TicketType.niederlassung_umzug: build_workflow_niederlassung_umzug,
    TicketType.niederlassung_schliessen: build_workflow_niederlassung_schliessen,
}


def build_workflow(ticket: Ticket) -> dict:
    builder = WORKFLOW_BUILDERS.get(ticket.ticket_type)

    if not builder:
        raise ValueError(f"No workflow builder for ticket type {ticket.ticket_type}")

    try:
        description = json.loads(ticket.description)
    except Exception:
        raise ValueError("Ticket description is not valid JSON")

    return builder(description)


def get_tickets_for_department(group_id: str) -> list[Ticket]:
    """
    Gibt alle Tickets zurück, die von einer bestimmten Fachabteilung
    noch bearbeitet werden müssen.
    """
    tickets = list_all_tickets()
    result = []

    for ticket in tickets:
        if ticket.status != RequestStatus.in_request:
            continue

        workflow = ticket.workflow_state_parsed
        departments = workflow.get("departments", {})

        dept = departments.get(group_id)
        if not dept:
            continue

        if dept.get("required") and dept.get("status") != "done":
            result.append(ticket)

    return result

from alpharequestmanager.database.database import get_group_ids_for_user

def get_tickets_for_user_departments(user_id: str) -> dict[str, list[Ticket]]:
    """
    Gibt Tickets gruppiert nach Fachabteilung zurück,
    für alle Gruppen, in denen der User Mitglied ist.
    """
    group_ids = get_group_ids_for_user(user_id)
    result = {}

    for group_id in group_ids:
        tickets = get_tickets_for_department(group_id)
        if tickets:
            result[group_id] = tickets

    return result


def _ticket_to_department_item(ticket: Ticket) -> dict:
    """
    Minimale, dashboard-taugliche Ticket-Darstellung
    """
    return {
        "id": ticket.id,
        "title": ticket.title,
        "type_key": ticket.ticket_type.value,
        "status": ticket.status.value,
        "priority": ticket.priority.value,
        "created_at": ticket.created_at.isoformat() if ticket.created_at else None,
    }


def get_department_requests_for_user(user_id: str) -> list[dict]:
    """
    Gibt alle offenen Fachabteilungs-Tickets für einen User zurück,
    gruppiert nach Fachabteilung.
    Ergebnis ist **vollständig JSON-serialisierbar**.
    """

    group_ids = get_group_ids_for_user(user_id)
    if not group_ids:
        return []

    tickets = list_all_tickets()
    result: list[dict] = []

    for group_id in group_ids:
        group_tickets: list[dict] = []

        for ticket in tickets:
            # Nur Tickets in Bearbeitung der Fachabteilungen
            if ticket.status != RequestStatus.in_request:
                continue

            workflow = ticket.workflow_state_parsed
            dept = workflow.get("departments", {}).get(group_id)

            if not dept:
                continue

            # Nur offene / nicht erledigte Abteilungsaufgaben
            if dept.get("required") and dept.get("status") != "done":
                group_tickets.append(
                    _ticket_to_department_item(ticket)
                )

        if group_tickets:
            result.append({
                "group_id": group_id,
                "group_name": get_group_name_from_id(group_id),
                "tickets": group_tickets,
            })

    return result