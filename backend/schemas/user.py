"""Ausgabe-Schema des angemeldeten Nutzers.

Eigene Datei, weil `UserOut` von `/auth/me` und `/auth/refresh-session`
gebraucht wird – also von einem Pfad, der mit Aufträgen nichts zu tun hat. Vorher
lag die Klasse in `schemas/ticket.py` und hätte mit dem Alt-System den
Login-Pfad mitgerissen.
"""
from typing import Any, List, Optional

from pydantic import BaseModel


class UserOut(BaseModel):
    id: str
    displayName: str
    mail: Optional[str] = None
    permissions: List[str] = []


class ProfileOut(BaseModel):
    """Vollständige Profil-Anzeige des angemeldeten Nutzers: Konto + Azure-Profil
    (aus dem Login) + der verknüpfte Directus-Mitarbeiter-Datensatz (`employee`,
    beliebige Felder je nach DIRECTUS_EMPLOYEE_FIELDS)."""
    id: str
    displayName: str
    mail: Optional[str] = None
    permissions: List[str] = []
    # Azure-Profil (aus Graph /me, in der Session gehalten)
    phone: Optional[str] = None
    mobile: Optional[str] = None
    company: Optional[str] = None
    position: Optional[str] = None
    address: Any = None
    groups: List[str] = []
    # Directus-Stammdaten (per E-Mail verknüpft); None, wenn kein Datensatz.
    employee: Optional[dict] = None
