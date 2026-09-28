"""tz-aware UTC-Zeitstempel für SLA/Runtime (§7 des Design-Docs).

Bewusst getrennt von tickets._now_iso() (naiv, Alt-System) und von der
History (Europe/Berlin). Intern rechnet das Prozess-System konsequent in UTC.

WICHTIG – zwei Repräsentationen, nicht vermischen:
  * `utcnow_iso()`   → tz-AWARE ISO-String für JSON-Felder (runtime_json.entered_at).
  * `to_db_datetime()` → NAIVE UTC-Zeit "YYYY-MM-DD HH:MM:SS" für DATETIME-SPALTEN.
MariaDB kennt keine Offset-behafteten DATETIME-Literale: ein "+00:00" im String
führt im (default) STRICT_TRANS_TABLES-Modus zu Fehler 1292. Jeder Schreib- und
Vergleichswert für eine DATETIME-Spalte MUSS durch to_db_datetime().
"""
from datetime import datetime, timezone
from typing import Optional, Union


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def utcnow_iso() -> str:
    """tz-aware ISO-8601 – nur für JSON-Felder, NIE für DATETIME-Spalten."""
    return datetime.now(timezone.utc).isoformat()


def as_aware_utc(value: Union[str, datetime]) -> datetime:
    """Parst/normalisiert auf tz-aware UTC (naive Werte gelten als UTC)."""
    dt = datetime.fromisoformat(value) if isinstance(value, str) else value
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def to_db_datetime(value: Optional[Union[str, datetime]]) -> Optional[str]:
    """Wert für eine MariaDB-DATETIME-Spalte: naive UTC, sekundengenau.
    None bleibt None (NULL)."""
    if value is None:
        return None
    return as_aware_utc(value).replace(tzinfo=None, microsecond=0).strftime("%Y-%m-%d %H:%M:%S")
