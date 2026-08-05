from typing import Optional

from pydantic import BaseModel


class AttachmentOut(BaseModel):
    id: int
    ticket_id: Optional[int] = None
    phase_key: Optional[str] = None
    family_id: str
    version: int
    is_current: bool
    original_filename: str
    content_type: Optional[str] = None
    size_bytes: int
    size_human: str
    sha256: Optional[str] = None
    uploaded_by_id: Optional[str] = None
    uploaded_by_name: Optional[str] = None
    uploaded_at: Optional[str] = None


class AttachmentListOut(BaseModel):
    items: list[AttachmentOut]
    total: int


class AttachmentStats(BaseModel):
    count: int
    total_bytes: int
    total_human: str
