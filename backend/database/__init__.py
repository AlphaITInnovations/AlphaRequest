from backend.database.connection import get_connection, _exec
from backend.database.tickets import DDL_TICKETS
from backend.database.settings import DDL_SETTINGS
from backend.database.users import USERS_DDL  # noqa: F401
from backend.database.ticket_watchers import TICKET_WATCHERS_DDL, backfill_owner_watchers
from backend.utils.logger import logger


def init_db():
    logger.info("Initializing database (MariaDB)")
    conn = get_connection()
    try:
        _exec(conn, DDL_TICKETS)
        _exec(conn, DDL_SETTINGS)
        _exec(conn, USERS_DDL)
        _exec(conn, TICKET_WATCHERS_DDL)
        conn.commit()
        logger.info("All tables ready")
    finally:
        conn.close()

    # Bestehende Tickets: Ersteller als Beobachter nachtragen (idempotent)
    try:
        backfill_owner_watchers()
    except Exception as e:
        logger.warning(f"Watcher-Backfill übersprungen: {e}")

    # Bestehende Tickets: Zuständigkeit der Bearbeitungsphase in den Workflow
    # migrieren (aus den Alt-Spalten assignee_*), damit diese nicht mehr nötig sind.
    try:
        from backend.services.workflow_state import backfill_phase_responsibility
        backfill_phase_responsibility()
    except Exception as e:
        logger.warning(f"Responsibility-Backfill übersprungen: {e}")

    # Workflow-Pflichtgruppen (Fachabteilungen) sicherstellen: fehlende werden
    # leer angelegt, damit jeder Workflow eine zuständige Gruppe auflösen kann.
    try:
        from backend.services.workflow_state import required_group_names, assign_group_names
        from backend.database.groups import ensure_required_groups
        created = ensure_required_groups(required_group_names(), hidden_names=assign_group_names())
        if created:
            logger.info("Fehlende Pflichtgruppen angelegt: %s", ", ".join(created))
    except Exception as e:
        logger.warning(f"Pflichtgruppen-Check übersprungen: {e}")