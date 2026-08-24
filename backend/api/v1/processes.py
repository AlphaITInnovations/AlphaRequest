"""
REST-API für Prozess-Definitionen (data-driven Workflows, Stufe 1).

Ressourcenorientiert; Nicht-CRUD-Aktionen als Custom Method (`:verb`).
Alle Mutationen sind auf Admin (PERM_ADMIN) beschränkt und werden auditiert;
Entwurf-/Versions-Reads erfordern Manage/Admin, der veröffentlichte Katalog ist
für alle Authentifizierten sichtbar.

Definitionen werden beim Anlegen/Bearbeiten/Import gegen das Meta-Schema
(schemas.process_definition.ProcessDefinition) validiert – FastAPI erzeugt bei
Verstößen einen RequestValidationError, den der Handler in main.py in den
einheitlichen Fehler-Envelope { error: { code, message, fields[] } } normalisiert.
"""
import json
from typing import Optional

from fastapi import APIRouter, Depends, File, Header, Response, UploadFile
from pydantic import BaseModel

from backend.core.dependencies import get_current_user
from backend.database import process_definitions as db
from backend.database import process_templates as tpl_db
from backend.database.audit_log import record_audit
from backend.database.groups import get_group_ids_for_user
from backend.database.users import PERM_ADMIN, PERM_MANAGE
from backend.schemas.process_definition import ProcessDefinition
from backend.schemas.responses import DataResponse, api_error, ErrorCode
import html

from backend.services import attachment_storage as storage
from backend.services import docx_fill
from backend.services import process_delete as pdel
from backend.services import process_permissions as perms
from backend.services import process_runtime as pr
from backend.services import process_visibility as vis
from backend.services import seed_definitions as seeds
from backend.utils.config import config
from backend.utils.logger import logger
from backend.utils.timeutil import utcnow_iso

router = APIRouter()


# ── Auth ────────────────────────────────────────────────────────────────────

def _require_admin(user: dict) -> None:
    if PERM_ADMIN not in (user.get("permissions", []) or []):
        raise api_error(403, ErrorCode.ADMIN_REQUIRED, "Admin-Rechte erforderlich")


def _require_manage(user: dict) -> None:
    perms = user.get("permissions", []) or []
    if PERM_ADMIN not in perms and PERM_MANAGE not in perms:
        raise api_error(403, ErrorCode.PERMISSION_DENIED, "Verwaltungsrechte erforderlich")


def _require_editable(key: Optional[str]) -> None:
    """Sperrt jede Änderung an einem System-Prozess – auch für Admins.

    System-Prozesse gehören zum Produkt und werden beim Start aus der
    Auslieferung gepflegt (services/seed_definitions.ensure_system_processes).
    Wäre die Sperre nur in der Oberfläche, käme der nächste Start und legte die
    Änderung als neue Version wieder um – ein Bearbeiten, das man verliert, ist
    schlimmer als eines, das man nicht anfangen kann. Wer eine eigene Variante
    braucht, macht mit `:duplicate` einen ganz normalen, änderbaren Prozess
    daraus; Lesen und Exportieren bleiben erlaubt.
    """
    if seeds.is_system_process(key):
        raise api_error(403, ErrorCode.SYSTEM_PROCESS_READONLY,
                        f"„{key}“ ist ein System-Prozess und nicht änderbar. Er wird mit der "
                        "Anwendung ausgeliefert und beim Start aktuell gehalten. Für eine "
                        "eigene Fassung: duplizieren.")
    if seeds.is_auto_managed(key):
        raise api_error(403, ErrorCode.SYSTEM_PROCESS_READONLY,
                        f"„{key}“ wird automatisch aus der Auslieferung (seeds/auto) gepflegt "
                        "und ist im UI nicht änderbar. Änderungen laufen über die JSON; beim "
                        "Start wird daraus eine neue Version veröffentlicht. Für eine eigene "
                        "Fassung: duplizieren.")


def _audit(user: dict, action: str, key: str, **details) -> None:
    record_audit(
        action=action,
        actor_id=user.get("id"),
        actor_name=user.get("displayName") or user.get("email") or "",
        entity_type="process_definition",
        entity_id=key,
        summary=f"Prozess „{key}“: {action}",
        details=details,
    )


# ── Out-Schema ────────────────────────────────────────────────────────────────

class ProcessOut(BaseModel):
    id: int
    key: str
    version: int
    status: str
    name: str
    definition: Optional[dict] = None
    #: Darf der/die Aufrufende einen Auftrag dieses Prozesses anlegen?
    #: Nur auf dem Katalog (GET /processes) gefüllt, damit die Anlage-Seite
    #: filtern kann, ohne jede Definition einzeln zu laden.
    may_create: Optional[bool] = None
    #: Symbol aus der Definition – Listen-Routen liefern `definition` nicht mit.
    icon: Optional[str] = None
    #: Kurzbeschreibung aus der Definition. Wie `icon` nur im Katalog gefüllt: die
    #: Kacheln der Anlage-Seite brauchen sie, damit erkennbar bleibt, wofür ein
    #: Prozess da ist (die Alt-Seite hatte diesen Satz je Kachel hartcodiert).
    description: Optional[str] = None
    #: Zum Produkt gehörender Prozess: nicht änderbar (jede Mutation antwortet mit
    #: SYSTEM_PROCESS_READONLY). Die Oberfläche soll die Knöpfe deshalb gar nicht
    #: erst anbieten – abgeleitet aus dem Key, kein DB-Feld.
    is_system: bool = False
    #: Auto-verwaltet (seeds/auto): ebenfalls im UI schreibgeschützt – die JSON ist
    #: die Wahrheit, der Start hält den Prozess aktuell. Abgeleitet aus dem Key.
    is_auto_managed: bool = False
    #: Global deaktiviert? Dann lassen sich keine neuen Aufträge anlegen. Eine
    #: key-weite Eigenschaft (process_state), unabhängig von der Version – im
    #: Katalog und in der veröffentlichten Ansicht gefüllt.
    disabled: bool = False
    base_version: Optional[int] = None
    created_by: Optional[str] = None
    created_by_name: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    published_at: Optional[str] = None
    etag: Optional[str] = None


def _out(row: dict) -> ProcessOut:
    """DB-Zeile → Antwort. EINZIGE Stelle, die ProcessOut baut – jeder
    Rückgabe-Pfad (Katalog, Versionsliste, Detail, Mutationen) läuft hier durch,
    damit `is_system` nirgends fehlt."""
    daten = {k: row.get(k) for k in ProcessOut.model_fields}
    # Aus dem Key abgeleitet: die Zeile führt kein solches Feld (und soll keins).
    daten["is_system"] = seeds.is_system_process(row.get("key"))
    daten["is_auto_managed"] = seeds.is_auto_managed(row.get("key"))
    # Nicht-optionales Bool: die meisten Zeilen führen die Spalte nicht (nur der
    # Katalog/die veröffentlichte Ansicht setzen sie danach explizit).
    daten["disabled"] = bool(row.get("disabled"))
    return ProcessOut(**daten)


def _set_etag(resp: Response, row: dict) -> None:
    if row.get("etag"):
        resp.headers["ETag"] = str(row["etag"])


def _dump(defn: ProcessDefinition) -> str:
    return json.dumps(defn.model_dump(by_alias=True), ensure_ascii=False)


# ── DB-Fehler → HTTP ────────────────────────────────────────────────────────

def _map_db_error(exc: Exception):
    if isinstance(exc, db.ProcessNotFound):
        return api_error(404, ErrorCode.PROCESS_NOT_FOUND, f"Prozess nicht gefunden: {exc}")
    if isinstance(exc, db.ProcessKeyExists):
        return api_error(409, ErrorCode.PROCESS_KEY_EXISTS, f"Prozess-Key existiert bereits: {exc}")
    if isinstance(exc, db.ProcessInvalidState):
        return api_error(409, ErrorCode.PROCESS_INVALID_STATE, str(exc))
    if isinstance(exc, db.ProcessVersionInUse):
        return api_error(409, ErrorCode.PROCESS_VERSION_IN_USE, str(exc))
    if isinstance(exc, db.ProcessVersionConflict):
        return api_error(409, ErrorCode.PROCESS_VERSION_CONFLICT, str(exc))
    return None


# ── Katalog / Read ─────────────────────────────────────────────────────────

@router.get("/processes", response_model=DataResponse[list[ProcessOut]])
def list_processes(user: dict = Depends(get_current_user)):
    """Veröffentlichter Prozess-Katalog (für alle Authentifizierten).

    Liefert je Prozess `may_create` und `icon`. Die vollständige Definition wird
    dafür gelesen, aber NICHT mitgesendet – sie gehört nicht in eine Liste.
    """
    rows = db.list_published_catalog(include_definition=True)
    gesperrt = db.disabled_keys()
    try:
        # Fachabteilungen (interne Gruppen) UND AD-Gruppen aus dem Login-Token:
        # das Alt-System berechtigte über beides. Katalog und Anlegen müssen
        # dieselbe Menge sehen, sonst zeigt die Oberfläche einen Prozess an,
        # dessen Anlegen dann 403 liefert.
        gids = get_group_ids_for_user(user.get("id")) if user.get("id") else []
        group_ids = list(gids) + [g for g in (user.get("groups") or []) if g]
    except Exception:
        logger.warning("Gruppen für Erstellrechte nicht ladbar – nur Admin darf anlegen")
        group_ids = []

    out: list[ProcessOut] = []
    for r in rows:
        item = _out(r)
        item.definition = None          # Blob nicht in der Liste ausliefern
        item.disabled = r.get("key") in gesperrt
        raw = r.get("definition") or {}
        item.icon = raw.get("icon")
        item.description = raw.get("description")
        try:
            defn = ProcessDefinition.model_validate(raw)
            item.may_create = perms.may_create(defn, user, group_ids)
        except Exception:
            # Kaputte Definition darf den Katalog nicht sprengen – fail-closed.
            logger.exception("Definition %s v%s nicht lesbar", r.get("key"), r.get("version"))
            item.may_create = False
        out.append(item)
    return DataResponse(data=out)


@router.get("/processes/{key}/versions", response_model=DataResponse[list[ProcessOut]])
def list_process_versions(key: str, user: dict = Depends(get_current_user)):
    _require_manage(user)
    rows = db.list_versions(key)
    if not rows:
        raise api_error(404, ErrorCode.PROCESS_NOT_FOUND, f"Prozess nicht gefunden: {key}")
    return DataResponse(data=[_out(r) for r in rows])


@router.get("/processes/{key}/versions/{version:int}:export")
def export_process_version(key: str, version: int, user: dict = Depends(get_current_user)):
    """Portable JSON-Definition einer Version (Export)."""
    _require_manage(user)
    row = db.get_definition(key, version)
    if not row:
        raise api_error(404, ErrorCode.PROCESS_NOT_FOUND, f"Prozess nicht gefunden: {key} v{version}")
    return DataResponse(data=row.get("definition"))


@router.get("/processes/{key}/versions/{version:int}", response_model=DataResponse[ProcessOut])
def get_process_version(key: str, version: int, response: Response,
                        user: dict = Depends(get_current_user)):
    _require_manage(user)
    row = db.get_definition(key, version)
    if not row:
        raise api_error(404, ErrorCode.PROCESS_NOT_FOUND, f"Prozess nicht gefunden: {key} v{version}")
    _set_etag(response, row)
    return DataResponse(data=_out(row))


@router.get("/processes/{key}", response_model=DataResponse[ProcessOut])
def get_published_process(key: str, user: dict = Depends(get_current_user)):
    """Aktuell veröffentlichte Version (für alle Authentifizierten)."""
    row = db.get_published(key)
    if not row:
        raise api_error(404, ErrorCode.PROCESS_NOT_FOUND, f"Kein veröffentlichter Prozess: {key}")
    item = _out(row)
    item.disabled = db.is_disabled(key)
    return DataResponse(data=item)


class FieldAccessOut(BaseModel):
    """Welche Felder diese Person beim ANLEGEN sehen und ausfüllen darf."""
    visible_fields: list[str] = []
    editable_fields: list[str] = []


@router.get("/processes/{key}/field-access", response_model=DataResponse[FieldAccessOut])
def get_create_field_access(key: str, user: dict = Depends(get_current_user)):
    """Feld-Auskunft für den Anlege-Dialog.

    Beim Anlegen gibt es noch kein Ticket, also auch keine Ticket-Antwort mit
    `visible_fields`/`editable_fields`. Ohne diese Auskunft müsste das Formular die
    Sichtbarkeit raten – es kennt die Gruppen-Mitgliedschaft aber gar nicht und
    würde Eingabefelder für Daten anbieten, die der Server anschließend verwirft.

    Gerechnet wird gegen die START-Phase und mit der anfragenden Person als
    künftiger Ersteller:in – genau die Rolle, die sie beim Anlegen hätte.
    """
    row = db.get_published(key)
    if not row or not row.get("definition"):
        raise api_error(404, ErrorCode.PROCESS_NOT_FOUND, f"Kein veröffentlichter Prozess: {key}")
    defn = ProcessDefinition.model_validate(row["definition"])
    start = defn.phases[0]
    provisorisch = {"owner_id": user.get("id"), "status": "in_progress",
                    "runtime": pr.initial_runtime(defn, utcnow_iso()), "values": {}}
    gids = vis.user_group_ids(user)
    ctx = vis.build_viewer_ctx(user, provisorisch, defn, group_ids=gids)
    return DataResponse(data=FieldAccessOut(
        visible_fields=sorted(vis.visible_field_keys(defn, ctx)),
        # ignore_conditions: die bedingte Anzeige wertet das Formular live aus.
        editable_fields=sorted(vis.editable_field_keys(defn, start, ctx, {},
                                                       ignore_conditions=True)),
    ))


# ── Mutationen (Admin) ────────────────────────────────────────────────────────

@router.post("/processes", response_model=DataResponse[ProcessOut])
def create_process(defn: ProcessDefinition, user: dict = Depends(get_current_user)):
    """Neuen Prozess als Draft v1 anlegen (key aus der Definition)."""
    _require_admin(user)
    # Auch das Anlegen: sonst wäre ein System-Key von Hand belegbar, bevor der
    # Start ihn pflegt – und der Startlauf schriebe dann in einen fremden Prozess.
    _require_editable(defn.key)
    try:
        row = db.create_process(defn.key, defn.name, _dump(defn), user.get("id"),
                                user.get("displayName") or user.get("email"))
    except Exception as exc:
        mapped = _map_db_error(exc)
        if mapped:
            raise mapped
        raise
    _audit(user, "process_created", defn.key, version=1)
    return DataResponse(data=_out(row))


@router.post("/processes/{key}/versions", response_model=DataResponse[ProcessOut])
def create_draft_version(key: str, user: dict = Depends(get_current_user)):
    """Neuen Bearbeitungs-Draft holen/anlegen (klont die published-Version)."""
    _require_admin(user)
    _require_editable(key)
    try:
        row = db.create_or_get_draft(key, user.get("id"),
                                     user.get("displayName") or user.get("email"))
    except Exception as exc:
        mapped = _map_db_error(exc)
        if mapped:
            raise mapped
        raise
    _audit(user, "process_draft_created", key, version=row["version"])
    return DataResponse(data=_out(row))


@router.put("/processes/{key}/versions/{version:int}", response_model=DataResponse[ProcessOut])
def update_process_draft(key: str, version: int, defn: ProcessDefinition, response: Response,
                         if_match: Optional[str] = Header(None, alias="If-Match"),
                         user: dict = Depends(get_current_user)):
    _require_admin(user)
    _require_editable(key)
    if defn.key != key:
        raise api_error(422, ErrorCode.VALIDATION_FAILED, "key im Body weicht vom Pfad ab",
                        fields=[{"path": "key", "code": "MISMATCH",
                                 "message": f"Body-key „{defn.key}“ ≠ Pfad-key „{key}“"}])
    try:
        row = db.update_draft(key, version, defn.name, _dump(defn), if_match=if_match)
    except Exception as exc:
        mapped = _map_db_error(exc)
        if mapped:
            raise mapped
        raise
    _audit(user, "process_draft_updated", key, version=version)
    _set_etag(response, row)
    return DataResponse(data=_out(row))


@router.post("/processes/{key}/versions/{version:int}:publish", response_model=DataResponse[ProcessOut])
def publish_process_version(key: str, version: int, user: dict = Depends(get_current_user)):
    _require_admin(user)
    _require_editable(key)
    try:
        row = db.publish(key, version)
    except Exception as exc:
        mapped = _map_db_error(exc)
        if mapped:
            raise mapped
        raise
    _audit(user, "process_published", key, version=version)
    return DataResponse(data=_out(row))


class SetActiveRequest(BaseModel):
    #: True = deaktivieren (keine neuen Aufträge), False = wieder freigeben.
    disabled: bool


@router.post("/processes/{key}:set-active", response_model=DataResponse[ProcessOut])
def set_process_active(key: str, body: SetActiveRequest,
                       user: dict = Depends(get_current_user)):
    """Prozess global (de)aktivieren.

    Deaktiviert blockiert NUR das Anlegen neuer Aufträge – laufende Aufträge und
    ihre Phasen bleiben unberührt. Der Zustand gilt key-weit über alle Versionen
    und überlebt eine Neuveröffentlichung. System-Prozesse sind ausgenommen
    (`_require_editable`): das Produkt garantiert ihre Verfügbarkeit.
    """
    _require_admin(user)
    _require_editable(key)
    row = db.get_published(key)
    if not row:
        # Nur veröffentlichte Prozesse sind überhaupt anlegbar – nur die lassen
        # sich sinnvoll (de)aktivieren. So bleibt kein verwaister Zustand zurück.
        raise api_error(404, ErrorCode.PROCESS_NOT_FOUND,
                        f"Kein veröffentlichter Prozess: {key}")
    db.set_disabled(key, body.disabled, user.get("id"),
                    user.get("displayName") or user.get("email"))
    _audit(user, "process_disabled" if body.disabled else "process_enabled",
           key, disabled=body.disabled)
    item = _out(row)
    item.disabled = body.disabled
    return DataResponse(data=item)


class DuplicateRequest(BaseModel):
    newKey: str


@router.post("/processes/{key}:duplicate", response_model=DataResponse[ProcessOut])
def duplicate_process(key: str, body: DuplicateRequest, user: dict = Depends(get_current_user)):
    _require_admin(user)
    # Die QUELLE darf ein System-Prozess sein – aus dem Basis-Ticket eine eigene,
    # änderbare Fassung zu machen ist der vorgesehene Weg. Nur das ZIEL nicht,
    # sonst legte man einen System-Key über die Kopie an.
    _require_editable(body.newKey)
    # Quelle = published, sonst höchste Version
    src = db.get_published(key)
    if not src:
        versions = db.list_versions(key)
        src = versions[0] if versions else None
    if not src or not src.get("definition"):
        raise api_error(404, ErrorCode.PROCESS_NOT_FOUND, f"Prozess nicht gefunden: {key}")

    raw = dict(src["definition"])
    raw["key"] = body.newKey
    try:
        defn = ProcessDefinition.model_validate(raw)   # validiert den neuen key mit
    except Exception:
        raise api_error(422, ErrorCode.VALIDATION_FAILED, "Kopie ist nicht valide (ungültiger neuer key?)",
                        fields=[{"path": "newKey", "code": "INVALID", "message": body.newKey}])
    try:
        row = db.duplicate(key, body.newKey, _dump(defn), defn.name, user.get("id"),
                           user.get("displayName") or user.get("email"))
    except Exception as exc:
        mapped = _map_db_error(exc)
        if mapped:
            raise mapped
        raise
    _audit(user, "process_duplicated", body.newKey, source=key)
    return DataResponse(data=_out(row))


class ImportRequest(BaseModel):
    targetKey: str
    definition: ProcessDefinition


@router.post("/processes:import", response_model=DataResponse[ProcessOut])
def import_process(body: ImportRequest, user: dict = Depends(get_current_user)):
    """Import: der Ziel-key muss bestätigt werden (nie allein aus dem JSON).

    Gruppen-Platzhalter der ausgelieferten JSONs (`HIER_GRUPPEN_ID_*`) werden
    gegen die Gruppen DIESER Installation aufgelöst – seit dem Wegfall des
    Seed-Dialogs ist der manuelle Import DER Weg, Repo-Definitionen
    einzuspielen. Fail-closed wie beim Seeder: ein stehen gebliebener
    Platzhalter würde still einen dauerhaft kaputten Prozess anlegen (niemand
    zuständig, vertrauliche Felder für niemanden sichtbar). Unbekannte ECHTE
    Gruppen-IDs sind dagegen erlaubt: der Import erzeugt einen Entwurf, dessen
    Fehler der Editor anzeigt und reparieren lässt.
    """
    _require_admin(user)
    _require_editable(body.targetKey)
    raw = body.definition.model_dump(by_alias=True)
    raw["key"] = body.targetKey

    try:
        from backend.database.groups import get_groups
        index = seeds.build_group_index(get_groups())
    except seeds.SeedError as exc:
        # Mehrdeutige Gruppennamen: Auflösung wäre Raterei – lieber ablehnen.
        raise api_error(422, ErrorCode.VALIDATION_FAILED, str(exc))
    except Exception:
        logger.warning("Gruppen für die Platzhalter-Auflösung nicht ladbar – "
                       "Import prüft nur auf verbliebene Platzhalter")
        index = {}
    raw = seeds.replace_placeholders(raw, seeds.build_placeholder_mapping(index))

    reste = seeds.unresolved_placeholders(raw)
    if reste:
        fehlende = sorted({seeds.PLACEHOLDER_GROUP_NAMES.get(wert, wert)
                           for _pfad, wert in reste})
        raise api_error(
            422, ErrorCode.VALIDATION_FAILED,
            "Gruppen-Platzhalter nicht auflösbar – bitte zuerst diese "
            f"Fachabteilungen anlegen: {', '.join(fehlende)}",
            fields=[{"path": pfad, "code": "UNRESOLVED_PLACEHOLDER", "message": wert}
                    for pfad, wert in reste])

    try:
        defn = ProcessDefinition.model_validate(raw)
    except Exception:
        raise api_error(422, ErrorCode.VALIDATION_FAILED, "Import ist nicht valide",
                        fields=[{"path": "targetKey", "code": "INVALID", "message": body.targetKey}])
    try:
        row = db.create_process(defn.key, defn.name, _dump(defn), user.get("id"),
                                user.get("displayName") or user.get("email"))
    except Exception as exc:
        mapped = _map_db_error(exc)
        if mapped:
            raise mapped
        raise
    _audit(user, "process_imported", defn.key)
    return DataResponse(data=_out(row))


# ── Ausgelieferte Prozesse einspielen (Admin) ────────────────────────────────

class SeedRequest(BaseModel):
    #: Trockenlauf ist der STANDARD: erst ansehen, was passieren würde, dann
    #: schreiben. Ein Knopf, der beim ersten Druck neun Prozesse veröffentlicht,
    #: wäre in der Oberfläche eine Falle.
    commit: bool = False
    #: Erstellrechte NICHT aus dem Alt-System übernehmen.
    skipPermissions: bool = False


class SeedOutcomeOut(BaseModel):
    """Was mit EINEM ausgelieferten Prozess passiert (ist)."""
    file: str
    key: Optional[str] = None
    #: created | would_create | skipped | error
    action: str
    message: str = ""
    warnings: list[str] = []
    #: System-Prozess: dieser Lauf fasst ihn nicht an (der Start pflegt ihn). Als
    #: eigenes Merkmal und nicht nur als Satz in `message`, damit die Oberfläche
    #: die Zeile kennzeichnen kann, ohne Text zu durchsuchen.
    is_system: bool = False
    #: Übernommene Erstellrechte – nur gefüllt, wenn der Prozess (auch) angelegt
    #: wird; an einem übersprungenen wird nichts gesetzt.
    create_permissions: Optional[dict] = None
    #: Alt-Gruppen, die `may_create` nie sieht (AD-Gruppen) – NICHT übernommen.
    ineffective_groups: list[str] = []


class SeedReportOut(BaseModel):
    """Derselbe Bericht, den das CLI-Skript ausgibt – als JSON."""
    commit: bool
    created: int
    skipped: int
    errors: int
    required_groups: list[str] = []
    created_groups: list[str] = []
    missing_groups: list[str] = []
    outcomes: list[SeedOutcomeOut] = []


def _seed_report_out(report) -> SeedReportOut:
    return SeedReportOut(
        commit=report.commit,
        created=report.erstellt,
        skipped=report.uebersprungen,
        errors=report.fehler,
        required_groups=seeds.required_group_names(),
        created_groups=list(report.angelegte_gruppen),
        missing_groups=list(report.fehlende_gruppen),
        outcomes=[SeedOutcomeOut(
            file=o.datei, key=o.key, action=o.aktion, message=o.meldung,
            warnings=list(o.warnungen), is_system=seeds.is_system_process(o.key),
            create_permissions=o.create_permissions,
            ineffective_groups=list(o.wirkungslose_gruppen),
        ) for o in report.outcomes],
    )


@router.post("/processes:seed", response_model=DataResponse[SeedReportOut])
def seed_shipped_processes(body: Optional[SeedRequest] = None,
                           user: dict = Depends(get_current_user)):
    """Die mitgelieferten Prozess-Definitionen einspielen (Admin, auditiert).

    Warum es diesen Endpunkt gibt: `python -m backend.scripts.seed_processes
    --commit` war der EINZIGE Weg, die ausgelieferten Prozesse in eine
    Installation zu bekommen. Ein Shell-Zugang auf dem Server darf nicht die
    Bedingung dafür sein, dass die Anwendung benutzbar wird.

    Warum es trotzdem ein Knopf und kein Automatismus ist: die neun
    Fach-Prozesse brauchen Fachabteilungen mit Verteiler-Adressen und die
    Übernahme der Erstellrechte. Automatisch veröffentlicht sähen sie fertig aus,
    wären aber nur für Admins anlegbar und schickten Mails an leere Verteiler.
    Deshalb entscheidet ein Mensch – nach einem Trockenlauf (`commit: false`,
    Standard), der nichts schreibt.

    Der System-Prozess Basis-Ticket wird übersprungen und sagt das: ihn pflegt
    der Start (services/seed_definitions.ensure_system_processes).
    """
    _require_admin(user)
    req = body or SeedRequest()
    try:
        report = seeds.seed_processes(
            commit=req.commit,
            with_permissions=not req.skipPermissions,
            actor=str(user.get("id") or "admin"),
            actor_name=user.get("displayName") or user.get("email") or "Admin",
        )
    except seeds.SeedError as exc:
        # Der Lauf konnte nicht sinnvoll starten (z.B. mehrdeutige Gruppennamen) –
        # das ist ein Zustand der Installation, kein Serverfehler.
        raise api_error(409, ErrorCode.PROCESS_SEED_FAILED, str(exc))
    out = _seed_report_out(report)
    record_audit(
        action="processes_seeded",
        actor_id=user.get("id"),
        actor_name=user.get("displayName") or user.get("email") or "",
        entity_type="process_definition",
        entity_id="*",
        summary=("Ausgelieferte Prozesse eingespielt" if req.commit
                 else "Ausgelieferte Prozesse: Trockenlauf (nichts geschrieben)"),
        details={"commit": req.commit, "with_permissions": not req.skipPermissions,
                 "created": out.created, "skipped": out.skipped, "errors": out.errors,
                 "created_groups": out.created_groups,
                 "keys": [o.key for o in out.outcomes if o.action in ("created", "would_create")]},
    )
    return DataResponse(data=out)


@router.delete("/processes/{key}/versions/{version:int}")
def delete_process_version(key: str, version: int, user: dict = Depends(get_current_user)):
    _require_admin(user)
    _require_editable(key)
    try:
        db.delete_version(key, version)
    except Exception as exc:
        mapped = _map_db_error(exc)
        if mapped:
            raise mapped
        raise
    _audit(user, "process_version_deleted", key, version=version)
    return {"ok": True}


# ── Ganzen Prozess löschen (zweistufig mit Mail-Bestätigung) ──────────────────

class DeleteRequest(BaseModel):
    #: Aufträge dieses Prozesses mit entfernen. Muss ausdrücklich gesetzt werden,
    #: wenn es welche gibt – sonst antwortet der Endpunkt mit 409.
    includeTickets: bool = False


class DeleteRequestOut(BaseModel):
    key: str
    name: str
    versions: list[dict] = []
    tickets: int = 0
    #: Wohin die Bestätigungs-Mail ging (ADMIN_MAIL).
    recipient: str
    expires_at: str


class DeletePreviewOut(BaseModel):
    """Was der Bestätigungs-Link löschen würde – reine Auskunft, kein Eingriff."""
    key: str
    name: str
    versions: list[dict] = []
    tickets: int = 0
    with_tickets: bool = False
    requested_by: Optional[str] = None


class ConfirmDeleteRequest(BaseModel):
    token: str


def _delete_error(exc: pdel.DeleteError):
    """Fachlicher Lösch-Abbruch -> HTTP. Die Codes sind für die Oberfläche gedacht."""
    status = {
        "no_recipient": 503,      # Konfiguration fehlt, nicht die Anfrage ist schuld
        "needs_tickets": 409,
        "not_found": 404,
        "superseded": 409,
        "expired": 410,
        "invalid": 400,
    }.get(exc.code, 400)
    return api_error(status, f"PROCESS_DELETE_{exc.code.upper()}", exc.message)


def _delete_mail(key: str, overview: dict, token: str, user: dict, empfaenger: str) -> None:
    """Bestätigungs-Mail mit Link.

    Ein Fehler hier darf NICHT stillschweigend durchgehen: ohne Mail gibt es keine
    Bestätigung und damit keine Löschung – der Aufrufende muss das erfahren.
    """
    from backend.services.microsoft_mail import send_mail_app_only

    link = f"{config.FRONTEND_URL}/prozesse/loeschen?token={token}"
    wer = user.get("displayName") or user.get("email") or user.get("id") or "-"
    n = int(overview.get("tickets") or 0)
    versionen = ", ".join(f"v{v['version']} ({v['status']})" for v in overview["versions"])
    betreff = (f"[AlphaRequest] Loeschung bestaetigen: Prozess {overview['name']}"
               .replace("\r", " ").replace("\n", " ")[:200])
    mit_anhang = " - samt Verlauf, Beobachter:innen und Anhaengen" if n else ""
    body = (
        f"<p><b>{html.escape(wer)}</b> moechte den Prozess "
        f"{html.escape(str(overview['name']))} "
        f"(<code>{html.escape(key)}</code>) loeschen.</p>"
        f"<p>Geloescht wuerden:<br>"
        f"&bull; Definition, alle Versionen: {html.escape(versionen)}<br>"
        f"&bull; Auftraege dieses Prozesses: <b>{n}</b>{mit_anhang}</p>"
        f"<p><b>Das laesst sich nicht rueckgaengig machen.</b></p>"
        f"<p>Zum Pruefen und Bestaetigen (Anmeldung als Admin erforderlich):<br>"
        f"{html.escape(link)}</p>"
        f"<p>Wurde diese Loeschung nicht von Ihnen veranlasst, ignorieren Sie diese "
        f"Mail - ohne Bestaetigung passiert nichts.</p>")
    send_mail_app_only(
        sender_upn_or_id="alpharequest@alpha-it-innovations.org",
        subject=betreff, body=body, to_recipients=[empfaenger],
        body_type="HTML", kind="process_delete_request",
    )


@router.post("/processes/{key}:request-delete", response_model=DataResponse[DeleteRequestOut])
def request_process_delete(key: str, body: Optional[DeleteRequest] = None,
                           user: dict = Depends(get_current_user)):
    """Löschung eines ganzen Prozesses anfordern - löscht noch NICHTS.

    Verschickt einen Bestätigungs-Link an `ADMIN_MAIL`. Erst die Bestätigung
    (`:confirm-delete`) entfernt Definition und Aufträge.
    """
    _require_admin(user)
    # Löschen ginge zwar, wäre aber sinnlos: der nächste Start legt den Prozess
    # wieder an. Nur die Aufträge blieben gelöscht.
    _require_editable(key)
    overview = db.process_overview(key)
    if overview is None:
        raise api_error(404, ErrorCode.PROCESS_NOT_FOUND, f"Prozess nicht gefunden: {key}")
    mit_auftraegen = bool(body.includeTickets) if body else False
    try:
        empfaenger = pdel.recipient()
        pdel.assert_tickets_acknowledged(overview, mit_auftraegen)
        token = pdel.make_token(key, overview, requested_by=user.get("id"),
                                include_tickets=mit_auftraegen)
    except pdel.DeleteError as exc:
        raise _delete_error(exc)
    try:
        _delete_mail(key, overview, token, user, empfaenger)
    except Exception as exc:
        logger.exception("Bestätigungs-Mail für die Löschung von %s fehlgeschlagen", key)
        raise api_error(502, "PROCESS_DELETE_MAIL_FAILED",
                        f"Die Bestätigungs-Mail konnte nicht versendet werden: {exc}")
    _audit(user, pdel.AUDIT_REQUESTED, key, tickets=overview["tickets"],
           with_tickets=mit_auftraegen, recipient=empfaenger)
    return DataResponse(data=DeleteRequestOut(
        key=key, name=overview["name"], versions=overview["versions"],
        tickets=overview["tickets"], recipient=empfaenger,
        expires_at=pdel.expires_at()))


@router.get("/processes:delete-preview", response_model=DataResponse[DeletePreviewOut])
def preview_process_delete(token: str, user: dict = Depends(get_current_user)):
    """Was der Bestätigungs-Link löschen würde. Reine Auskunft, kein Eingriff."""
    _require_admin(user)
    try:
        data = pdel.load_token(token)
        overview = db.process_overview(str(data["key"]))
        pdel.assert_matches(data, overview)
    except pdel.DeleteError as exc:
        raise _delete_error(exc)
    return DataResponse(data=DeletePreviewOut(
        key=overview["key"], name=overview["name"], versions=overview["versions"],
        tickets=overview["tickets"], with_tickets=bool(data.get("with_tickets")),
        requested_by=data.get("by")))


@router.post("/processes:confirm-delete", response_model=DataResponse[dict])
def confirm_process_delete(body: ConfirmDeleteRequest,
                           user: dict = Depends(get_current_user)):
    """Bestätigte Löschung ausführen: erst die Aufträge, dann die Definition.

    Diese Reihenfolge ist wichtig. Ein Auftrag ohne seine gepinnte Definition wäre
    nicht mehr lesbar (die API antwortet mit PROCESS_DEFINITION_MISSING); bricht es
    dagegen NACH den Aufträgen ab, steht die Definition noch und der Vorgang lässt
    sich wiederholen.
    """
    _require_admin(user)
    try:
        data = pdel.load_token(body.token)
        key = str(data["key"])
    except pdel.DeleteError as exc:
        raise _delete_error(exc)
    # Der Key steht im Token, nicht im Pfad: die Sperre muss hier ein zweites Mal
    # greifen, sonst genügte ein Token aus der Zeit vor der Aufnahme in
    # SYSTEM_PROCESS_KEYS.
    _require_editable(key)
    try:
        overview = db.process_overview(key)
        pdel.assert_matches(data, overview)
        pdel.assert_tickets_acknowledged(overview, bool(data.get("with_tickets")))
    except pdel.DeleteError as exc:
        raise _delete_error(exc)

    # Aufträge zuerst - jeder einzeln auditiert, damit nachvollziehbar bleibt, WAS
    # verschwunden ist (der Audit-Eintrag überlebt die Löschung).
    geloeschte_tickets = 0
    if overview["tickets"]:
        from backend.database import process_tickets as tstore
        rows, _total = tstore.list_tickets(process_key=key, limit=10_000, offset=0)
        for r in rows:
            record_audit(
                action="process_ticket_deleted", actor_id=user.get("id"),
                actor_name=user.get("displayName") or user.get("email") or "",
                entity_type="process_ticket", entity_id=str(r["id"]),
                summary=f"Prozess-Ticket #{r['id']} mit dem Prozess {key} geloescht",
                details={"process_key": key, "status": r.get("status"),
                         "owner_id": r.get("owner_id"), "via": "process_delete"},
            )
            if tstore.delete(int(r["id"])):
                geloeschte_tickets += 1

    try:
        versionen = db.delete_process(key)
    except Exception as exc:
        mapped = _map_db_error(exc)
        if mapped:
            raise mapped
        raise
    # Dokument-Vorlagen (Zeilen + Blobs) mitnehmen – sonst verwaisen sie und ein
    # später gleichnamiger Prozess bekäme über get_template die ALTE .docx.
    try:
        for r in tpl_db.delete_all(key):
            if r.get("stored_path"):
                storage.delete(r["stored_path"])
    except Exception:
        logger.warning("Vorlagen-Cleanup für „%s“ übersprungen", key)
    _audit(user, pdel.AUDIT_CONFIRMED, key, versions=versionen,
           tickets=geloeschte_tickets, requested_by=data.get("by"))
    return DataResponse(data={"key": key, "versions_deleted": versionen,
                              "tickets_deleted": geloeschte_tickets})


# ── Dokument-Vorlage (.docx) je Prozess ───────────────────────────────────────
#
# Die Vorlage ist installationsspezifisch (der echte Vertrag) und liegt daher
# NICHT im Seed, sondern wird hier pro Installation hochgeladen. Beim Export der
# Dokument-Phase füllt services/docx_fill die {{marker}} aus den Auftragswerten
# (Zuordnung Marker→Feld = DocumentSpec.bindings). Bewusst KEIN _require_editable:
# die Vorlage ist Betriebsdaten, kein Definitions-Inhalt – sie darf auch bei
# System-Prozessen gesetzt werden.

_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _safe_docname(name: Optional[str]) -> str:
    base = (name or "Vorlage.docx").strip() or "Vorlage.docx"
    keep = "".join(c for c in base if c.isalnum() or c in " _-.()äöüÄÖÜß").strip()
    return (keep or "Vorlage.docx")[:150]


def _content_disposition(filename: str) -> str:
    """Header mit ASCII-Rückfallebene + RFC-5987 `filename*` – sonst sprengt ein
    Nicht-latin-1-Zeichen (Ł, ş, CJK) den Header (Starlette kodiert latin-1)."""
    import urllib.parse
    ascii_name = filename.encode("ascii", "ignore").decode("ascii") or "Vorlage.docx"
    quoted = urllib.parse.quote(filename, safe="")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quoted}"


def _template_bytes(row: dict) -> bytes:
    from pathlib import Path
    return Path(storage.full_path(row["stored_path"])).read_bytes()


def _template_info(row: dict) -> dict:
    try:
        placeholders = docx_fill.find_placeholders(_template_bytes(row))
    except Exception:
        logger.exception("Vorlage %s nicht lesbar", row.get("process_key"))
        placeholders = []
    return {"exists": True, "filename": row.get("original_filename"),
            "size": row.get("size_bytes"), "placeholders": placeholders,
            "uploaded_at": str(row.get("uploaded_at") or ""),
            "uploaded_by": row.get("uploaded_by_name")}


@router.get("/processes/{key}/phases/{phase}/document-template")
def get_document_template(key: str, phase: str, user: dict = Depends(get_current_user)):
    """Info zur Vorlage + Liste der gefundenen {{marker}} (für die Zuordnung)."""
    _require_manage(user)
    row = tpl_db.get_template(key, phase)
    return DataResponse(data=_template_info(row) if row else {"exists": False})


@router.post("/processes/{key}/phases/{phase}/document-template")
async def upload_document_template(key: str, phase: str, file: UploadFile = File(...),
                                   user: dict = Depends(get_current_user)):
    """Vorlage (.docx) hochladen/ersetzen. Gibt die gefundenen Marker zurück."""
    _require_admin(user)
    if not (file.filename or "").lower().endswith(".docx"):
        raise api_error(422, ErrorCode.VALIDATION_FAILED,
                        "Nur Word-Dateien (.docx) werden als Vorlage unterstützt")
    max_bytes = config.MAX_UPLOAD_MB * 1024 * 1024
    try:
        stored_path, size, _sha = storage.save_stream(file.file, max_bytes=max_bytes)
    except storage.FileTooLarge:
        raise api_error(413, "FILE_TOO_LARGE", f"Datei zu groß (max. {config.MAX_UPLOAD_MB} MB)")
    # Lesbarkeit prüfen (gültiges .docx?) – sonst den Blob gleich wieder entfernen.
    try:
        placeholders = docx_fill.find_placeholders(_template_bytes({"stored_path": stored_path}))
    except Exception:
        storage.delete(stored_path)
        raise api_error(422, "INVALID_DOCX",
                        "Die Datei ließ sich nicht als Word-Dokument (.docx) lesen")
    old = tpl_db.get_template(key, phase)
    tpl_db.set_template(process_key=key, phase_key=phase, stored_path=stored_path,
                        original_filename=_safe_docname(file.filename),
                        content_type=file.content_type, size_bytes=size,
                        uploaded_by_id=user.get("id"),
                        uploaded_by_name=user.get("displayName") or user.get("email"))
    if old and old.get("stored_path") and old["stored_path"] != stored_path:
        storage.delete(old["stored_path"])
    record_audit(action="process_template_uploaded", actor_id=user.get("id"),
                 actor_name=user.get("displayName") or "", entity_type="process",
                 entity_id=key,
                 summary=f"Dokument-Vorlage für „{key}“ (Phase „{phase}“) hochgeladen ({size} B)",
                 details={"phase": phase, "filename": _safe_docname(file.filename),
                          "placeholders": placeholders})
    row = tpl_db.get_template(key, phase)
    return DataResponse(data=_template_info(row))


@router.get("/processes/{key}/phases/{phase}/document-template/download")
def download_document_template(key: str, phase: str, user: dict = Depends(get_current_user)):
    _require_manage(user)
    row = tpl_db.get_template(key, phase)
    if not row:
        raise api_error(404, "TEMPLATE_NOT_FOUND", "Keine Vorlage hinterlegt")
    return Response(content=_template_bytes(row), media_type=_DOCX_MIME,
                    headers={"Content-Disposition":
                             _content_disposition(_safe_docname(row["original_filename"]))})


@router.delete("/processes/{key}/phases/{phase}/document-template")
def delete_document_template(key: str, phase: str, user: dict = Depends(get_current_user)):
    _require_admin(user)
    row = tpl_db.delete_template(key, phase)
    if row and row.get("stored_path"):
        storage.delete(row["stored_path"])
    record_audit(action="process_template_deleted", actor_id=user.get("id"),
                 actor_name=user.get("displayName") or "", entity_type="process",
                 entity_id=key,
                 summary=f"Dokument-Vorlage für „{key}“ (Phase „{phase}“) entfernt",
                 details={"phase": phase})
    return DataResponse(data={"exists": False})
