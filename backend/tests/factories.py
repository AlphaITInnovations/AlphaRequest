"""Leichtgewichtige Bau-Helfer für die Ebene-1-Tests (kein DB-Zugriff)."""

from types import SimpleNamespace


def make_ticket(*, id=1, owner_id="owner-1", owner_name="Owner",
                workflow=None, history=None):
    """Fake-Ticket mit genau den Attributen, die die workflow_state-Funktionen lesen."""
    return SimpleNamespace(
        id=id,
        owner_id=owner_id,
        owner_name=owner_name,
        workflow_state_parsed=workflow if workflow is not None else {},
        history_parsed=history if history is not None else [],
    )


def wf(phases, idx=0):
    """Workflow-Dict im „neuen Format"."""
    return {"phases": phases, "current_phase_index": idx}


def phase(key, ptype, status="in_progress", *, responsibility=None, departments=None, view=None):
    p = {"key": key, "type": ptype, "status": status}
    if responsibility is not None:
        p["responsibility"] = responsibility
    if departments is not None:
        p["departments"] = departments
    if view is not None:
        p["view"] = view
    return p


def group(gid, name="Gruppe"):
    return {"kind": "group", "id": gid, "name": name}


def user(uid, name="Person"):
    return {"kind": "user", "id": uid, "name": name}


def dept(name, *, required=True, status="open"):
    return {"name": name, "required": required, "status": status}
