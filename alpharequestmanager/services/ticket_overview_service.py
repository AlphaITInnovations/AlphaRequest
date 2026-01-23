from __future__ import annotations

from typing import Iterable, List, Optional

from alpharequestmanager.database.database import settings_get, settings_set

_SETTINGS_KEY = "TICKET_OVERVIEW_GROUPS"


def _normalize_member_id(member_id: str) -> str:
    if not isinstance(member_id, str):
        raise TypeError("member_id must be a str")
    mid = member_id.strip()
    if not mid:
        raise ValueError("member_id must not be empty/blank")
    return mid


def _sanitize_groups(raw: object) -> List[str]:
    """
    Macht aus beliebigem DB-Inhalt eine saubere, eindeutige Liste von Strings.
    - entfernt None / Nicht-Strings
    - trimmt Whitespace
    - entfernt leere Strings
    - entfernt Duplikate (bei Beibehaltung der Reihenfolge)
    """
    if not isinstance(raw, list):
        return []

    seen = set()
    cleaned: List[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        mid = item.strip()
        if not mid:
            continue
        if mid in seen:
            continue
        seen.add(mid)
        cleaned.append(mid)

    return cleaned


def get_overview_groups() -> List[str]:
    raw = settings_get(_SETTINGS_KEY, default=[])
    return _sanitize_groups(raw)


def save_overview_groups(groups: Iterable[str]) -> None:
    """
    Speichert die Liste bereinigt & eindeutig.
    Acceptet Iterable, damit du auch Sets/Tuples übergeben kannst.
    """
    if groups is None:
        raise TypeError("groups must not be None")

    # Wir bereinigen hier bewusst nochmal, damit auch direkte Aufrufer safe sind.
    cleaned = _sanitize_groups(list(groups))
    settings_set(_SETTINGS_KEY, cleaned)


def add_overview_groups_member(member_id: str) -> bool:
    """
    Fügt member_id hinzu, wenn noch nicht vorhanden.
    Returns: True wenn hinzugefügt, False wenn schon drin.
    """
    mid = _normalize_member_id(member_id)
    groups = get_overview_groups()

    if mid in groups:
        return False

    groups.append(mid)
    save_overview_groups(groups)
    return True


def remove_overview_groups_member(member_id: str) -> bool:
    """
    Entfernt member_id, falls vorhanden.
    Returns: True wenn entfernt, False wenn nicht vorhanden.
    """
    mid = _normalize_member_id(member_id)
    groups = get_overview_groups()

    if mid not in groups:
        return False

    groups = [g for g in groups if g != mid]
    save_overview_groups(groups)
    return True


def is_overview_groups_member(user_id: str) -> bool:
    mid = _normalize_member_id(user_id)
    return mid in get_overview_groups()


def ensure_overview_groups_member(member_id: str) -> None:
    """
    Idempotent: danach ist der User garantiert drin.
    (Wenn du keinen bool brauchst.)
    """
    add_overview_groups_member(member_id)
