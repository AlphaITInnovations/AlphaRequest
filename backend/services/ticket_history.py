import json
from datetime import datetime
from backend.database.tickets import get_ticket, update_ticket


def add_history_event(
    ticket_id: int,
    *,
    actor_id: str | None,
    actor_name: str,
    actor_type: str = "user",  # "user" | "system"
    action: str,
    details: dict | None = None,
) -> None:
    ticket = get_ticket(ticket_id)
    if not ticket:
        return

    history = ticket.history_parsed
    history.append({
        "timestamp": datetime.utcnow().isoformat(),
        "actor": {
            "id": actor_id,
            "name": actor_name,
            "type": actor_type,
        },
        "action": action,
        "details": details or {},
    })

    update_ticket(
        ticket_id=ticket_id,
        history=json.dumps(history, ensure_ascii=False),
    )


def add_field_change_events(
    ticket_id: int,
    *,
    actor_id: str | None,
    actor_name: str,
    changes: dict,  # {"field": (old_value, new_value)}
) -> None:
    """Schreibt pro geändertem Feld ein eigenes History-Event."""
    for field, (old_val, new_val) in changes.items():
        add_history_event(
            ticket_id,
            actor_id=actor_id,
            actor_name=actor_name,
            action=f"{field}_changed",
            details={"field": field, "old_value": old_val, "new_value": new_val},
        )


def get_ticket_history(ticket_id: int) -> list[dict]:
    ticket = get_ticket(ticket_id)
    if not ticket:
        return []

    history = ticket.history_parsed
    if not isinstance(history, list):
        return []

    return sorted(history, key=lambda x: x.get("timestamp", ""))