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


class AttachmentAdminOut(AttachmentOut):
    """Zeile der Admin-Übersicht.

    Dort stehen Anhänge BEIDER Welten in einer Liste, deshalb ist `entity_type`
    Pflicht: die Oberfläche verlinkt danach (Alt-Ticket vs. Prozess-Auftrag – die
    IDs überschneiden sich!). Ein Default wäre hier gefährlich, weil eine fehlende
    Angabe still als Alt-Ticket durchgehen und auf ein fremdes Ticket zeigen würde.
    `ticket_title` löst die DB-Schicht je Welt auf (NULL = Entität gelöscht/unbekannt)."""
    entity_type: str
    field_key: Optional[str] = None
    ticket_title: Optional[str] = None


class AttachmentListOut(BaseModel):
    items: list[AttachmentAdminOut]
    total: int


class AttachmentStats(BaseModel):
    count: int
    total_bytes: int
    total_human: str
