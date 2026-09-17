"""Zuordnung angemeldeter Azure-AD-User ↔ Directus-Mitarbeiter-Datensatz (per E-Mail).

Grundprinzip des Systems: die **Identität** kommt aus Azure (Login, oid, Gruppen,
Benachrichtigung), die **Stammdaten** (Name, Position, Vorgesetzter …) liegen in
Directus. Verknüpft wird über die E-Mail. Bewusst ENV-konfiguriert (Kern-
Infrastruktur), nicht über die admin-editierbaren Directus-Quellen.

`lookup_employee` unterscheidet sauber:
  - Treffer            → der Datensatz (dict),
  - kein Treffer       → None (Konto ohne Directus-Stammdaten),
  - Directus down/aus  → EmployeeLookupError (der Aufrufer entscheidet Break-Glass).

Nur Treffer werden (kurz) gecacht – „nicht gefunden" und Fehler bewusst nicht,
damit ein frisch angelegter Datensatz sofort greift und ein Ausfall nicht
festgeschrieben wird.
"""
from __future__ import annotations

import time
from typing import Callable, Optional

from backend.services import directus_client
from backend.utils.config import config


class EmployeeLookupError(RuntimeError):
    """Directus nicht konfiguriert oder nicht erreichbar – die Zuordnung konnte
    nicht geprüft werden (zu unterscheiden vom sauberen „kein Datensatz")."""


#: email(lowercased) -> (record, expires_at)
_cache: dict[str, tuple[dict, float]] = {}


def _now() -> float:
    return time.time()


def clear_cache() -> None:
    """Cache leeren (Tests / nach Stammdaten-Änderung)."""
    _cache.clear()


def lookup_employee(
    email: str,
    *,
    query: Callable[..., list[dict]] = directus_client.query_items,
    is_configured: Callable[[], bool] = directus_client.is_configured,
    now: Callable[[], float] = _now,
) -> Optional[dict]:
    """Directus-Datensatz zur E-Mail holen.

    Rückgabe: der Datensatz bei Treffer, None wenn es zu dieser E-Mail keinen gibt.
    Wirft EmployeeLookupError, wenn Directus nicht konfiguriert/erreichbar ist.
    """
    raw = (email or "").strip()
    key = raw.lower()
    if not key:
        return None

    hit = _cache.get(key)
    if hit is not None and hit[1] > now():
        return hit[0]

    if not is_configured():
        raise EmployeeLookupError("Directus ist nicht konfiguriert")

    try:
        rows = query(
            config.DIRECTUS_EMPLOYEE_COLLECTION,
            fields=(config.DIRECTUS_EMPLOYEE_FIELDS or None),
            # Directus speichert die Mail klein – deshalb kleingeschrieben
            # vergleichen (Azure liefert sie oft gemischt, z. B. „Vorname.Name@…").
            filter={config.DIRECTUS_EMPLOYEE_EMAIL_FIELD: {"_eq": key}},
            limit=1,
        )
    except directus_client.DirectusError as e:
        raise EmployeeLookupError(str(e)) from e

    rec = rows[0] if rows else None
    if rec is not None:
        _cache[key] = (rec, now() + config.DIRECTUS_EMPLOYEE_CACHE_TTL)
    return rec


def list_employees(
    *,
    query: Callable[..., list[dict]] = directus_client.query_items,
    is_configured: Callable[[], bool] = directus_client.is_configured,
) -> list[dict]:
    """Alle Mitarbeitenden für die Personen-Dropdowns/-Listen aus Directus.

    Rückgabe je Person: {id, displayName, mail} – id UND mail sind die
    kleingeschriebene E-Mail (der durchgängige Personenschlüssel). Personen ohne
    E-Mail werden übersprungen (ohne Schlüssel nicht referenzierbar). Wirft
    EmployeeLookupError, wenn Directus nicht konfiguriert/erreichbar ist – der
    Aufrufer (Cache-Sync) entscheidet fail-soft.
    """
    if not is_configured():
        raise EmployeeLookupError("Directus ist nicht konfiguriert")

    email_field = config.DIRECTUS_EMPLOYEE_EMAIL_FIELD
    name_fields = config.DIRECTUS_EMPLOYEE_NAME_FIELDS
    fields = list(dict.fromkeys([email_field, *name_fields]))  # dedupe, Reihenfolge

    try:
        rows = query(config.DIRECTUS_EMPLOYEE_COLLECTION, fields=fields,
                     limit=config.DIRECTUS_EMPLOYEE_LIST_LIMIT)
    except directus_client.DirectusError as e:
        raise EmployeeLookupError(str(e)) from e

    out: list[dict] = []
    for r in rows:
        email = str(r.get(email_field) or "").strip().lower()
        if not email:
            continue
        name = " ".join(str(r.get(f)).strip() for f in name_fields if r.get(f)).strip()
        out.append({"id": email, "displayName": name or email, "mail": email})
    return out
