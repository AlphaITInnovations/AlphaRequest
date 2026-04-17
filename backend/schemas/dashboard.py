from pydantic import BaseModel
from typing import Optional
from backend.models.models import TicketType


class DashboardTicket(BaseModel):
    id: int
    title: str
    type_key: str
    status: str
    priority: str
    created_at: str


class DepartmentTicket(BaseModel):
    id: int
    title: str
    type_key: str
    created_at: str


class DepartmentGroup(BaseModel):
    group_id: str
    group_name: str
    tickets: list[DepartmentTicket]


class DashboardResponse(BaseModel):
    orders: list[DashboardTicket]
    created_orders: list[DashboardTicket]
    department_requests: list[DepartmentGroup]
    allowed_ticket_types: list[str]