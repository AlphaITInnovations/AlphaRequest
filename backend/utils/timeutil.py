"""tz-aware UTC-Zeitstempel für SLA/Runtime (§7 des Design-Docs).

Bewusst getrennt von tickets._now_iso() (naiv, Alt-System) und von der
History (Europe/Berlin). Intern rechnet das Prozess-System konsequent in UTC.
"""
from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
