import time
from alpharequestmanager.database import database
from alpharequestmanager.services import ninja_api
from alpharequestmanager.services.ninja_api import get_ticket
from alpharequestmanager.utils.logger import logger
from alpharequestmanager.utils.config import config
from alpharequestmanager.models.models import Ticket


def poll_ninja_changes():
    """
    Pollt alle Tickets mit 'ninja_ticket_id' und synchronisiert Status-Änderungen zurück ins Self-Service-Portal.
    """
    tickets = database.list_pending_tickets()
    for t in tickets:

        ninja_ticket = get_ticket(t.ninja_ticket_id)
        status_id = ninja_ticket.get("status", {}).get("statusId")

        if status_id == 5000:
            comment = ninja_api.get_alpha_request_comment(ninja_ticket)
            database.update_ticket(int(t.id), comment=comment)
            status = ninja_api.is_alpha_request_approved(t.ninja_ticket_id)
            sendeverfolgung = ninja_api.get_alpha_request_sendeverfolgung(ninja_ticket)
            database.set_sendeverfolgung(int(t.id), sendeverfolgung=sendeverfolgung)
            if status:
                logger.info("Ticket has been approved: " + str(t.ninja_ticket_id))
                database.update_ticket(int(t.id), status="approved")
            elif not status:
                logger.info("Ticket has been rejected: " + str(t.ninja_ticket_id))
                database.update_ticket(int(t.id), status="rejected")


def start_polling():
    logger.info("Starte Ninja-Sync Polling...")
    while True:
        poll_ninja_changes()
        logger.info("Successfull Ninja-Sync Polling...")
        time.sleep(config.NINJA_POLL_INTERVAL)



def poll_ticket_changes(t: Ticket):
    pass