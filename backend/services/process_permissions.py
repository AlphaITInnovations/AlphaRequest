"""
Erstellrechte eines Prozesses (Teil der Definition, siehe CreatePermissions).

Reine Prüf-Logik ohne DB-Zugriff, damit sie testbar bleibt – die
Gruppen-Mitgliedschaft reicht der Aufrufer herein.
"""
from typing import Iterable, Optional

from backend.database.users import PERM_ADMIN
from backend.schemas.process_definition import ProcessDefinition


def may_create(defn: ProcessDefinition, user: dict,
               group_ids: Optional[Iterable[str]] = None) -> bool:
    """Darf `user` einen Auftrag dieses Prozesses anlegen?

    Reihenfolge: Admin darf immer · „jeder" · Person explizit genannt ·
    Mitglied einer berechtigten Gruppe. Sonst nein (Default-Deny).
    """
    perms = set(user.get("permissions") or [])
    if PERM_ADMIN in perms:
        return True

    cp = defn.createPermissions
    if cp.everyone:
        return True

    uid = user.get("id")
    if uid and uid in set(cp.users or []):
        return True

    allowed = set(cp.groups or [])
    if allowed and set(group_ids or ()) & allowed:
        return True
    return False


def creatable_keys(defns: Iterable[ProcessDefinition], user: dict,
                   group_ids: Optional[Iterable[str]] = None) -> set:
    """Schlüssel aller Prozesse, die `user` anlegen darf."""
    gids = list(group_ids or ())
    return {d.key for d in defns if may_create(d, user, gids)}
