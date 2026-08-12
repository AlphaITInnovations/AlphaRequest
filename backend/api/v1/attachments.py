"""
Datei-Anhänge für Aufträge (Grundlage – noch nicht an konkrete Phasen gebunden).

Blobs liegen auf dem Dateisystem (attachment_storage), Metadaten in der DB
(database.attachments). Upload/Download sind an den Ticket-Zugriff gekoppelt;
die Admin-Übersicht (Speicherplatz/Suche) liegt unter /settings/attachments.
Jeder Upload/jede Löschung wird im Audit-Log festgehalten; Versionen bleiben
über die `family_id` nachvollziehbar.

Zwei Welten: /tickets/… bedient das Alt-System, /process-tickets/… die
definitions-getriebenen Aufträge (Zugriff über services.process_access). Die
Endpunkte für Download/Löschen sind GEMEINSAM – sie finden den Anhang über seine
ID und wählen die Zugriffsprüfung anhand von `entity_type`.
"""
from typing import Literal, Optional

from fastapi import APIRouter, Depends, UploadFile, File, Form, Query
from fastapi.responses import FileResponse

from backend.core.dependencies import get_current_user
from backend.database import tickets as database
from backend.database import attachments as att_db
from backend.database import process_definitions as defstore
from backend.database import process_tickets as pstore
from backend.database.audit_log import record_audit
from backend.database.users import PERM_ADMIN
from backend.services import attachment_storage as storage
from backend.services import process_access as acc
from backend.services import process_runtime as pr
from backend.services import process_visibility as vis
from backend.schemas.attachment import (AttachmentAdminOut, AttachmentOut, AttachmentListOut,
                                        AttachmentStats)
from backend.schemas.process_definition import ProcessDefinition, Widget
from backend.schemas.responses import DataResponse, api_error, ErrorCode
from backend.utils.config import config
from backend.utils.files import safe_filename, human_size
from backend.utils.logger import logger
# Zugriffs-Helfer wiederverwenden (kein Zyklus: tickets importiert attachments nicht).
from backend.api.v1.tickets import _get_ticket_or_404, _assert_ticket_access

router = APIRouter()


class ProcessAttachmentOut(AttachmentOut):
    """Anhang eines Prozess-Auftrags. Erweitert die Alt-Ausgabe um die zwei neuen
    Merkmale; `ticket_id` ist hier die ID des Prozess-Tickets."""
    entity_type: str = att_db.ENTITY_PROCESS_TICKET
    field_key: Optional[str] = None


def _to_out(row: dict) -> AttachmentOut:
    ua = row.get("uploaded_at")
    return AttachmentOut(
        id=row["id"],
        ticket_id=row.get("ticket_id"),
        phase_key=row.get("phase_key"),
        family_id=row["family_id"],
        version=row["version"],
        is_current=bool(row["is_current"]),
        original_filename=row["original_filename"],
        content_type=row.get("content_type"),
        size_bytes=row["size_bytes"],
        size_human=human_size(row["size_bytes"]),
        sha256=row.get("sha256"),
        uploaded_by_id=row.get("uploaded_by_id"),
        uploaded_by_name=row.get("uploaded_by_name"),
        uploaded_at=ua.isoformat() if hasattr(ua, "isoformat") else (str(ua) if ua else None),
    )


def _to_process_out(row: dict) -> ProcessAttachmentOut:
    return ProcessAttachmentOut(
        **_to_out(row).model_dump(),
        entity_type=row.get("entity_type") or att_db.ENTITY_PROCESS_TICKET,
        field_key=row.get("field_key"),
    )


def _to_admin_out(row: dict) -> AttachmentAdminOut:
    """Zeile der Admin-Übersicht (beide Welten gemischt). Fallback auf das
    Alt-System entspricht dem Spalten-Default `entity_type='ticket'`."""
    return AttachmentAdminOut(
        **_to_out(row).model_dump(),
        entity_type=row.get("entity_type") or att_db.ENTITY_TICKET,
        field_key=row.get("field_key"),
        ticket_title=row.get("ticket_title"),
    )


# ── Ticket-Anhänge ───────────────────────────────────────────────────────────

@router.post("/tickets/{ticket_id}/attachments", response_model=DataResponse[AttachmentOut])
async def upload_attachment(
    ticket_id: int,
    file: UploadFile = File(...),
    phase_key: Optional[str] = Form(None),
    family_id: Optional[str] = Form(None),   # gesetzt = neue Version einer bestehenden Datei
    user: dict = Depends(get_current_user),
):
    ticket = _get_ticket_or_404(ticket_id)
    _assert_ticket_access(ticket, user)

    max_bytes = config.MAX_UPLOAD_MB * 1024 * 1024
    try:
        stored_path, size, sha = storage.save_stream(file.file, max_bytes=max_bytes)
    except storage.FileTooLarge:
        raise api_error(413, "FILE_TOO_LARGE", f"Datei zu groß (max. {config.MAX_UPLOAD_MB} MB)")
    except Exception:
        logger.exception("Attachment-Upload fehlgeschlagen (Ticket %s)", ticket_id)
        raise api_error(500, "UPLOAD_FAILED", "Datei konnte nicht gespeichert werden")

    att = att_db.insert_attachment(
        ticket_id=ticket_id,
        phase_key=(phase_key or None),
        family_id=(family_id or None),
        original_filename=safe_filename(file.filename),
        stored_path=stored_path,
        content_type=file.content_type,
        size_bytes=size,
        sha256=sha,
        uploaded_by_id=user["id"],
        uploaded_by_name=user.get("displayName") or "",
    )

    record_audit(
        action="file_uploaded",
        actor_id=user["id"],
        actor_name=user.get("displayName") or "",
        entity_type="attachment",
        entity_id=str(att["id"]),
        summary=f"Datei '{att['original_filename']}' ({human_size(size)}) zu Ticket #{ticket_id} hochgeladen (v{att['version']})",
        details={
            "ticket_id": ticket_id, "phase_key": att.get("phase_key"),
            "filename": att["original_filename"], "size_bytes": size, "sha256": sha,
            "family_id": att["family_id"], "version": att["version"],
        },
    )
    return DataResponse(data=_to_out(att))


@router.get("/tickets/{ticket_id}/attachments", response_model=DataResponse[list[AttachmentOut]])
def list_ticket_attachments(
    ticket_id: int,
    include_versions: bool = Query(False),
    user: dict = Depends(get_current_user),
):
    ticket = _get_ticket_or_404(ticket_id)
    _assert_ticket_access(ticket, user)
    rows = att_db.list_for_ticket(ticket_id, include_versions=include_versions)
    return DataResponse(data=[_to_out(r) for r in rows])


# ── Prozess-Anhänge (definitions-getriebene Aufträge) ────────────────────────

def _process_ticket_or_404(ticket_id: int) -> tuple[dict, Optional[ProcessDefinition]]:
    """Prozess-Ticket + GEPINNTE Definition laden.

    Fehlt/bricht die Definition, wird bewusst NICHT abgebrochen: `defn=None` ist
    für process_access default-deny (nur Aufsicht/Ersteller:in kommt durch), also
    die sichere Variante – und die Dateien eines Auftrags mit defekter Definition
    bleiben für die Aufsicht erreichbar."""
    row = pstore.get(ticket_id)
    if not row:
        raise api_error(404, ErrorCode.TICKET_NOT_FOUND, "Ticket nicht gefunden")
    try:
        d = defstore.get_definition(row["process_key"], row["process_version"])
        defn = ProcessDefinition.model_validate(d["definition"]) if d and d.get("definition") else None
    except Exception:
        logger.exception("Gepinnte Definition für Prozess-Ticket %s nicht ladbar", ticket_id)
        defn = None
    return row, defn


def _current_phase_key(row: dict, defn: Optional[ProcessDefinition]) -> Optional[str]:
    if defn is None:
        return None
    cur = pr.current_phase(defn, row.get("runtime") or {})
    return cur.key if cur else None


def _assert_process_view(row: dict, defn: Optional[ProcessDefinition], user: dict) -> None:
    if not acc.may_view(defn, row, user, vis.user_group_ids(user)):
        # Bewusst 404 (wie in process_tickets.py): nicht verraten, dass es den Auftrag gibt.
        raise api_error(404, ErrorCode.TICKET_NOT_FOUND, "Ticket nicht gefunden")


def _assert_process_edit(row: dict, defn: Optional[ProcessDefinition], user: dict) -> None:
    gids = vis.user_group_ids(user)
    if not acc.may_view(defn, row, user, gids):
        raise api_error(404, ErrorCode.TICKET_NOT_FOUND, "Ticket nicht gefunden")
    if not acc.may_edit(defn, row, user, gids):
        raise api_error(403, ErrorCode.TICKET_FORBIDDEN,
                        "Nur die aktuell zuständige Stelle kann Dateien dieses Auftrags ändern")


def _assert_attachment_field(defn: Optional[ProcessDefinition], field_key: Optional[str]) -> None:
    """`field_key` muss ein Feld der GEPINNTEN Definition mit widget='attachment'
    sein – sonst hängen Dateien an Feldern, die es im Prozess gar nicht gibt: sie
    wären im Formular unsichtbar, würden aber Speicher belegen und in der
    Admin-Übersicht auftauchen. Deshalb hart 422 statt stiller Annahme."""
    if field_key is None:
        return
    if defn is None:
        raise api_error(500, "PROCESS_DEFINITION_MISSING",
                        "Gepinnte Prozess-Definition fehlt – Anhang-Feld nicht prüfbar")
    f = next((f for f in defn.fields if f.key == field_key), None)
    if f is None or f.widget != Widget.attachment:
        raise api_error(422, ErrorCode.VALIDATION_FAILED, "Unbekanntes Anhang-Feld",
                        fields=[{"path": field_key, "code": "NOT_AN_ATTACHMENT_FIELD",
                                 "message": f"„{field_key}“ ist kein Anhang-Feld dieses Prozesses"}])


@router.post("/process-tickets/{ticket_id}/attachments",
             response_model=DataResponse[ProcessAttachmentOut])
async def upload_process_attachment(
    ticket_id: int,
    file: UploadFile = File(...),
    field_key: Optional[str] = Form(None),   # gesetzt = Datei gehört zu diesem Anhang-Feld
    family_id: Optional[str] = Form(None),   # gesetzt = neue Version einer bestehenden Datei
    user: dict = Depends(get_current_user),
):
    row, defn = _process_ticket_or_404(ticket_id)
    _assert_process_edit(row, defn, user)
    field_key = field_key or None
    _assert_attachment_field(defn, field_key)

    max_bytes = config.MAX_UPLOAD_MB * 1024 * 1024
    try:
        stored_path, size, sha = storage.save_stream(file.file, max_bytes=max_bytes)
    except storage.FileTooLarge:
        raise api_error(413, "FILE_TOO_LARGE", f"Datei zu groß (max. {config.MAX_UPLOAD_MB} MB)")
    except Exception:
        logger.exception("Attachment-Upload fehlgeschlagen (Prozess-Ticket %s)", ticket_id)
        raise api_error(500, "UPLOAD_FAILED", "Datei konnte nicht gespeichert werden")

    att = att_db.insert_attachment(
        entity_type=att_db.ENTITY_PROCESS_TICKET,
        ticket_id=ticket_id,
        field_key=field_key,
        # phase_key dokumentiert, in WELCHER Phase die Datei entstand (reine Historie).
        phase_key=_current_phase_key(row, defn),
        family_id=(family_id or None),
        original_filename=safe_filename(file.filename),
        stored_path=stored_path,
        content_type=file.content_type,
        size_bytes=size,
        sha256=sha,
        uploaded_by_id=user["id"],
        uploaded_by_name=user.get("displayName") or "",
    )

    record_audit(
        action="file_uploaded",
        actor_id=user["id"],
        actor_name=user.get("displayName") or "",
        entity_type="attachment",
        entity_id=str(att["id"]),
        summary=(f"Datei '{att['original_filename']}' ({human_size(size)}) zu Prozess-Ticket "
                 f"#{ticket_id} hochgeladen (v{att['version']})"),
        details={
            "entity_type": att_db.ENTITY_PROCESS_TICKET, "ticket_id": ticket_id,
            "field_key": field_key, "phase_key": att.get("phase_key"),
            "filename": att["original_filename"], "size_bytes": size, "sha256": sha,
            "family_id": att["family_id"], "version": att["version"],
        },
    )
    return DataResponse(data=_to_process_out(att))


@router.get("/process-tickets/{ticket_id}/attachments",
            response_model=DataResponse[list[ProcessAttachmentOut]])
def list_process_attachments(
    ticket_id: int,
    include_versions: bool = Query(False),
    field_key: Optional[str] = Query(None),
    user: dict = Depends(get_current_user),
):
    row, defn = _process_ticket_or_404(ticket_id)
    _assert_process_view(row, defn, user)
    # Auch beim LESEN prüfen: ein unbekannter field_key würde sonst still eine
    # leere Liste liefern und einen Tippfehler im Formular verschleiern.
    _assert_attachment_field(defn, field_key or None)
    rows = att_db.list_for_ticket(ticket_id, include_versions=include_versions,
                                  entity_type=att_db.ENTITY_PROCESS_TICKET,
                                  field_key=(field_key or None))
    return DataResponse(data=[_to_process_out(r) for r in rows])


# ── Gemeinsam: Download / Löschen (beide Welten, Auswahl über entity_type) ────

def _entity_label(att: dict) -> str:
    """Für Audit-Texte: aus welcher Welt stammt der Anhang?"""
    return ("Prozess-Ticket" if att.get("entity_type") == att_db.ENTITY_PROCESS_TICKET
            else "Ticket")


def _assert_attachment_access(att: dict, user: dict, *, write: bool) -> None:
    """Zugriff auf einen Anhang – je nach Welt über den Alt-Ticket-Zugriff oder
    über services.process_access (may_view zum Lesen, may_edit zum Ändern)."""
    if att.get("entity_type") == att_db.ENTITY_PROCESS_TICKET:
        row, defn = _process_ticket_or_404(att["ticket_id"])
        if write:
            _assert_process_edit(row, defn, user)
        else:
            _assert_process_view(row, defn, user)
        return
    # Alt-System: an den Ticket-Zugriff koppeln (Admins über den globalen Zugriff).
    if att.get("ticket_id"):
        ticket = database.get_ticket(att["ticket_id"])
        if ticket:
            _assert_ticket_access(ticket, user)


@router.get("/attachments/{attachment_id}/download")
def download_attachment(attachment_id: int, user: dict = Depends(get_current_user)):
    att = att_db.get_attachment(attachment_id)
    if not att or att.get("deleted_at"):
        raise api_error(404, "NOT_FOUND", "Anhang nicht gefunden")
    _assert_attachment_access(att, user, write=False)
    try:
        path = storage.full_path(att["stored_path"])
    except ValueError:
        raise api_error(404, "NOT_FOUND", "Anhang nicht gefunden")
    if not path.is_file():
        raise api_error(404, "NOT_FOUND", "Datei nicht mehr vorhanden")
    return FileResponse(
        str(path),
        filename=att["original_filename"],
        media_type=att.get("content_type") or "application/octet-stream",
    )


@router.delete("/attachments/{attachment_id}")
def delete_attachment(attachment_id: int, user: dict = Depends(get_current_user)):
    att = att_db.get_attachment(attachment_id)
    if not att or att.get("deleted_at"):
        raise api_error(404, "NOT_FOUND", "Anhang nicht gefunden")
    if att.get("entity_type") == att_db.ENTITY_PROCESS_TICKET:
        # Prozess-Welt: Löschen ist ein Eingriff in den Auftrag → may_edit.
        # Bewusst NICHT „nur wer hochgeladen hat": Anhänge gehören zum Auftrag,
        # und die zuständige Stelle muss eine Fehl-Datei ersetzen können.
        _assert_attachment_access(att, user, write=True)
    else:
        is_admin = PERM_ADMIN in (user.get("permissions", []) or [])
        if not is_admin and att.get("uploaded_by_id") != user["id"]:
            raise api_error(403, ErrorCode.PERMISSION_DENIED, "Kein Recht, diesen Anhang zu löschen")

    att_db.soft_delete(attachment_id)
    storage.delete(att["stored_path"])
    record_audit(
        action="file_deleted",
        actor_id=user["id"],
        actor_name=user.get("displayName") or "",
        entity_type="attachment",
        entity_id=str(attachment_id),
        summary=(f"Datei '{att['original_filename']}' "
                 f"({_entity_label(att)} #{att.get('ticket_id')}) gelöscht"),
        details={"entity_type": att.get("entity_type") or att_db.ENTITY_TICKET,
                 "ticket_id": att.get("ticket_id"), "field_key": att.get("field_key"),
                 "filename": att["original_filename"],
                 "family_id": att.get("family_id"), "version": att.get("version")},
    )
    return {"ok": True}


# ── Admin-Übersicht (Speicherplatz + Suche) ──────────────────────────────────

def _require_admin(user: dict) -> None:
    if PERM_ADMIN not in (user.get("permissions", []) or []):
        raise api_error(403, ErrorCode.ADMIN_REQUIRED, "Admin-Rechte erforderlich")


@router.get("/settings/attachments/stats", response_model=DataResponse[AttachmentStats])
def attachments_stats(user: dict = Depends(get_current_user)):
    _require_admin(user)
    s = att_db.stats()
    return DataResponse(data=AttachmentStats(
        count=s["count"], total_bytes=s["total_bytes"], total_human=human_size(s["total_bytes"]),
    ))


@router.get("/settings/attachments", response_model=DataResponse[AttachmentListOut])
def attachments_list(
    user: dict = Depends(get_current_user),
    q: Optional[str] = None,
    # Welt-Filter; die Werte MÜSSEN att_db.ENTITY_TICKET / ENTITY_PROCESS_TICKET
    # entsprechen (Literal braucht echte Literale – ein Test hält beides synchron).
    # Alles andere → 422, damit ein Tippfehler nicht still „beide Welten" bedeutet.
    entity_type: Optional[Literal["ticket", "process_ticket"]] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    _require_admin(user)
    rows, total = att_db.list_all(q=q, entity_type=entity_type, limit=limit, offset=offset)
    return DataResponse(data=AttachmentListOut(items=[_to_admin_out(r) for r in rows], total=total))
