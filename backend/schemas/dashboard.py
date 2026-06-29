from pydantic import BaseModel


class DepartmentTicket(BaseModel):
    id: int
    title: str
    type_key: str
    created_at: str
    status: str
    priority: str
    phase_type: str
    phase_label: str
    # group_id der Reviewing-Abteilung (für ?department=); None in Assignment-Phase.
    department_id: str | None = None


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


class DashboardResponse(BaseModel):
    orders: list[DashboardTicket]
    # Tickets, die der Nutzer beobachtet (Ersteller ist automatisch Beobachter).
    watched_orders: list[DashboardTicket]
    # Einheitliche „Meine Abteilung"-Liste (Assignment + Durchführung, dedupliziert).
    department_board: list[DepartmentGroup]
    allowed_ticket_types: list[str]


class InvolvedTicket(DashboardTicket):
    # Rollen des Nutzers an diesem Ticket:
    # ersteller | beobachter | zustaendig | bearbeiter | fachabteilung
    roles: list[str] = []


class InvolvedResponse(BaseModel):
    # Eine Seite der Tickets, bei denen der Nutzer jemals beteiligt war.
    involved: list[InvolvedTicket]
    # Gesamtzahl der Treffer (nach Filter) – für das Paging im Frontend.
    total: int = 0