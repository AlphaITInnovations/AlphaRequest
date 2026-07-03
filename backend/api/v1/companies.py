from fastapi import APIRouter, Depends
from pydantic import BaseModel
from backend.core.dependencies import get_current_user
from backend.database.settings import get_companies
from backend.schemas.responses import DataResponse

router = APIRouter()


class CompaniesOut(BaseModel):
    companies: list[str]
    count: int


@router.get("/companies", response_model=DataResponse[CompaniesOut])
def get_companies_endpoint(user: dict = Depends(get_current_user)):
    """Firmenliste (Namen) für die Ticket-Formulare. Das Anlegen/Bearbeiten von
    Firmen inkl. Personalnummern-Bereichen läuft admin-geschützt über
    PUT /settings/companies (siehe settings.py)."""
    items = get_companies()
    return DataResponse(data=CompaniesOut(companies=items, count=len(items)))