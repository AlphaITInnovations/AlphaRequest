import json
from datetime import datetime
from alpharequestmanager.database.database import get_ticket, update_ticket


def add_history_event(
    ticket_id: int,
    *,
    actor_id: str | None,
    actor_name: str,
    actor_type: str = "user",  # user | system
    action: str,
    details: dict | None = None,
):
    ticket = get_ticket(ticket_id)
    if not ticket:
        return

    history = ticket.history_parsed
    print("before:", history)
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
    print("after:", history)
    update_ticket(
        ticket_id=ticket_id,
        history=json.dumps(history, ensure_ascii=False),
    )


def get_ticket_history(ticket_id: int) -> list[dict]:
    ticket = get_ticket(ticket_id)
    if not ticket:
        return []

    history = ticket.history_parsed or []

    if not isinstance(history, list):
        return []

    try:
        history = sorted(
            history,
            key=lambda x: x.get("timestamp", "")
        )
    except Exception:
        pass

    return history
