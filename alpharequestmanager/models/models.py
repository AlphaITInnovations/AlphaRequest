import json
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
from typing import Optional, List, Dict, Any


class RequestStatus(str, Enum):
    in_progress = "in_progress"
    in_request  = "in_request"
    archived    = "archived"
    rejected    = "rejected"



class TicketType(str, Enum):
    hardware = "hardware"
    niederlassung_anmelden = "niederlassung-anmelden"
    niederlassung_schliessen = "niederlassung-schliessen"
    niederlassung_umzug = "niederlassung-umzug"
    zugang_beantragen = "zugang-beantragen"
    zugang_sperren = "zugang-sperren"



class TicketPriority(str, Enum):
    low      = "low"
    medium   = "medium"
    high     = "high"
    critical = "critical"



@dataclass
class Ticket:
    # ================= CORE =================
    id: int
    title: str
    ticket_type: TicketType
    description: str

    owner_id: str
    owner_name: str
    owner_info: Optional[str]

    status: RequestStatus
    priority: TicketPriority = TicketPriority.medium

    # ================= CURRENT ASSIGNMENT =================
    assignee_id: Optional[str] = None
    assignee_name: Optional[str] = None

    accountable_id: Optional[str] = None
    accountable_name: Optional[str] = None

    supervisor_id: Optional[str] = None
    supervisor_name: Optional[str] = None

    assignee_group_id: Optional[str] = None
    assignee_group_name: Optional[str] = None

    # ================= HISTORY =================
    # JSON-Array als String
    assignment_history: str = "[]"

    # ================= META =================
    comment: str = ""
    ninja_metadata: Optional[str] = None
    workflow_state: Optional[str] = None

    #tags: List[str] = field(default_factory=list)

    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None

    # ------------------------------------------------------------------
    # FACTORY
    # ------------------------------------------------------------------
    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "Ticket":

        def parse_json(val, default):
            if not val:
                return default
            try:
                return json.loads(val)
            except Exception:
                return default

        def parse_dt(val):
            if not val:
                return None
            try:
                return datetime.fromisoformat(val)
            except Exception:
                return None

        # priority
        raw_prio = row.get("priority")
        try:
            priority = TicketPriority(raw_prio)
        except Exception:
            priority = TicketPriority.medium

        return cls(
            id=int(row["id"]),
            title=row.get("title", ""),
            ticket_type=TicketType(row.get("ticket_type")),
            description=row.get("description", ""),

            owner_id=row.get("owner_id", ""),
            owner_name=row.get("owner_name", ""),
            owner_info=row.get("owner_info"),

            status=RequestStatus(row.get("status")),
            priority=priority,

            assignee_id=row.get("assignee_id"),
            assignee_name=row.get("assignee_name"),

            accountable_id=row.get("accountable_id"),
            accountable_name=row.get("accountable_name"),

            supervisor_id=row.get("supervisor_id"),
            supervisor_name=row.get("supervisor_name"),

            assignee_group_id=row.get("assignee_group_id"),
            assignee_group_name=row.get("assignee_group_name"),

            assignment_history=row.get("assignment_history") or "[]",

            comment=row.get("comment") or "",
            ninja_metadata=row.get("ninja_metadata"),
            workflow_state=row.get("workflow_state"),

            #tags=parse_json(row.get("tags"), []),

            created_at=parse_dt(row.get("created_at")) or datetime.utcnow(),
            updated_at=parse_dt(row.get("updated_at")),
        )

    # ------------------------------------------------------------------
    # PARSED HELPERS
    # ------------------------------------------------------------------
    @staticmethod
    def _safe_json(val: Optional[str], default: Any):
        if not val:
            return default
        try:
            return json.loads(val)
        except Exception:
            return default

    @property
    def assignment_history_parsed(self) -> List[Dict[str, Any]]:
        """
        List of history events:
        [
          {
            timestamp: str,
            assignee?: {id, name},
            supervisor?: {id, name},
            group?: {id, name},
            action?: str
          }
        ]
        """
        return self._safe_json(self.assignment_history, [])

    @property
    def owner_info_parsed(self) -> Dict[str, Any]:
        return self._safe_json(self.owner_info, {})

    @property
    def metadata(self) -> Dict[str, Any]:
        return self._safe_json(self.ninja_metadata, {})

    @property
    def ninja_ticket_id(self) -> Optional[int]:
        return self.metadata.get("ninja_ticket_id")

    @property
    def synced_at(self) -> Optional[datetime]:
        ts = self.metadata.get("synced_at")
        try:
            return datetime.fromisoformat(ts) if ts else None
        except Exception:
            return None

    @property
    def workflow_state_parsed(self) -> dict:
        return self._safe_json(self.workflow_state, {})
