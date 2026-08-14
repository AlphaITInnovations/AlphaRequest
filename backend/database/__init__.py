from backend.database.connection import get_connection, _exec
from backend.database.settings import DDL_SETTINGS
from backend.database.users import USERS_DDL, USERS_MIGRATIONS
from backend.database.audit_log import AUDIT_LOG_DDL
from backend.database.attachments import ATTACHMENTS_DDL, ATTACHMENTS_MIGRATIONS
from backend.database.process_definitions import (
    PROCESS_DEFINITIONS_DDL, PROCESS_DEFINITIONS_MIGRATIONS,
)
from backend.database.process_tickets import PROCESS_TICKETS_DDL, PROCESS_TICKETS_MIGRATIONS
from backend.database.process_ticket_events import (
    PROCESS_TICKET_EVENTS_DDL, PROCESS_TICKET_EVENTS_MIGRATIONS,
)
from backend.database.process_ticket_watchers import PROCESS_TICKET_WATCHERS_DDL
from backend.database.process_sequences import PROCESS_SEQUENCE_CLAIMS_DDL
from backend.database.process_timer_fires import (
    PROCESS_TIMER_FIRES_DDL, PROCESS_TIMER_FIRES_MIGRATIONS,
)
from backend.utils.logger import logger


def init_db():
    logger.info("Initializing database (MariaDB)")
    conn = get_connection()
    try:
        _exec(conn, DDL_SETTINGS)
        _exec(conn, USERS_DDL)
        for migration in USERS_MIGRATIONS:
            _exec(conn, migration)
        _exec(conn, AUDIT_LOG_DDL)
        _exec(conn, ATTACHMENTS_DDL)
        _exec(conn, PROCESS_DEFINITIONS_DDL)
        _exec(conn, PROCESS_TICKETS_DDL)
        _exec(conn, PROCESS_TICKET_EVENTS_DDL)
        _exec(conn, PROCESS_TICKET_WATCHERS_DDL)
        _exec(conn, PROCESS_TIMER_FIRES_DDL)
        _exec(conn, PROCESS_SEQUENCE_CLAIMS_DDL)
        conn.commit()
        logger.info("All tables ready")
    finally:
        conn.close()

    # Indizes/Spalten idempotent nachrüsten (in-place, non-fatal – reine Performance
    # bzw. additive Spalten). Greift nur für bereits bestehende Tabellen; neu
    # angelegte enthalten alles schon aus dem DDL.
    #
    # Die Tabellen des entfernten Alt-Systems (tickets, ticket_watchers,
    # ticket_locks, ticket_group_permissions) werden hier NICHT mehr angelegt oder
    # migriert. Bestehende Installationen behalten sie – gedroppt wird nichts, das
    # ist eine bewusste Entscheidung des Betriebs und nicht Aufgabe des Starts.
    try:
        conn = get_connection()
        try:
            for migration in (list(ATTACHMENTS_MIGRATIONS)
                              + list(PROCESS_DEFINITIONS_MIGRATIONS)
                              + list(PROCESS_TICKETS_MIGRATIONS)
                              + list(PROCESS_TICKET_EVENTS_MIGRATIONS)
                              + list(PROCESS_TIMER_FIRES_MIGRATIONS)):
                _exec(conn, migration)
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        logger.warning(f"Index-/Spalten-Migrationen übersprungen: {e}")

    # Pflicht-Fachabteilungen sicherstellen: fehlende werden leer angelegt, damit
    # jeder ausgelieferte Prozess eine zuständige Gruppe auflösen kann. Namensquelle
    # ist services/seed_definitions – dieselbe Liste, aus der die Seeds ihre
    # Gruppen-Platzhalter auflösen. Ohne diesen Schritt hätte eine frische
    # Installation keine einzige Fachabteilung.
    try:
        from backend.services.seed_definitions import (
            AUTO_ASSIGNED_GROUP_NAMES, required_group_names,
        )
        from backend.database.groups import ensure_required_groups
        created = ensure_required_groups(required_group_names(),
                                        hidden_names=AUTO_ASSIGNED_GROUP_NAMES)
        if created:
            logger.info("Fehlende Pflichtgruppen angelegt: %s", ", ".join(created))
    except Exception as e:
        logger.warning(f"Pflichtgruppen-Check übersprungen: {e}")

    # System-Prozesse (heute das Basis-Ticket) sicherstellen. NACH dem DDL oben,
    # weil hier in `process_definitions` geschrieben wird.
    #
    # Das gehört in den Start, weil die Anwendung ohne veröffentlichte Definition
    # unbenutzbar ist: „Neues Ticket" endete in „Dieser Prozess ist nicht (mehr)
    # verfügbar", bis jemand von Hand ein Skript auf dem Server ausführte. Ein
    # Prozess, der zum PRODUKT gehört, darf keinen Shell-Zugang brauchen.
    #
    # Nur die selbsttragenden Prozesse laufen hier mit (Begründung im Docstring
    # von ensure_system_processes); die übrigen neun bleiben beim Admin-Knopf
    # `POST /processes:seed`. Fehlschlag = Warnung, kein Startabbruch: eine
    # laufende Installation soll nicht daran hängen.
    try:
        from backend.services.seed_definitions import ensure_system_processes
        for o in ensure_system_processes():
            if o.aktion == "error":
                logger.warning("System-Prozess %s: %s", o.key, o.meldung)
    except Exception as e:
        logger.warning(f"System-Prozesse übersprungen: {e}")
