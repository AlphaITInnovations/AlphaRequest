from __future__ import annotations
import json
from typing import List, Optional, Dict, Any

from alpharequestmanager.utils.logger import logger
from alpharequestmanager.models.models import Ticket, RequestStatus, TicketPriority, TicketType
from alpharequestmanager.models import models
from alpharequestmanager.database import database as db


class TicketService:
    """
    Ticket-Service
    Enthält alle Geschäftslogiken:
    - CRUD
    - Assignees + Gruppen
    - Kommentare
    - Status
    - Ninja-Metadaten
    - Tracking (Sendeverfolgung)
    - Berechtigungen
    - Priority & Tags
    """

    # ---------------------------------------------------------
    # Ticket ERSTELLEN
    # ---------------------------------------------------------
    def create_ticket(
        self,
        title: str,
        ticket_type: models.TicketType,
        description: str,
        owner_id: str,
        owner_name: str,
        owner_info: str,
        ninja_metadata: Optional[Dict[str, Any]] = None,
        priority: TicketPriority = TicketPriority.medium,
        tags: Optional[List[str]] = None,
    ) -> int:

        ticket_id = db.insert_ticket(
            title=title,
            ticket_type=ticket_type,
            description=description,
            owner_id=owner_id,
            owner_name=owner_name,
            owner_info=owner_info,
            ninja_metadata=json.dumps(ninja_metadata) if ninja_metadata else None,
            priority=priority.value,
            tags=tags or [],
        )

        logger.info(f"Created ticket #{ticket_id}")
        return ticket_id

    # ---------------------------------------------------------
    # Ticket-LISTEN
    # ---------------------------------------------------------
    def list_all(self) -> List[Ticket]:
        return db.list_all_tickets()

    def list_by_owner(self, owner_id: str) -> List[Ticket]:
        return db.list_tickets_by_owner(owner_id)

    def list_by_assignee(self, user_id: str) -> List[Ticket]:
        return db.list_tickets_by_assignee(user_id)

    def list_pending(self) -> List[Ticket]:
        return db.list_pending_tickets()

    def list_by_assignee_group(self, group_id: str) -> List[Ticket]:
        return db.list_tickets_by_assignee_group(group_id)

    # ---------------------------------------------------------
    # Ticket-LESEN
    # ---------------------------------------------------------
    def get_ticket(self, ticket_id: int) -> Optional[Ticket]:
        return db.get_ticket(ticket_id)

    # ---------------------------------------------------------
    # Ticket-UPDATES
    # ---------------------------------------------------------
    def update_ticket(self, ticket_id: int, **fields) -> None:
        logger.info(f"Updating ticket #{ticket_id}: {fields}")
        db.update_ticket(ticket_id, **fields)

    def set_status(self, ticket_id: int, status: RequestStatus) -> None:
        logger.info(f"Setting status for ticket #{ticket_id}: {status.value}")
        db.update_ticket(ticket_id, status=status.value)

    def set_comment(self, ticket_id: int, text: str) -> None:
        db.update_ticket(ticket_id, comment=text)

    # ---------------------------------------------------------
    # Assignee Handling
    # ---------------------------------------------------------
    def set_assignee(self, ticket_id: int, user_id: str, user_name: str):
        logger.info(f"Assign ticket #{ticket_id} → {user_name} ({user_id})")
        return db.set_assignee(ticket_id, user_id, user_name)

    # Gruppen (neu!)
    def set_assignee_group(self, ticket_id: int, group_id: str, group_name: str):
        logger.info(f"Assign group for ticket #{ticket_id}: {group_name} ({group_id})")
        return db.set_assignee_group(ticket_id, group_id, group_name)

    # ---------------------------------------------------------
    # Priority & Tags
    # ---------------------------------------------------------
    def set_priority(self, ticket_id: int, priority: TicketPriority):
        logger.info(f"Set priority for ticket #{ticket_id}: {priority.value}")
        db.update_ticket(ticket_id, priority=priority.value)

    def set_tags(self, ticket_id: int, tags: List[str]):
        logger.info(f"Set tags for ticket #{ticket_id}: {tags}")
        db.update_ticket(ticket_id, tags=tags)

    def add_tag(self, ticket_id: int, tag: str):
        ticket = db.get_ticket(ticket_id)
        tags = ticket.tags or []
        if tag not in tags:
            tags.append(tag)
            db.update_ticket(ticket_id, tags=tags)

    def remove_tag(self, ticket_id: int, tag: str):
        ticket = db.get_ticket(ticket_id)
        tags = [t for t in (ticket.tags or []) if t != tag]
        db.update_ticket(ticket_id, tags=tags)

    # ---------------------------------------------------------
    # Ninja-Metadaten
    # ---------------------------------------------------------
    def set_ninja_metadata(self, ticket_id: int, ninja_ticket_id: int):
        logger.info(f"Link local #{ticket_id} -> Ninja #{ninja_ticket_id}")
        db.update_ticket_metadata(ticket_id, ninja_ticket_id=ninja_ticket_id)

    def get_ninja_metadata(self, ticket_id: int) -> Optional[Dict[str, Any]]:
        return db.get_ticket_metadata(ticket_id)

    # ---------------------------------------------------------
    # Tracking
    # ---------------------------------------------------------
    def set_sendeverfolgung(self, ticket_id: int, tracking_data: dict) -> None:
        logger.info(f"Set tracking info for ticket #{ticket_id}")
        db.set_sendeverfolgung(ticket_id, tracking_data)

    # ---------------------------------------------------------
    # Löschen
    # ---------------------------------------------------------
    def delete_ticket(self, ticket_id: int) -> bool:
        return db.delete_ticket(ticket_id)

    # ---------------------------------------------------------
    # Berechtigungen
    # ---------------------------------------------------------
    def can_delete(self, user: dict, ticket_id: int) -> bool:
        """Admins dürfen alles. Nutzer nur eigene Tickets."""
        if user.get("is_admin"):
            return True

        owned = db.list_tickets_by_owner(user["id"])
        return any(t.id == ticket_id for t in owned)

    def can_create(self, user_id: str, ticket_type: str) -> bool:
        perms = db.load_ticket_permissions()
        allowed = perms.get(ticket_type)

        # leere Liste = keine Einschränkung
        if not allowed:
            return True

        return user_id in allowed
