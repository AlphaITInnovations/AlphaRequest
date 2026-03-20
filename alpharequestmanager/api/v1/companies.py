from fastapi import APIRouter, Depends, HTTPException, Body
from pydantic import BaseModel
from alpharequestmanager.core.dependencies import get_current_user
from alpharequestmanager.database.settings import get_companies, set_companies
from alpharequestmanager.schemas.responses import DataResponse
from alpharequestmanager.utils.logger import logger

router = APIRouter()


class CompaniesOut(BaseModel):
    companies: list[str]
    count: int


class CompaniesIn(BaseModel):
    companies: list[str]


def _normalize_companies(items: list[str]) -> list[str]:
    seen = set()
    result = []
    for item in items:
        v = item.strip()
        if v and v not in seen:
            seen.add(v)
            result.append(v)
    return result


@router.get("/companies", response_model=DataResponse[CompaniesOut])
def get_companies_endpoint(user: dict = Depends(get_current_user)):
    items = get_companies()
    return DataResponse(data=CompaniesOut(companies=items, count=len(items)))


@router.put("/companies", response_model=DataResponse[CompaniesOut])
def set_companies_endpoint(
    payload: CompaniesIn,
    user: dict = Depends(get_current_user),
):
    if not user.get("is_admin"):
        raise HTTPException(403, "Admin-Rechte erforderlich")

    normalized = _normalize_companies(payload.companies)
    if not normalized:
        raise HTTPException(422, "Mindestens eine Firma erforderlich")

    try:
        set_companies(normalized)
    except Exception as e:
        logger.exception("Failed to update companies: %s", e)
        raise HTTPException(500, "Fehler beim Speichern")

    items = get_companies()
    return DataResponse(data=CompaniesOut(companies=items, count=len(items)))