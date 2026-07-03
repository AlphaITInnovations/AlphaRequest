"""Reine Logik für Ticket-Sammelaktionen (ohne DB/I-O, damit unit-testbar)."""

from typing import Optional

VALID_BULK_ACTIONS = ("archive", "delete")


def normalize_bulk_action(action: str) -> Optional[str]:
    """Normalisiert die Aktion oder gibt None bei unbekannter Aktion zurück."""
    a = (action or "").strip().lower()
    return a if a in VALID_BULK_ACTIONS else None


def required_permission_for_bulk(action: str) -> str:
    """Benötigte Berechtigung je Aktion: Löschen nur Admin, Archivieren ab Manager."""
    return "admin" if action == "delete" else "manage"
