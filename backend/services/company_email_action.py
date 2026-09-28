"""Automations-Aktion `company_email`: automatische Firmenmail + Directus-Eindeutigkeit.

Beim Verlassen der Phase (on_exit, blockierend) wird – falls das Zielfeld leer ist –
die Firmenmail `vorname.nachname@firmendomain` gebildet (transliteriert, klein) und
gegen Microsoft-Exchange-Normen (Länge/Zeichen) geprüft. Anschließend wird in der
Directus-Collection nachgesehen, ob die Adresse schon existiert. Ist das Format
untauglich ODER die Adresse vergeben, wird `conflictField` gesetzt und der Aufrufer
blockiert den Phasenabschluss (das Feld ist dann per editableWhen änderbar).

Fail-open: ist Directus nicht erreichbar, wird NICHT blockiert (Infrastruktur-Ausfall
soll den Ablauf nicht anhalten) – die finale Anlage prüft ohnehin erneut.
"""
from __future__ import annotations

import re
from typing import Callable, Optional

from backend.services import directus_client
from backend.database.settings import get_companies_full


# ä/ö/ü/ß → ae/oe/ue/ss sowie gängige Akzente entschärfen (Exchange-SMTP: ASCII).
_TRANSLIT = {
    "ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss",
    "à": "a", "á": "a", "â": "a", "ã": "a", "å": "a", "ç": "c",
    "è": "e", "é": "e", "ê": "e", "ë": "e", "ì": "i", "í": "i", "î": "i", "ï": "i",
    "ñ": "n", "ò": "o", "ó": "o", "ô": "o", "õ": "o", "ø": "o",
    "ù": "u", "ú": "u", "û": "u", "ý": "y",
}

#: local-part: nur a-z0-9.- , kein führender/abschließender Punkt, keine Doppelpunkte
_LOCAL_RE = re.compile(r"^(?!\.)(?!.*\.\.)[a-z0-9.\-]+(?<!\.)$")


def _slug(s) -> str:
    """Namensteil → E-Mail-tauglich: transliteriert, klein, nur a-z0-9, Rest → '-'."""
    s = (str(s or "")).strip().lower()
    s = "".join(_TRANSLIT.get(ch, ch) for ch in s)
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s


def build_local(first, last) -> Optional[str]:
    """`vorname.nachname` (transliteriert). None, wenn ein Teil leer ist."""
    f, l = _slug(first), _slug(last)
    return f"{f}.{l}" if f and l else None


def valid_exchange_email(email: str) -> bool:
    """Grobe Exchange-/SMTP-Prüfung: ein @, local 1–64 Zeichen und zeichen-konform,
    Gesamtlänge ≤ 254, Domain mit Punkt und ohne Leerzeichen."""
    if not email or email.count("@") != 1:
        return False
    local, _, domain = email.partition("@")
    if not (1 <= len(local) <= 64) or len(email) > 254:
        return False
    if not _LOCAL_RE.match(local):
        return False
    if " " in domain or "." not in domain or domain.startswith(".") or domain.endswith("."):
        return False
    return True


def _domain_for(company_name, companies) -> Optional[str]:
    if not company_name:
        return None
    for c in (companies or []):
        if c.get("name") == company_name:
            return (c.get("domain") or "").strip().lower() or None
    return None


def execute(
    action, row: dict, defn, phase,
    *,
    query: Callable[..., list[dict]] = directus_client.query_items,
    is_configured: Callable[[], bool] = directus_client.is_configured,
    companies=None,
) -> dict:
    """Gibt changes zurück: {values: {targetField, conflictField}, email_conflict: bool,
    email_conflict_reason: 'format'|'exists'|None}. Wirft nicht."""
    spec = getattr(action, "email", None)
    if spec is None:
        return {}
    values = row.get("values") or {}
    target = str(values.get(spec.targetField) or "").strip()

    if not target:
        # Automatisch bilden – nur wenn Vor-/Nachname UND Firmen-Domain vorliegen.
        comps = companies if companies is not None else get_companies_full()
        domain = _domain_for(values.get(spec.companyField), comps)
        local = build_local(values.get(spec.firstNameField), values.get(spec.lastNameField))
        target = f"{local}@{domain}" if (local and domain) else ""

    email = target.strip().lower()
    if not email:
        # Nichts zu setzen/prüfen (Namen/Domain fehlen) – kein Konflikt, keine Blockade.
        return {}

    invalid = not valid_exchange_email(email)
    exists = False
    if not invalid and is_configured():
        try:
            rows = query(spec.collection, fields=[spec.emailField],
                         filter={spec.emailField: {"_eq": email}}, limit=1)
            exists = bool(rows)
        except directus_client.DirectusError:
            exists = False   # fail-open: Directus-Ausfall blockiert den Ablauf nicht

    conflict = invalid or exists
    reason = "format" if invalid else ("exists" if exists else None)
    return {"values": {spec.targetField: email, spec.conflictField: conflict},
            "email_conflict": conflict, "email_conflict_reason": reason}
