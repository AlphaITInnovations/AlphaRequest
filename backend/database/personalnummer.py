import json

from backend.database.connection import get_connection, _fetchone, _exec
from backend.database.settings import normalize_company, pnr_format

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

        # Grenzen sind Ziffern-Strings (führende Nullen); numerisch rechnen, mit
        # führenden Nullen ausgeben (Breite = längste Grenze, via pnr_format).
        from_i = int(c["pnr_from"])
        to_i = int(c["pnr_to"])

        nxt = (c["pnr_current"] + 1) if c["pnr_current"] is not None else from_i
        if nxt > to_i:
            raise PersonalnummerExhausted(
                f"Der Personalnummern-Bereich der Firma „{company_name}“ ist erschöpft."
            )

        c["pnr_current"] = nxt
        remaining = to_i - nxt
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
            "number": pnr_format(c, nxt),   # z.B. "00896"
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


