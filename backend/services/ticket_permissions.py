"""
Ticket-Erstellungsrechte werden als extra_permissions auf dem User gespeichert.
Permission-Format: "create_<ticket_type>" z.B. "create_onboarding"
Die Settings-Tabelle (TICKET_PERMISSIONS) wird nicht mehr verwendet.
"""

from backend.database.users import (
    list_users,
    add_extra_permission,
    remove_extra_permission,
    get_user,
    set_extra_permissions,
)
from backend.models.models import TicketType


# ── Helpers ───────────────────────────────────────────────────────────────────

VALID_TICKET_TYPES: frozenset[str] = frozenset(t.value for t in TicketType)


def _perm(ticket_type: str) -> str:
    return f"create_{ticket_type}"


def _require_valid_type(ticket_type: str) -> None:
    if ticket_type not in VALID_TICKET_TYPES:
        raise ValueError(
            f"Ungültiger TicketType: {ticket_type!r}. "
            f"Erlaubt: {sorted(VALID_TICKET_TYPES)}"
        )


# ── Read ──────────────────────────────────────────────────────────────────────

def load_ticket_permissions() -> dict[str, list[str]]:
    """
    Gibt für jeden TicketType die Liste der erlaubten User-IDs zurück.
    { "onboarding": ["user_id_1", ...], ... }
    """
    result: dict[str, list[str]] = {t.value: [] for t in TicketType}

    for user in list_users():
        for perm in user.extra_permissions:
            if perm.startswith("create_"):
                ticket_type = perm[len("create_"):]
                if ticket_type in result:
                    result[ticket_type].append(user.microsoft_id)

    return result


def can_user_create_ticket(ticket_type: str, user_id: str) -> bool:
    """
    Prüft ob ein User einen bestimmten Tickettyp erstellen darf.
    - Admins haben keine automatischen Sonderrechte
    - Leere Liste / unbekannter Typ => niemand darf
    """
    if not ticket_type or not user_id:
        return False

    user = get_user(user_id)
    if not user:
        return False

    return _perm(ticket_type) in user.extra_permissions


def get_allowed_ticket_types_for_user(user_id: str) -> list[str]:
    """Gibt alle Tickettypen zurück die der User erstellen darf."""
    if not user_id:
        return []

    user = get_user(user_id)
    if not user:
        return []

    valid = {t.value for t in TicketType}
    return [
        perm[len("create_"):]
        for perm in user.extra_permissions
        if perm.startswith("create_") and perm[len("create_"):] in valid
    ]


# ── Write ─────────────────────────────────────────────────────────────────────

def add_user_ticket_permission(ticket_type: str, user_id: str) -> None:
    _require_valid_type(ticket_type)
    add_extra_permission(user_id, _perm(ticket_type))


def remove_user_ticket_permission(ticket_type: str, user_id: str) -> None:
    _require_valid_type(ticket_type)
    remove_extra_permission(user_id, _perm(ticket_type))


def set_ticket_permissions_safe(payload: dict[str, list[str]]) -> None:
    """
    Ersetzt für jeden übergebenen TicketType die erlaubten User komplett.
    Andere extra_permissions der User (z.B. "manage") bleiben unberührt.
    """
    valid_types = {t.value for t in TicketType}
    all_users   = {u.microsoft_id: u for u in list_users()}

    # Sammle gewünschten Zielzustand: user_id → set of create_* perms
    target: dict[str, set[str]] = {uid: set() for uid in all_users}

    for ticket_type, user_ids in payload.items():
        if ticket_type not in valid_types:
            continue
        perm = _perm(ticket_type)
        for user_id in user_ids:
            if user_id in target:
                target[user_id].add(perm)

    # Für jeden User: create_* permissions auf Zielzustand bringen
    for user_id, user in all_users.items():
        current_create = {
            p for p in user.extra_permissions if p.startswith("create_")
        }
        desired_create = target[user_id]

        for perm in current_create - desired_create:
            remove_extra_permission(user_id, perm)
        for perm in desired_create - current_create:
            add_extra_permission(user_id, perm)