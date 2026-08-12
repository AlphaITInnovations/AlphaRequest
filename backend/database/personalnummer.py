"""Personalnummern-Vergabe: die reine Rechenlogik.

Bewusst OHNE DB-Zugriff. Der atomare Vergabe-Pfad (Sperre auf der
COMPANIES-Settings-Zeile, Ledger, Kollisionsprüfung) liegt im neuen System in
`database/process_sequences.py` und ruft `compute_next_personalnummer` von hier
auf. Die frühere DB-Hülle `db_assign_personalnummer_for_company` gehörte zum
Alt-System und ist mit ihm entfallen.
"""

from backend.database.settings import pnr_format

COMPANIES_KEY = "COMPANIES"


class PersonalnummerNotConfigured(Exception):
    """Firma unbekannt oder ohne hinterlegten Personalnummern-Bereich."""


class PersonalnummerExhausted(Exception):
    """Der Personalnummern-Bereich der Firma ist erschöpft."""


def compute_next_personalnummer(companies: list[dict], company_name: str,
                                warn_remaining: int) -> tuple[list[dict], dict]:
    """
    REINE Logik der Personalnummern-Vergabe (kein DB-Zugriff → unit-testbar).

    `companies` = Liste bereits normalisierter Firmen-Dicts. Zählt den Zähler der
    passenden Firma hoch (bei geteiltem Zähler die Quell-Firma) und gibt die
    AKTUALISIERTE Liste sowie das Ergebnis-Dict zurück:
      { number, remaining, should_warn, company_name, mandant, pnr_to }
    Wirft PersonalnummerNotConfigured / PersonalnummerExhausted.
    """
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

    result = {
        "number": pnr_format(target, nxt),   # z.B. "00896"
        "remaining": remaining,
        "should_warn": should_warn,
        "company_name": target["name"],       # Firma, deren Bereich/Zähler genutzt wurde
        "mandant": requester["mandant"],       # Mandant der anfragenden Firma
        "pnr_to": target["pnr_to"],
    }
    return companies, result
