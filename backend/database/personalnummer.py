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

        requester = companies[idx]

        # Teilt sich die Firma einen Zähler mit einer anderen? → auf die Quell-Firma
        # auflösen; der Zähler DIESER Quelle wird hochgezählt (gemeinsamer Zähler).
        target_idx = idx
        if requester["pnr_shared_with"]:
            src_name = requester["pnr_shared_with"]
            target_idx = next((i for i, c in enumerate(companies) if c["name"] == src_name), None)
            if target_idx is None:
                raise PersonalnummerNotConfigured(
                    f"„{company_name}“ teilt den Zähler mit „{src_name}“, diese Firma ist aber nicht hinterlegt."
                )

        target = companies[target_idx]
        if target["pnr_from"] is None or target["pnr_to"] is None:
            raise PersonalnummerNotConfigured(
                f"Für die Firma „{target['name']}“ ist kein Personalnummern-Bereich hinterlegt."
            )

        # Grenzen sind Ziffern-Strings (führende Nullen); numerisch rechnen, mit
        # führenden Nullen ausgeben (Breite = längste Grenze, via pnr_format).
        from_i = int(target["pnr_from"])
        to_i = int(target["pnr_to"])

        nxt = (target["pnr_current"] + 1) if target["pnr_current"] is not None else from_i
        if nxt > to_i:
            raise PersonalnummerExhausted(
                f"Der Personalnummern-Bereich der Firma „{target['name']}“ ist erschöpft."
            )

        target["pnr_current"] = nxt
        remaining = to_i - nxt
        should_warn = remaining <= warn_remaining and not target["pnr_warned"]
        if should_warn:
            target["pnr_warned"] = True
        companies[target_idx] = target

        _exec(
            conn,
            "INSERT INTO settings(`key`,`value`) VALUES(%s,%s) "
            "ON DUPLICATE KEY UPDATE `value`=VALUES(`value`)",
            (COMPANIES_KEY, json.dumps(companies, ensure_ascii=False)),
        )
        conn.commit()
        return {
            "number": pnr_format(target, nxt),   # z.B. "00896"
            "remaining": remaining,
            "should_warn": should_warn,
            "company_name": target["name"],       # Firma, deren Bereich/Zähler genutzt wurde
            "mandant": requester["mandant"],       # Mandant der anfragenden Firma
            "pnr_to": target["pnr_to"],
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


