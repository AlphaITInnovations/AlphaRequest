import uuid
from typing import List, Optional

from backend.database.settings import settings_get, settings_set


# ── CRUD ──────────────────────────────────────────────────────────────────────

def get_groups() -> List[dict]:
    groups = settings_get("TICKET_GROUPS", default=[])
    if not isinstance(groups, list):
        return []

    # Backward compatibility
    for g in groups:
        if "members" not in g:
            g["members"] = []
        if "distributions" not in g:
            g["distributions"] = []
        if "hidden" not in g:
            g["hidden"] = False

    return groups


def save_groups(groups: List[dict]) -> None:
    if not isinstance(groups, list):
        raise ValueError("Groups must be list")
    settings_set("TICKET_GROUPS", groups)


def ensure_required_groups(required_names: List[str]) -> List[str]:
    """
    Stellt sicher, dass für jeden geforderten Namen eine Gruppe existiert
    (case-insensitive). Fehlende Gruppen werden leer angelegt (keine Mitglieder,
    keine Verteiler). Idempotent. Gibt die Namen der neu angelegten Gruppen zurück.
    """
    groups = get_groups()
    existing = {g.get("name", "").strip().lower() for g in groups}
    created: List[str] = []
    for name in required_names:
        key = (name or "").strip().lower()
        if not key or key in existing:
            continue
        groups.append({
            "id": uuid.uuid4().hex,
            "name": name,
            "members": [],
            "distributions": [],
        })
        existing.add(key)
        created.append(name)
    if created:
        save_groups(groups)
    return created


# ── Lookups ───────────────────────────────────────────────────────────────────

def get_users_from_group(group_id: str) -> List[str]:
    if not group_id:
        return []
    for g in get_groups():
        if g.get("id") == group_id:
            members = g.get("members", [])
            return members if isinstance(members, list) else []
    return []


def get_groupID_from_name(group_name: str) -> Optional[str]:
    if not group_name:
        return None
    for g in get_groups():
        if g.get("name") == group_name:
            return g.get("id")
    return None


def get_group_ids_for_user(user_id: str) -> List[str]:
    if not user_id:
        return []
    return [
        g.get("id")
        for g in get_groups()
        if isinstance(g.get("members"), list) and user_id in g["members"]
    ]


def get_group_name_from_id(group_id: str) -> Optional[str]:
    for g in get_groups():
        if g.get("id") == group_id:
            return g.get("name")
    return None


# ── Distributions ─────────────────────────────────────────────────────────────

def get_distributions_from_group(group_id: str) -> List[str]:
    if not group_id:
        return []
    for g in get_groups():
        if g.get("id") == group_id:
            distributions = g.get("distributions", [])
            return distributions if isinstance(distributions, list) else []
    return []


def get_distributions_from_group_name(group_name: str) -> List[str]:
    group_id = get_groupID_from_name(group_name)
    if not group_id:
        return []
    return get_distributions_from_group(group_id)