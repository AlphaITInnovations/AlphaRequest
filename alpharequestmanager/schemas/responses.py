from typing import Generic, TypeVar, Optional
from pydantic import BaseModel

T = TypeVar("T")


class Meta(BaseModel):
    total: int
    limit: int
    offset: int


class DataResponse(BaseModel, Generic[T]):
    """Einzelne Ressource: { data: T }"""
    data: T


class ListResponse(BaseModel, Generic[T]):
    """Liste: { data: [...], meta: {...} }"""
    data: list[T]
    meta: Meta


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail


# ── Hilfsfunktion für konsistente Fehler ──────────────────────────────────────
from fastapi import HTTPException

def api_error(status: int, code: str, message: str) -> HTTPException:
    """
    Wirft einen HTTPException mit strukturiertem Body.
    Verwendung: raise api_error(404, "TICKET_NOT_FOUND", "Ticket nicht gefunden")
    """
    return HTTPException(
        status_code=status,
        detail={"code": code, "message": message}
    )


# ── Error-Codes als Konstanten (kein Magic-String mehr) ───────────────────────
class ErrorCode:
    TICKET_NOT_FOUND       = "TICKET_NOT_FOUND"
    TICKET_FORBIDDEN       = "TICKET_FORBIDDEN"
    INVALID_ASSIGNEE       = "INVALID_ASSIGNEE"
    INVALID_DESCRIPTION    = "INVALID_DESCRIPTION"
    INVALID_STATUS         = "INVALID_STATUS"
    DEPARTMENT_FORBIDDEN   = "DEPARTMENT_FORBIDDEN"
    PERMISSION_DENIED      = "PERMISSION_DENIED"
    ADMIN_REQUIRED         = "ADMIN_REQUIRED"