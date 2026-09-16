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
            filter={config.DIRECTUS_EMPLOYEE_EMAIL_FIELD: {"_eq": raw}},
            limit=1,
        )
    except directus_client.DirectusError as e:
        raise EmployeeLookupError(str(e)) from e

    rec = rows[0] if rows else None
    if rec is not None:
        _cache[key] = (rec, now() + config.DIRECTUS_EMPLOYEE_CACHE_TTL)
    return rec
