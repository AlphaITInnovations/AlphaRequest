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
    id: int
    title: str
    ticket_type: TicketType
    description: str
    owner_id: str
    owner_name: str
    comment: str
    status: RequestStatus
    created_at: datetime

    owner_info: Optional[str] = None
    ninja_metadata: Optional[str] = None

    assignee_id: Optional[str] = None
    assignee_name: Optional[str] = None
    assignee_history: Optional[str] = None

    assignee_group_id: Optional[str] = None
    assignee_group_name: Optional[str] = None

    priority: TicketPriority = TicketPriority.medium
    tags: List[str] = field(default_factory=list)

    updated_at: Optional[datetime] = None


    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "Ticket":

        def parse_json(val, default):
            if not val:
                return default
            try:
                return json.loads(val)
            except Exception:
                return default

        # created_at
        created_raw = row.get("created_at")
        try:
            created_at = datetime.fromisoformat(created_raw) if created_raw else datetime.utcnow()
        except Exception:
            created_at = datetime.utcnow()

        # updated_at
        updated_raw = row.get("updated_at")
        try:
            updated_at = datetime.fromisoformat(updated_raw) if updated_raw else None
        except Exception:
            updated_at = None

        # priority field (can be None or missing)
        raw_prio = row.get("priority")
        priority = TicketPriority(raw_prio) if raw_prio in TicketPriority.__members__.values() else TicketPriority.medium

        # tags is JSON list
        tags = parse_json(row.get("tags"), default=[])

        return cls(
            id=int(row["id"]),
            title=row.get("title", ""),
            ticket_type=row.get("ticket_type", ""),
            description=row.get("description", ""),
            owner_id=row.get("owner_id", ""),
            owner_name=row.get("owner_name", ""),
            comment=row.get("comment") or "",
            status=RequestStatus(row.get("status", "pending")),
            created_at=created_at,

            owner_info=row.get("owner_info"),
            ninja_metadata=row.get("ninja_metadata"),

            assignee_id=row.get("assignee_id"),
            assignee_name=row.get("assignee_name"),
            assignee_history=row.get("assignee_history"),

            assignee_group_id=row.get("assignee_group_id"),
            assignee_group_name=row.get("assignee_group_name"),

            priority=priority,
            tags=tags,
            updated_at=updated_at,
        )


    @property
    def metadata(self) -> Dict[str, Any]:
        """Parsed NinjaOne metadata"""
        return self._safe_json(self.ninja_metadata, {})

    @property
    def ninja_ticket_id(self) -> Optional[int]:
        return self.metadata.get("ninja_ticket_id")

    @property
    def synced_at(self) -> Optional[datetime]:
        ts = self.metadata.get("synced_at")
        if not ts:
            return None
        try:
            return datetime.fromisoformat(ts)
        except Exception:
            return None

    @property
    def owner_info_parsed(self) -> Dict[str, Any]:
        return self._safe_json(self.owner_info, {})

    @property
    def assignee_history_parsed(self) -> List[Dict[str, Any]]:
        return self._safe_json(self.assignee_history, [])


    @staticmethod
    def _safe_json(val: Optional[str], default: Any):
        if not val:
            return default
        try:
            return json.loads(val)
        except Exception:
            return default
