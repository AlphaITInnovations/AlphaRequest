import json
from typing import Optional

from backend.database.connection import get_connection, _fetchone, _exec
from backend.database.settings import settings_get, settings_set

SETTINGS_KEY = "PERSONALNUMMER"


def db_init_personalnummer(start_value: int) -> None:
    """Legt den Startwert an – nur wenn noch kein Eintrag existiert (atomisch)."""
    conn = get_connection()
    try:
        conn.begin()
        row = _fetchone(
            conn,
            "SELECT value FROM settings WHERE `key`=%s FOR UPDATE",
            (SETTINGS_KEY,),
        )
        if not row:
            _exec(
                conn,
                "INSERT INTO settings(`key`,`value`) VALUES(%s,%s)",
                (SETTINGS_KEY, json.dumps(start_value)),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def db_get_personalnummer(default: int) -> int:
    return int(settings_get(SETTINGS_KEY, default=default))


def db_next_personalnummer(end_value: int) -> int:
    """Inkrementiert atomar und gibt die neue Nummer zurück."""
    conn = get_connection()
    try:
        conn.begin()
        row = _fetchone(
            conn,
            "SELECT value FROM settings WHERE `key`=%s FOR UPDATE",
            (SETTINGS_KEY,),
        )
        current = int(json.loads(row["value"])) if row else end_value

        next_nr = current + 1
        if next_nr > end_value:
            raise RuntimeError("PERSONALNUMMER_END überschritten")

        _exec(
            conn,
            "INSERT INTO settings(`key`,`value`) VALUES(%s,%s) "
            "ON DUPLICATE KEY UPDATE `value`=VALUES(`value`)",
            (SETTINGS_KEY, json.dumps(next_nr)),
        )
        conn.commit()
        return next_nr
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def db_reset_personalnummer(start_value: int) -> None:
    settings_set(SETTINGS_KEY, start_value)