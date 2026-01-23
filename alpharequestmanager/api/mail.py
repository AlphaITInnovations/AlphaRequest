from fastapi import APIRouter, HTTPException, Depends, Body
from pydantic import BaseModel, EmailStr, Field
from alpharequestmanager.core.dependencies import get_current_user
from alpharequestmanager.utils.logger import logger
from alpharequestmanager.services.microsoft_mail import send_test_mail

router = APIRouter(prefix="/api", tags=["mail"])


def require_admin(user):
    if not user.get("is_admin"):
        raise HTTPException(403, "Admin privileges required")


class TestMailPayload(BaseModel):
    to: EmailStr = Field(..., description="Empfängeradresse für die Testmail")


@router.post("/admin/test-mail")
async def api_send_test_mail(
    payload: TestMailPayload = Body(...),
    user=Depends(get_current_user),
):
    require_admin(user)

    try:
        send_test_mail(str(payload.to))
        logger.info(f"Testmail sent to {payload.to}")
        return {"ok": True}
    except Exception as e:
        logger.exception("Failed to send test mail")
        raise HTTPException(500, f"Could not send test mail: {str(e)}")
