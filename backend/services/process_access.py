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


def may_force_archive(user: dict) -> bool:
    """Zwangsabschluss: Admin ODER Manager.

    Die Aufsichts-Rolle „manage" darf Aufträge aus der Auftragsliste archivieren
    (Alt-System-Regel: viewer liest nur, manager darf zusätzlich archivieren,
    admin darf alles). Bewusst eine EIGENE Funktion statt einer Aufweichung von
    may_edit – archivieren ist die einzige Schreibaktion der Manager-Rolle.
    """
    return is_admin(user) or PERM_MANAGE in set(user.get("permissions") or [])


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


def responsible_group_refs(defn: Optional[ProcessDefinition]) -> tuple[set, list]:
    """(unbedingte Gruppen, bedingte Regeln) über ALLE Phasen.

    unbedingt = immer zuständig (group-Phase oder departments-Regel ohne `when`).
    bedingt   = Liste von (group, when) für bedingte departments-Regeln – erst
    gegen die Auftragswerte auszuwerten. group_from_field bleibt außen vor (die
    Gruppe steht erst zur Laufzeit im Auftrag, nicht in der Definition)."""
    uncond: set = set()
    cond: list = []
    if defn is None:
        return uncond, cond
    for p in defn.phases:
        r = p.responsibility
        if r.kind == ResponsibilityKind.group and r.group:
            uncond.add(r.group)
        elif r.kind == ResponsibilityKind.departments:
            for dr in r.rule:
                if not dr.group:
                    continue
                if dr.when is None:
                    uncond.add(dr.group)
                else:
                    cond.append((dr.group, dr.when))
    return uncond, cond


def _phase_reached(pe: dict) -> bool:
    """Wurde diese Runtime-Phase schon BETRETEN? `pending` ohne `entered_at` = noch
    nicht (spätere Phase); alles andere (open/done bzw. `entered_at` gesetzt) = ja.
    Rücksprung (reopen/send_back) setzt Phasen VOR dem Ziel auf `done` (erreicht)
    und dahinter zurück auf `pending` (gilt dann wieder als nicht erreicht)."""
    return pe.get("status") != "pending" or bool(pe.get("entered_at"))


def group_in_reached_phase(defn: Optional[ProcessDefinition], runtime: dict,
                           gset: set) -> bool:
    """Ist eine der Gruppen `gset` in einer vom Auftrag WIRKLICH BETRETENEN Phase
    (aktuell oder abgeschlossen) zuständig – Fachabteilung ODER group-Phase?

    Fachabteilungen zählen über den beim Eintritt geseedeten Abteilungs-Stand der
    Phase (`runtime.phases[i].departments`): dort ist die bedingte Regel bereits
    aufgelöst (z. B. Fuhrpark nur bei Dienstwagen=Ja). So erscheint ein Auftrag im
    persönlichen Archiv erst, wenn er die Phase der Abteilung ERREICHT hat – nicht
    schon, weil sie laut Definition irgendwann einmal zuständig wäre."""
    if defn is None or not gset:
        return False
    phases = defn.phases
    for i, pe in enumerate(runtime.get("phases") or []):
        if i >= len(phases) or not _phase_reached(pe):
            continue
        r = phases[i].responsibility
        if r.kind == ResponsibilityKind.group and r.group in gset:
            return True
        if r.kind == ResponsibilityKind.departments \
                and any(d.get("group") in gset for d in (pe.get("departments") or [])):
            return True
    return False


def archive_involved(defn: Optional[ProcessDefinition], row: dict, user: dict,
                     group_ids: Iterable[str], *, is_watcher: bool = False) -> bool:
    """War/ist der/die Nutzende an DIESEM Auftrag beteiligt – fürs persönliche
    Archiv (ALLE Status): Ersteller:in · Beobachter:in · aktuell Zuständige:r ·
    Mitglied einer Gruppe/Fachabteilung, die in einer vom Auftrag TATSÄCHLICH
    ERREICHTEN Phase zuständig ist/war.

    WICHTIG: Eine Fachabteilung sieht den Auftrag erst, wenn er ihre Phase erreicht
    hat (oder hatte) – NICHT schon, weil die Abteilung laut Definition später einmal
    zuständig wäre. Ein Onboarding mit Dienstwagen taucht beim Fuhrpark also erst
    auf, wenn es in der Durchführung ist; wird es vorher abgelehnt/gelöscht, bekommt
    die noch nicht beteiligte Abteilung nichts davon mit. Über die AKTUELLE
    Mitgliedschaft (neue Mitglieder sehen die erreichte Vergangenheit).

    BEWUSST OHNE Aufsichts-Kurzschluss: die Aufsichtsrolle (view/manage/admin) ist
    Sache der Übersicht „Alle Aufträge", NICHT des persönlichen Archivs. (Das
    Detail-Lesen erlaubt der Aufsicht trotzdem der Zugriff – über may_view.)"""
    uid = user.get("id")
    if uid and row.get("owner_id") == uid:
        return True
    if is_watcher:
        return True
    gset = set(group_ids or ())
    # Aktuell zuständig (deckt owner/user/assignable/group/departments der AKTIVEN Phase).
    if is_responsible(defn, row, user, gset):
        return True
    # ODER Gruppe/Fachabteilung in einer bereits erreichten Phase (Vergangenheit).
    return group_in_reached_phase(defn, row.get("runtime") or {}, gset)


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


def _phase_groups(row: dict, phase) -> set:
    """Zuständige Gruppen einer BELIEBIGEN Phase (nicht nur der aktuellen)."""
    r = phase.responsibility
    if r.kind == ResponsibilityKind.group and r.group:
        return {r.group}
    if r.kind == ResponsibilityKind.group_from_field:
        picked = (row.get("values") or {}).get(r.fromField or "")
        return {picked} if picked else set()
    if r.kind == ResponsibilityKind.departments:
        return {dr.group for dr in r.rule if dr.group}
    return set()


def is_responsible_for_phase(defn: Optional[ProcessDefinition], row: dict, phase,
                             user: dict, group_ids: Iterable[str]) -> bool:
    """Wie `is_responsible`, aber für eine BESTIMMTE Phase (z. B. die Dokument-Phase),
    unabhängig davon, welche Phase gerade aktuell ist."""
    if defn is None or phase is None:
        return False
    uid = user.get("id")
    r = phase.responsibility
    if r.kind == ResponsibilityKind.owner:
        return bool(uid) and row.get("owner_id") == uid
    if r.kind == ResponsibilityKind.user:
        return bool(uid) and r.user == uid
    if r.kind == ResponsibilityKind.assignable:
        picked = (row.get("values") or {}).get(r.fromField or "")
        return bool(uid) and picked == uid
    if r.kind in (ResponsibilityKind.group, ResponsibilityKind.departments,
                  ResponsibilityKind.group_from_field):
        return bool(set(group_ids) & _phase_groups(row, phase))
    return False


def may_generate_document(defn: Optional[ProcessDefinition], row: dict, user: dict,
                          group_ids: Iterable[str]) -> bool:
    """Darf die Person das Dokument (z. B. den Arbeitsvertrag) erzeugen? NUR die für
    die DOKUMENT-Phase zuständige Stelle und Admins – ausdrücklich NICHT Ersteller:in,
    Beobachter:innen oder andere Beteiligte. Gate an der Dokument-Phase (nicht der
    aktuellen), damit „wer erzeugt das Dokument" eindeutig ist."""
    if is_admin(user):
        return True
    if defn is None:
        return False
    docphase = next((p for p in defn.phases if p.document is not None), None)
    return is_responsible_for_phase(defn, row, docphase, user, group_ids)


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
