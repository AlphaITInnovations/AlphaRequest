"""
Timer-Mathematik für Automations (§6.1/§7) – rein, deterministisch, DB-frei.

Fälligkeit wird IMMER aus entered_at abgeleitet (nicht aus fired_at → kein Drift):
    occurrence = floor((elapsed - after) / repeat) + 1,   occurrence 1 = erste Periode
mit elapsed = (now - entered_at) - accumulated_pause.

Missed-Window: One-Shot feuert einmal; Repeat macht Fire-once-Catch-up (nur die
zuletzt fällige Occurrence löst die Aktion aus, übersprungene werden als
unterdrückt vermerkt). Diese Datei liefert die Zahlen; das Feuern/der Ledger
liegt im Scheduler.
"""
from datetime import datetime, timedelta
from typing import Optional

from backend.schemas.process_definition import PhaseDef, TriggerType
from backend.services.iso_duration import parse_duration


def _elapsed_seconds(entered_at_iso: str, now: datetime, paused_ms: int = 0) -> float:
    entered = datetime.fromisoformat(entered_at_iso)
    return (now - entered).total_seconds() - (paused_ms or 0) / 1000.0


def max_due_occurrence(after_s: int, repeat_s: int, elapsed_s: float) -> int:
    """Höchste fällige Occurrence (0 = noch keine)."""
    if elapsed_s < after_s:
        return 0
    if not repeat_s:
        return 1
    return int((elapsed_s - after_s) // repeat_s) + 1


def next_due_at(entered_at_iso: str, after_s: int, repeat_s: int,
                paused_ms: int, fired_occurrence: int) -> Optional[datetime]:
    """Zeitpunkt, zu dem die nächste Occurrence NACH fired_occurrence fällig wird
    (None = keine weitere)."""
    entered = datetime.fromisoformat(entered_at_iso)
    if fired_occurrence == 0:
        offset = after_s
    else:
        if not repeat_s:
            return None
        offset = after_s + fired_occurrence * repeat_s
    return entered + timedelta(seconds=offset + (paused_ms or 0) / 1000.0)


def _phase_timers(phase: PhaseDef, extra=()):
    """Timer-Automations der Phase PLUS prozessweite (definition.automations)."""
    return [a for a in list(extra) + list(phase.automations)
            if a.trigger.type == TriggerType.timer]


def compute_next_timer_due(phase: PhaseDef, entered_at_iso: str, paused_ms: int,
                           fired_map: dict, extra=()) -> Optional[datetime]:
    """Frühester nächster Timer-Fälligkeitszeitpunkt der Phase → next_timer_due_at.
    fired_map: {automation_id: höchste bereits gefeuerte Occurrence}."""
    best: Optional[datetime] = None
    for a in _phase_timers(phase, extra):
        after_s = parse_duration(a.trigger.after)
        repeat_s = parse_duration(a.trigger.repeat) if a.trigger.repeat else 0
        nd = next_due_at(entered_at_iso, after_s, repeat_s, paused_ms, fired_map.get(a.id, 0))
        if nd is not None and (best is None or nd < best):
            best = nd
    return best


#: Obergrenze für nachzuholende Occurrences pro Automation und Sweep. Nur die
#: LETZTE feuert; die davor werden nur verbucht – ohne Deckel wären das nach einem
#: langen Ausfall tausende Einzel-Inserts (z.B. repeat PT5M über ein Wochenende).
MAX_CATCHUP = 50


def due_timers(phase: PhaseDef, entered_at_iso: str, now: datetime,
               paused_ms: int, fired_map: dict, extra=()) -> list[tuple]:
    """Liste (automation, [Occurrences … max_due]) der jetzt fälligen Timer.
    Die letzte Occurrence löst die Aktion aus, die davor sind Catch-up (unterdrückt)."""
    out = []
    elapsed = _elapsed_seconds(entered_at_iso, now, paused_ms)
    for a in _phase_timers(phase, extra):
        after_s = parse_duration(a.trigger.after)
        repeat_s = parse_duration(a.trigger.repeat) if a.trigger.repeat else 0
        maxd = max_due_occurrence(after_s, repeat_s, elapsed)
        fired = fired_map.get(a.id, 0)
        if maxd > fired:
            first = max(fired + 1, maxd - MAX_CATCHUP + 1)
            out.append((a, list(range(first, maxd + 1))))
    return out
