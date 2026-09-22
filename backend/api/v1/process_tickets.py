"""
REST-API für definitions-getriebene Tickets (Prozess-Instanzen, Stufe 2).

Neues, sauberes Schema (ersetzt später `view`/`overview`); während des Umbaus
unter /process-tickets parallel zum Alt-System.

Zugriff (nicht mehr admin-only): `_assert_view` lässt Aufsicht, Ersteller:in,
aktuell Zuständige und Beobachter:innen herein – und liefert nur die Feldwerte
aus, die der Sichtbarkeits-Filter freigibt. `_assert_edit` verlangt zusätzlich
die Zuständigkeit für die AKTUELLE Phase.

Jedes Ticket wird gegen seine GEPINNTE Definition validiert/abgewickelt.
Server-Validierung in zwei Pässen (§9): Wert-Form bei POST/PATCH,
Phasen-Abschluss bei :advance.
"""
import json
from typing import Optional

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel

from backend.core.dependencies import get_current_user
from backend.database import process_tickets as store
from backend.database import process_definitions as defstore
from backend.database import process_ticket_watchers as watchers
from backend.database.audit_log import record_audit
from backend.database.groups import get_group_ids_for_user
from backend.database.users import PERM_ADMIN
from backend.schemas.process_definition import (
    TODAY_BINDING, ProcessDefinition, ResponsibilityKind,
)
from backend.schemas.responses import (
    DataResponse, ListResponse, Meta, api_error, ErrorCode,
)
from backend.services import process_access as acc
from backend.services import directus_client as dc
from backend.services import directus_snapshot
from backend.services import process_actions as pactions
from backend.services import process_compute as compute
from backend.services import process_engine as engine
from backend.services import process_events as events
from backend.services import process_permissions as perms
from backend.services import process_prefill
from backend.services import process_runtime as pr
from backend.services import process_sequences as seq
from backend.services import process_validation as pv
from backend.services import process_visibility as vis
from backend.schemas.process_definition import TriggerType
from backend.utils.logger import logger
from backend.utils.timeutil import utcnow_iso

router = APIRouter()


def _require_admin(user: dict) -> None:
    if PERM_ADMIN not in (user.get("permissions", []) or []):
        raise api_error(403, ErrorCode.ADMIN_REQUIRED, "Admin-Rechte erforderlich")


# ── Schemas ──────────────────────────────────────────────────────────────────

class CreateTicketRequest(BaseModel):
    processKey: str
    title: Optional[str] = None
    priority: Optional[str] = None
    values: Optional[dict] = None
    #: Startphase direkt weiterschalten (Standard). Der Client setzt das auf
    #: false, wenn er ANSCHLIESSEND Datei-Anhänge hochlädt und erst DANACH selbst
    #: :advance ruft – nur so landen die Anhänge (z. B. Lebenslauf) in der
    #: Freigabe-Mail, die beim Verlassen der Startphase verschickt wird.
    autoStart: bool = True


class PatchTicketRequest(BaseModel):
    title: Optional[str] = None
    values: Optional[dict] = None
    #: Priorität nachträglich ändern (Whitelist ALLOWED_PRIORITY). Bisher war sie
    #: nach dem Anlegen unveränderlich – das Details-Panel des Basis-Tickets
    #: bietet sie aber wie im Alt-System zur Bearbeitung an.
    priority: Optional[str] = None


class TicketAbilities(BaseModel):
    """Was DIESE Person mit DIESEM Auftrag darf.

    Damit muss die Oberfläche die Rechte nicht nachbauen (sie kennt die
    Gruppen-Mitgliedschaft gar nicht) und zeigt keine Schaltflächen, die der
    Server anschließend mit 403 abweist. Verbindlich bleiben die Endpunkte.
    """
    edit: bool = False
    internal_comment: bool = False
    manage_watchers: bool = False
    #: Dateien hochladen – weiter gefasst als edit: auch die Ersteller:in darf
    #: Unterlagen nachreichen, solange der Auftrag läuft (api/v1/attachments.py).
    attach: bool = False
    reopen: bool = False
    #: Notfalleingriffe (Admin): hängenden Auftrag zwangsweise abschließen bzw. löschen.
    archive: bool = False
    delete: bool = False
    #: Fachabteilungen der AKTUELLEN Phase, die DIESE Person quittieren darf –
    #: rein Mitgliedschaft (kein Admin-Override). Die Oberfläche zeigt den
    #: „Erledigt"-Knopf nur für diese; verbindlich bleibt der Endpunkt.
    completable_departments: list[str] = []
    #: Darf den ausgefüllten Vertrag/das Dokument einer Dokument-Phase sehen und
    #: exportieren (Vollsicht/Admin – spiegelt den Gate in _docx_fill_prep).
    #: Beobachter:innen/Involvierte OHNE Vollsicht bekommen stattdessen nur einen
    #: Hinweis, dass das Dokument gerade erstellt wird.
    export_document: bool = False


class ProcessTicketOut(BaseModel):
    id: int
    process_key: str
    process_version: int
    title: str
    status: str
    priority: str
    owner_id: Optional[str] = None
    owner_name: Optional[str] = None
    values: dict = {}
    runtime: dict = {}
    current_phase: Optional[str] = None
    current_phase_label: Optional[str] = None
    responsibility: Optional[dict] = None
    next_timer_due_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    abilities: TicketAbilities = TicketAbilities()
    #: Welche Felder diese Person SEHEN bzw. in der aktuellen Phase BEARBEITEN darf.
    #: Das Formular richtet sich danach, statt die Gruppen-Logik nachzubauen – es
    #: kennt die Gruppen-Mitgliedschaft gar nicht.
    visible_fields: list[str] = []
    editable_fields: list[str] = []


# ── Helfer ─────────────────────────────────────────────────────────────────

def _load_pinned_defn(row: dict, cache: Optional[dict] = None) -> ProcessDefinition:
    """Gepinnte Definition laden und parsen.

    `cache` (pro Request) verhindert das N+1-Muster in Listen: ohne ihn würde je
    Zeile eine DB-Abfrage UND eine vollständige Pydantic-Validierung derselben
    Definition laufen. Gepinnte (key, version) sind unveränderlich (§4), das
    Ergebnis ist also innerhalb eines Requests sicher wiederverwendbar."""
    pin = (row["process_key"], row["process_version"])
    if cache is not None and pin in cache:
        return cache[pin]
    d = defstore.get_definition(*pin)
    if not d or not d.get("definition"):
        raise api_error(500, "PROCESS_DEFINITION_MISSING",
                        f"Gepinnte Definition {pin[0]} v{pin[1]} fehlt")
    defn = ProcessDefinition.model_validate(d["definition"])
    if cache is not None:
        cache[pin] = defn
    return defn


def _is_terminal(row: dict) -> bool:
    return row["status"] in ("archived", "rejected") or bool((row.get("runtime") or {}).get("rejected"))


def _completable_departments(row: dict, defn: Optional[ProcessDefinition],
                             user: Optional[dict], group_ids, resp: Optional[dict]) -> list:
    """Fachabteilungen der aktuellen Phase, in denen DIESE Person Mitglied ist.

    Bewusst OHNE Admin-Override: die Oberfläche soll nur die eigene(n) Abteilung(en)
    zum Quittieren anbieten. Der Admin-Notfalleingriff bleibt am Endpunkt möglich
    (may_complete_department), taucht aber nicht als Normal-Knopf auf.
    """
    if not user or defn is None or _is_terminal(row):
        return []
    if not resp or resp.get("kind") != "departments":
        return []
    gset = set(group_ids or ())
    return [d.get("group") for d in (resp.get("departments") or [])
            if d.get("group") and d["group"] in gset]


def _may_manage_watchers(row: dict, user: Optional[dict]) -> bool:
    """Beobachter:innen EINTRAGEN (und fremde austragen) dürfen NUR die Ersteller:in
    und Admins – prozessübergreifend. Bewusst NICHT die zuständige Stelle: das
    Beobachten gibt dauerhaften Lesezugriff, den soll nur die anlegende Person bzw.
    ein Admin vergeben. (Sich selbst wieder AUSTRAGEN darf jede:r – siehe Endpunkt.)"""
    if not user:
        return False
    uid = user.get("id")
    return acc.is_admin(user) or (bool(uid) and row.get("owner_id") == uid)


def _abilities(row: dict, defn: Optional[ProcessDefinition], user: Optional[dict],
               group_ids, completable_departments: Optional[list] = None,
               can_export_document: bool = False) -> TicketAbilities:
    if not user:
        return TicketAbilities()
    gids = set(group_ids or ())
    darf_bearbeiten = acc.may_edit(defn, row, user, gids) and not _is_terminal(row)
    ist_owner = bool(user.get("id")) and row.get("owner_id") == user.get("id")
    return TicketAbilities(
        edit=darf_bearbeiten,
        internal_comment=acc.is_process_staff(defn, user, gids),
        manage_watchers=_may_manage_watchers(row, user),
        # Muss die Regel in attachments._assert_process_attach spiegeln.
        attach=(acc.may_edit(defn, row, user, gids)
                or (ist_owner and not _is_terminal(row))),
        # Wiederaufnahme greift in einen FERTIGEN Auftrag ein – nur Admin.
        reopen=acc.is_admin(user) and _is_terminal(row),
        # Archivieren dürfen auch Manager (Aufsichts-Rolle „manage") – die
        # einzige Schreibaktion dieser Rolle, siehe acc.may_force_archive.
        archive=acc.may_force_archive(user) and not _is_terminal(row),
        delete=acc.is_admin(user),
        completable_departments=completable_departments or [],
        export_document=can_export_document,
    )


def _field_access(row: dict, defn: Optional[ProcessDefinition], phase, ctx: vis.ViewerCtx
                  ) -> tuple[list, list]:
    """Sichtbare und (in dieser Phase) bearbeitbare Feld-Schlüssel.

    `visible_field_keys` verträgt `defn=None` (default-deny), `editable_field_keys`
    NICHT – und `_out` wird mit None aufgerufen, wenn die gepinnte Definition fehlt.
    Daher der frühe Ausstieg.
    """
    if defn is None:
        return [], []
    sichtbar = sorted(vis.visible_field_keys(defn, ctx))
    if phase is None or _is_terminal(row):
        return sichtbar, []
    # ignore_conditions: die bedingte Anzeige (visibleWhen) wertet das Formular
    # live gegen den Tippstand aus – hier geht es nur um das Rollen-Gate.
    bearbeitbar = sorted(vis.editable_field_keys(
        defn, phase, ctx, row.get("values") or {}, ignore_conditions=True))
    return sichtbar, bearbeitbar


def _may_export_document(row: dict, defn: Optional[ProcessDefinition],
                         user: Optional[dict], group_ids) -> bool:
    """Darf diese Person das Dokument (z. B. den Arbeitsvertrag) erzeugen? NUR die
    für die AKTUELLE Phase zuständige Stelle und Admins – ausdrücklich NICHT
    Beobachter:innen, sonstige Beteiligte oder Voll-Sicht-Leser (die Dokument-Phase
    setzt grantsFullView, das darf das Erzeugen NICHT freischalten). `may_edit` =
    zuständig-für-die-aktuelle-Phase ODER Admin, aus den ECHTEN Gruppen (unabhängig
    vom Entry-Modus/Abteilungs-Link). Spiegelt den Gate in `_docx_fill_prep`."""
    if not user or defn is None:
        return False
    return acc.may_generate_document(defn, row, user, group_ids)


def _redact_responsibility(resp: Optional[dict], defn: Optional[ProcessDefinition],
                           ctx: vis.ViewerCtx) -> Optional[dict]:
    """Der aus einem Auftragsfeld gewählte Zuständige (kind=assignable /
    group_from_field) ist ein FELD-Wert und unterliegt daher der Feld-Sicht wie
    jeder andere Wert: darf der Betrachter das Quellfeld (`from_field`) nicht sehen,
    wird der gewählte user/group ausgeblendet. Ohne das leakt ein als confidential
    markiertes Zuständigkeits-Feld über `responsibility`, obwohl `values` es korrekt
    verbirgt. Feste group/user-Zuständigkeiten (aus der Definition, ohne from_field)
    sind nicht betroffen."""
    if not resp or not resp.get("from_field"):
        return resp
    if resp["from_field"] in vis.visible_field_keys(defn, ctx):
        return resp
    key = "group" if resp.get("kind") == "group" else "user"
    return {**resp, key: None}


def _out(row: dict, defn: Optional[ProcessDefinition], ctx: vis.ViewerCtx,
         user: Optional[dict] = None, group_ids=()) -> ProcessTicketOut:
    cur = pr.current_phase(defn, row["runtime"]) if defn else None
    # Zuständigkeit wird server-seitig (ungefiltert) aufgelöst; die Feldwerte im
    # Output werden nach Sichtbarkeit gefiltert (§5.1: einzige wertetragende Naht).
    resp = pr.resolve_responsibility(cur, row.get("values") or {}) if cur else None
    # Bei Fachabteilungen den LIVE-Stand aus dem Runtime zeigen (wer hat schon
    # abgeschlossen?) – resolve_responsibility kennt nur die Definition.
    if resp and resp.get("kind") == "departments":
        live = pr.current_departments(row.get("runtime") or {})
        if live:
            resp = {**resp, "departments": live}
    data = {k: row.get(k) for k in (
        "id", "process_key", "process_version", "title", "status", "priority",
        "owner_id", "owner_name", "runtime", "next_timer_due_at",
        "created_at", "updated_at")}
    data["values"] = vis.filter_values(defn, row.get("values") or {}, ctx)
    data["current_phase"] = cur.key if cur else None
    data["current_phase_label"] = (cur.label or cur.key) if cur else None
    # Feld-Sicht auch auf die (aus einem Feld gewählte) Zuständigkeit anwenden.
    data["responsibility"] = _redact_responsibility(resp, defn, ctx)
    completable = _completable_departments(row, defn, user, group_ids, resp)
    # Dokument/Vertrag exportieren: echtes Vollsicht/Admin-Recht aus den ECHTEN
    # Gruppen – NICHT aus dem (beim Abteilungs-Link heruntergescopeten) Anzeige-Ctx,
    # sonst sperrt der Fachabteilungs-Link die Dokument-Phase für die zuständige
    # Stelle. Spiegelt den Gate in _docx_fill_prep.
    can_export = _may_export_document(row, defn, user, group_ids)
    data["abilities"] = _abilities(row, defn, user, group_ids, completable, can_export)
    data["visible_fields"], data["editable_fields"] = _field_access(row, defn, cur, ctx)
    return ProcessTicketOut(**data)


def _view_ctx(row: dict, defn, user: dict, gids, view: Optional[str],
              department: Optional[str]) -> vis.ViewerCtx:
    """Feld-Sicht nach ENTRY-Modus, nicht nur nach Rolle (bewusst entkoppelt):

    - `view=admin` (nur Admin): voller Blick – der EINZIGE Ort, an dem der Admin
      wirklich ALLE Felder sieht.
    - `view=department` (Fachabteilungs-Link, `department`=Gruppe): NUR Basis +
      genau diese Fachabteilung – für jede:n gleich, damit die Abteilungsansicht
      über Nutzer/Gruppen hinweg identisch aussieht. Scope-DOWN: die Abteilungs-
      felder gibt es nur, wenn man WIRKLICH Mitglied dieser Gruppe ist (sonst nur
      Basis). Der Link weitet NIE über die echte Berechtigung hinaus aus.
    - sonst (Normal/Lesen): die eigene Sicht OHNE reinen Admin-Bonus – view/manage-
      Aufsicht, Owner- und Phasen-Vollsicht bleiben, der Admin-Gottmodus nicht.
    """
    gset = set(gids or ())
    if view == "admin" and acc.is_admin(user):
        return vis.build_viewer_ctx(user, row, defn, group_ids=gset)
    if view == "department" and department:
        return vis.ViewerCtx(full_view=False, is_admin=False,
                             group_ids=(gset & {department}))
    return _read_ctx(user, row, defn, gset)


def _read_ctx(user: dict, row: dict, defn, gids=None) -> vis.ViewerCtx:
    """Sicht für ALLE Antwort-Objekte AUSSERHALB der ausdrücklichen Admin-Ansicht
    (Liste, Mutationen, Erstellen). Der reine Admin-Bonus bleibt hier IMMER aus –
    alle Felder zeigt einzig der Detail-GET mit ?view=admin. Für Nicht-Admins ein
    No-Op (view/manage-Aufsicht, Owner- und Phasen-Vollsicht bleiben). BEWUSST NICHT
    im Dokument-Export (_docx_fill_prep) – das ist ein eigenes, ungefiltertes Gate.

    Beobachter:innen bekommen hier KEINE Vollsicht: sie sehen die Felder nur im
    Rahmen ihrer eigenen Berechtigung (Gruppen-Sicht)."""
    return vis.build_viewer_ctx(user, row, defn, group_ids=gids, suppress_admin=True)


def _actor_name(user: dict) -> str:
    return user.get("displayName") or user.get("email") or user.get("id") or "System"


def _render_title(defn: ProcessDefinition, values: dict, now_iso: str) -> str:
    """Titel aus `defn.titleTemplate` erzeugen: {{feld.key}} aus den (fertig
    berechneten) Startphasen-Werten, {{erstellt}} = Erstellzeitpunkt. Auf die
    Spaltenbreite (VARCHAR 255) gekappt."""
    from datetime import datetime
    from backend.services import mail_template as mt

    def _erstellt() -> str:
        try:
            dt = datetime.fromisoformat((now_iso or "").replace("Z", "+00:00"))
            return dt.strftime("%d.%m.%Y %H:%M")
        except Exception:
            return str(now_iso or "")

    def resolve(token: str) -> str:
        if token == "erstellt":
            return _erstellt()
        return mt.format_value(values.get(token))

    return mt.substitute(defn.titleTemplate, resolve).strip()[:255]


def _safe_restamp(row: dict, defn: ProcessDefinition) -> None:
    """Timer neu stempeln, ohne den Request zu kippen – aber NIEMALS stillschweigend:
    ein Fehlschlag wird als ERROR geloggt UND auditiert, sonst sähe ein toter Timer
    aus wie „keine Timer konfiguriert" (Review-Blocker)."""
    try:
        engine.restamp(row, defn)
    except Exception as exc:
        logger.error("Timer-Stempel für Ticket #%s fehlgeschlagen: %s", row.get("id"), exc,
                     exc_info=True)
        record_audit(
            action="process_timer_stamp_failed", actor_id=None, actor_name="System",
            actor_type="system", entity_type="process_ticket", entity_id=str(row.get("id")),
            summary=f"Timer konnte nicht gesetzt werden: {type(exc).__name__}",
            details={"error": str(exc)[:500]},
        )


def _sequence_error(exc: "seq.SequenceError"):
    """Vergabe-Fehler → HTTP. Ein erschöpfter Nummernkreis ist ein fachlicher
    Konflikt (409), kein Serverfehler; eine Kollision zwischen Anspruchs-Ledger und
    Zählerstand dagegen schon – die muss jemand ansehen. Die Codes sind bewusst
    dieselben wie im Alt-System, damit die Meldung im Frontend gleich bleibt."""
    if isinstance(exc, seq.SequenceExhausted):
        return api_error(409, "PERSONALNUMMER_FAILED", str(exc))
    if isinstance(exc, seq.SequenceNotConfigured):
        return api_error(400, "PERSONALNUMMER_FAILED", str(exc))
    if isinstance(exc, seq.SequenceWriteConflict):
        return api_error(409, "TICKET_CONFLICT", str(exc))
    logger.error("Nummernkreis-Kollision bei der Vergabe: %s", exc)
    return api_error(500, "PERSONALNUMMER_FAILED", str(exc))


def _email_conflict_error(exc: "engine.EmailConflict"):
    """Firmenmail-Konflikt beim Phasenabschluss → 422 mit Feld-Fehler. Das Feld ist
    per editableWhen jetzt änderbar; die Meldung markiert es (rot) im Formular."""
    msg = ("Diese Firmenmail existiert bereits – bitte anpassen."
           if exc.reason == "exists" else
           "Die Firmenmail entspricht nicht den Exchange-Vorgaben – bitte anpassen.")
    return api_error(422, ErrorCode.VALIDATION_FAILED, "Firmenmail-Konflikt",
                     fields=[{"path": exc.field, "code": "EMAIL_CONFLICT", "message": msg}])


def _watcher_ids(ticket_id) -> set:
    """Beobachter-IDs – fail-closed: nicht ladbar heißt „keine Beobachter“, also
    kein Zugriff über diesen Weg (statt versehentlich allen Zugriff zu geben)."""
    try:
        return watchers.watcher_ids(int(ticket_id))
    except Exception:
        logger.warning("Beobachter für Ticket #%s nicht ladbar – fail-closed", ticket_id)
        return set()


def _assert_view(row: dict, defn, user: dict) -> list:
    """Zugriff prüfen und die Gruppen-Mitgliedschaft zurückgeben (einmal geladen)."""
    gids = vis.user_group_ids(user)
    if not acc.may_view(defn, row, user, gids, _watcher_ids(row["id"])):
        # Bewusst 404: nicht verraten, dass es den Auftrag gibt.
        raise api_error(404, "TICKET_NOT_FOUND", "Ticket nicht gefunden")
    return gids


def _assert_view_or_archive(row: dict, defn, user: dict) -> list:
    """Lesen für Detail UND gepinnte Definition: aktive Sicht ODER Archiv-
    Beteiligung (Mitglied einer Gruppe/Fachabteilung, die in einer vom Auftrag
    ERREICHTEN Phase zuständig ist/war). Bewusst breiter als _assert_view, damit
    Archiv-Links auch abgeschlossene Aufträge öffnen. Verlauf/Events, Anhänge und
    Bearbeiten bleiben beim strengen _assert_view. Die gelieferten Feldwerte filtert
    weiterhin die Feld-Sichtbarkeit; die Definition trägt ohnehin keine Werte."""
    gids = vis.user_group_ids(user)
    # may_view deckt Owner/Beobachter/aktuell-Zuständige/Aufsicht schon ab – hier
    # nur noch die frühere Beteiligung an einer erreichten Phase ergänzen.
    if (acc.may_view(defn, row, user, gids, _watcher_ids(row["id"]))
            or acc.archive_involved(defn, row, user, gids)):
        return gids
    raise api_error(404, "TICKET_NOT_FOUND", "Ticket nicht gefunden")


def _assert_edit(row: dict, defn, user: dict) -> list:
    """Zusätzlich: nur die aktuell zuständige Stelle (und Admin) darf eingreifen."""
    gids = _assert_view(row, defn, user)
    if not acc.may_edit(defn, row, user, gids):
        raise api_error(403, ErrorCode.TICKET_FORBIDDEN,
                        "Nur die aktuell zuständige Stelle kann diesen Auftrag bearbeiten")
    return gids


# ── Endpunkte ────────────────────────────────────────────────────────────────

# Übersichts-Sichtbarkeit für Nicht-Aufsicht: „aktuell zuständig" steht im
# Runtime-/Feldwert-JSON und ist nicht per SQL filterbar – deshalb ein gebundener
# Scan der AKTIVEN Aufträge. Eigene (owner) + beobachtete Aufträge kommen dagegen
# vollständig über SQL (kein Cap). _OVERVIEW_MINE_CAP begrenzt nur die (praktisch
# beschränkten) eigenen Aufträge defensiv.
_OVERVIEW_SCAN_CAP = 3000
_OVERVIEW_MINE_CAP = 5000


def _overview_match(r: dict, status: Optional[str], process_key: Optional[str],
                    q: Optional[str]) -> bool:
    """Client-Filter (status/process_key/q) auf eine Zeile anwenden – für die Quellen,
    die nicht schon SQL-seitig gefiltert wurden (beobachtete/aktiv-zuständige)."""
    if status and r.get("status") != status:
        return False
    if process_key and r.get("process_key") != process_key:
        return False
    if q and q.lower() not in str(r.get("title") or "").lower():
        return False
    return True


@router.get("/process-tickets", response_model=ListResponse[ProcessTicketOut])
def list_process_tickets(
    user: dict = Depends(get_current_user),
    status: Optional[str] = None,
    process_key: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    # Definitionen je (key, version) nur EINMAL laden/parsen und die Gruppen-
    # Mitgliedschaft einmal abfragen – sonst 2 DB-Abfragen + 1 Validierung pro Zeile.
    defn_cache: dict = {}
    gids = vis.user_group_ids(user)

    def render(r: dict) -> ProcessTicketOut:
        try:
            d = _load_pinned_defn(r, defn_cache)
        except Exception:
            d = None
        return _out(r, d, _read_ctx(user, r, d, gids), user, gids)

    # Aufsicht (view/manage/admin) sieht ALLE Aufträge – die DB paginiert korrekt.
    if acc.has_oversight(user):
        rows, total = store.list_tickets(status=status, process_key=process_key, q=q,
                                         limit=limit, offset=offset)
        return ListResponse(data=[render(r) for r in rows],
                            meta=Meta(total=total, limit=limit, offset=offset))

    # Ohne Aufsicht: die Sichtbarkeit VOR der Paginierung bestimmen, sonst enthält
    # eine „Seite" (die global zuletzt geänderten) womöglich keine eigenen Aufträge
    # und die Gesamtzahl/Blätterung stimmt nicht. Sichtbare Quellen:
    #   a) eigene (owner)      – vollständig über den owner_id-Index
    #   b) beobachtete         – vollständig über die Beobachter-Tabelle
    #   c) aktuell zuständig   – Runtime/Feldwert-JSON → gebundener Aktiv-Scan
    uid = user.get("id")
    by_id: dict = {}
    if uid:
        owner_rows, _ = store.list_tickets(owner_id=uid, status=status,
                                           process_key=process_key, q=q,
                                           limit=_OVERVIEW_MINE_CAP, offset=0)
        for r in owner_rows:
            by_id[r["id"]] = r
        try:
            watched = [t for t in watchers.ticket_ids_for_watcher(uid) if t not in by_id]
            for r in store.get_many(watched):
                if _overview_match(r, status, process_key, q):
                    by_id[r["id"]] = r
        except Exception:
            logger.warning("Beobachtete Aufträge nicht ladbar – fail-closed")

    truncated = False
    # „aktuell zuständig" gibt es nur an nicht-terminalen Aufträgen. Bei einem Filter
    # auf einen terminalen Status entfällt der Scan (eigene/beobachtete terminale
    # Aufträge kommen schon oben; „war mal zuständig" ist Sache des Archivs).
    if status not in ("archived", "rejected"):
        active = store.list_active_full(limit=_OVERVIEW_SCAN_CAP + 1)
        if len(active) > _OVERVIEW_SCAN_CAP:
            truncated = True
            active = active[:_OVERVIEW_SCAN_CAP]
            logger.warning("Auftragsliste: Aktiv-Scan-Grenze %d erreicht – aktuell "
                           "zuständige Aufträge jenseits davon fehlen (Nutzer %s)",
                           _OVERVIEW_SCAN_CAP, uid)
        for r in active:
            if r["id"] in by_id or not _overview_match(r, status, process_key, q):
                continue
            try:
                d = _load_pinned_defn(r, defn_cache)
            except Exception:
                d = None
            if acc.is_responsible(d, r, user, gids):
                by_id[r["id"]] = r

    ordered = sorted(by_id.values(),
                     key=lambda r: (str(r.get("updated_at") or ""), r["id"]), reverse=True)
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return ListResponse(data=[render(r) for r in page],
                        meta=Meta(total=total, limit=limit, offset=offset, truncated=truncated))


@router.post("/process-tickets", response_model=DataResponse[ProcessTicketOut])
def create_process_ticket(body: CreateTicketRequest, user: dict = Depends(get_current_user)):
    pub = defstore.get_published(body.processKey)
    if not pub or not pub.get("definition"):
        raise api_error(404, ErrorCode.PROCESS_NOT_FOUND, f"Kein veröffentlichter Prozess: {body.processKey}")
    defn = ProcessDefinition.model_validate(pub["definition"])

    # Global deaktiviert? Dann lässt sich kein neuer Auftrag anlegen – unabhängig
    # von den Erstellrechten (die Sperre gilt für alle bis zur Freigabe).
    if defstore.is_disabled(defn.key):
        raise api_error(409, ErrorCode.PROCESS_DISABLED,
                        f"Der Prozess „{defn.name}“ ist derzeit deaktiviert – es können keine "
                        "neuen Aufträge angelegt werden.")

    # Erstellrechte kommen aus der Definition (createPermissions). Admins dürfen
    # immer; für alle anderen greift das erst, wenn die Endpunkte über Admin
    # hinaus geöffnet werden – die Prüfung sitzt schon an der richtigen Stelle.
    try:
        # Fachabteilungen (interne Gruppen) UND AD-Gruppen aus dem Login-Token:
        # das Alt-System berechtigte über beides, createPermissions.groups mischt
        # sie ebenfalls. Ohne die AD-Gruppen verlöre jede Person das Anlegerecht,
        # die es heute nur über eine AD-Gruppe hat.
        gids = get_group_ids_for_user(user.get("id")) if user.get("id") else []
        group_ids = list(gids) + [g for g in (user.get("groups") or []) if g]
    except Exception:
        logger.warning("Gruppen für Erstellrechte nicht ladbar – fail-closed")
        group_ids = []
    if not perms.may_create(defn, user, group_ids):
        raise api_error(403, ErrorCode.PERMISSION_DENIED,
                        f"Keine Berechtigung, Aufträge des Prozesses „{defn.name}“ anzulegen")

    submitted = body.values or {}
    catalog = {f.key for f in defn.fields}
    unknown = [k for k in submitted if k not in catalog]
    if unknown:
        raise api_error(422, ErrorCode.VALIDATION_FAILED, "Unbekannte Felder",
                        fields=[{"path": k, "code": "UNKNOWN_FIELD", "message": f"Unbekanntes Feld „{k}“"}
                                for k in unknown])

    now = utcnow_iso()
    start_phase = defn.phases[0]
    # Provisorischer Kontext (Ersteller:in = Owner → Vollsicht); Schreibschutz auf
    # die editierbaren Felder der Start-Phase anwenden. Der endgültige Runtime
    # entsteht erst UNTEN mit den fertigen Werten – nur so kann die Start-Phase
    # ihre bedingten Fachabteilungen korrekt bestimmen.
    provisional = {"owner_id": user.get("id"), "status": "in_progress",
                   "runtime": pr.initial_runtime(defn, now), "values": {}}
    ctx = _read_ctx(user, provisional, defn)
    try:
        values = vis.apply_writes(defn, start_phase, {}, submitted, ctx)
    except vis.AppendOnlyViolation as exc:
        raise api_error(422, ErrorCode.VALIDATION_FAILED, "Eingaben ungültig",
                        fields=[{"path": exc.field_key, "code": "APPEND_ONLY", "message": str(exc)}])

    # Antragsteller-Felder aus den Daten der angemeldeten Person vorbelegen
    # (read-only prefill – autoritativ, überschreibt evtl. mitgeschickte Werte).
    values = process_prefill.apply_prefill(defn, values, user)

    errs = pv.validate_values(defn, values)
    if errs:
        raise api_error(422, ErrorCode.VALIDATION_FAILED, "Eingaben ungültig", fields=errs)
    # Autor/Zeitstempel serverseitig setzen, dann Directus-Snapshot der Auswahl,
    # dann abgeleitete Felder füllen (computed darf auf Snapshot-Werte zugreifen).
    values = compute.stamp_server_fields(defn, values, {}, actor=_actor_name(user), now_iso=now)
    # Snapshot-Zielfelder sind read-only und wurden vom Schreibschutz verworfen.
    # Beim Anlegen die im Formular live gefüllten Werte als Rückfall übernehmen:
    # gelingt der autoritative Re-Fetch, überschreibt er sie; scheitert er (Directus
    # findet den Datensatz nicht), bleiben die gezeigten Werte erhalten – sonst
    # stünde alles leer (Basisdaten, Titel-Vorlage …).
    values = directus_snapshot.seed_snapshot_targets(defn, values, submitted)
    values = directus_snapshot.apply_snapshots(defn, values, {})
    values = compute.apply_computed(defn, values)

    runtime = pr.initial_runtime(defn, now, values)
    status = pr.enter_status_for(start_phase)
    # Titel: aus der Vorlage erzeugen (falls konfiguriert), sonst manuell/Name.
    # Eine leere Vorlagen-Ausgabe (nichts eingesetzt) fällt auf den Namen zurück.
    ticket_title = (_render_title(defn, values, now) or defn.name) if defn.titleTemplate \
        else (body.title or defn.name)
    row = store.create(
        process_key=defn.key, process_version=pub["version"],
        title=ticket_title, status=status, priority=(body.priority or "normal"),
        owner_id=user.get("id"), owner_name=user.get("displayName") or user.get("email"),
        values_json=json.dumps(values, ensure_ascii=False),
        runtime_json=json.dumps(runtime, ensure_ascii=False),
    )
    # Ersteller:in beobachtet den eigenen Auftrag automatisch (wie im Alt-System) –
    # so bekommt sie die Fortschritts-Mails, ohne zuständig zu sein.
    try:
        watchers.add_watcher(row["id"], user.get("id"),
                             user.get("displayName") or user.get("email"),
                             added_by=user.get("id"))
    except Exception:
        logger.warning("Ersteller:in konnte für #%s nicht als Beobachter eingetragen werden",
                       row["id"])
    events.record(row, events.CREATED, actor_id=user.get("id"), actor_name=_actor_name(user),
                  details={"process_key": defn.key, "version": pub["version"]})
    # Auch beim ANLEGEN festhalten, WAS in die Felder eingetragen wurde – als
    # „Angaben geändert" (alt→neu, from = leer). So zeigt der Verlauf die Erst-
    # Eingaben genau wie ein späteres Bearbeiten; die Feld-Sicht greift dabei wie
    # überall (process_events.redact bindet fields UND changes an dieselbe Sicht,
    # und lässt den Eintrag entfallen, wenn davon nichts sichtbar ist).
    init_changes = {k: {"from": None, "to": v} for k, v in values.items()
                    if v is not None and v != "" and v != []}
    if init_changes:
        events.record(row, events.UPDATED, actor_id=user.get("id"), actor_name=_actor_name(user),
                      details={"fields": sorted(init_changes), "changes": init_changes})
    if not body.autoStart:
        # Der Client lädt gleich Datei-Anhänge hoch und ruft DANACH :advance –
        # so verlässt der Auftrag die Startphase erst nach dem Upload und die
        # Freigabe-Mail bekommt die Anhänge mit. Ohne diese Ausnahme feuerte das
        # on_enter-auto_advance sofort und die Mail ginge ohne Anhänge raus.
        # :advance prüft die Pflichtangaben erneut, bevor es weiterschaltet.
        _safe_restamp(row, defn)
        return DataResponse(data=_out(row, defn, _read_ctx(user, row, defn),
                                      user, group_ids))
    # Ein `auto_advance` aus den on_enter-Automationen wurde hier bisher
    # STILLSCHWEIGEND verworfen (der Rückgabewert wurde ignoriert). Prozesse, die
    # direkt nach dem Anlegen weiterschalten sollen – z. B. das Basis-Ticket, das
    # sofort bei der gewählten Fachabteilung landen muss – blieben dadurch in der
    # Startphase bei der erstellenden Person liegen.
    will_weiter = engine.run_inline(row, defn,
                                    pr.current_phase(defn, row["runtime"]),
                                    {TriggerType.on_enter})
    if will_weiter:
        # Vor dem automatischen Weiterschalten die Pflichtangaben der Startphase
        # prüfen: `create` prüft nur die Wert-FORM, nicht den Phasen-Abschluss.
        # Ohne das könnte ein Auftrag unvollständig in die nächste Phase rutschen.
        offen = pv.validate_phase_completion(defn, start_phase, values)
        if offen:
            raise api_error(422, ErrorCode.VALIDATION_FAILED,
                            "Pflichtangaben fehlen", fields=offen)
        try:
            engine.transition(row, defn, actor=user)
        except seq.SequenceError as exc:
            raise _sequence_error(exc)
        except engine.EmailConflict as exc:
            raise _email_conflict_error(exc)
    else:
        _safe_restamp(row, defn)
    return DataResponse(data=_out(row, defn, _read_ctx(user, row, defn),
                                  user, group_ids))


class ArchiveRow(BaseModel):
    """Archiv-Zeile: bewusst OHNE Werte (§5.1) – nur Titel/Status/Phase/Datum."""
    id: int
    process_key: str
    process_version: int
    title: str
    status: str
    priority: str = "normal"
    phase: Optional[str] = None
    phase_label: Optional[str] = None
    is_owner: bool = False
    #: Ersteller:in – für das globale Archiv (Aufsicht) als Spalte/Filter nützlich.
    owner_name: str = ""
    created_at: str = ""
    updated_at: str = ""


class ArchivePage(BaseModel):
    items: list[ArchiveRow] = []
    total: int = 0
    limit: int = 25
    offset: int = 0
    #: Scan-Obergrenze erreicht – die Liste ist evtl. NICHT vollständig (kein
    #: stilles Kürzen: das Frontend weist darauf hin).
    truncated: bool = False


#: Harte Scan-Obergrenze fürs Archiv: die Beteiligungsprüfung läuft je Zeile in
#: Python, deshalb wird nicht die ganze Tabelle geladen.
_ARCHIVE_SCAN_CAP = 2000


@router.get("/process-tickets/archive", response_model=DataResponse[ArchivePage])
def list_archive(user: dict = Depends(get_current_user), q: Optional[str] = Query(None),
                 status: Optional[str] = Query(None), process_key: Optional[str] = Query(None),
                 created_by: Optional[str] = Query(None),
                 date_from: Optional[str] = Query(None), date_to: Optional[str] = Query(None),
                 date_field: str = Query("updated"), sort: str = Query("updated_desc"),
                 scope: str = Query("mine"), limit: int = Query(25, ge=1, le=100),
                 offset: int = Query(0, ge=0)):
    """Archiv (jeder Status), gleiche Struktur für zwei Reichweiten:

    - `scope=mine` (Default): PERSÖNLICH – nur Aufträge, an denen die Person je
      beteiligt war (Ersteller:in · Beobachter:in · Mitglied einer je zuständigen
      Gruppe/Fachabteilung; bedingte Regeln gegen die Werte geprüft). OHNE
      Aufsichts-Kurzschluss.
    - `scope=all`: GLOBAL – alle Aufträge. Verlangt eine Aufsichtsrolle
      (view/manage/admin), sonst 403.

    Filter: `q` (Titel), `status` (komma-separiert), `process_key`. Exaktes Paging
    über den gefilterten Satz. Keine Feldwerte (die gibt es nur im Detail, gefiltert)."""
    global_scope = scope == "all"
    if global_scope and not acc.has_oversight(user):
        raise api_error(403, ErrorCode.TICKET_FORBIDDEN,
                        "Das globale Archiv ist der Aufsicht vorbehalten")
    uid = user.get("id")
    gids = set(vis.user_group_ids(user))
    watched: set = set()
    if uid and not global_scope:
        try:
            watched = set(watchers.ticket_ids_for_watcher(uid))
        except Exception:
            logger.warning("Beobachtungen fürs Archiv nicht ladbar – fail-closed")

    defn_cache: dict = {}

    def _item(r: dict) -> ArchiveRow:
        try:
            defn = _load_pinned_defn(r, defn_cache)
        except Exception:
            defn = None
        phase = pr.current_phase(defn, r.get("runtime") or {}) if defn else None
        return ArchiveRow(
            id=r["id"], process_key=r["process_key"], process_version=r["process_version"],
            title=r.get("title") or "", status=r["status"],
            priority=r.get("priority") or "normal",
            phase=phase.key if phase else None,
            phase_label=(phase.label or phase.key) if phase else None,
            is_owner=bool(uid and r.get("owner_id") == uid),
            owner_name=r.get("owner_name") or "",
            created_at=(r.get("created_at") or "")[:10],
            updated_at=(r.get("updated_at") or "")[:10])

    # GLOBAL (Aufsicht): keine Beteiligungsprüfung je Zeile → direkt in SQL
    # filtern, sortieren und pagen. Skaliert auf beliebig viele Aufträge (kein
    # 2000er-Deckel, kein Kürzen) – gerade die Datums-/Ersteller-Filter fänden
    # sonst nur im Aktualitäts-Fenster.
    if global_scope:
        rows, total = store.list_global_archive(
            status=[s.strip() for s in status.split(",") if s.strip()] if status else None,
            process_key=process_key or None, created_by=created_by or None, q=q or None,
            date_from=date_from or None, date_to=date_to or None,
            date_field=date_field, sort=sort, limit=limit, offset=offset)
        return DataResponse(data=ArchivePage(items=[_item(r) for r in rows], total=total,
                                             limit=limit, offset=offset, truncated=False))

    # PERSÖNLICH: Beteiligung läuft je Zeile in Python → gedeckelter Scan
    # (`truncated` meldet, wenn die Grenze greift). Eine Zeile MEHR holen, um
    # „genau cap" (vollständig) von „> cap" (gekürzt) zu unterscheiden.
    rows = store.list_all_lightweight(limit=_ARCHIVE_SCAN_CAP + 1)
    truncated = len(rows) > _ARCHIVE_SCAN_CAP
    rows = rows[:_ARCHIVE_SCAN_CAP]
    # Günstige Vorfilter (reduzieren die Zeilen VOR der Beteiligungsprüfung).
    if q:
        ql = q.lower()
        rows = [r for r in rows if ql in (r.get("title") or "").lower()
                or ql in f"#{r.get('id')}" or ql in str(r.get("id") or "")
                or ql in (r.get("owner_name") or "").lower()]
    if status:
        sset = {s.strip() for s in status.split(",") if s.strip()}
        if sset:
            rows = [r for r in rows if r.get("status") in sset]
    if process_key:
        rows = [r for r in rows if r.get("process_key") == process_key]
    if created_by:
        cb = created_by.lower()
        rows = [r for r in rows if cb in (r.get("owner_name") or "").lower()]
    if date_from or date_to:
        col = "created_at" if date_field == "created" else "updated_at"
        lo = (date_from or "")[:10]
        hi = (date_to or "")[:10]
        rows = [r for r in rows
                if (not lo or (r.get(col) or "")[:10] >= lo)
                and (not hi or (r.get(col) or "")[:10] <= hi)]
    included: set = set()
    for r in rows:
        try:
            defn = _load_pinned_defn(r, defn_cache)
        except Exception:
            defn = None
        if acc.archive_involved(defn, r, user, gids, is_watcher=(r["id"] in watched)):
            included.add(r["id"])
    filtered = [r for r in rows if r["id"] in included]   # bewahrt updated_at-DESC
    _SORTS = {"updated_desc": ("updated_at", True), "updated_asc": ("updated_at", False),
              "created_desc": ("created_at", True), "created_asc": ("created_at", False)}
    sort_col, sort_rev = _SORTS.get(sort, ("updated_at", True))
    if sort != "updated_desc":   # Default ist schon so sortiert
        filtered.sort(key=lambda r: (str(r.get(sort_col) or ""), r["id"]), reverse=sort_rev)
    total = len(filtered)
    page = filtered[offset:offset + limit]
    return DataResponse(data=ArchivePage(items=[_item(r) for r in page], total=total,
                                         limit=limit, offset=offset, truncated=truncated))


# ── CSV-Export / -Import des globalen Archivs (Admin) ─────────────────────────

_ARCHIVE_CSV_HEADER = ["id", "process_key", "process_version", "title", "status", "priority",
                       "owner_id", "owner_name", "current_phase", "created_at", "updated_at",
                       "values_json", "runtime_json"]


def _phase_key_from_runtime(rt: dict) -> str:
    """Aktuellen Phasen-Schlüssel direkt aus der Runtime lesen (ohne Definition)."""
    phases = (rt or {}).get("phases") or []
    idx = (rt or {}).get("current_index", 0)
    return phases[idx].get("key") if 0 <= idx < len(phases) else ""


@router.get("/process-tickets/archive.csv")
def export_archive_csv(user: dict = Depends(get_current_user), q: Optional[str] = Query(None),
                       status: Optional[str] = Query(None), process_key: Optional[str] = Query(None),
                       created_by: Optional[str] = Query(None),
                       date_from: Optional[str] = Query(None), date_to: Optional[str] = Query(None),
                       date_field: str = Query("updated"), sort: str = Query("updated_desc")):
    """CSV-Export des globalen Archivs mit den GLEICHEN Filtern wie die Liste.

    Enthält die VOLLDATEN (values_json + runtime_json) – nur so ist ein späterer
    Restore möglich. Deshalb NUR Admin: die Datei umgeht die normale Feld-Sicht
    (auch vertrauliche Felder stehen roh drin). Zeichen-BOM, damit Excel UTF-8
    (Umlaute) korrekt öffnet; Trennzeichen „;" (deutsches Excel)."""
    if not acc.is_admin(user):
        raise api_error(403, ErrorCode.ADMIN_REQUIRED,
                        "Der Voll-Export ist Admins vorbehalten (enthält alle Feldwerte)")
    import csv
    import io
    rows = store.export_global_archive(
        status=[s.strip() for s in status.split(",") if s.strip()] if status else None,
        process_key=process_key or None, created_by=created_by or None, q=q or None,
        date_from=date_from or None, date_to=date_to or None, date_field=date_field, sort=sort)
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
    w.writerow(_ARCHIVE_CSV_HEADER)
    for r in rows:
        rt = r.get("runtime") or {}
        w.writerow([
            r.get("id"), r.get("process_key"), r.get("process_version"),
            r.get("title") or "", r.get("status") or "", r.get("priority") or "normal",
            r.get("owner_id") or "", r.get("owner_name") or "",
            _phase_key_from_runtime(rt),
            r.get("created_at") or "", r.get("updated_at") or "",
            json.dumps(r.get("values") or {}, ensure_ascii=False),
            json.dumps(rt, ensure_ascii=False),
        ])
    record_audit(action="process_archive_exported", actor_id=user.get("id"),
                 actor_name=_actor_name(user), entity_type="process_ticket", entity_id="archive",
                 summary=f"Globales Archiv exportiert ({len(rows)} Aufträge)")
    body = ("﻿" + buf.getvalue()).encode("utf-8")
    return Response(content=body, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": _content_disposition("archiv_export.csv")})


class CsvImportRequest(BaseModel):
    csv: str
    commit: bool = False


@router.post("/process-tickets/archive:import-csv")
def import_archive_csv(body: CsvImportRequest, user: dict = Depends(get_current_user)):
    """CSV-Restore ins globale Archiv. NUR Admin (legt Aufträge an).

    Additiv, NIE überschreibend: jede Zeile wird mit ihrer ORIGINAL-Nummer
    angelegt; existiert die Nummer bereits, wird die Zeile ÜBERSPRUNGEN.
    `commit=false` (Default) ist eine VORSCHAU – es wird nichts geschrieben, nur
    der Bericht (neu/übersprungen/fehlerhaft) zurückgegeben. Fehlt die (gepinnte)
    Prozess-Definition oder ist das JSON kaputt, wird die Zeile als „fehlerhaft"
    gemeldet statt einen kaputten Auftrag anzulegen."""
    if not acc.is_admin(user):
        raise api_error(403, ErrorCode.ADMIN_REQUIRED, "Nur Admins können Aufträge importieren")
    import csv
    import io
    reader = csv.DictReader(io.StringIO((body.csv or "").lstrip("﻿")), delimiter=";")
    created: list = []
    skipped: list = []
    failed: list = []
    defn_ok: dict = {}
    seen: set = set()   # in DIESER Datei schon eingeplante Nummern (siehe unten)

    def _fail(line, tid, reason):
        failed.append({"line": line, "id": tid, "reason": reason})

    for line, row in enumerate(reader, start=2):   # Zeile 1 = Kopf
        raw_id = (row.get("id") or "").strip()
        try:
            tid = int(raw_id)
        except (TypeError, ValueError):
            _fail(line, None, f"ungültige Nummer „{raw_id}“"); continue
        pk = (row.get("process_key") or "").strip()
        try:
            ver = int((row.get("process_version") or "").strip())
        except (TypeError, ValueError):
            _fail(line, tid, "ungültige Prozess-Version"); continue
        pin = (pk, ver)
        if pin not in defn_ok:
            defn_ok[pin] = defstore.get_definition(pk, ver) is not None
        if not defn_ok[pin]:
            _fail(line, tid, f"Prozess „{pk}“ v{ver} ist hier nicht vorhanden"); continue
        try:
            values = json.loads(row.get("values_json") or "{}")
            runtime = json.loads(row.get("runtime_json") or "{}")
            if not isinstance(values, dict) or not isinstance(runtime, dict):
                raise ValueError
        except (ValueError, TypeError):
            _fail(line, tid, "values_json/runtime_json ist kein gültiges JSON-Objekt"); continue
        # Übersprungen, wenn die Nummer schon in der DB liegt ODER in dieser Datei
        # bereits eingeplant ist. Der zweite Fall hält die Vorschau (commit=false,
        # es wird nichts geschrieben) mit dem tatsächlichen Commit im Gleichlauf:
        # ohne ihn zählte die Vorschau zwei gleiche neue Nummern beide als „neu",
        # während der Commit die zweite verwirft.
        if store.get(tid) is not None:
            skipped.append({"line": line, "id": tid, "reason": "Nummer existiert bereits"}); continue
        if tid in seen:
            skipped.append({"line": line, "id": tid, "reason": "Nummer in dieser Datei doppelt"}); continue
        if body.commit:
            try:
                store.create_with_id(
                    id=tid, process_key=pk, process_version=ver,
                    title=row.get("title") or "", status=row.get("status") or "in_progress",
                    priority=row.get("priority") or "normal",
                    owner_id=(row.get("owner_id") or "").strip() or None,
                    owner_name=(row.get("owner_name") or "").strip() or None,
                    values_json=json.dumps(values, ensure_ascii=False),
                    runtime_json=json.dumps(runtime, ensure_ascii=False),
                    created_at=(row.get("created_at") or "").strip() or None,
                    updated_at=(row.get("updated_at") or "").strip() or None)
            except Exception as exc:
                _fail(line, tid, f"Anlegen fehlgeschlagen: {str(exc)[:150]}"); continue
        seen.add(tid)
        created.append({"line": line, "id": tid})

    if body.commit and created:
        record_audit(action="process_archive_imported", actor_id=user.get("id"),
                     actor_name=_actor_name(user), entity_type="process_ticket", entity_id="archive",
                     summary=f"CSV-Import: {len(created)} Aufträge angelegt "
                             f"({len(skipped)} übersprungen, {len(failed)} fehlerhaft)",
                     details={"created": [c["id"] for c in created],
                              "skipped": len(skipped), "failed": len(failed)})
    return DataResponse(data={
        "committed": body.commit,
        "counts": {"created": len(created), "skipped": len(skipped), "failed": len(failed)},
        "created": created, "skipped": skipped, "failed": failed})


@router.get("/process-tickets/{ticket_id}", response_model=DataResponse[ProcessTicketOut])
def get_process_ticket(ticket_id: int, user: dict = Depends(get_current_user),
                       view: Optional[str] = Query(None),
                       department: Optional[str] = Query(None)):
    """`view`/`department` steuern die FELD-Sicht nach Entry-Modus (siehe
    `_view_ctx`) – NICHT den Zugriff: den prüft `_assert_view_or_archive`
    unverändert. So sieht der Admin nur in der Admin-Ansicht alles, und der
    Fachabteilungs-Link zeigt für alle nur Basis + die eine Abteilung."""
    row = store.get(ticket_id)
    if not row:
        raise api_error(404, "TICKET_NOT_FOUND", "Ticket nicht gefunden")
    try:
        defn = _load_pinned_defn(row)
    except Exception:
        defn = None
    # Aktive Sicht ODER Archiv-Beteiligung – so öffnen Archiv-Links auch
    # abgeschlossene Aufträge (Feld-Sichtbarkeit/Dokument-Gate greifen weiter).
    gids = _assert_view_or_archive(row, defn, user)
    ctx = _view_ctx(row, defn, user, gids, view, department)
    return DataResponse(data=_out(row, defn, ctx, user, gids))


@router.get("/process-tickets/{ticket_id}/definition")
def get_pinned_definition(ticket_id: int, user: dict = Depends(get_current_user)):
    """Die GEPINNTE Definition dieses Auftrags – Grundlage für Formular und Anzeige.

    Eigener Endpunkt, weil `GET /processes/{key}/versions/{v}` Verwaltungsrechte
    verlangt (dort kommt man auch an unveröffentlichte Entwürfe). Hier entscheidet
    ausschließlich der Zugriff auf den AUFTRAG: wer ihn sehen darf, darf auch
    wissen, wie er aufgebaut ist. Feldwerte stehen hier keine drin.
    """
    row = store.get(ticket_id)
    if not row:
        raise api_error(404, "TICKET_NOT_FOUND", "Ticket nicht gefunden")
    try:
        defn = _load_pinned_defn(row)
    except Exception:
        defn = None
    # Companion zum aufgeweiteten Detail-GET: wer den Auftrag (auch übers Archiv)
    # sehen darf, darf auch seine Struktur laden – sonst bricht die Leseansicht.
    _assert_view_or_archive(row, defn, user)
    if defn is None:
        raise api_error(500, "PROCESS_DEFINITION_MISSING",
                        f"Gepinnte Definition {row['process_key']} "
                        f"v{row['process_version']} fehlt")
    return DataResponse(data=defn.model_dump(mode="json", by_alias=True, exclude_none=True))


class DocumentExportRequest(BaseModel):
    #: Welches Dokument der Phase (documents[].key). Leer = das erste.
    document: Optional[str] = None
    #: Nur für den Alt-Weg (keine .docx-Vorlage hinterlegt): das im Client
    #: gefüllte HTML der Dokument-Vorlage. Mit hochgeladener .docx-Vorlage
    #: irrelevant – dann füllt der Server die Vorlage selbst.
    html: Optional[str] = None
    #: Dateiname ohne Endung; überschreibt den aus der Vorlage abgeleiteten Namen.
    filename: Optional[str] = None
    #: Marker→Wert aus dem Frontend-Editor. Ist es gesetzt, füllt der Server die
    #: .docx GENAU mit diesen Werten (statt aus den bindings) – so kann die
    #: bearbeitende Person manuelle Felder ausfüllen und Auto-Werte korrigieren.
    #: Leerer Wert ⇒ Marker bleibt eine Lücke.
    overrides: Optional[dict[str, str]] = None
    #: NUR für die Vorschau: eingesetzte Werte mit unsichtbaren Marken umschließen,
    #: damit das Frontend sie hervorheben kann. Der echte Word/PDF-Export lässt es weg.
    highlight: bool = False
    #: Ausgabeformat: "docx" (Standard) oder "pdf" (LibreOffice rendert die gefüllte
    #: Vorlage originalgetreu). Die Vorschau im Editor holt sich "pdf".
    format: str = "docx"


def _safe_filename(name: Optional[str]) -> str:
    """Dateiname für den Download absichern (keine Pfade/Steuerzeichen)."""
    base = (name or "Dokument").strip() or "Dokument"
    keep = "".join(c for c in base if c.isalnum() or c in " _-.()äöüÄÖÜß").strip()
    return (keep or "Dokument")[:120]


def _content_disposition(filename: str) -> str:
    """Content-Disposition-Header, der auch Nicht-latin-1-Namen (Ł, ş, CJK) verträgt.

    Starlette kodiert Header-Werte als latin-1; ein Name wie „Arbeitsvertrag_Łukasz"
    würde den Response-Aufbau mit UnicodeEncodeError (→ HTTP 500) sprengen. Deshalb
    ein reiner ASCII-`filename=` als Rückfallebene UND `filename*=UTF-8''…`
    (RFC 5987) mit dem echten Namen für Browser, die es verstehen.
    """
    import urllib.parse
    ascii_name = filename.encode("ascii", "ignore").decode("ascii") or "Dokument.docx"
    quoted = urllib.parse.quote(filename, safe="")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quoted}"


def _option_text(field, raw) -> str:
    """Einen skalaren Wert wie in der Vorschau in seine Options-Beschriftung
    übersetzen (statische Auswahl). User-/Gruppen-Felder werden hier NICHT
    aufgelöst – sie sind als Vertrags-Platzhalter nicht zugelassen (der Editor
    bietet sie nicht an), sodass Vorschau und Export übereinstimmen."""
    v = str(raw)
    for o in (getattr(field, "options", None) or []):
        if o.value == v:
            return o.label or o.value
    from backend.services.mail_template import de_date
    return de_date(v)   # ISO-Datum → deutsches Format (24.08.2026)


def _fill_text(field, raw) -> str:
    """Feldwert für die .docx-Vorlage darstellen – deckungsgleich mit der
    Vorschau (Ja/Nein, Options-Beschriftung, Liste). Leer → "" ; der Aufrufer
    lässt den Marker dann WEG, damit fill_docx dort die Lücke (GAP) setzt statt
    eines „—" (das im Vertrag wie ein gewollter Gedankenstrich aussähe)."""
    if raw is None or raw == "":
        return ""
    if isinstance(raw, bool):
        return "Ja" if raw else "Nein"
    if isinstance(raw, (list, tuple)):
        parts = [_option_text(field, v) for v in raw if not isinstance(v, (dict, list, tuple))]
        return ", ".join(p for p in parts if p)
    if isinstance(raw, dict):
        return ""
    return _option_text(field, raw)


_MIME_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _pick_docphase(defn, runtime):
    """Die Dokument-Phase der Definition: die aktuelle, sonst die erste mit
    Vorlagen. `None`, wenn es keine gibt."""
    if defn is None:
        return None
    cur = pr.current_phase(defn, runtime or {})
    if cur is not None and cur.documents:
        return cur
    return next((p for p in defn.phases if p.documents), None)


def _pick_document(docphase, document_key):
    """Das gewünschte Dokument der Phase (documents[].key); leerer Key = das erste.
    `None`, wenn es die Phase/das Dokument nicht gibt."""
    if docphase is None or not docphase.documents:
        return None
    if document_key:
        return next((d for d in docphase.documents if d.key == document_key), None)
    return docphase.documents[0]


def _load_template_row(row, docphase, doc):
    """Die Vorlage je (Prozess, Phase, Dokument) laden – `None`, falls keine
    hinterlegt. Fehler beim Lookup schlucken (still auf „keine Vorlage" degradieren)."""
    from backend.database import process_templates as tpl_db
    if docphase is None or doc is None or not row.get("process_key"):
        return None
    try:
        return tpl_db.get_template(row["process_key"], docphase.key, doc.key)
    except Exception:
        logger.exception("Vorlage-Lookup für #%s fehlgeschlagen", row.get("id"))
        return None


def _docx_fill_prep(row, defn, doc, user):
    """Gate (Vollsicht/Admin) + sichtbarkeitsgefilterte Werte + Katalog + bindings
    des gewählten Dokuments.

    §5.1: Der gefüllte Vertrag trägt auch vertrauliche Werte (Gehalt …) – nur
    Vollsicht/Admin, und selbst dort bleibt ein `confidential`-Feld gesperrt
    (filter_values), landet also als Lücke, nicht im Klartext. Wirft 403.
    """
    gids = vis.user_group_ids(user)
    # Erzeugen darf NUR die für die aktuelle Phase zuständige Stelle (bzw. Admin) –
    # nicht Beobachter:innen/Voll-Sicht-Leser. Die Feld-SICHT (confidential) filtert
    # danach zusätzlich über den ctx.
    if not acc.may_generate_document(defn, row, user, gids):
        raise api_error(403, ErrorCode.TICKET_FORBIDDEN,
                        "Nur die zuständige Stelle bzw. Admins dürfen das Dokument "
                        "erzeugen")
    ctx = vis.build_viewer_ctx(user, row, defn, group_ids=gids)
    values = vis.filter_values(defn, row.get("values") or {}, ctx)
    catalog = {f.key: f for f in defn.fields}
    bindings = dict(doc.bindings) if doc else {}
    return values, catalog, bindings


def _binding_text(binding, catalog, values) -> str:
    """Wert eines Marker-Bindings: aktuelles Datum (Sonderquelle @today), sonst der
    (sichtbarkeitsgefilterte) Feldwert – wie in der Vorschau (Options-Beschriftung,
    Ja/Nein, deutsches Datum) und mit optionalem Rechen-Versatz für NUMERISCHE
    Felder (z. B. Urlaubsanspruch - 20)."""
    if binding.field == TODAY_BINDING:
        from datetime import date
        return date.today().strftime("%d.%m.%Y")
    text = _fill_text(catalog.get(binding.field), values.get(binding.field))
    if binding.offset and text:
        try:
            text = str(int(text) + binding.offset)
        except (TypeError, ValueError):
            pass   # nicht-numerisch → Versatz ignorieren
    return text


def _auto_fill_values(bindings, catalog, values) -> dict:
    """Auto-Werte je Marker aus den bindings. LEERE werden weggelassen, damit
    fill_docx dort die Lücke setzt statt eines „—"."""
    out = {}
    for marker, binding in bindings.items():
        text = _binding_text(binding, catalog, values)
        if text != "":
            out[marker] = text
    return out


def _read_template_bytes(tpl) -> bytes:
    from pathlib import Path
    from backend.services import attachment_storage as _storage
    try:
        return Path(_storage.full_path(tpl["stored_path"])).read_bytes()
    except Exception:
        raise api_error(500, "TEMPLATE_UNREADABLE", "Die hinterlegte Vorlage ist nicht lesbar")


@router.get("/process-tickets/{ticket_id}/document:fields")
def document_fields(ticket_id: int, document: str = "", user: dict = Depends(get_current_user)):
    """Marker der Vorlage (eines Dokuments) + vorausgefüllte (sichtbarkeits-
    gefilterte) Werte – Grundlage für den Editor im Frontend. 409, falls keine
    Vorlage hinterlegt."""
    row = store.get(ticket_id)
    if not row:
        raise api_error(404, "TICKET_NOT_FOUND", "Ticket nicht gefunden")
    try:
        defn = _load_pinned_defn(row)
    except Exception:
        defn = None
    # Leserecht ZUERST prüfen (wie die Schwester-Endpunkte): sonst verrieten die
    # 409-Zweige unten Nicht-Lesern die Existenz/Dokument-Lage des Auftrags.
    _assert_view(row, defn, user)
    docphase = _pick_docphase(defn, row.get("runtime"))
    doc = _pick_document(docphase, document)
    if defn is None or docphase is None or doc is None:
        raise api_error(409, "TEMPLATE_MISSING", "Diese Phase hat kein solches Dokument.")
    tpl = _load_template_row(row, docphase, doc)
    if tpl is None:
        raise api_error(409, "TEMPLATE_MISSING",
                        "Für dieses Dokument ist keine Vorlage hinterlegt. "
                        "Bitte im Prozess-Editor eine .docx- oder PDF-Vorlage hochladen.")
    values, catalog, bindings = _docx_fill_prep(row, defn, doc, user)
    from backend.services import docx_fill, pdf_fill, template_format
    from backend.services import mail_template as mt
    tpl_bytes = _read_template_bytes(tpl)
    tpl_format = template_format.detect(tpl_bytes)
    markers = (pdf_fill.find_placeholders(tpl_bytes) if tpl_format == template_format.PDF
               else docx_fill.find_placeholders(tpl_bytes))
    out = []
    for m in markers:
        b = bindings.get(m)
        if b is not None:
            if b.field == TODAY_BINDING:
                label = "Aktuelles Datum"
            else:
                f = catalog.get(b.field)
                label = (f.label if (f and f.label) else b.field)
                if b.offset:
                    label += f" ({b.offset:+d})"      # z. B. „Urlaubsanspruch (-20)"
            out.append({"name": m, "label": label, "bound": True,
                        "value": _binding_text(b, catalog, values)})
        else:
            out.append({"name": m, "label": m, "bound": False, "value": ""})

    def _resolve(token: str) -> str:
        if token == "title":
            return str(row.get("title") or "")
        if token == "id":
            return str(row.get("id") or "")
        return mt.format_value(values.get(token))

    filename = _safe_filename(mt.substitute((doc.filename if doc else "") or "Dokument", _resolve))
    return DataResponse(data={"filename": filename, "phase": docphase.key,
                              "document": doc.key, "format": tpl_format,
                              "title": (doc.title if doc else None), "markers": out})


@router.post("/process-tickets/{ticket_id}/document:export")
def export_ticket_document(ticket_id: int, body: DocumentExportRequest,
                           user: dict = Depends(get_current_user)):
    """Die Dokument-Phase als Word-Datei (.docx) ausliefern.

    Mit hochgeladener .docx-Vorlage füllt der SERVER die {{marker}}: entweder aus
    `overrides` (Frontend-Editor – manuelle Felder + Korrekturen) oder aus den
    Auto-Werten der bindings. Ohne Vorlage bleibt der Alt-Weg HTML→.docx.

    Zugriff: der Vorlage-Weg verlangt Vollsicht/Admin (der Vertrag trägt evtl.
    vertrauliche Werte); der HTML-Weg genügt Leserecht (Werte stehen im HTML).
    PDF erzeugt das Frontend selbst."""
    row = store.get(ticket_id)
    if not row:
        raise api_error(404, "TICKET_NOT_FOUND", "Ticket nicht gefunden")
    try:
        defn = _load_pinned_defn(row)
    except Exception:
        defn = None

    docphase = _pick_docphase(defn, row.get("runtime"))
    doc = _pick_document(docphase, body.document or "")
    tpl = _load_template_row(row, docphase, doc)

    if tpl is not None and docphase is not None and doc is not None:
        values, catalog, bindings = _docx_fill_prep(row, defn, doc, user)
        from backend.services import docx_fill, pdf_fill, template_format
        from backend.services import mail_template as mt
        # Editor-Werte (overrides) haben Vorrang; leere Marker bleiben Lücke.
        if body.overrides is not None:
            fill_values = {m: v for m, v in body.overrides.items() if v}
        else:
            fill_values = _auto_fill_values(bindings, catalog, values)

        def _resolve(token: str) -> str:
            if token == "title":
                return str(row.get("title") or "")
            if token == "id":
                return str(row.get("id") or "")
            return mt.format_value(values.get(token))

        name = _safe_filename(
            body.filename or mt.substitute((doc.filename if doc else "") or "Dokument", _resolve))
        tpl_bytes = _read_template_bytes(tpl)

        # PDF-Vorlage: AcroForm-Feldwerte serverseitig füllen → natives PDF (kein
        # LibreOffice-Umweg, egal was body.format sagt; highlight ist bei PDF ohne Wirkung).
        if template_format.detect(tpl_bytes) == template_format.PDF:
            pdf = pdf_fill.fill_pdf(tpl_bytes, fill_values)
            return Response(content=pdf, media_type="application/pdf",
                            headers={"Content-Disposition": _content_disposition(name + ".pdf")})

        data = docx_fill.fill_docx(tpl_bytes, fill_values, mark=body.highlight)
        if body.format == "pdf":
            # .docx originalgetreu über LibreOffice rendern (Vorschau + PDF-Export).
            from backend.services import docx_to_pdf
            try:
                pdf = docx_to_pdf.convert(data)
            except docx_to_pdf.ConversionError as exc:
                raise api_error(500, "PDF_CONVERSION_FAILED",
                                f"Das PDF konnte nicht erzeugt werden: {exc}")
            return Response(content=pdf, media_type="application/pdf",
                            headers={"Content-Disposition": _content_disposition(name + ".pdf")})
        return Response(content=data, media_type=_MIME_DOCX,
                        headers={"Content-Disposition": _content_disposition(name + ".docx")})

    # Kein Template → bisheriger HTML→docx-Weg (Werte stehen im gesendeten HTML,
    # Leserecht genügt).
    _assert_view(row, defn, user)
    # Im .docx-Modus wird KEIN html gesendet; ohne hinterlegte Vorlage käme sonst
    # nur eine leere Datei heraus (Fehlkonfiguration, kein Export).
    if not (body.html or "").strip():
        raise api_error(409, "TEMPLATE_MISSING",
                        "Für diese Dokument-Phase ist keine Vorlage hinterlegt. "
                        "Bitte im Prozess-Editor eine .docx-Vorlage hochladen.")
    from backend.services.html_to_docx import html_to_docx
    data = html_to_docx(body.html or "")
    return Response(content=data, media_type=_MIME_DOCX,
                    headers={"Content-Disposition":
                             _content_disposition(_safe_filename(body.filename) + ".docx")})


@router.patch("/process-tickets/{ticket_id}", response_model=DataResponse[ProcessTicketOut])
def patch_process_ticket(ticket_id: int, body: PatchTicketRequest, user: dict = Depends(get_current_user)):
    row = store.get(ticket_id)
    if not row:
        raise api_error(404, "TICKET_NOT_FOUND", "Ticket nicht gefunden")
    defn = _load_pinned_defn(row)
    gids = _assert_edit(row, defn, user)
    if _is_terminal(row):
        raise api_error(409, ErrorCode.PROCESS_INVALID_STATE, "Ticket ist abgeschlossen/abgelehnt")
    ctx = _read_ctx(user, row, defn, gids)
    phase = pr.current_phase(defn, row["runtime"])
    if phase is None:
        raise api_error(409, ErrorCode.PROCESS_INVALID_STATE, "Keine aktive Phase")

    # Fester Titel: sagt die Definition titleEditable=false, wird der Titel beim
    # Anlegen festgelegt und ist danach für ALLE nur lesbar – auch für die
    # zuständige Stelle. Serverseitig, damit sich das nicht per API umgehen lässt.
    if (body.title is not None and body.title != row.get("title")
            and not defn.titleEditable):
        raise api_error(422, ErrorCode.VALIDATION_FAILED, "Titel ist fest",
                        fields=[{"path": "title", "code": "TITLE_LOCKED",
                                 "message": "Der Titel wird beim Anlegen festgelegt "
                                            "und kann danach nicht geändert werden"}])

    submitted = body.values or {}
    catalog = {f.key for f in defn.fields}
    unknown = [k for k in submitted if k not in catalog]
    if unknown:
        raise api_error(422, ErrorCode.VALIDATION_FAILED, "Unbekannte Felder",
                        fields=[{"path": k, "code": "UNKNOWN_FIELD", "message": f"Unbekanntes Feld „{k}“"}
                                for k in unknown])

    stored = row.get("values") or {}
    # Schreibschutz: nur sichtbare + in dieser Phase editierbare Felder übernehmen;
    # der Rest wird verworfen (verborgene Felder behalten ihren Bestandswert).
    # writable_keys wertet visibleWhen gegen einen sicheren Kontext aus (keine
    # Freischaltung über nicht-editierbare Body-Felder).
    try:
        merged_raw = vis.apply_writes(defn, phase, stored, submitted, ctx)
    except vis.AppendOnlyViolation as exc:
        raise api_error(422, ErrorCode.VALIDATION_FAILED, "Eingaben ungültig",
                        fields=[{"path": exc.field_key, "code": "APPEND_ONLY", "message": str(exc)}])
    allowed = vis.writable_keys(defn, phase, ctx, stored, submitted)
    to_apply = {k: v for k, v in merged_raw.items() if k in allowed and stored.get(k) != v}
    # Das Feld, das die Zuständigkeit DIESER Phase trägt (group_from_field /
    # assignable), darf nicht geleert werden: danach wäre NIEMAND mehr zuständig und
    # nur ein Admin käme noch an den Auftrag. `validate_values` lässt ein explizites
    # Leeren bewusst durch (Pflicht greift erst beim Phasenabschluss) – hier ist es
    # aber kein halbfertiger Entwurf, sondern ein Rechteverlust.
    quelle = phase.responsibility.fromField
    if (phase.responsibility.kind in (ResponsibilityKind.group_from_field,
                                      ResponsibilityKind.assignable)
            and quelle in to_apply and not to_apply[quelle]):
        raise api_error(422, ErrorCode.VALIDATION_FAILED, "Zuständigkeit fehlt",
                        fields=[{"path": quelle, "code": "REQUIRED",
                                 "message": "Ohne zuständige Stelle könnte niemand "
                                            "weiterarbeiten"}])

    errs = pv.validate_values(defn, to_apply)
    if errs:
        raise api_error(422, ErrorCode.VALIDATION_FAILED, "Eingaben ungültig", fields=errs)

    merged = compute.stamp_server_fields(defn, merged_raw, stored,
                                         actor=_actor_name(user), now_iso=utcnow_iso())
    merged = directus_snapshot.apply_snapshots(defn, merged, stored)
    merged = compute.apply_computed(defn, merged)
    try:
        row = store.update_values(ticket_id, json.dumps(merged, ensure_ascii=False),
                                  title=body.title, expected_rev=row.get("rev"))
    except store.ProcessTicketConflict as exc:
        raise api_error(409, "TICKET_CONFLICT", str(exc))
    # Priorität: eigener Pfad neben den Feldwerten (sie ist Ticket-Metadatum,
    # kein Prozessfeld). Gate ist dasselbe may_edit wie für den ganzen PATCH.
    if body.priority is not None and body.priority != row.get("priority"):
        from backend.schemas.process_definition import ALLOWED_PRIORITY
        if body.priority not in ALLOWED_PRIORITY:
            raise api_error(422, ErrorCode.VALIDATION_FAILED, "Unbekannte Priorität",
                            fields=[{"path": "priority", "code": "INVALID",
                                     "message": f"Erlaubt: {', '.join(sorted(ALLOWED_PRIORITY))}"}])
        alt_prio = row.get("priority")
        store.set_priority(ticket_id, body.priority)
        row["priority"] = body.priority
        events.record(row, events.PRIORITY_CHANGED, actor_id=user.get("id"),
                      actor_name=_actor_name(user),
                      details={"from": alt_prio, "to": body.priority})

    if to_apply:
        # Verlauf: geänderte Felder samt alt→neu-Wert. Beim LESEN wird pro Feld-Sicht
        # redigiert (process_events.redact) – wer ein Feld nicht sehen darf, bekommt
        # weder den Schlüssel noch den Wert. `stored` ist der Stand VOR dem Schreiben.
        changes = {k: {"from": stored.get(k), "to": to_apply[k]} for k in to_apply}
        events.record(row, events.UPDATED, actor_id=user.get("id"),
                      actor_name=_actor_name(user),
                      details={"fields": sorted(to_apply.keys()), "changes": changes})
        wants_advance = engine.run_inline(row, defn, phase, {TriggerType.on_field_change},
                                          changed_fields=set(to_apply.keys()))
        if wants_advance:
            try:
                engine.transition(row, defn)
            except seq.SequenceError as exc:
                raise _sequence_error(exc)
            except engine.EmailConflict as exc:
                raise _email_conflict_error(exc)
        else:
            _safe_restamp(row, defn)
    return DataResponse(data=_out(row, defn, ctx, user, gids))


@router.post("/process-tickets/{ticket_id}:advance", response_model=DataResponse[ProcessTicketOut])
def advance_process_ticket(ticket_id: int, user: dict = Depends(get_current_user)):
    row = store.get(ticket_id)
    if not row:
        raise api_error(404, "TICKET_NOT_FOUND", "Ticket nicht gefunden")
    defn = _load_pinned_defn(row)
    _assert_edit(row, defn, user)
    if _is_terminal(row):
        raise api_error(409, ErrorCode.PROCESS_INVALID_STATE, "Ticket ist abgeschlossen/abgelehnt")
    runtime = row["runtime"]
    values = row.get("values") or {}
    phase = pr.current_phase(defn, runtime)
    if phase is None:
        raise api_error(409, ErrorCode.PROCESS_INVALID_STATE, "Keine aktive Phase")

    errs = pv.validate_phase_completion(defn, phase, values)
    if errs:
        raise api_error(422, ErrorCode.VALIDATION_FAILED, "Phase kann nicht abgeschlossen werden", fields=errs)

    # Fachabteilungs-Phase: erst wenn alle PFLICHT-Abteilungen fertig sind.
    offen = pr.open_required_departments(runtime)
    if offen:
        raise api_error(409, ErrorCode.DEPARTMENT_FORBIDDEN,
                        "Es stehen noch Fachabteilungen aus",
                        fields=[{"path": d["group"], "code": "DEPARTMENT_OPEN",
                                 "message": "Diese Fachabteilung hat noch nicht abgeschlossen"}
                                for d in offen])

    # Phasenübergang zentral in der Engine: on_exit → advance → on_enter → Timer.
    # Den Verlaufs-Eintrag schreibt die Engine (mit `actor`) – nur so ist er auch
    # bei verketteten auto_advance und beim Scheduler garantiert dabei.
    try:
        engine.transition(row, defn, expected_rev=row.get("rev"), actor=user)
    except store.ProcessTicketConflict as exc:
        raise api_error(409, "TICKET_CONFLICT", str(exc))
    except seq.SequenceError as exc:
        raise _sequence_error(exc)
    except engine.EmailConflict as exc:
        raise _email_conflict_error(exc)
    gids = vis.user_group_ids(user)
    return DataResponse(data=_out(row, defn,
                                  _read_ctx(user, row, defn, gids),
                                  user, gids))


class RejectRequest(BaseModel):
    reason: str


def _melde_ablehnung(row: dict, defn, reason: str, by_name: str) -> None:
    """Ersteller:in über die Ablehnung informieren.

    Die Ablehnung ist zu diesem Zeitpunkt schon gespeichert – ein Mail-Fehler darf
    sie nicht kippen, muss aber sichtbar im Log landen (das Alt-System hat hier
    immer gemailt; stillschweigend nichts zu tun wäre die schlechteste Variante).
    """
    try:
        pactions.notify_rejection(row, defn, reason=reason, by_name=by_name)
    except Exception:
        logger.exception("Ablehnungs-Mail für #%s fehlgeschlagen", row.get("id"))


MAX_REASON_LEN = 2000


def _pflicht_begruendung(reason: Optional[str], pfad: str = "reason") -> str:
    """Begründung prüfen. Eine Ablehnung ohne Grund ist im Verlauf nicht erklärbar
    und die antragstellende Person erfährt nie, was zu ändern wäre – das Alt-System
    hat sie deshalb erzwungen."""
    text = (reason or "").strip()
    if not text:
        raise api_error(422, ErrorCode.VALIDATION_FAILED, "Begründung fehlt",
                        fields=[{"path": pfad, "code": "REQUIRED",
                                 "message": "Bitte begründen, warum abgelehnt wird"}])
    if len(text) > MAX_REASON_LEN:
        raise api_error(422, ErrorCode.VALIDATION_FAILED, "Begründung zu lang",
                        fields=[{"path": pfad, "code": "TOO_LONG",
                                 "message": f"Maximal {MAX_REASON_LEN} Zeichen"}])
    return text


@router.post("/process-tickets/{ticket_id}:reject", response_model=DataResponse[ProcessTicketOut])
def reject_process_ticket(ticket_id: int, body: RejectRequest,
                          user: dict = Depends(get_current_user)):
    row = store.get(ticket_id)
    if not row:
        raise api_error(404, "TICKET_NOT_FOUND", "Ticket nicht gefunden")
    try:
        defn_for_acc = _load_pinned_defn(row)
    except Exception:
        defn_for_acc = None
    _assert_edit(row, defn_for_acc, user)
    if _is_terminal(row):
        raise api_error(409, ErrorCode.PROCESS_INVALID_STATE, "Ticket ist bereits abgeschlossen/abgelehnt")
    grund = _pflicht_begruendung(body.reason)
    runtime = pr.reject(row["runtime"])
    try:
        row = store.update_runtime(ticket_id, runtime_json=json.dumps(runtime, ensure_ascii=False),
                                   status="rejected", expected_rev=row.get("rev"))
    except store.ProcessTicketConflict as exc:
        raise api_error(409, "TICKET_CONFLICT", str(exc))
    from backend.metrics.process_metrics import record_process_terminal
    record_process_terminal("rejected")
    events.record(row, events.REJECTED, actor_id=user.get("id"),
                  actor_name=_actor_name(user), body=grund)
    try:
        defn = _load_pinned_defn(row)
    except Exception:
        defn = None
    _melde_ablehnung(row, defn, grund, _actor_name(user))
    gids = vis.user_group_ids(user)
    return DataResponse(data=_out(row, defn,
                                  _read_ctx(user, row, defn, gids),
                                  user, gids))


# ── Fachabteilungen einzeln abschließen ──────────────────────────────────────

class DepartmentActionRequest(BaseModel):
    note: Optional[str] = None


def _department_action(ticket_id: int, group_id: str, status: str,
                       note: Optional[str], user: dict) -> ProcessTicketOut:
    """Gemeinsamer Pfad für :complete / :reject / :skip einer Fachabteilung."""
    row = store.get(ticket_id)
    if not row:
        raise api_error(404, "TICKET_NOT_FOUND", "Ticket nicht gefunden")
    defn = _load_pinned_defn(row)
    gids = _assert_view(row, defn, user)
    if _is_terminal(row):
        raise api_error(409, ErrorCode.PROCESS_INVALID_STATE, "Ticket ist abgeschlossen/abgelehnt")
    if status == "rejected":
        note = _pflicht_begruendung(note, "note")

    # Nur Mitglieder GENAU DIESER Abteilung (oder Admin) – sonst könnte die IT
    # für den Fuhrpark quittieren.
    if not acc.may_complete_department(defn, row, user, gids, group_id):
        raise api_error(403, ErrorCode.DEPARTMENT_FORBIDDEN,
                        "Nur Mitglieder dieser Fachabteilung können hier abschließen")

    runtime = row["runtime"]
    # Vorherigen Status merken: on_department_done-Automationen dürfen NUR beim
    # echten Übergang nach „done" feuern (ein erneutes :complete derselben
    # Abteilung würde sonst nicht-idempotente Aktionen doppelt auslösen).
    _prev = pr.department_entry(runtime, group_id)
    # Teilnahme ZUERST prüfen – sonst könnte in einer Randlage (alle Abteilungs-
    # Regeln bedingt, aktuell keine aktiv → leere Live-Liste, may_complete_department
    # fällt auf die statischen Regeln zurück) die blockierende Directus-Anlage laufen,
    # BEVOR set_department_status mit 409 ablehnt. Kein Seiteneffekt vor der Prüfung.
    if _prev is None:
        raise api_error(409, ErrorCode.DEPARTMENT_FORBIDDEN,
                        "Diese Fachabteilung ist an der aktuellen Phase nicht beteiligt")
    prior_status = _prev.get("status")
    ist_uebergang = status == "done" and prior_status != "done"

    # BLOCKIEREND ZUERST: directus_write mit onError=block (z. B. Mitarbeiter in
    # Directus anlegen) läuft VOR dem Persistieren von „done". Scheitert es, wird
    # der Abschluss ABGEBROCHEN – die Abteilung bleibt offen, nichts wird als
    # erledigt gespeichert. Bei Erfolg wird die zurückgeschriebene id sofort
    # persistiert (idempotent: ein Retry findet die id / den Datensatz und legt
    # nicht doppelt an).
    if ist_uebergang:
        _cur_phase = pr.current_phase(defn, runtime)
        try:
            blk_changes = engine.run_department_done_blocking(row, defn, _cur_phase, group_id)
        except dc.DirectusError as exc:
            raise api_error(502, "DIRECTUS_WRITE_FAILED",
                            f"Abschließen nicht möglich – der Directus-Schreibvorgang ist "
                            f"fehlgeschlagen: {exc}. Bitte erneut versuchen.")
        except Exception:
            logger.exception("Blockierende Automation für #%s (Gruppe %s) fehlgeschlagen",
                             ticket_id, group_id)
            raise api_error(502, "DIRECTUS_WRITE_FAILED",
                            "Abschließen nicht möglich – eine automatische Aktion ist "
                            "fehlgeschlagen. Bitte erneut versuchen.")
        if blk_changes:
            pactions.apply_action_changes(row, defn, blk_changes, store)
            runtime = row["runtime"]   # apply_action_changes kann row (rev/runtime) erneuern

    if not pr.set_department_status(runtime, group_id, status,
                                   by=user.get("id"), by_name=_actor_name(user),
                                   at=utcnow_iso(), note=note):
        raise api_error(409, ErrorCode.DEPARTMENT_FORBIDDEN,
                        "Diese Fachabteilung ist an der aktuellen Phase nicht beteiligt")

    # Bei Ablehnung wird der ganze Auftrag abgelehnt (wie im Alt-System) – deshalb
    # gilt hier derselbe Begründungszwang wie bei :reject.
    new_status = row["status"]
    if status == "rejected":
        runtime = pr.reject(runtime)
        new_status = "rejected"
    try:
        row = store.update_runtime(ticket_id, runtime_json=json.dumps(runtime, ensure_ascii=False),
                                   status=new_status, expected_rev=row.get("rev"),
                                   next_timer_due_at=row.get("next_timer_due_at"))
    except store.ProcessTicketConflict as exc:
        raise api_error(409, "TICKET_CONFLICT", str(exc))

    if status == "rejected":
        from backend.metrics.process_metrics import record_process_terminal
        record_process_terminal("rejected")
    events.record(row, {"done": events.DEPARTMENT_DONE,
                        "skipped": events.DEPARTMENT_SKIPPED,
                        "rejected": events.DEPARTMENT_REJECTED}[status],
                  actor_id=user.get("id"), actor_name=_actor_name(user),
                  body=note, details={"group": group_id})
    # Danach die NICHT-blockierenden on_department_done-Automationen (Benachrichtigen
    # etc.) – nur beim echten Übergang nach „done". Die blockierenden liefen bereits
    # oben (vor dem Persistieren von „done").
    if ist_uebergang:
        try:
            cur_phase = pr.current_phase(defn, row.get("runtime") or {})
            engine.run_department_done(row, defn, cur_phase, group_id)
        except Exception:
            logger.exception("on_department_done-Automationen für #%s (Gruppe %s) fehlgeschlagen",
                             ticket_id, group_id)
    if status == "rejected":
        _melde_ablehnung(row, defn, note or "", _actor_name(user))
    return _out(row, defn, _read_ctx(user, row, defn, gids),
                user, gids)


@router.post("/process-tickets/{ticket_id}/departments/{group_id}:complete",
             response_model=DataResponse[ProcessTicketOut])
def complete_department(ticket_id: int, group_id: str,
                        body: Optional[DepartmentActionRequest] = None,
                        user: dict = Depends(get_current_user)):
    return DataResponse(data=_department_action(
        ticket_id, group_id, "done", (body.note if body else None), user))


@router.post("/process-tickets/{ticket_id}/departments/{group_id}:skip",
             response_model=DataResponse[ProcessTicketOut])
def skip_department(ticket_id: int, group_id: str,
                   body: Optional[DepartmentActionRequest] = None,
                   user: dict = Depends(get_current_user)):
    """Nicht zuständig / nichts zu tun – gilt als erledigt, ohne Bearbeitung."""
    return DataResponse(data=_department_action(
        ticket_id, group_id, "skipped", (body.note if body else None), user))


@router.post("/process-tickets/{ticket_id}/departments/{group_id}:reject",
             response_model=DataResponse[ProcessTicketOut])
def reject_department(ticket_id: int, group_id: str,
                     body: Optional[DepartmentActionRequest] = None,
                     user: dict = Depends(get_current_user)):
    """Ablehnung durch eine Fachabteilung lehnt den gesamten Auftrag ab."""
    return DataResponse(data=_department_action(
        ticket_id, group_id, "rejected", (body.note if body else None), user))


# ── Verlauf & Nachträge ──────────────────────────────────────────────────────

MAX_COMMENT_LEN = 5000


class EventOut(BaseModel):
    id: int
    action: str
    phase_key: Optional[str] = None
    epoch: int = 0
    actor_id: Optional[str] = None
    actor_name: Optional[str] = None
    actor_type: str = "user"
    internal: bool = False
    body: Optional[str] = None
    details: dict = {}
    created_at: Optional[str] = None


class CommentRequest(BaseModel):
    body: str
    internal: bool = False


def _load_for_view(ticket_id: int, user: dict) -> tuple[dict, Optional[ProcessDefinition], list]:
    """Ticket + gepinnte Definition laden und Leserecht prüfen."""
    row = store.get(ticket_id)
    if not row:
        raise api_error(404, "TICKET_NOT_FOUND", "Ticket nicht gefunden")
    try:
        defn = _load_pinned_defn(row)
    except Exception:
        defn = None
    return row, defn, _assert_view(row, defn, user)


@router.get("/process-tickets/{ticket_id}/events", response_model=ListResponse[EventOut])
def list_ticket_events(ticket_id: int, user: dict = Depends(get_current_user),
                       limit: int = Query(200, ge=1, le=500),
                       offset: int = Query(0, ge=0),
                       view: Optional[str] = None):
    """Verlauf eines Auftrags – redigiert: Einträge über nicht sichtbare Felder
    entfallen, interne Nachträge sieht nur die bearbeitende Seite. Der reine
    Admin-Bonus bleibt wie überall aus – ALLE vertraulichen Feld-Metadaten sieht
    ein Admin nur über die ausdrückliche Admin-Ansicht (?view=admin)."""
    row, defn, gids = _load_for_view(ticket_id, user)
    suppress = not (view == "admin" and acc.is_admin(user))
    evs, total = events.for_viewer(row, defn, user, gids, limit=limit, offset=offset,
                                   suppress_admin=suppress)
    return ListResponse(data=[EventOut(**e) for e in evs],
                        meta=Meta(total=total, limit=limit, offset=offset))


@router.post("/process-tickets/{ticket_id}/comments", response_model=DataResponse[EventOut])
def add_ticket_comment(ticket_id: int, body: CommentRequest,
                       user: dict = Depends(get_current_user)):
    """Nachtrag schreiben. Jede Person mit Leserecht darf – ein interner Nachtrag
    nur die bearbeitende Seite (sonst könnte die antragstellende Person Text
    hinterlegen, den sie selbst anschließend nicht mehr sieht)."""
    row, defn, gids = _load_for_view(ticket_id, user)
    text = (body.body or "").strip()
    if not text:
        raise api_error(422, ErrorCode.VALIDATION_FAILED, "Nachtrag ist leer",
                        fields=[{"path": "body", "code": "REQUIRED",
                                 "message": "Bitte einen Text eingeben"}])
    if len(text) > MAX_COMMENT_LEN:
        raise api_error(422, ErrorCode.VALIDATION_FAILED, "Nachtrag zu lang",
                        fields=[{"path": "body", "code": "TOO_LONG",
                                 "message": f"Maximal {MAX_COMMENT_LEN} Zeichen"}])
    if body.internal and not acc.is_process_staff(defn, user, gids):
        raise api_error(403, ErrorCode.PERMISSION_DENIED,
                        "Interne Nachträge kann nur die bearbeitende Seite schreiben")

    # Bewusst `write` (nicht `record`): geht der Nachtrag verloren, muss der
    # Aufrufer einen Fehler sehen und nicht ein stilles „gespeichert".
    ev = events.write(row, events.COMMENT, actor_id=user.get("id"),
                      actor_name=_actor_name(user), internal=body.internal, body=text)
    try:
        recips = pactions.notify_comment(
            row, pr.current_phase(defn, row["runtime"]) if defn else None,
            author_name=_actor_name(user), body_text=text, internal=body.internal,
            actor_email=user.get("email") or user.get("mail"))
        if recips:
            logger.info("Nachtrag zu #%s an %s Empfänger", ticket_id, len(recips))
    except Exception:
        logger.exception("Nachtrags-Mail für #%s fehlgeschlagen", ticket_id)
    return DataResponse(data=EventOut(**ev))


# ── Wiederaufnahme ───────────────────────────────────────────────────────────

class ReopenRequest(BaseModel):
    reason: str
    phase: Optional[str] = None


class SetPhaseRequest(BaseModel):
    phase: str
    reason: str = ""


class SetTitleRequest(BaseModel):
    title: str


class RawValuesRequest(BaseModel):
    values: dict
    reason: str = ""


class RawValuesOut(BaseModel):
    """UNGEFILTERTE Feldwerte – nur für den Admin-Roh-Editor. Die normale
    Ticket-Antwort filtert auf Katalog-Felder; ein Editor auf der gefilterten
    Sicht würde unsichtbare Alt-Schlüssel beim nächsten Speichern zerstören."""
    values: dict


@router.post("/process-tickets/{ticket_id}:archive", response_model=DataResponse[ProcessTicketOut])
def archive_process_ticket(ticket_id: int, body: RejectRequest,
                           user: dict = Depends(get_current_user)):
    """Auftrag zwangsweise abschließen (Admin-Notfalleingriff).

    Für Fälle, in denen ein Auftrag hängt, den niemand mehr weiterschalten kann –
    etwa weil die zuständige Gruppe aufgelöst wurde. Der Grund ist Pflicht, sonst
    steht im Verlauf ein Abschluss ohne Erklärung. Rückholbar über :reopen.
    """
    row = store.get(ticket_id)
    if not row:
        raise api_error(404, "TICKET_NOT_FOUND", "Ticket nicht gefunden")
    if not acc.may_force_archive(user):
        raise api_error(403, ErrorCode.ADMIN_REQUIRED,
                        "Nur Manager oder Admins können einen Auftrag zwangsweise abschließen")
    if _is_terminal(row):
        raise api_error(409, ErrorCode.PROCESS_INVALID_STATE,
                        "Der Auftrag ist bereits abgeschlossen/abgelehnt")
    grund = _pflicht_begruendung(body.reason)
    runtime = pr.force_archive(row["runtime"])
    try:
        row = store.update_runtime(ticket_id, runtime_json=json.dumps(runtime, ensure_ascii=False),
                                   status="archived", expected_rev=row.get("rev"))
    except store.ProcessTicketConflict as exc:
        raise api_error(409, "TICKET_CONFLICT", str(exc))
    from backend.metrics.process_metrics import record_process_terminal
    record_process_terminal("archived")
    try:
        defn = _load_pinned_defn(row)
    except Exception:
        defn = None
    events.record(row, events.ADVANCED, actor_id=user.get("id"), actor_name=_actor_name(user),
                  body=grund, details={"from_phase": None, "to_phase": None,
                                       "status": "archived", "forced": True})
    _safe_restamp(row, defn) if defn else store.set_next_timer(ticket_id, None)
    gids = vis.user_group_ids(user)
    return DataResponse(data=_out(row, defn,
                                  _read_ctx(user, row, defn, gids),
                                  user, gids))


@router.delete("/process-tickets/{ticket_id}")
def delete_process_ticket(ticket_id: int, user: dict = Depends(get_current_user)):
    """Auftrag endgültig löschen (Admin).

    Vor der Löschung wird auditiert – der Audit-Eintrag überlebt sie bewusst,
    sonst wäre nicht mehr nachvollziehbar, dass es den Auftrag je gab. Die
    vergebenen Nummern-Ansprüche bleiben stehen: eine ausgegebene Personalnummer
    darf nicht erneut vergeben werden.
    """
    row = store.get(ticket_id)
    if not row:
        raise api_error(404, "TICKET_NOT_FOUND", "Ticket nicht gefunden")
    if not acc.is_admin(user):
        raise api_error(403, ErrorCode.ADMIN_REQUIRED, "Nur Admins können Aufträge löschen")
    record_audit(
        action="process_ticket_deleted", actor_id=user.get("id"),
        actor_name=_actor_name(user), entity_type="process_ticket", entity_id=str(ticket_id),
        summary=f"Prozess-Ticket #{ticket_id} gelöscht: {row.get('title')}",
        details={"process_key": row.get("process_key"), "status": row.get("status"),
                 "owner_id": row.get("owner_id")},
    )
    store.delete(ticket_id)
    return DataResponse(data={"deleted": ticket_id})


@router.post("/process-tickets/{ticket_id}:reopen", response_model=DataResponse[ProcessTicketOut])
def reopen_process_ticket(ticket_id: int, body: ReopenRequest,
                          user: dict = Depends(get_current_user)):
    """Abgeschlossenen/abgelehnten Auftrag wieder aufnehmen.

    Nur Admin (Notfall-Eingriff in einen fertigen Auftrag). Ein Grund ist Pflicht –
    ohne ihn wäre im Verlauf nicht nachvollziehbar, warum ein fertiger Auftrag
    wieder offen ist. Nicht für aktive Aufträge: „zurück zu Phase X" ist eine
    andere Aktion und hat hier absichtlich keinen Einstieg.
    """
    row = store.get(ticket_id)
    if not row:
        raise api_error(404, "TICKET_NOT_FOUND", "Ticket nicht gefunden")
    if not acc.is_admin(user):
        raise api_error(403, ErrorCode.ADMIN_REQUIRED,
                        "Nur Admins können einen abgeschlossenen Auftrag wieder aufnehmen")
    defn = _load_pinned_defn(row)
    if not _is_terminal(row):
        raise api_error(409, ErrorCode.PROCESS_INVALID_STATE,
                        "Der Auftrag ist noch aktiv – hier gibt es nichts wieder aufzunehmen")
    reason = (body.reason or "").strip()
    if not reason:
        raise api_error(422, ErrorCode.VALIDATION_FAILED, "Grund fehlt",
                        fields=[{"path": "reason", "code": "REQUIRED",
                                 "message": "Bitte begründen, warum der Auftrag wieder aufgenommen wird"}])

    try:
        runtime, status = pr.reopen(defn, row["runtime"], utcnow_iso(),
                                    phase_key=body.phase, values=row.get("values") or {})
    except ValueError as exc:
        raise api_error(422, ErrorCode.VALIDATION_FAILED, str(exc),
                        fields=[{"path": "phase", "code": "UNKNOWN_REF", "message": str(exc)}])
    try:
        row = store.update_runtime(ticket_id, runtime_json=json.dumps(runtime, ensure_ascii=False),
                                   status=status, expected_rev=row.get("rev"))
    except store.ProcessTicketConflict as exc:
        raise api_error(409, "TICKET_CONFLICT", str(exc))

    phase = pr.current_phase(defn, row["runtime"])
    events.write(row, events.REOPENED, actor_id=user.get("id"), actor_name=_actor_name(user),
                 body=reason, details={"phase": phase.key if phase else None,
                                       "epoch": runtime.get("epoch")})
    # Die Phase wird ERNEUT betreten: on_enter-Automationen und die
    # Zuständigkeits-Mail müssen laufen, sonst wartet die Stelle auf nichts.
    engine.run_inline(row, defn, phase, {TriggerType.on_enter})
    try:
        pactions.notify_phase_entry(row, defn, phase)
    except Exception:
        logger.exception("Benachrichtigung nach Wiederaufnahme von #%s fehlgeschlagen", ticket_id)
    _safe_restamp(row, defn)
    gids = vis.user_group_ids(user)
    return DataResponse(data=_out(row, defn,
                                  _read_ctx(user, row, defn, gids),
                                  user, gids))


# ── Admin-Werkzeuge (Reparatur laufender Aufträge) ───────────────────────────
# Beide Endpunkte sind HART auf Admins beschränkt – sie umgehen absichtlich die
# normalen Schreibregeln (Phasen-Rechte, Feld-Sichtbarkeit, Validierung), denn
# genau die verhindern in einem kaputten Zustand die Reparatur.

@router.post("/process-tickets/{ticket_id}:set-phase",
             response_model=DataResponse[ProcessTicketOut])
def set_process_ticket_phase(ticket_id: int, body: SetPhaseRequest,
                             user: dict = Depends(get_current_user)):
    """AKTIVEN Auftrag auf eine beliebige Phase stellen (vor oder zurück).

    Für hängende Aufträge: verlorene Freigabe-Mail, versehentlich
    abgeschlossene Phase, leerlaufende Zuständigkeit. Nutzt dieselbe Mechanik
    wie die Wiederaufnahme: Epoch-Bump (sonst blieben Timer stumm, die im
    ersten Durchlauf schon gefeuert haben), Abteilungs-Stand der Zielphase wird
    neu aufgebaut, on_enter-Automationen und Zuständigkeits-Mail laufen erneut.
    Terminale Aufträge nehmen den benannten Weg über :reopen (mit Zielphase).
    """
    row = store.get(ticket_id)
    if not row:
        raise api_error(404, "TICKET_NOT_FOUND", "Ticket nicht gefunden")
    if not acc.is_admin(user):
        raise api_error(403, ErrorCode.ADMIN_REQUIRED,
                        "Nur Admins können die Phase eines Auftrags umstellen")
    if _is_terminal(row):
        raise api_error(409, ErrorCode.PROCESS_INVALID_STATE,
                        "Der Auftrag ist abgeschlossen/abgelehnt – bitte über "
                        "„Wieder aufnehmen“ (dort lässt sich die Zielphase wählen)")
    defn = _load_pinned_defn(row)
    grund = _pflicht_begruendung(body.reason)
    von = pr.current_phase(defn, row["runtime"])
    try:
        runtime, status = pr.reopen(defn, row["runtime"], utcnow_iso(),
                                    phase_key=body.phase, values=row.get("values") or {})
    except ValueError as exc:
        raise api_error(422, ErrorCode.VALIDATION_FAILED, str(exc),
                        fields=[{"path": "phase", "code": "UNKNOWN_REF", "message": str(exc)}])
    try:
        row = store.update_runtime(ticket_id, runtime_json=json.dumps(runtime, ensure_ascii=False),
                                   status=status, expected_rev=row.get("rev"))
    except store.ProcessTicketConflict as exc:
        raise api_error(409, "TICKET_CONFLICT", str(exc))
    phase = pr.current_phase(defn, row["runtime"])
    # record (best-effort) wie bei den übrigen Phasenwechseln: ein kaputter
    # Verlauf darf die Reparatur nicht verhindern – er wird geloggt.
    events.record(row, events.ADVANCED, actor_id=user.get("id"), actor_name=_actor_name(user),
                  body=grund, details={"from_phase": von.key if von else None,
                                       "to_phase": phase.key if phase else None,
                                       "forced": True, "epoch": runtime.get("epoch")})
    # Wie bei der Wiederaufnahme: die Zielphase wird BETRETEN. Ein etwaiges
    # auto_advance wird bewusst NICHT ausgeführt – die Phase ist hier eine
    # ausdrückliche Admin-Entscheidung, keine Durchgangsstation.
    engine.run_inline(row, defn, phase, {TriggerType.on_enter})
    try:
        pactions.notify_phase_entry(row, defn, phase)
    except Exception:
        logger.exception("Benachrichtigung nach Phasen-Umstellung von #%s fehlgeschlagen", ticket_id)
    _safe_restamp(row, defn)
    gids = vis.user_group_ids(user)
    return DataResponse(data=_out(row, defn,
                                  _read_ctx(user, row, defn, gids),
                                  user, gids))


def _admin_row_or_error(ticket_id: int, user: dict, aktion: str) -> dict:
    row = store.get(ticket_id)
    if not row:
        raise api_error(404, "TICKET_NOT_FOUND", "Ticket nicht gefunden")
    if not acc.is_admin(user):
        raise api_error(403, ErrorCode.ADMIN_REQUIRED, f"Nur Admins können {aktion}")
    return row


@router.post("/process-tickets/{ticket_id}:remind", response_model=DataResponse[ProcessTicketOut])
def remind_responsible(ticket_id: int, user: dict = Depends(get_current_user)):
    """Zuständigkeits-Benachrichtigung der AKTUELLEN Phase erneut auslösen (Nudge).

    Für liegengebliebene Aufträge: dieselbe Mail wie beim Betreten der Phase geht
    erneut an die zuständige Stelle (Freigabe-Phase: die Entscheidungs-Mail mit
    Links; Beobachter:innen nur die Info-Mail). KEIN Zustandswechsel. Terminale
    Aufträge haben keine zuständige Stelle → 409.
    """
    row = _admin_row_or_error(ticket_id, user, "eine Erinnerung senden")
    if _is_terminal(row):
        raise api_error(409, ErrorCode.PROCESS_INVALID_STATE,
                        "Der Auftrag ist abgeschlossen/abgelehnt – es gibt keine zuständige Stelle")
    defn = _load_pinned_defn(row)
    phase = pr.current_phase(defn, row.get("runtime") or {})
    try:
        recips = pactions.notify_phase_entry(row, defn, phase) or []
    except Exception:
        logger.exception("Erinnerung für #%s fehlgeschlagen", ticket_id)
        recips = []
    # Die Mail ist bereits raus (unumkehrbar) – der Verlaufs-/Audit-Eintrag darf
    # deshalb NICHT werfen: record() ist best-effort. Sonst käme nach dem Versand
    # ein 500, und ein Retry schickte eine zweite Erinnerung.
    events.record(row, events.REMINDER_SENT, actor_id=user.get("id"), actor_name=_actor_name(user),
                  details={"phase": phase.key if phase else None, "recipients": recips})
    gids = vis.user_group_ids(user)
    return DataResponse(data=_out(row, defn, _read_ctx(user, row, defn, gids), user, gids))


@router.post("/process-tickets/{ticket_id}:set-title", response_model=DataResponse[ProcessTicketOut])
def set_process_ticket_title(ticket_id: int, body: SetTitleRequest,
                             user: dict = Depends(get_current_user)):
    """Auftragstitel korrigieren (Admin, jeder Status). Steht im Verlauf/Audit."""
    row = _admin_row_or_error(ticket_id, user, "den Titel ändern")
    new = (body.title or "").strip()
    if not new:
        raise api_error(422, ErrorCode.VALIDATION_FAILED, "Titel fehlt",
                        fields=[{"path": "title", "code": "REQUIRED",
                                 "message": "Bitte einen Titel angeben"}])
    old = row.get("title") or ""
    defn = _load_pinned_defn(row)
    if new != old:
        try:
            # Werte unverändert lassen, nur den Titel setzen (values_json wird
            # mitgeschrieben – deshalb den vorhandenen Bestand erneut serialisieren).
            row = store.update_values(
                ticket_id, values_json=json.dumps(row.get("values") or {}, ensure_ascii=False),
                title=new, expected_rev=row.get("rev"))
        except store.ProcessTicketConflict as exc:
            raise api_error(409, "TICKET_CONFLICT", str(exc))
        events.write(row, events.TITLE_CHANGED, actor_id=user.get("id"),
                     actor_name=_actor_name(user), details={"from": old, "to": new})
    gids = vis.user_group_ids(user)
    return DataResponse(data=_out(row, defn, _read_ctx(user, row, defn, gids), user, gids))


# Slash-Pfad statt `:aktion`-Suffix: Roh-Werte sind eine UNTER-RESSOURCE (wie
# /definition und /watchers), keine Aktion – und ein GET auf `{id}:raw-values`
# würde von der früher registrierten Route GET /process-tickets/{ticket_id}
# verschluckt (Starlette matcht Pfad-Parameter über alles außer „/").
@router.get("/process-tickets/{ticket_id}/raw-values",
            response_model=DataResponse[RawValuesOut])
def get_process_ticket_raw_values(ticket_id: int, user: dict = Depends(get_current_user)):
    """Die GESPEICHERTEN Feldwerte, ungefiltert (nur Admin, für den Roh-Editor)."""
    row = _admin_row_or_error(ticket_id, user, "Roh-Werte lesen")
    return DataResponse(data=RawValuesOut(values=row.get("values") or {}))


@router.put("/process-tickets/{ticket_id}/raw-values",
            response_model=DataResponse[RawValuesOut])
def set_process_ticket_raw_values(ticket_id: int, body: RawValuesRequest,
                                  user: dict = Depends(get_current_user)):
    """Feldwerte eines Auftrags ROH ersetzen (Admin-Reparatur, auch archivierte).

    BEWUSST ohne Phasen-Schreibrechte, Sichtbarkeits-Filter und Feld-Validierung:
    repariert wird genau der Zustand, den die normalen Pfade nicht mehr zulassen
    (z. B. eine leergelaufene Zuständigkeit). Zwei Zugeständnisse: abgeleitete
    Felder werden nachgezogen (sonst widersprächen sie ihren Quellfeldern beim
    nächsten normalen Speichern), und der Grund ist Pflicht. Im Verlauf stehen die
    geänderten Felder samt alt→neu-Wert – je Feld-Sicht redigiert (redact).
    """
    row = _admin_row_or_error(ticket_id, user, "Roh-Werte eines Auftrags ersetzen")
    defn = _load_pinned_defn(row)
    grund = _pflicht_begruendung(body.reason)
    alt = row.get("values") or {}
    neu = compute.apply_computed(defn, dict(body.values))
    geaendert = sorted(k for k in set(alt) | set(neu) if alt.get(k) != neu.get(k))
    changes = {k: {"from": alt.get(k), "to": neu.get(k)} for k in geaendert}
    try:
        row = store.update_values(ticket_id, json.dumps(neu, ensure_ascii=False),
                                  expected_rev=row.get("rev"))
    except store.ProcessTicketConflict as exc:
        raise api_error(409, "TICKET_CONFLICT", str(exc))
    events.record(row, events.UPDATED, actor_id=user.get("id"), actor_name=_actor_name(user),
                  body=grund, details={"fields": geaendert, "changes": changes, "raw": True})
    return DataResponse(data=RawValuesOut(values=row.get("values") or {}))


# ── Beobachter:innen ─────────────────────────────────────────────────────────

class WatcherOut(BaseModel):
    id: str
    name: Optional[str] = None
    added_by: Optional[str] = None
    created_at: Optional[str] = None


class WatcherRequest(BaseModel):
    userId: Optional[str] = None      # leer = sich selbst eintragen


def _display_name(user_id: str) -> Optional[str]:
    """Anzeigename einer Person (denormalisiert in der Watcher-Zeile).

    Zuerst app_users (bereits angemeldete Person). Für nie angemeldete Personen –
    die man als Beobachter/Zuständige wählen kann, ohne dass eine app_users-Zeile
    existiert – Fallback auf den Directus-Mitarbeiter-Datensatz per E-Mail. Sonst
    None (Aufrufer zeigt dann die rohe E-Mail). `get_user` liefert eine Dataclass.
    """
    try:
        from backend.database.users import get_user
        row = get_user(user_id)
        if isinstance(row, dict):
            nm = row.get("displayName") or row.get("display_name") or row.get("email")
            if nm:
                return nm
        elif row is not None:
            nm = getattr(row, "display_name", None) or getattr(row, "email", None)
            if nm:
                return nm
    except Exception:
        logger.warning("Anzeigename für %s nicht auflösbar (app_users)", user_id)

    if user_id and "@" in str(user_id):
        try:
            from backend.services import directus_employee
            nm = directus_employee.display_name_of(directus_employee.lookup_employee(user_id))
            if nm:
                return nm
        except Exception:
            logger.warning("Anzeigename für %s nicht auflösbar (Directus)", user_id)
    return None


@router.get("/process-tickets/{ticket_id}/watchers", response_model=ListResponse[WatcherOut])
def list_ticket_watchers(ticket_id: int, user: dict = Depends(get_current_user)):
    row, _defn, _gids = _load_for_view(ticket_id, user)
    rows = watchers.list_watchers(row["id"])
    return ListResponse(data=[WatcherOut(**w) for w in rows],
                        meta=Meta(total=len(rows), limit=len(rows), offset=0))


@router.post("/process-tickets/{ticket_id}/watchers", response_model=ListResponse[WatcherOut])
def add_ticket_watcher(ticket_id: int, body: Optional[WatcherRequest] = None,
                       user: dict = Depends(get_current_user)):
    """Beobachter:in eintragen.

    Beobachten gibt dauerhaften Lesezugriff (Rechte-Vergabe) – daher dürfen NUR
    die Ersteller:in und Admins jemanden eintragen (auch sich selbst), NICHT die
    zuständige Stelle. Prozessübergreifend.
    """
    row, defn, gids = _load_for_view(ticket_id, user)
    target = (body.userId if body else None) or user.get("id")
    if not target:
        raise api_error(422, ErrorCode.VALIDATION_FAILED, "Keine Person angegeben",
                        fields=[{"path": "userId", "code": "REQUIRED", "message": "Pflichtfeld"}])
    if not _may_manage_watchers(row, user):
        raise api_error(403, ErrorCode.TICKET_FORBIDDEN,
                        "Nur die Ersteller:in und Admins können Beobachter:innen eintragen")

    name = (_actor_name(user) if target == user.get("id") else _display_name(target))
    if watchers.add_watcher(row["id"], target, name, added_by=user.get("id")):
        events.record(row, events.WATCHER_ADDED, actor_id=user.get("id"),
                      actor_name=_actor_name(user),
                      details={"watcher": target, "watcher_name": name})
    rows = watchers.list_watchers(row["id"])
    return ListResponse(data=[WatcherOut(**w) for w in rows],
                        meta=Meta(total=len(rows), limit=len(rows), offset=0))


@router.delete("/process-tickets/{ticket_id}/watchers",
               response_model=ListResponse[WatcherOut])
def remove_ticket_watcher(ticket_id: int, body: Optional[WatcherRequest] = None,
                          user: dict = Depends(get_current_user)):
    """Beobachtung beenden. Die Ziel-ID (jetzt eine E-Mail) kommt im BODY, nicht im
    Pfad – personenbezogene Daten gehören nicht in URLs/Logs. Ohne `userId`: sich
    selbst. Sich selbst immer; andere nur die Ersteller:in + Admins."""
    row, defn, gids = _load_for_view(ticket_id, user)
    me = str(user.get("id") or "").strip().lower()
    watcher_id = (str((body.userId if body else None) or "").strip().lower()) or me
    if watcher_id != me and not _may_manage_watchers(row, user):
        raise api_error(403, ErrorCode.TICKET_FORBIDDEN,
                        "Nur die Ersteller:in und Admins können andere Beobachter:innen entfernen")
    if watchers.remove_watcher(row["id"], watcher_id):
        # Name mitschreiben (wie beim Eintragen), damit der Verlauf nicht eine
        # rohe Nutzer-ID zeigt.
        events.record(row, events.WATCHER_REMOVED, actor_id=user.get("id"),
                      actor_name=_actor_name(user),
                      details={"watcher": watcher_id, "watcher_name": _display_name(watcher_id)})
    rows = watchers.list_watchers(row["id"])
    return ListResponse(data=[WatcherOut(**w) for w in rows],
                        meta=Meta(total=len(rows), limit=len(rows), offset=0))
