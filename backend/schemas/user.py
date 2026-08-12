"""Ausgabe-Schema des angemeldeten Nutzers.

Eigene Datei, weil `UserOut` von `/auth/me` und `/auth/refresh-session`
gebraucht wird – also von einem Pfad, der mit Aufträgen nichts zu tun hat. Vorher
lag die Klasse in `schemas/ticket.py` und hätte mit dem Alt-System den
Login-Pfad mitgerissen.
"""
from typing import List, Optional

from pydantic import BaseModel


class UserOut(BaseModel):
    id: str
    displayName: str
    mail: Optional[str] = None
    permissions: List[str] = []
