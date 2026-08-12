from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from backend.core.dependencies import get_current_user
from backend.database import process_definitions as defstore
from backend.database import process_tickets as pstore
from backend.database import tickets as database
from backend.models.models import TicketType
from backend.schemas.process_definition import ProcessDefinition
from backend.services import process_access as acc
from backend.services import process_runtime as pr
from backend.services import process_visibility as vis
from backend.services.ticket_permissions import can_user_create_ticket
from backend.services.workflow_state import get_dashboard_work, get_involved_tickets
from backend.schemas.dashboard import (
    DashboardResponse, DashboardTicket, DepartmentGroup, DepartmentTicket,
    DepartmentRef, InvolvedTicket, InvolvedResponse,
)
from backend.schemas.responses import DataResponse
from backend.utils.logger import logger

router = APIRouter()


def _to_dashboard_ticket(t) -> DashboardTicket:
    return DashboardTicket(
        id=t.id,
        title=t.title,
        type_key=t.ticket_type if isinstance(t.ticket_type, str) else t.ticket_type.value,
        status=t.status if isinstance(t.status, str) else t.status.value,
        priority=t.priority if isinstance(t.priority, str) else t.priority.value,
        created_at=t.created_at.strftime("%d.%m.%Y") if hasattr(t.created_at, "strftime") else str(t.created_at)[:10],
    )


def _board_item_to_dashboard_ticket(it: dict) -> DashboardTicket:
    return DashboardTicket(
        id=it["id"],
        title=it["title"],
        type_key=it["type_key"],
        status=it["status"],
        priority=it["priority"],
        created_at=(it["created_at"] or "")[:10],
    )


# ── Prozess-Aufträge (neues, definitions-getriebenes System) ──────────────────
#
# Das neue System läuft parallel zum Alt-System (eigene Tabelle `process_tickets`).
# Ohne diesen Block wäre die Arbeit dort im Dashboard unsichtbar. Der Block ist
# ADDITIV: alle bestehenden Schlüssel der Antwort bleiben unverändert.

# Eigene Aufträge: mehr als das braucht die Übersicht nicht (Vollliste unter
# /prozess-auftraege). Der Scan-Wert begrenzt die Zeilen, die für die
# Beteiligungs-Prüfung (may_view, läuft in Python) geladen werden.
_PROCESS_MY_LIMIT = 25
_PROCESS_SCAN_LIMIT = 200


class ProcessDashboardTicket(BaseModel):
    """Übersichts-Zeile eines Prozess-Auftrags.

    Bewusst OHNE `values`/`runtime`: das Dashboard ist kein wertetragender Kanal
    (§5.1). Es werden nur Titel, Status, Phase, Datum und IDs ausgegeben – die
    Feldwerte gibt es ausschließlich in der Detail-Ansicht, dort gefiltert.
    """
    id: int
    process_key: str
    process_version: int
    title: str
    status: str
    priority: str
    phase: Optional[str] = None
    phase_label: Optional[str] = None
    # true = ich habe den Auftrag angelegt (sonst: ich bin beteiligt/zuständig)
    is_owner: bool = False
    created_at: str = ""
    updated_at: str = ""


class ProcessDashboardBlock(BaseModel):
    my: list[ProcessDashboardTicket] = []
    involved: list[ProcessDashboardTicket] = []
    # Anzahl je Status – nur über die Aufträge, die dieser Nutzer sehen darf.
    counts: dict[str, int] = {}


class DashboardResponseWithProcess(DashboardResponse):
    """Antwort des Dashboards + Prozess-Block.

    Als Unterklasse, damit die bestehenden Schlüssel (orders, watched_orders,
    department_board, …) unangetastet bleiben und das Frontend nichts verliert.
    """
    process: ProcessDashboardBlock = ProcessDashboardBlock()


def _load_process_defn(row: dict, cache: dict) -> Optional[ProcessDefinition]:
    """Gepinnte Definition laden/parsen – je (key, version) nur EINMAL.

    Gepinnte Versionen sind unveränderlich (§4), das Ergebnis ist innerhalb eines
    Requests also sicher wiederverwendbar. Ohne den Cache liefe pro Zeile eine
    DB-Abfrage UND eine vollständige Pydantic-Validierung derselben Definition (N+1).

    Fehlt oder bricht eine Definition, wird None gecacht (auch das ist genau EIN
    Ladeversuch): das Dashboard darf an einem einzelnen kaputten Pin nicht
    scheitern. Der Auftrag fällt dann durch die Default-Deny-Prüfung in may_view
    heraus – außer für Aufsichtsrechte, und die dürfen ihn ohnehin sehen.
    """
    pin = (row["process_key"], row["process_version"])
    if pin in cache:
        return cache[pin]
    defn = None
    try:
        d = defstore.get_definition(*pin)
        if d and d.get("definition"):
            defn = ProcessDefinition.model_validate(d["definition"])
        else:
            logger.warning("Gepinnte Definition %s v%s fehlt (Dashboard)", *pin)
    except Exception as exc:
        logger.warning("Definition %s v%s nicht ladbar (Dashboard): %s", *pin, exc)
    cache[pin] = defn
    return defn


def _to_process_ticket(row: dict, defn: Optional[ProcessDefinition],
                       is_owner: bool) -> ProcessDashboardTicket:
    phase = pr.current_phase(defn, row.get("runtime") or {}) if defn else None
    return ProcessDashboardTicket(
        id=row["id"],
        process_key=row["process_key"],
        process_version=row["process_version"],
        title=row.get("title") or "",
        status=row["status"],
        priority=row["priority"],
        phase=phase.key if phase else None,
        phase_label=(phase.label or phase.key) if phase else None,
        is_owner=is_owner,
        created_at=(row.get("created_at") or "")[:10],
        updated_at=(row.get("updated_at") or "")[:10],
    )


def _process_block(user: dict) -> ProcessDashboardBlock:
    """Prozess-Aufträge fürs Dashboard: eigene + solche, an denen ich beteiligt bin.

    Beteiligung entscheidet ausschließlich process_access.may_view (Aufsicht ·
    Ersteller:in · aktuell Zuständige) – dieselbe Naht wie in der Detail-Route,
    damit hier nichts auftaucht, was dort 404 wäre. Wer Aufsichtsrechte hat, sieht
    entsprechend alle aktiven Aufträge (wie in der Liste /process-tickets).
    """
    uid = user.get("id")
    # Gruppen-Mitgliedschaft und Definitionen EINMAL – nicht pro Zeile (N+1).
    group_ids = vis.user_group_ids(user)
    defn_cache: dict = {}

    my_rows = pstore.list_for_owner(uid, limit=_PROCESS_MY_LIMIT, include_runtime=True) if uid else []
    my = [_to_process_ticket(r, _load_process_defn(r, defn_cache), True) for r in my_rows]

    involved: list[ProcessDashboardTicket] = []
    for row in pstore.list_active(limit=_PROCESS_SCAN_LIMIT):
        if uid and row.get("owner_id") == uid:
            continue                        # steht schon unter „my"
        defn = _load_process_defn(row, defn_cache)
        if not acc.may_view(defn, row, user, group_ids):
            continue
        involved.append(_to_process_ticket(row, defn, False))

    # Zähler nur über die SICHTBAREN Aufträge – eine globale Statistik würde
    # Unbeteiligten verraten, wie viel im System läuft.
    counts: dict[str, int] = {}
    for t in my + involved:
        counts[t.status] = counts.get(t.status, 0) + 1
    return ProcessDashboardBlock(my=my, involved=involved, counts=counts)


def _process_block_safe(user: dict) -> ProcessDashboardBlock:
    """Das neue System darf das Dashboard nie kippen (z. B. fehlende Tabelle vor
    der ersten Migration) – im Fehlerfall bleibt der Block leer."""
    try:
        return _process_block(user)
    except Exception as exc:
        logger.warning("Prozess-Aufträge fürs Dashboard nicht ladbar: %s", exc, exc_info=True)
        return ProcessDashboardBlock()


@router.get("/dashboard", response_model=DataResponse[DashboardResponseWithProcess])
def get_dashboard(user: dict = Depends(get_current_user)):
    user_id = user["id"]

    # ── Arbeitslisten aus der aktuellen Zuständigkeit (ein Durchlauf) ──────────
    work = get_dashboard_work(user_id)

    # 1. Mir persönlich zugewiesen (aktuelle Phase: kind=user)
    my_orders = [_board_item_to_dashboard_ticket(it) for it in work["assigned"]]

    # 2. Meine Abteilung (Bearbeitung + Durchführung, jedes Ticket einmal)
    department_board = [
        DepartmentGroup(
            group_id=d["group_id"],
            group_name=d["group_name"] or d["group_id"],
            tickets=[
                DepartmentTicket(
                    id=t["id"],
                    title=t["title"],
                    type_key=t["type_key"],
                    created_at=(t["created_at"] or "")[:10],
                    status=t["status"],
                    priority=t["priority"],
                    phase_type=t["phase_type"],
                    phase_label=t["phase_label"],
                    department_id=t["department_id"],
                )
                for t in d["tickets"]
            ],
        )
        for d in work["departments"]
    ]

    # 3. Beobachtete Tickets (Ersteller ist automatisch Beobachter)
    from backend.database.ticket_watchers import list_ticket_ids_for_watcher
    watched_tickets = [database.get_ticket(tid) for tid in list_ticket_ids_for_watcher(user_id)]
    watched_orders = [_to_dashboard_ticket(t) for t in watched_tickets if t]

    # ── Erlaubte Ticket-Typen ──────────────────────────────────────────────────
    user_groups = user.get("groups", []) or []
    allowed = [
        t.value for t in TicketType
        if can_user_create_ticket(t.value, user_id, user_groups)
    ]

    # ── Alle (sichtbaren) Fachabteilungen des Nutzers (auch ohne Aufträge) ──────
    from backend.database.groups import get_groups, get_group_ids_for_user
    member_ids = set(get_group_ids_for_user(user_id))
    my_departments = [
        DepartmentRef(id=g["id"], name=g.get("name") or g["id"])
        for g in get_groups()
        if g.get("id") in member_ids and not g.get("hidden")
    ]

    return DataResponse(data=DashboardResponseWithProcess(
        orders=my_orders,
        watched_orders=watched_orders,
        department_board=department_board,
        my_departments=my_departments,
        allowed_ticket_types=allowed,
        # Additiv: Aufträge aus dem neuen, definitions-getriebenen System.
        process=_process_block_safe(user),
    ))


# Lesbare Typ-Bezeichnungen (für die serverseitige Suche, analog Frontend).
_TYPE_LABELS = {
    "hardware": "Hardwarebestellung",
    "zugang-beantragen": "Onboarding Mitarbeiter:innen",
    "zugang-sperren": "Offboarding Mitarbeiter:innen",
    "niederlassung-anmelden": "Niederlassung anmelden",
    "niederlassung-umzug": "Niederlassung umziehen",
    "niederlassung-schliessen": "Niederlassung schließen",
    "marketing-stellenanzeige": "Marketing - Stellenanzeige",
    "hotelbuchung": "Hotelbuchung",
    "basis-ticket": "Ticket",
}


@router.get("/dashboard/involved", response_model=DataResponse[InvolvedResponse])
def get_involved(
    user: dict = Depends(get_current_user),
    limit: int = Query(15, ge=1, le=100),
    offset: int = Query(0, ge=0),
    search: str | None = None,
    status: str | None = None,
    priority: str | None = None,
    since_days: int = Query(14, ge=0, le=3650),   # 0 = alle (kein Zeitfenster)
):
    """
    Tickets (inkl. archiviert), bei denen der Nutzer beteiligt war – Archiv zum
    Zurückverfolgen. Standardmäßig auf Tickets der letzten `since_days` Tage
    begrenzt (0 = alle), serverseitig gefiltert (Suche/Status/Priorität) und
    paginiert (limit/offset); liefert die Gesamtzahl der Treffer mit.
    """
    items = get_involved_tickets(user["id"], since_days=since_days or None)

    q = (search or "").strip().lower()
    if q:
        def matches(it: dict) -> bool:
            label = _TYPE_LABELS.get(it["type_key"], it["type_key"])
            return (
                q in (it["title"] or "").lower()
                or q in label.lower()
                or q in (it["type_key"] or "").lower()
            )
        items = [it for it in items if matches(it)]

    if status and status != "all":
        items = [it for it in items if it["status"] == status]
    if priority and priority != "all":
        items = [it for it in items if it["priority"] == priority]

    total = len(items)
    page = items[offset:offset + limit]

    involved = [
        InvolvedTicket(
            id=it["id"],
            title=it["title"],
            type_key=it["type_key"],
            status=it["status"],
            priority=it["priority"],
            created_at=(it["created_at"] or "")[:10],
            roles=it["roles"],
        )
        for it in page
    ]
    return DataResponse(data=InvolvedResponse(involved=involved, total=total))
