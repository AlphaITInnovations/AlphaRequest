from typing import Generic, TypeVar
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


class FieldError(BaseModel):
    """Ein einzelner Feld-Fehler (Body-/Schema-Validierung)."""
    path: str
    code: str
    message: str


class ErrorDetail(BaseModel):
    code: str
    message: str
    fields: list[FieldError] | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail


# ── Hilfsfunktion für konsistente Fehler ──────────────────────────────────────
from fastapi import HTTPException

def api_error(status: int, code: str, message: str,
              fields: list[dict] | None = None) -> HTTPException:
    """
    Wirft einen HTTPException mit strukturiertem Body. Der Exception-Handler in
    main.py normalisiert `detail` in den einheitlichen Envelope { error: {...} }.
    Verwendung: raise api_error(404, "TICKET_NOT_FOUND", "Ticket nicht gefunden")
    """
    detail: dict = {"code": code, "message": message}
    if fields:
        detail["fields"] = fields
    return HTTPException(status_code=status, detail=detail)


# ── Error-Codes als Konstanten (kein Magic-String mehr) ───────────────────────
class ErrorCode:
    TICKET_NOT_FOUND       = "TICKET_NOT_FOUND"
    TICKET_FORBIDDEN       = "TICKET_FORBIDDEN"
    INVALID_ASSIGNEE       = "INVALID_ASSIGNEE"
    INVALID_DESCRIPTION    = "INVALID_DESCRIPTION"
    INVALID_STATUS         = "INVALID_STATUS"
    INVALID_WATCHER        = "INVALID_WATCHER"
    DEPARTMENT_FORBIDDEN   = "DEPARTMENT_FORBIDDEN"
    PERMISSION_DENIED      = "PERMISSION_DENIED"
    ADMIN_REQUIRED         = "ADMIN_REQUIRED"
    TICKET_LOCKED          = "TICKET_LOCKED"
    # Validierung / generisch
    VALIDATION_FAILED      = "VALIDATION_FAILED"
    HTTP_ERROR             = "HTTP_ERROR"
    # Prozess-Definitionen
    PROCESS_NOT_FOUND         = "PROCESS_NOT_FOUND"
    PROCESS_KEY_EXISTS        = "PROCESS_KEY_EXISTS"
    PROCESS_INVALID_STATE     = "PROCESS_INVALID_STATE"
    PROCESS_VERSION_CONFLICT  = "PROCESS_VERSION_CONFLICT"
    PROCESS_VERSION_IN_USE    = "PROCESS_VERSION_IN_USE"