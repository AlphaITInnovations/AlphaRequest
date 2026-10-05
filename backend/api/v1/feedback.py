import base64
from fastapi import APIRouter, Depends, File, Form, UploadFile
from typing import Optional

from backend.core.dependencies import get_current_user
from backend.utils.config import config
from backend.utils.logger import logger
from backend.utils.files import safe_filename
from backend.services.microsoft_mail import (
    EmailAttachment, brand_logo_attachment, render_corporate_email, send_mail_app_only,
)
from backend.schemas.responses import DataResponse, ErrorCode, api_error

router = APIRouter()

#: Graph deckelt die GESAMTE Nachricht bei ~4 MB; base64 bläht die Rohgröße um 4/3.
#: Deshalb die KODIERTE Gesamtgröße messen (wie bei der Freigabe-Mail) und konservativ
#: darunter bleiben – sonst scheitert der Versand still.
_ATTACH_TOTAL_B64_LIMIT = int(3.5 * 1024 * 1024)
_ATTACH_MAX_FILES = 10


@router.post("/feedback")
async def submit_feedback(
    message: str = Form(...),
    page: Optional[str] = Form(None),
    files: list[UploadFile] = File(default=[]),
    user: dict = Depends(get_current_user),
):
    """Sendet einen Fehlerbericht / Feedback per Mail an die konfigurierte Adresse.
    Optionale Anlagen (z. B. Screenshots) werden der Mail beigefügt (multipart)."""
    text = (message or "").strip()
    if not text:
        raise api_error(400, ErrorCode.INVALID_DESCRIPTION, "Bitte eine Beschreibung angeben")
    if not config.BUG_REPORT_MAIL:
        raise api_error(503, "FEEDBACK_NO_RECIPIENT",
                        "Keine Empfänger:in für Fehlerberichte konfiguriert (BUG_REPORT_MAIL)")

    files = [f for f in (files or []) if f and f.filename]
    if len(files) > _ATTACH_MAX_FILES:
        raise api_error(400, "FEEDBACK_TOO_MANY_FILES",
                        f"Höchstens {_ATTACH_MAX_FILES} Anlagen je Bericht")

    user_attachments: list[EmailAttachment] = []
    total_b64 = 0
    for f in files:
        try:
            raw = await f.read()
        except Exception:
            logger.exception("Feedback-Anlage „%s“ nicht lesbar", f.filename)
            raise api_error(400, "FEEDBACK_ATTACH_UNREADABLE",
                            f"Anlage „{f.filename}“ konnte nicht gelesen werden")
        if not raw:
            continue
        b64 = base64.b64encode(raw).decode("utf-8")
        total_b64 += len(b64)
        if total_b64 > _ATTACH_TOTAL_B64_LIMIT:
            raise api_error(413, "FEEDBACK_ATTACH_TOO_LARGE",
                            "Die Anlagen sind insgesamt zu groß (max. ca. 2,5 MB). Bitte "
                            "kleinere oder weniger Dateien anhängen.")
        user_attachments.append(EmailAttachment(
            filename=safe_filename(f.filename),
            content_bytes_b64=b64,
            content_type=f.content_type or "application/octet-stream"))

    reporter      = user.get("displayName") or user.get("id") or "Unbekannt"
    reporter_mail = user.get("mail") or user.get("email")
    page_s        = (page or "").strip() or "—"

    anlagen_zeile = (f"Anlagen: {len(user_attachments)}\n" if user_attachments else "")
    intro = (
        f"Neuer Fehlerbericht / Feedback aus AlphaRequest:\n\n"
        f"Von: {reporter}" + (f" ({reporter_mail})" if reporter_mail else "") + "\n"
        f"Seite: {page_s}\n"
        f"{anlagen_zeile}\n"
        f"Beschreibung:\n{text}"
    )

    try:
        send_mail_app_only(
            sender_upn_or_id="alpharequest@alpha-it-innovations.org",
            subject=f"[Fehlerbericht] {reporter}",
            body=render_corporate_email(
                subject="Fehlerbericht / Feedback",
                headline="AlphaRequest – Fehlerbericht",
                intro=intro,
                info_box_url=config.FRONTEND_URL,
                content="",
            ),
            to_recipients=[config.BUG_REPORT_MAIL],
            reply_to=[reporter_mail] if reporter_mail else None,
            body_type="HTML",
            attachments=[a for a in [brand_logo_attachment(), *user_attachments] if a],
        )
    except Exception as e:
        logger.error(f"Fehlerbericht-Mail fehlgeschlagen: {e}")
        raise api_error(502, "MAIL_FAILED", "Fehlerbericht konnte nicht gesendet werden")

    return DataResponse(data={"ok": True})
