"""Dashboard: die Arbeit des angemeldeten Nutzers in den Prozess-Aufträgen.

Seit dem Rückbau des Alt-Systems ist der Prozess-Block der EINZIGE Inhalt. Die
Alt-Schlüssel (`orders`, `watched_orders`, `department_board`,
`allowed_ticket_types`) und der Endpunkt `/dashboard/involved` sind entfallen;
der Katalog der anlegbaren Prozesse steht in `GET /processes` (`may_create`), das
Archiv in `GET /process-tickets`.

Der Schlüssel `process` bleibt als Klammer bestehen (kein Flatten): so ändert
sich für die bestehenden Leser `data.process.*` im Frontend nichts.
"""
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.core.dependencies import get_current_user
from backend.database import process_definitions as defstore
from backend.database import process_tickets as pstore
from backend.schemas.process_definition import ProcessDefinition
from backend.services import process_access as acc
from backend.services import process_runtime as pr
from backend.services import process_visibility as vis
from backend.schemas.responses import DataResponse
from backend.utils.logger import logger

router = APIRouter()

# Eigene Aufträge: mehr als das braucht die Übersicht nicht (Vollliste unter
# /process-tickets). Der Scan-Wert begrenzt die Zeilen, die für die
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


class DepartmentRef(BaseModel):
    id: str
    name: str


class DashboardResponse(BaseModel):
    """Antwort des Dashboards (nur noch Prozess-Inhalte).

    `my_departments` bleibt erhalten, obwohl es aus dem Alt-Dashboard stammt: es
    kommt ausschließlich aus den Gruppen (geteilter Baustein) und beantwortet die
    Frage „in welchen Fachabteilungen bin ich?" – auch ohne offene Aufträge.
    """
    # Alle (sichtbaren) Fachabteilungen, in denen der Nutzer Mitglied ist.
    my_departments: list[DepartmentRef] = []
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


def _my_departments(user_id: str) -> list[DepartmentRef]:
    """Fachabteilungen, in denen der Nutzer Mitglied ist (ohne versteckte).

    Darf das Dashboard nicht kippen – im Fehlerfall bleibt die Liste leer.
    """
    try:
        from backend.database.groups import get_groups, get_group_ids_for_user
        member_ids = set(get_group_ids_for_user(user_id))
        return [
            DepartmentRef(id=g["id"], name=g.get("name") or g["id"])
            for g in get_groups()
            if g.get("id") in member_ids and not g.get("hidden")
        ]
    except Exception as exc:
        logger.warning("Fachabteilungen fürs Dashboard nicht ladbar: %s", exc, exc_info=True)
        return []


@router.get("/dashboard", response_model=DataResponse[DashboardResponse])
def get_dashboard(user: dict = Depends(get_current_user)):
    return DataResponse(data=DashboardResponse(
        my_departments=_my_departments(user["id"]),
        process=_process_block_safe(user),
    ))
