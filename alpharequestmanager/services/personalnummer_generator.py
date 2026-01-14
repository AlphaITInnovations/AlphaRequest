import json
from alpharequestmanager.utils.config import config
from alpharequestmanager.database.database import (
    get_connection,
    settings_get,
    settings_set,
    _fetchone,
    _exec,
)

SETTINGS_KEY = "PERSONALNUMMER"

def init_personalnummer() -> None:
    conn = get_connection()
    try:
        conn.begin()

        row = _fetchone(
            conn,
            "SELECT value FROM settings WHERE `key`=%s FOR UPDATE",
            (SETTINGS_KEY,)
        )

        if not row:
            start_value = config.PERSONALNUMMER_START
            _exec(
                conn,
                "INSERT INTO settings(`key`,`value`) VALUES(%s,%s)",
                (SETTINGS_KEY, json.dumps(start_value))
            )

        conn.commit()

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def get_personalnummer() -> int:
    return int(
        settings_get(
            SETTINGS_KEY,
            default=config.PERSONALNUMMER_START
        )
    )

def next_personalnummer() -> int:
    conn = get_connection()
    try:
        conn.begin()

        row = _fetchone(
            conn,
            "SELECT value FROM settings WHERE `key`=%s FOR UPDATE",
            (SETTINGS_KEY,)
        )

        if not row:
            current = config.PERSONALNUMMER_START
        else:
            current = int(json.loads(row["value"]))

        next_nr = current + 1

        if next_nr > config.PERSONALNUMMER_END:
            raise RuntimeError("PERSONALNUMMER_END überschritten")

        _exec(
            conn,
            "INSERT INTO settings(`key`,`value`) VALUES(%s,%s) "
            "ON DUPLICATE KEY UPDATE `value`=VALUES(`value`)",
            (SETTINGS_KEY, json.dumps(next_nr))
        )

        conn.commit()
        return next_nr

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def reset_personalnummer() -> None:
    settings_set(
        SETTINGS_KEY,
        config.PERSONALNUMMER_START
    )
