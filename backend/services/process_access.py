"""
Zugriff auf einen Prozess-Auftrag: wer darf ihn SEHEN, wer BEARBEITEN?

Getrennt von der Feld-Sichtbarkeit (process_visibility): hier geht es um den
Auftrag als Ganzes. Wer Zugriff hat, sieht anschließend nur die Felder, die der
Sichtbarkeits-Filter freigibt.

Reine Logik – Gruppen-Mitgliedschaft und Beobachter reicht der Aufrufer herein.
"""
from typing import Iterable, Optional

from backend.database.users import PERM_ADMIN, PERM_MANAGE, PERM_VIEW
from backend.schemas.process_definition import ProcessDefinition, ResponsibilityKind
from backend.services import process_runtime as pr


def has_oversight(user: dict) -> bool:
    """Aufsichtsrechte: darf grundsätzlich alle Aufträge sehen."""
    perms = set(user.get("permissions") or [])
    return bool(perms & {PERM_VIEW, PERM_MANAGE, PERM_ADMIN})


def is_admin(user: dict) -> bool:
    return PERM_ADMIN in set(user.get("permissions") or [])


def responsible_groups(defn: Optional[ProcessDefinition], row: dict) -> set:
    """Gruppen, die für die AKTUELLE Phase zuständig sind (inkl. Abteilungen)."""
    if defn is None:
        return set()
    runtime = row.get("runtime") or {}
    phase = pr.current_phase(defn, runtime)
    if phase is None:
        return set()
    r = phase.responsibility
    if r.kind == ResponsibilityKind.group and r.group:
        return {r.group}
    if r.kind == ResponsibilityKind.group_from_field:
        # Die Gruppe steht im Auftrag, nicht in der Definition.
        picked = (row.get("values") or {}).get(r.fromField or "")
        return {picked} if picked else set()
    if r.kind == ResponsibilityKind.departments:
        # Live-Stand bevorzugen (bedingte Abteilungen stehen dort schon fest).
        live = pr.current_departments(runtime)
        if live:
            return {d["group"] for d in live if d.get("group")}
        return {dr.group for dr in r.rule if dr.group}
    return set()


def staff_groups(defn: Optional[ProcessDefinition]) -> set:
    """ALLE Gruppen, die in irgendeiner Phase des Prozesses zuständig sind.

    Im Gegensatz zu `responsible_groups` phasen-UNABHÄNGIG – gedacht für
    Entscheidungen, die über den Auftrag hinweg stabil bleiben müssen (interne
    Nachträge). Wäre „intern" an die aktuelle Phase gekoppelt, würde eine Notiz,
    die die IT in Phase 2 geschrieben hat, in Phase 4 für die IT unsichtbar.
    """
    if defn is None:
        return set()
    out: set = set()
    for p in defn.phases:
        r = p.responsibility
        if r.kind == ResponsibilityKind.group and r.group:
            out.add(r.group)
        elif r.kind == ResponsibilityKind.departments:
            out |= {dr.group for dr in r.rule if dr.group}
    return out


def is_process_staff(defn: Optional[ProcessDefinition], user: dict,
                     group_ids: Iterable[str]) -> bool:
    """Gehört der/die Nutzende zur bearbeitenden Seite dieses Prozesses?

    Aufsicht oder Mitglied einer der beteiligten Fachabteilungen. Maßgeblich für
    interne Nachträge: die sieht die Bearbeitungsseite, NICHT die antragstellende
    Person (auch dann nicht, wenn sie den Auftrag angelegt hat oder beobachtet).

    EINSCHRÄNKUNG: Bei `kind=group_from_field` steht die Gruppe im Auftrag, nicht
    in der Definition – `staff_groups` kann sie also nicht kennen. Für solche
    Prozesse (Basis-Ticket) gilt die bearbeitende Gruppe hier NICHT als
    „bearbeitende Seite"; interne Nachträge bleiben dort der Aufsicht vorbehalten.
    """
    if has_oversight(user):
        return True
    return bool(set(group_ids or ()) & staff_groups(defn))


def is_responsible(defn: Optional[ProcessDefinition], row: dict, user: dict,
                   group_ids: Iterable[str]) -> bool:
    """Ist der/die Nutzende für die aktuelle Phase zuständig?"""
    if defn is None:
        return False
    runtime = row.get("runtime") or {}
    phase = pr.current_phase(defn, runtime)
    if phase is None:
        return False
    uid = user.get("id")
    r = phase.responsibility
    if r.kind == ResponsibilityKind.owner:
        return bool(uid) and row.get("owner_id") == uid
    if r.kind == ResponsibilityKind.user:
        return bool(uid) and r.user == uid
    if r.kind == ResponsibilityKind.assignable:
        # Zuständig ist, wer im hinterlegten Personen-Feld steht.
        picked = (row.get("values") or {}).get(r.fromField or "")
        return bool(uid) and picked == uid
    if r.kind in (ResponsibilityKind.group, ResponsibilityKind.departments,
                  ResponsibilityKind.group_from_field):
        return bool(set(group_ids) & responsible_groups(defn, row))
    return False


def may_view(defn: Optional[ProcessDefinition], row: dict, user: dict,
             group_ids: Iterable[str], watcher_ids: Iterable[str] = ()) -> bool:
    """Darf der/die Nutzende diesen Auftrag öffnen?

    Aufsicht (view/manage/admin) · Ersteller:in · aktuell Zuständige ·
    Beobachter:innen. Sonst nein (Default-Deny).

    Bewusst NICHT: „war mal zuständig". Das braucht eine Beteiligungs-Historie;
    solange die fehlt, ist Beobachter der vorgesehene Weg für Dauer-Einsicht.
    """
    if has_oversight(user):
        return True
    uid = user.get("id")
    if uid and row.get("owner_id") == uid:
        return True
    if uid and uid in set(watcher_ids or ()):
        return True
    return is_responsible(defn, row, user, group_ids)


def may_edit(defn: Optional[ProcessDefinition], row: dict, user: dict,
             group_ids: Iterable[str]) -> bool:
    """Darf der/die Nutzende Werte ändern bzw. die Phase weiterschalten?

    Nur die aktuell zuständige Stelle – und Admins. Reine Aufsicht (view) darf
    LESEN, aber nicht eingreifen.
    """
    if is_admin(user):
        return True
    return is_responsible(defn, row, user, group_ids)


def may_complete_department(defn: Optional[ProcessDefinition], row: dict, user: dict,
                            group_ids: Iterable[str], group_id: str) -> bool:
    """Darf der/die Nutzende GENAU DIESE Fachabteilung abschließen?

    Zwei Bedingungen, und die erste gilt AUCH für Admins:
      1. Die Abteilung muss an der aktuellen Phase beteiligt sein – für eine
         unbeteiligte Abteilung gibt es nichts abzuschließen.
      2. Mitgliedschaft in genau dieser Abteilung. Nur DAS darf ein Admin
         überspringen (Notfall-Eingriff), sonst könnte die IT für den Fuhrpark
         quittieren.
    """
    if group_id not in responsible_groups(defn, row):
        return False
    if is_admin(user):
        return True
    return group_id in set(group_ids)
