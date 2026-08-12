from backend.database.connection import get_connection, _exec
from backend.database.tickets import DDL_TICKETS, TICKETS_MIGRATIONS
from backend.database.settings import DDL_SETTINGS
from backend.database.users import USERS_DDL, USERS_MIGRATIONS
from backend.database.ticket_watchers import TICKET_WATCHERS_DDL, backfill_owner_watchers
from backend.database.audit_log import AUDIT_LOG_DDL
from backend.database.attachments import ATTACHMENTS_DDL, ATTACHMENTS_MIGRATIONS
from backend.database.process_definitions import (
    PROCESS_DEFINITIONS_DDL, PROCESS_DEFINITIONS_MIGRATIONS,
)
from backend.database.process_tickets import PROCESS_TICKETS_DDL, PROCESS_TICKETS_MIGRATIONS
from backend.database.process_timer_fires import (
    PROCESS_TIMER_FIRES_DDL, PROCESS_TIMER_FIRES_MIGRATIONS,
)
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
        _exec(conn, PROCESS_DEFINITIONS_DDL)
        _exec(conn, PROCESS_TICKETS_DDL)
        _exec(conn, PROCESS_TIMER_FIRES_DDL)
        conn.commit()
        logger.info("All tables ready")
    finally:
        conn.close()

    # Indizes/Spalten idempotent nachrüsten (in-place, non-fatal – reine Performance
    # bzw. additive Spalten). Greift nur für bereits bestehende Tabellen; neu
    # angelegte enthalten alles schon aus dem DDL.
    try:
        conn = get_connection()
        try:
            for migration in (list(TICKETS_MIGRATIONS)
                              + list(ATTACHMENTS_MIGRATIONS)
                              + list(PROCESS_DEFINITIONS_MIGRATIONS)
                              + list(PROCESS_TICKETS_MIGRATIONS)
                              + list(PROCESS_TIMER_FIRES_MIGRATIONS)):
                _exec(conn, migration)
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        logger.warning(f"Index-/Spalten-Migrationen übersprungen: {e}")

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