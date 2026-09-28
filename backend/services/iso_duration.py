"""Minimaler ISO-8601-Dauer-Parser für Timer-Trigger (z.B. "P7D", "P14D", "PT12H").

Unterstützt Wochen/Tage/Stunden/Minuten/Sekunden (W/D/H/M/S). Monate/Jahre sind
bewusst NICHT unterstützt (variable Länge). Gibt Sekunden (int) zurück.
"""
import re

_RE = re.compile(
    r"^P(?:(?P<w>\d+)W)?(?:(?P<d>\d+)D)?"
    r"(?:T(?:(?P<h>\d+)H)?(?:(?P<m>\d+)M)?(?:(?P<s>\d+)S)?)?$"
)
_MULT = {"w": 604800, "d": 86400, "h": 3600, "m": 60, "s": 1}


def parse_duration(text: str) -> int:
    if not text or not isinstance(text, str):
        raise ValueError("leere Dauer")
    m = _RE.fullmatch(text.strip())
    if not m or not any(m.group(k) for k in _MULT):
        raise ValueError(f"ungültige ISO-8601-Dauer: {text!r}")
    return sum(int(m.group(k)) * mult for k, mult in _MULT.items() if m.group(k))
