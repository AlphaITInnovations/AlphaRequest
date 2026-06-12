from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from backend.models.models import (
    Ticket, TicketType, RequestStatus, TicketPriority
)


class WatcherOut(BaseModel):
    id: str
    name: Optional[str] = None


class TicketOut(BaseModel):
    id: int
    title: str
    ticket_type: TicketType
    description: str
    owner_id: str
    owner_name: str
    comment: str
    status: RequestStatus
    priority: TicketPriority
    created_at: datetime
    updated_at: Optional[datetime] = None
    assignee_id: Optional[str] = None
    assignee_name: Optional[str] = None
    accountable_id: Optional[str] = None
    accountable_name: Optional[str] = None
    assignee_group_id: Optional[str] = None
    assignee_group_name: Optional[str] = None
    workflow_state: Optional[dict] = None
    # Nur im Detail-Endpoint befüllt (Listen vermeiden so N+1-Queries).
    watchers: List[WatcherOut] = []

    model_config = {"from_attributes": True}

    @classmethod
    def from_ticket(cls, t: Ticket, watchers: Optional[list] = None) -> "TicketOut":
        return cls(
            id=t.id,
            title=t.title,
            ticket_type=t.ticket_type,
            description=t.description,
            owner_id=t.owner_id,
            owner_name=t.owner_name,
            comment=t.comment,
            status=t.status,
            priority=t.priority,
            created_at=t.created_at,
            updated_at=t.updated_at,
            assignee_id=t.assignee_id,
            assignee_name=t.assignee_name,
            accountable_id=t.accountable_id,
            accountable_name=t.accountable_name,
            assignee_group_id=t.assignee_group_id,
            assignee_group_name=t.assignee_group_name,
            workflow_state=t.workflow_state_parsed or None,
            watchers=[WatcherOut(**w) for w in (watchers or [])],
        )


class TicketListResponse(BaseModel):
    items: list[TicketOut]
    total: int


class TicketCreateRequest(BaseModel):
    ticket_type: TicketType
    description: str
    assignee_id: str
    assignee_name: str
    accountable_id: str
    accountable_name: str
    comment: str = ""
    priority: TicketPriority = TicketPriority.medium
    # Beobachter (inkl. Ersteller). Leer = Backend trägt nur den Ersteller ein.
    watchers: List[WatcherOut] = []


class BasisTicketCreateRequest(BaseModel):
    title: str
    description: str
    assignee_id: str
    assignee_name: str
    accountable_id: str
    accountable_name: str
    comment: Optional[str] = ""
    priority: TicketPriority = TicketPriority.medium
    watchers: List[WatcherOut] = []


class TicketUpdateRequest(BaseModel):
    description: Optional[str] = None
    comment: Optional[str] = None
    assignee_id: Optional[str] = None
    assignee_name: Optional[str] = None
    accountable_id: Optional[str] = None
    accountable_name: Optional[str] = None
    priority: Optional[TicketPriority] = None
    action: str = "save"


class UserOut(BaseModel):
    id: str
    displayName: str
    mail: Optional[str] = None
    permissions: List[str] = []