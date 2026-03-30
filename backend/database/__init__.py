from backend.database.connection import get_connection, _exec
from backend.database.tickets import DDL_TICKETS
from backend.database.settings import DDL_SETTINGS
from backend.database.users import USERS_DDL  # noqa: F401
from backend.utils.logger import logger


def init_db():
    logger.info("Initializing database (MariaDB)")
    conn = get_connection()
    try:
        _exec(conn, DDL_TICKETS)
        _exec(conn, DDL_SETTINGS)
        _exec(conn, USERS_DDL)
        conn.commit()
        logger.info("All tables ready")
    finally:
        conn.close()