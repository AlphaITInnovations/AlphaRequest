from fastapi import APIRouter, Depends, HTTPException, status, Request

from alpharequestmanager.core.dependencies import get_current_user
from alpharequestmanager.services.personalnummer_generator import (
    next_personalnummer, reset_personalnummer,
)

router = APIRouter()

@router.get("/api/personalnummer/next", status_code=status.HTTP_200_OK)
async def get_next_personalnummer(
    request: Request,
    user: dict = Depends(get_current_user),
):
    try:
        nr = next_personalnummer()
        return {
            "success": True,
            "personalnummer": nr,
        }

    except RuntimeError as e:
        # z. B. END überschritten
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        )

    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Fehler beim Generieren der Personalnummer",
        )


@router.post("/api/personalnummer/reset", status_code=status.HTTP_200_OK)
async def reset_personalnummer_endpoint(
    request: Request,
    user: dict = Depends(get_current_user),
):
    if not user.get("is_admin", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin-Rechte erforderlich",
        )

    try:
        reset_personalnummer()
        return {
            "success": True,
            "message": "Personalnummer wurde zurückgesetzt",
        }

    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Fehler beim Zurücksetzen der Personalnummer",
        )
