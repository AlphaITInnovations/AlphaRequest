from backend.database.connection import get_connection, _exec
from backend.database.tickets import DDL_TICKETS, TICKETS_MIGRATIONS
from backend.database.settings import DDL_SETTINGS
from backend.database.users import USERS_DDL, USERS_MIGRATIONS
from backend.database.ticket_watchers import TICKET_WATCHERS_DDL, backfill_owner_watchers
from backend.database.audit_log import AUDIT_LOG_DDL
from backend.database.attachments import ATTACHMENTS_DDL
from backend.utils.logger import logger


def init_db():
    logger.info("Initializing database (MariaDB)")
    conn = get_connection()
    try:
        _exec(conn, DDL_TICKETS)
        _exec(conn, DDL_SETTINGS)
        _exec(conn, USERS_DDL)
        for migration in USERS_MIGRATIONS:
            _exec(conn, migration)
        _exec(conn, TICKET_WATCHERS_DDL)
        _exec(conn, AUDIT_LOG_DDL)
        _exec(conn, ATTACHMENTS_DDL)
        conn.commit()
        logger.info("All tables ready")
    finally:
        conn.close()

    # Indizes idempotent nachrüsten (in-place, non-fatal – reine Performance).
    try:
        conn = get_connection()
        try:
            for migration in TICKETS_MIGRATIONS:
                _exec(conn, migration)
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        logger.warning(f"Ticket-Index-Migrationen übersprungen: {e}")

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

    # Bestehende Onboarding-Tickets einmalig ins neue base-Format migrieren
    # (Basisdaten aus personal → base, private_address → private_street,
    # allgemein.appearance_company → it.appearance_company). Danach greifen alle
    # Tickets einheitlich ohne Legacy-Fallbacks.
    try:
        from backend.services.onboarding_migration import backfill_onboarding_descriptions
        backfill_onboarding_descriptions()
    except Exception as e:
        logger.warning(f"Onboarding-Format-Migration übersprungen: {e}")

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