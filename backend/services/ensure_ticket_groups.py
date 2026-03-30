from backend.database import database as db
from backend.models.models import TicketType
from backend.utils.logger import logger
import uuid


def ensure_ticket_groups():
    """
    Stellt sicher, dass für jeden TicketType genau eine Gruppe existiert.
    Gruppenname == TicketType.value
    """

    groups = db.get_groups()
    existing_names = {g["name"] for g in groups}

    created = 0

    for ticket_type in TicketType:
        group_name = ticket_type.value

        if group_name in existing_names:
            continue

        new_group = {
            "id": uuid.uuid4().hex,
            "name": group_name,
            "members": []
        }

        groups.append(new_group)
        created += 1
        logger.info(f"📦 Fachabteilung erstellt: {group_name}")

    if created:
        db.save_groups(groups)
        logger.info(f"✅ {created} Ticket-Gruppen initialisiert")
    else:
        logger.info("ℹ️ Alle Ticket-Gruppen bereits vorhanden")
