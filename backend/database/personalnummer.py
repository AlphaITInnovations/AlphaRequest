import json
from typing import Optional

from backend.database.connection import get_connection, _fetchone, _exec
from backend.database.settings import settings_get, settings_set, normalize_company

SETTINGS_KEY = "PERSONALNUMMER"
COMPANIES_KEY = "COMPANIES"


class PersonalnummerNotConfigured(Exception):
    """Firma unbekannt oder ohne hinterlegten Personalnummern-Bereich."""


class PersonalnummerExhausted(Exception):
    """Der Personalnummern-Bereich der Firma ist erschöpft."""


def db_assign_personalnummer_for_company(company_name: str, warn_remaining: int) -> dict:
    """
    Vergibt atomar die nächste Personalnummer für eine Firma und erhöht deren
    Zähler. Sperrt dazu die COMPANIES-Settings-Zeile (FOR UPDATE), damit keine
    Nummer doppelt vergeben wird.

    Rückgabe: { number, remaining, should_warn, company_name, mandant, pnr_to }
    Wirft PersonalnummerNotConfigured / PersonalnummerExhausted.
    """
    conn = get_connection()
    try:
        conn.begin()
        row = _fetchone(
            conn,
            "SELECT `value` FROM settings WHERE `key`=%s FOR UPDATE",
            (COMPANIES_KEY,),
        )
        try:
            raw = json.loads(row["value"]) if row and row["value"] else []
        except Exception:
            raw = []
        if not isinstance(raw, list):
            raw = []

        companies = [normalize_company(x) for x in raw]
        idx = next((i for i, c in enumerate(companies) if c["name"] == company_name), None)
        if idx is None:
            raise PersonalnummerNotConfigured(f"Firma „{company_name}“ ist nicht hinterlegt.")

        c = companies[idx]
        if c["pnr_from"] is None or c["pnr_to"] is None:
            raise PersonalnummerNotConfigured(
                f"Für die Firma „{company_name}“ ist kein Personalnummern-Bereich hinterlegt."
            )

        nxt = (c["pnr_current"] + 1) if c["pnr_current"] is not None else c["pnr_from"]
        if nxt > c["pnr_to"]:
            raise PersonalnummerExhausted(
                f"Der Personalnummern-Bereich der Firma „{company_name}“ ist erschöpft."
            )

        c["pnr_current"] = nxt
        remaining = c["pnr_to"] - nxt
        should_warn = remaining <= warn_remaining and not c["pnr_warned"]
        if should_warn:
            c["pnr_warned"] = True
        companies[idx] = c

        _exec(
            conn,
            "INSERT INTO settings(`key`,`value`) VALUES(%s,%s) "
            "ON DUPLICATE KEY UPDATE `value`=VALUES(`value`)",
            (COMPANIES_KEY, json.dumps(companies, ensure_ascii=False)),
        )
        conn.commit()
        return {
            "number": nxt,
            "remaining": remaining,
            "should_warn": should_warn,
            "company_name": company_name,
            "mandant": c["mandant"],
            "pnr_to": c["pnr_to"],
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


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