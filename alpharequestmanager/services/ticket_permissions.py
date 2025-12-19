from alpharequestmanager.database.database import settings_get, settings_set
from alpharequestmanager.models.models import TicketType
from alpharequestmanager.utils.logger import logger


def load_ticket_permissions() -> dict:
    data = settings_get("TICKET_PERMISSIONS", {})
    if not isinstance(data, dict):
        return {}

    allowed = get_allowed_ticket_types()
    cleaned = {}

    for t in allowed:
        users = data.get(t)
        cleaned[t] = [str(u) for u in users] if isinstance(users, list) else []

    return cleaned



def can_user_create_ticket(ticket_type: str, user_id: str) -> bool:
    """
    Prüft, ob ein User einen bestimmten Tickettyp erstellen darf.
    - Admins haben KEINE Sonderrechte
    - Leere Liste => niemand darf
    - Tickettyp nicht vorhanden => niemand darf
    """

    if not ticket_type or not user_id:
        return False

    permissions = load_ticket_permissions()

    allowed_users = permissions.get(ticket_type)
    if not isinstance(allowed_users, list):
        return False

    return user_id in allowed_users


def get_allowed_ticket_types_for_user(user_id: str) -> list[str]:
    """
    Gibt alle Tickettypen zurück, die der User erstellen darf.
    """
    if not user_id:
        return []

    permissions = load_ticket_permissions()
    allowed = []

    for ticket_type, users in permissions.items():
        if isinstance(users, list) and user_id in users:
            allowed.append(ticket_type)

    return allowed


def init_ticket_permissions():
    """
    Stellt sicher, dass für jeden TicketType ein Permission-Eintrag existiert.
    Fehlende Tickettypen werden mit leerer Liste ergänzt.
    """
    raw = settings_get("TICKET_PERMISSIONS", {})

    if not isinstance(raw, dict):
        logger.warning("TICKET_PERMISSIONS ist kein dict – wird zurückgesetzt")
        raw = {}

    changed = False

    for t in TicketType:
        key = t.value
        if key not in raw or not isinstance(raw.get(key), list):
            raw[key] = []
            changed = True

    if changed:
        settings_set("TICKET_PERMISSIONS", raw)
        logger.info("TICKET_PERMISSIONS initialisiert / ergänzt")

    return raw


def get_allowed_ticket_types() -> set[str]:
    return {t.value for t in TicketType}


def add_user_ticket_permission(ticket_type: str, user_id: str):
    perms = load_ticket_permissions()

    if ticket_type not in get_allowed_ticket_types():
        raise ValueError(f"Ungültiger TicketType: {ticket_type}")

    if user_id not in perms[ticket_type]:
        perms[ticket_type].append(user_id)
        settings_set("TICKET_PERMISSIONS", perms)


def remove_user_ticket_permission(ticket_type: str, user_id: str):
    perms = load_ticket_permissions()

    if ticket_type not in get_allowed_ticket_types():
        raise ValueError(f"Ungültiger TicketType: {ticket_type}")

    if user_id in perms[ticket_type]:
        perms[ticket_type].remove(user_id)
        settings_set("TICKET_PERMISSIONS", perms)


def set_ticket_permissions_safe(payload: dict):
    allowed = get_allowed_ticket_types()
    perms = init_ticket_permissions()

    for ticket_type, users in payload.items():
        if ticket_type not in allowed:
            continue  # oder raise Exception

        if not isinstance(users, list):
            continue

        perms[ticket_type] = [str(u) for u in users]

    settings_set("TICKET_PERMISSIONS", perms)

