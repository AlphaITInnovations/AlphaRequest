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

import json
from typing import Optional

from backend.models.models import TicketType
from backend.services.phase_definitions import PhaseType
from backend.database.groups import get_groups, get_group_ids_for_user


# ── Registry ────────────────────────────────────────────────────────────────────
# base:        dot-Pfade, die jede beteiligte Fachabteilung sehen darf
# departments: Gruppenname -> dot-Pfade, die NUR diese Fachabteilung zusätzlich sieht
VISIBILITY: dict[TicketType, dict] = {
    TicketType.zugang_beantragen: {
        # Basisdaten sind ein eigener desc-Block (salutation, first_name, last_name,
        # contract_company, location, cost_center) und fuer jede beteiligte
        # Fachabteilung sichtbar. Die personal.*-Eintraege sind reine Legacy-Fallbacks
        # fuer Alt-Tickets, die diese Felder noch unter personal hatten.
        "base": [
            "base",
            "personal.first_name",
            "personal.last_name",
            "personal.contract_company",
            "personal.location",
            "personal.cost_center",
        ],
        "departments": {
            "IT": ["it"],
            "Fuhrpark": ["fuhrpark"],
            # HR sieht den kompletten personal-Block (inkl. personal_number, title, start_date …)
            "Personalabteilung": ["personal"],
        },
    },
    # Weitere Tickettypen nach Bedarf ergänzen. Ohne Eintrag => keine Filterung.
}


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
    """True, wenn der Betrachter die ganze Beschreibung sehen darf."""
    perms = user.get("permissions", []) or []
    if any(p in perms for p in ("view", "manage", "admin")):
        return True

    uid = user.get("id")
    if uid and getattr(ticket, "owner_id", None) == uid:
        return True

    wf = ticket.workflow_state_parsed if hasattr(ticket, "workflow_state_parsed") else (ticket or {})
    gids = set(get_group_ids_for_user(uid)) if uid else set()
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
                       only_department: Optional[str] = None) -> dict:
    """Gefilterte Kopie der (bereits geparsten) Beschreibung für diesen Betrachter.

    `only_department` (Gruppen-ID): über den Fachabteilungs-Link aufgerufen → strikt
    Basis + GENAU diese eine Fachabteilung, auch wenn der User in mehreren
    Fachabteilungen ist (bzw. Oversight/Ersteller). Die Abteilungs-Pfade werden nur
    hinzugefügt, wenn der User Voll-Sicht hat ODER Mitglied dieser Gruppe ist
    (kein Enumerieren fremder Abteilungen über den Query-Parameter)."""
    if not isinstance(desc, dict):
        return desc
    spec = _spec_for(ticket)
    if not spec:
        return desc
    if only_department is not None:
        allowed = set(spec.get("base", []))
        gids = set(get_group_ids_for_user(user.get("id"))) if user else set()
        if is_full_view(ticket, user) or only_department in gids:
            allowed |= _department_paths_by_gid(spec, only_department)
        return _prune(desc, allowed)
    if user is None or is_full_view(ticket, user):
        return desc
    return _prune(desc, _allowed_paths(ticket, user, spec))


def filter_description_str(ticket, user: Optional[dict], desc_str: str,
                           only_department: Optional[str] = None) -> str:
    """Wie filter_description, aber für die roh als String gehaltene desc (TicketOut)."""
    if user is None and only_department is None:
        return desc_str
    spec = _spec_for(ticket)
    if not spec:
        return desc_str
    if only_department is None and is_full_view(ticket, user):
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


def filter_history(ticket, user: Optional[dict], history: list) -> list:
    """Für eingeschränkte Betrachter die desc-Diff-Werte aus dem Verlauf entfernen.

    Die Tatsache „Beschreibung geändert" bleibt sichtbar; die konkreten Alt/Neu-Werte
    (die sonst die gesamte desc enthielten) werden entfernt. Andere Änderungen
    (Priorität, Kommentar, Status) bleiben erhalten. Aktionsunabhängig, damit auch
    admin_raw_edited & Co. abgedeckt sind.
    """
    if user is None:
        return history
    spec = _spec_for(ticket)
    if not spec or is_full_view(ticket, user):
        return history

    out: list = []
    for e in history:
        details = e.get("details") or {}
        changes = details.get("changes") or {}
        if "description" in changes:
            new_changes = {k: v for k, v in changes.items() if k != "description"}
            new_changes["description"] = {"redacted": True}
            e = {**e, "details": {**details, "changes": new_changes}}
        out.append(e)
    return out
