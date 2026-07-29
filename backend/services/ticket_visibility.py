"""
Feld-genaue Sichtbarkeit der Ticket-Beschreibung je Fachabteilung.

Motivation: Fachabteilungen in der Durchführung dürfen nur Basisdaten + ihren
eigenen Abschnitt der `description` sehen – der Rest darf sie serverseitig gar
nicht erst erreichen (Frontend-Ausblenden würde die Daten trotzdem übertragen).

Modell:
  - `VISIBILITY[TicketType]` beschreibt, welche dot-Pfade Basis sind (immer sichtbar
    für Beteiligte) und welche Pfade je Fachabteilung (Gruppenname) sichtbar sind.
  - Voll sehen (kein Filter): Oversight (view/manage/admin), der Ersteller und die
    Zuständigen jeder Assignment-Phase (Freigabe/BackOffice/Bearbeitung/Reisestelle).
    Diese verarbeiten den ganzen Vorgang.
  - Eingeschränkt: alle übrigen Beteiligten (Mitglieder einer Durchführungs-
    Fachabteilung) → Basis ∪ Pfade ihrer Fachabteilung(en).
  - Tickettypen OHNE Eintrag werden NICHT gefiltert (Bestandsverhalten).

Sicherheits-Grundsatz: im Zweifel restriktiv. Kann die desc eines gefilterten
Betrachters nicht sauber verarbeitet werden, wird lieber nichts als zu viel
zurückgegeben.
"""

import copy
import json
from typing import Optional

from backend.models.models import TicketType, RequestStatus
from backend.services.phase_definitions import PhaseType
from backend.database.groups import get_groups, get_group_ids_for_user
from backend.database.ticket_watchers import is_watcher


# ── Registry ────────────────────────────────────────────────────────────────────
# base:        dot-Pfade, die jede beteiligte Fachabteilung sehen darf
# departments: Gruppenname -> dot-Pfade, die NUR diese Fachabteilung zusätzlich sieht
VISIBILITY: dict[TicketType, dict] = {
    TicketType.zugang_beantragen: {
        # Basisdaten sind ein eigener desc-Block (salutation, first_name, last_name,
        # contract_company, location, cost_center) und fuer jede beteiligte
        # Fachabteilung sichtbar. Alt-Tickets wurden per Migration ins base-Format
        # ueberfuehrt (backend/services/onboarding_migration.py), daher kein
        # personal.*-Fallback mehr noetig.
        "base": ["base"],
        "departments": {
            "IT": ["it"],
            "Fuhrpark": ["fuhrpark"],
            # HR sieht den kompletten personal-Block (inkl. personal_number, title, start_date …)
            "Personalabteilung": ["personal"],
        },
    },
    # Weitere Tickettypen nach Bedarf ergänzen. Ohne Eintrag => keine Filterung.
}


# ── Vertrauliche Felder (hartes Gate, ÜBERSCHREIBT die Voll-Sicht) ────────────────
# Diese dot-Pfade sehen AUSSCHLIESSLICH Mitglieder einer der genannten Gruppen
# (plus Admins) – unabhängig von Owner/Oversight/Beobachter/Bearbeiter/Involviert.
# Anwendungsfall: Gehalt/Konditionen im Einstellungs-Prozess (P1) – nur die
# Personalabteilung. Werden zusätzlich zur normalen Feld-Sichtbarkeit angewandt
# und beim Schreiben geschützt (siehe preserve_confidential).
CONFIDENTIAL_FIELDS: dict[TicketType, dict] = {
    TicketType.einstellung: {
        "paths": ["personal.salary", "personal.conditions"],
        # Sekretariat GL erstellt/versendet in P1 den Arbeitsvertrag → nur diese
        # Fachabteilung (plus Admin) sieht Gehalt/Konditionen.
        "groups": ["Sekretariat GL"],
    },
}


def _confidential_spec_for(ticket) -> Optional[dict]:
    tt = getattr(ticket, "ticket_type", None)
    if isinstance(tt, TicketType):
        return CONFIDENTIAL_FIELDS.get(tt)
    if isinstance(tt, str):
        for member in TicketType:
            if tt in (member.value, member.name):
                return CONFIDENTIAL_FIELDS.get(member)
    return None


def _may_see_confidential(user: Optional[dict], spec: dict) -> bool:
    """True, wenn der Betrachter die vertraulichen Felder sehen darf: interner Aufruf
    (user=None, z.B. Admin-Detail), Admin, oder Mitglied einer erlaubten Gruppe."""
    if user is None:
        return True
    perms = user.get("permissions", []) or []
    if "admin" in perms:
        return True
    uid = user.get("id")
    if not uid:
        return False
    gids = set(get_group_ids_for_user(uid))
    groups_by_name = {g["name"].strip().lower(): g["id"] for g in get_groups()}
    allowed = {groups_by_name.get(n.strip().lower()) for n in spec.get("groups", [])}
    allowed.discard(None)
    return bool(gids & allowed)


def _get_path(node, path: str):
    for p in path.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(p)
    return node


def _delete_path(node: dict, path: str) -> None:
    parts = path.split(".")
    for p in parts[:-1]:
        node = node.get(p) if isinstance(node, dict) else None
        if not isinstance(node, dict):
            return
    if isinstance(node, dict):
        node.pop(parts[-1], None)


def _set_path(node: dict, path: str, value) -> None:
    parts = path.split(".")
    for p in parts[:-1]:
        nxt = node.get(p)
        if not isinstance(nxt, dict):
            nxt = {}
            node[p] = nxt
        node = nxt
    node[parts[-1]] = value


def _strip_confidential(ticket, user: Optional[dict], desc):
    """Entfernt vertrauliche Felder, wenn der Betrachter sie nicht sehen darf."""
    if not isinstance(desc, dict):
        return desc
    spec = _confidential_spec_for(ticket)
    if not spec or _may_see_confidential(user, spec):
        return desc
    out = copy.deepcopy(desc)
    for path in spec.get("paths", []):
        _delete_path(out, path)
    return out


def preserve_confidential(ticket, user: Optional[dict], new_desc: dict, old_desc: dict) -> dict:
    """Schreibschutz für vertrauliche Felder: darf der Betrachter sie nicht sehen,
    werden sie aus der ALTEN Beschreibung übernommen – ein gefilterter Client kann
    sie so nicht (mit leeren Werten) überschreiben."""
    spec = _confidential_spec_for(ticket)
    if not spec or _may_see_confidential(user, spec):
        return new_desc
    if not isinstance(new_desc, dict):
        return new_desc
    out = copy.deepcopy(new_desc)
    old_desc = old_desc if isinstance(old_desc, dict) else {}
    for path in spec.get("paths", []):
        old_val = _get_path(old_desc, path)
        if old_val is None:
            _delete_path(out, path)
        else:
            _set_path(out, path, old_val)
    return out


# ── Spec-Auflösung ──────────────────────────────────────────────────────────────

def _spec_for(ticket) -> Optional[dict]:
    tt = getattr(ticket, "ticket_type", None)
    if isinstance(tt, TicketType):
        return VISIBILITY.get(tt)
    if isinstance(tt, str):
        for member in TicketType:
            if tt in (member.value, member.name):
                return VISIBILITY.get(member)
    return None


# ── Betrachter-Einordnung ────────────────────────────────────────────────────────

def is_full_view(ticket, user: dict) -> bool:
    """True, wenn der Betrachter die ganze Beschreibung UND den Verlauf sehen darf:
      - Oversight (view/manage/admin), Ersteller, Beobachter → immer;
      - Zuständige der Assignment-Phasen (die den Vorgang bearbeiten) → nur solange
        das Ticket AKTIV ist. Nach Archivierung/Ablehnung fällt diese Bearbeiter-
        Voll-Sicht weg (Need-to-know), sie sehen dann nur noch ihre erlaubten Felder.
    """
    perms = user.get("permissions", []) or []
    if any(p in perms for p in ("view", "manage", "admin")):
        return True

    uid = user.get("id")
    if not uid:
        return False
    if getattr(ticket, "owner_id", None) == uid:
        return True
    try:
        if is_watcher(getattr(ticket, "id", None), uid):
            return True
    except Exception:
        pass

    # Bearbeiter-Voll-Sicht nur bei aktiven Tickets.
    status = getattr(ticket, "status", None)
    status = status.value if hasattr(status, "value") else status
    if status in (RequestStatus.archived.value, RequestStatus.rejected.value):
        return False

    wf = ticket.workflow_state_parsed if hasattr(ticket, "workflow_state_parsed") else (ticket or {})
    gids = set(get_group_ids_for_user(uid))
    for phase in wf.get("phases", []):
        # Nur Assignment-Phasen gelten als "verarbeitende" Stelle. Die
        # department_review-Phase ist genau die, die eingeschränkt werden soll.
        if phase.get("type") != PhaseType.assignment.value:
            continue
        resp = phase.get("responsibility") or {}
        kind = resp.get("kind")
        if kind == "user" and resp.get("id") == uid:
            return True
        if kind == "group" and resp.get("id") in gids:
            return True
    return False


def is_restricted_viewer(ticket, user: Optional[dict]) -> bool:
    """True, wenn dieser Betrachter nur eine gefilterte Sicht hat (Tickettyp mit
    Spec UND kein Voll-Zugriff). Für Schreibschutz und UI-Hinweise."""
    return user is not None and _spec_for(ticket) is not None and not is_full_view(ticket, user)


def _allowed_paths(ticket, user: dict, spec: dict) -> set:
    """Basis-Pfade ∪ Pfade der Durchführungs-Fachabteilungen, in denen der User ist."""
    allowed = set(spec.get("base", []))
    uid = user.get("id")
    gids = set(get_group_ids_for_user(uid)) if uid else set()
    groups_by_name = {g["name"].strip().lower(): g["id"] for g in get_groups()}
    for dept_name, paths in spec.get("departments", {}).items():
        gid = groups_by_name.get(dept_name.strip().lower())
        if gid and gid in gids:
            allowed.update(paths)
    return allowed


# ── Pfad-Beschnitt ────────────────────────────────────────────────────────────────

def _covered(path: str, allowed: set) -> bool:
    """path ist erlaubt, wenn er einem erlaubten Pfad entspricht oder darunter liegt."""
    return any(path == a or path.startswith(a + ".") for a in allowed)


def _has_allowed_under(path: str, allowed: set) -> bool:
    """Existiert ein erlaubter Pfad TIEFER als `path` (dann muss rekursiert werden)?"""
    return any(a.startswith(path + ".") for a in allowed)


def _prune(node: dict, allowed: set, prefix: str = "") -> dict:
    out: dict = {}
    for key, value in node.items():
        p = f"{prefix}.{key}" if prefix else key
        if _covered(p, allowed):
            out[key] = value
        elif isinstance(value, dict) and _has_allowed_under(p, allowed):
            child = _prune(value, allowed, p)
            if child:
                out[key] = child
    return out


# ── Öffentliche API ────────────────────────────────────────────────────────────────

def _department_paths_by_gid(spec: dict, gid: str) -> set:
    """dot-Pfade GENAU einer Fachabteilung (per Gruppen-ID) aus der Spec."""
    if not gid:
        return set()
    id_to_name = {g["id"]: g["name"].strip().lower() for g in get_groups()}
    target = id_to_name.get(gid)
    if not target:
        return set()
    for dept_name, paths in spec.get("departments", {}).items():
        if dept_name.strip().lower() == target:
            return set(paths)
    return set()


def filter_description(ticket, user: Optional[dict], desc: dict,
                       only_department: Optional[str] = None,
                       force_scope: bool = False) -> dict:
    """Gefilterte Kopie der (bereits geparsten) Beschreibung für diesen Betrachter.

    `only_department` (Gruppen-ID): über den Fachabteilungs-Link aufgerufen → strikt
    Basis + GENAU diese eine Fachabteilung, auch wenn der User in mehreren
    Fachabteilungen ist (bzw. Oversight/Ersteller). Die Abteilungs-Pfade werden nur
    hinzugefügt, wenn der User Voll-Sicht hat ODER Mitglied dieser Gruppe ist
    (kein Enumerieren fremder Abteilungen über den Query-Parameter).

    `force_scope` (Involviert-Tab): IMMER nach Fachabteilungs-Mitgliedschaft scopen
    (Basis ∪ eigene Abteilungen) – Rolle/Voll-Sicht (Oversight/Ersteller/Beobachter/
    Bearbeiter) wird bewusst ignoriert. Wer mehr sehen darf, muss dafür in die
    „Alle Aufträge"-Ansicht wechseln."""
    if not isinstance(desc, dict):
        return desc
    # Vertrauliche Felder werden IMMER zusätzlich beschnitten (überschreibt Voll-Sicht).
    return _strip_confidential(
        ticket, user,
        _apply_field_visibility(ticket, user, desc, only_department, force_scope),
    )


def _apply_field_visibility(ticket, user: Optional[dict], desc: dict,
                            only_department: Optional[str], force_scope: bool) -> dict:
    """Normale Feld-Sichtbarkeit (Basis/Fachabteilungen) ohne das Confidential-Gate."""
    spec = _spec_for(ticket)
    if not spec:
        return desc
    if only_department is not None:
        allowed = set(spec.get("base", []))
        gids = set(get_group_ids_for_user(user.get("id"))) if user else set()
        if is_full_view(ticket, user) or only_department in gids:
            allowed |= _department_paths_by_gid(spec, only_department)
        return _prune(desc, allowed)
    if force_scope and user is not None:
        return _prune(desc, _allowed_paths(ticket, user, spec))
    if user is None or is_full_view(ticket, user):
        return desc
    return _prune(desc, _allowed_paths(ticket, user, spec))


def filter_description_str(ticket, user: Optional[dict], desc_str: str,
                           only_department: Optional[str] = None) -> str:
    """Wie filter_description, aber für die roh als String gehaltene desc (TicketOut)."""
    if user is None and only_department is None:
        return desc_str
    has_conf = _confidential_spec_for(ticket) is not None
    spec = _spec_for(ticket)
    if not spec and not has_conf:
        return desc_str
    # Voll-Sicht-Abkürzung nur, wenn KEINE vertraulichen Felder zu beschneiden sind.
    if only_department is None and not has_conf and is_full_view(ticket, user):
        return desc_str
    try:
        parsed = json.loads(desc_str or "{}")
    except Exception:
        # Kein gültiges JSON → beim Abteilungs-Scope restriktiv, sonst unverändert.
        return "{}" if only_department is not None else desc_str
    try:
        return json.dumps(
            filter_description(ticket, user, parsed, only_department=only_department),
            ensure_ascii=False,
        )
    except Exception:
        return "{}"   # im Zweifel restriktiv


def history_visible(ticket, user: Optional[dict]) -> bool:
    """Verlauf ist nur für Voll-Sicht-Betrachter sichtbar (Oversight, Ersteller,
    Beobachter, aktive Bearbeiter). Eingeschränkte sehen KEINEN Verlauf."""
    return user is None or is_full_view(ticket, user)
