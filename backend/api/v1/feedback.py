from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional

from backend.core.dependencies import get_current_user
from backend.utils.config import config
from backend.utils.logger import logger
from backend.services.microsoft_mail import send_mail_app_only, render_corporate_email
from backend.schemas.responses import DataResponse, ErrorCode, api_error

router = APIRouter()


class FeedbackRequest(BaseModel):
    message: str
    page: Optional[str] = None


@router.post("/feedback")
def submit_feedback(data: FeedbackRequest, user: dict = Depends(get_current_user)):
    """Sendet einen Fehlerbericht / Feedback per Mail an die konfigurierte Adresse."""
    message = (data.message or "").strip()
    if not message:
        raise api_error(400, ErrorCode.INVALID_DESCRIPTION, "Bitte eine Beschreibung angeben")
    if not config.BUG_REPORT_MAIL:
        raise api_error(503, "FEEDBACK_NO_RECIPIENT",
                        "Kein Empfänger für Fehlerberichte konfiguriert (BUG_REPORT_MAIL)")

    reporter      = user.get("displayName") or user.get("id") or "Unbekannt"
    reporter_mail = user.get("mail") or user.get("email")
    page          = (data.page or "").strip() or "—"

    intro = (
        f"Neuer Fehlerbericht / Feedback aus AlphaRequest:\n\n"
        f"Von: {reporter}" + (f" ({reporter_mail})" if reporter_mail else "") + "\n"
        f"Seite: {page}\n\n"
        f"Beschreibung:\n{message}"
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
        )
    except Exception as e:
        logger.error(f"Fehlerbericht-Mail fehlgeschlagen: {e}")
        raise api_error(502, "MAIL_FAILED", "Fehlerbericht konnte nicht gesendet werden")

    return DataResponse(data={"ok": True})
