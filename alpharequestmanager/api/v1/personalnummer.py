from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from alpharequestmanager.core.dependencies import get_current_user
from alpharequestmanager.schemas.responses import DataResponse
from alpharequestmanager.services.personalnummer_generator import (
    next_personalnummer, reset_personalnummer,
)

router = APIRouter()


class PersonalnummerOut(BaseModel):
    personalnummer: int


class ResetOut(BaseModel):
    message: str


@router.get("/personalnummer/next", response_model=DataResponse[PersonalnummerOut])
def get_next_personalnummer(user: dict = Depends(get_current_user)):
    try:
        nr = next_personalnummer()
        return DataResponse(data=PersonalnummerOut(personalnummer=nr))
    except RuntimeError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except Exception:
        raise HTTPException(status_code=500, detail="Fehler beim Generieren")


@router.post("/personalnummer/reset", response_model=DataResponse[ResetOut])
def reset_personalnummer_endpoint(user: dict = Depends(get_current_user)):
    if not user.get("is_admin"):
        raise HTTPException(403, "Admin-Rechte erforderlich")
    try:
        reset_personalnummer()
        return DataResponse(data=ResetOut(message="Personalnummer wurde zurückgesetzt"))
    except Exception:
        raise HTTPException(500, "Fehler beim Zurücksetzen")