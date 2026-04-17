"""
Ticket-Erstellungsrechte werden als extra_permissions auf dem User gespeichert.
Permission-Format: "create_<ticket_type>" z.B. "create_onboarding"

Zusätzlich können AD-Gruppen-IDs pro Tickettyp berechtigt werden.
Wenn ein User Mitglied einer berechtigten AD-Gruppe ist, darf er den
Tickettyp ebenfalls erstellen.
"""

import json
from backend.database.users import (
    list_users,
    add_extra_permission,
    remove_extra_permission,
    get_user,
    set_extra_permissions,
    upsert_user,
)
from backend.database.ticket_group_permissions import (
    load_all as _load_group_perms_db,
    set_all as _set_group_perms_db,
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


def can_user_create_ticket(
    ticket_type: str,
    user_id: str,
    user_group_ids: list[str] | None = None,
) -> bool:
    """
    Prüft ob ein User einen bestimmten Tickettyp erstellen darf.
    Erlaubt wenn:
      1. Der User die extra_permission "create_<type>" hat, ODER
      2. Der User Mitglied einer AD-Gruppe ist, die für diesen Typ berechtigt ist.
    """
    if not ticket_type or not user_id:
        return False

    user = get_user(user_id)
    if not user:
        return False

    # 1. Direkte User-Permission
    if _perm(ticket_type) in user.extra_permissions:
        return True

    # 2. Gruppen-Permission
    if user_group_ids:
        group_perms = load_group_ticket_permissions()
        allowed_groups = set(group_perms.get(ticket_type, []))
        if allowed_groups & set(user_group_ids):
            return True

    return False


def get_allowed_ticket_types_for_user(
    user_id: str,
    user_group_ids: list[str] | None = None,
) -> list[str]:
    """Gibt alle Tickettypen zurück die der User erstellen darf (direkt oder via Gruppe)."""
    if not user_id:
        return []

    user = get_user(user_id)
    if not user:
        return []

    valid = {t.value for t in TicketType}
    allowed = set()

    # Direkte Permissions
    for perm in user.extra_permissions:
        if perm.startswith("create_") and perm[len("create_"):] in valid:
            allowed.add(perm[len("create_"):])

    # Gruppen-Permissions
    if user_group_ids:
        group_perms = load_group_ticket_permissions()
        user_groups_set = set(user_group_ids)
        for ticket_type, group_ids in group_perms.items():
            if ticket_type in valid and user_groups_set & set(group_ids):
                allowed.add(ticket_type)

    return sorted(allowed)


# ── Write ─────────────────────────────────────────────────────────────────────

def add_user_ticket_permission(ticket_type: str, user_id: str) -> None:
    _require_valid_type(ticket_type)
    add_extra_permission(user_id, _perm(ticket_type))


def remove_user_ticket_permission(ticket_type: str, user_id: str) -> None:
    _require_valid_type(ticket_type)
    remove_extra_permission(user_id, _perm(ticket_type))


def set_ticket_permissions_safe(
    payload: dict[str, list[str]],
    user_cache: list[dict] | None = None,
) -> None:
    """
    Ersetzt für jeden übergebenen TicketType die erlaubten User komplett.
    Andere extra_permissions der User (z.B. "manage") bleiben unberührt.

    user_cache: app.state.user_cache – wird benötigt um User die noch nie
    eingeloggt waren automatisch in der DB anzulegen.
    """
    valid_types = {t.value for t in TicketType}
    all_users   = {u.microsoft_id: u for u in list_users()}

    # Unbekannte User-IDs aus dem Cache anlegen (noch nie eingeloggt)
    if user_cache:
        cache_by_id  = {u["id"]: u for u in user_cache}
        all_user_ids = {uid for user_ids in payload.values() for uid in user_ids}

        for user_id in all_user_ids:
            if user_id not in all_users and user_id in cache_by_id:
                u = cache_by_id[user_id]
                upsert_user(
                    microsoft_id=user_id,
                    display_name=u.get("displayName", ""),
                    email=u.get("mail") or u.get("userPrincipalName") or "",
                )
                all_users[user_id] = get_user(user_id)

    # Zielzustand: user_id → gewünschte create_* permissions
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
        current_create = {p for p in user.extra_permissions if p.startswith("create_")}
        desired_create = target[user_id]

        for perm in current_create - desired_create:
            remove_extra_permission(user_id, perm)
        for perm in desired_create - current_create:
            add_extra_permission(user_id, perm)


# ── Group Permissions (AD-Gruppen → Ticket-Typen) ────────────────────────────

def load_group_ticket_permissions() -> dict[str, list[str]]:
    """
    Gibt für jeden TicketType die Liste der erlaubten AD-Gruppen-IDs zurück.
    { "zugang-beantragen": ["ad-group-id-1", ...], ... }
    """
    data = _load_group_perms_db()
    # Sicherstellen dass alle TicketTypes vorhanden sind
    result = {t.value: [] for t in TicketType}
    for k, v in data.items():
        if k in result:
            result[k] = v
    return result


def set_group_ticket_permissions(payload: dict[str, list[str]]) -> None:
    """
    Setzt die Gruppen-Permissions für Ticket-Typen.
    payload: { "zugang-beantragen": ["ad-group-id-1", ...], ... }
    """
    valid_types = {t.value for t in TicketType}
    cleaned = {
        k: list(set(v))
        for k, v in payload.items()
        if k in valid_types and isinstance(v, list)
    }
    _set_group_perms_db(cleaned)