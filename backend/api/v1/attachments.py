"""
Datei-Anhänge für Aufträge (Grundlage – noch nicht an konkrete Phasen gebunden).

Blobs liegen auf dem Dateisystem (attachment_storage), Metadaten in der DB
(database.attachments). Upload/Download sind an den Ticket-Zugriff gekoppelt;
die Admin-Übersicht (Speicherplatz/Suche) liegt unter /settings/attachments.
Jeder Upload/jede Löschung wird im Audit-Log festgehalten; Versionen bleiben
über die `family_id` nachvollziehbar.
"""
from typing import Optional

from fastapi import APIRouter, Depends, UploadFile, File, Form, Query
from fastapi.responses import FileResponse

from backend.core.dependencies import get_current_user
from backend.database import tickets as database
from backend.database import attachments as att_db
from backend.database.audit_log import record_audit
from backend.database.users import PERM_ADMIN
from backend.services import attachment_storage as storage
from backend.schemas.attachment import AttachmentOut, AttachmentListOut, AttachmentStats
from backend.schemas.responses import DataResponse, api_error, ErrorCode
from backend.utils.config import config
from backend.utils.files import safe_filename, human_size
from backend.utils.logger import logger
# Zugriffs-Helfer wiederverwenden (kein Zyklus: tickets importiert attachments nicht).
from backend.api.v1.tickets import _get_ticket_or_404, _assert_ticket_access

router = APIRouter()


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


@router.get("/attachments/{attachment_id}/download")
def download_attachment(attachment_id: int, user: dict = Depends(get_current_user)):
    att = att_db.get_attachment(attachment_id)
    if not att or att.get("deleted_at"):
        raise api_error(404, "NOT_FOUND", "Anhang nicht gefunden")
    # Download an den Ticket-Zugriff koppeln (Admins über den globalen Zugriff).
    if att.get("ticket_id"):
        ticket = database.get_ticket(att["ticket_id"])
        if ticket:
            _assert_ticket_access(ticket, user)
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
        summary=f"Datei '{att['original_filename']}' (Ticket #{att.get('ticket_id')}) gelöscht",
        details={"ticket_id": att.get("ticket_id"), "filename": att["original_filename"],
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
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    _require_admin(user)
    rows, total = att_db.list_all(q=q, limit=limit, offset=offset)
    return DataResponse(data=AttachmentListOut(items=[_to_out(r) for r in rows], total=total))
