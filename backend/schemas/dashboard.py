from pydantic import BaseModel


class DepartmentTicket(BaseModel):
    id: int
    title: str
    type_key: str
    created_at: str
    status: str
    priority: str


class DepartmentGroup(BaseModel):
    group_id: str
    group_name: str
    tickets: list[DepartmentTicket]


class DashboardTicket(BaseModel):
    id: int
    title: str
    type_key: str
    status: str
    priority: str
    created_at: str
    assignee_group_id: str | None = None
    assignee_group_name: str | None = None


class DashboardResponse(BaseModel):
    orders: list[DashboardTicket]
    group_orders: list[DashboardTicket]      # ← NEU
    created_orders: list[DashboardTicket]
    department_requests: list[DepartmentGroup]
    allowed_ticket_types: list[str]