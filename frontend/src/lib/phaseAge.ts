/**
 * Liegezeit eines Auftrags in seiner AKTUELLEN Phase („liegt seit X Tagen").
 *
 * Grundlage ist der Eintrittszeitpunkt der Phase (`runtime.phases[i].entered_at`)
 * – ohne jede Prozess-Konfiguration und unabhängig davon, ob für die Phase eine
 * Eskalation eingestellt ist. So fällt in der Arbeitsliste auf, was liegen bleibt.
 *
 * Bewusst ein reines Modul (ohne Vue), damit es ohne DOM testbar ist.
 */
import type { ProcessRuntime } from '@/types/process'

/** Ab so vielen vollen Tagen gilt ein Auftrag als „liegt schon länger" (gelb). */
export const PHASE_AGE_WARN_DAYS = 3
/** Ab so vielen vollen Tagen gilt ein Auftrag als „liegt zu lange" (rot). */
export const PHASE_AGE_ALERT_DAYS = 7

export type PhaseAgeLevel = 'fresh' | 'warn' | 'alert'

export interface PhaseAge {
  /** Volle 24-h-Tage seit Phaseneintritt. */
  days: number
  level: PhaseAgeLevel
  /** Kurztext für die Plakette: „< 1 Tag", „1 Tag", „5 Tage". */
  short: string
  /** Satz für den Tooltip. */
  long: string
}

const DAY_MS = 86_400_000

/** Eintrittszeitpunkt der aktuellen Phase aus dem Runtime – null, wenn der Auftrag
 *  abgeschlossen/abgelehnt ist oder der Zeitstempel fehlt (Altbestand). */
export function currentPhaseEnteredAt(
  rt: Partial<ProcessRuntime> | null | undefined,
): string | null {
  if (!rt || rt.rejected) return null
  const phases = rt.phases ?? []
  const idx = rt.current_index ?? 0
  if (idx < 0 || idx >= phases.length) return null
  return phases[idx]?.entered_at || null
}

/** Zeitstempel ohne Zonen-Angabe sind serverseitig UTC (Altbestand) – sonst würde
 *  der Browser sie als Lokalzeit lesen. */
function parseUtc(iso: string): number {
  const hasZone = /([zZ]|[+-]\d{2}:?\d{2})$/.test(iso.trim())
  return Date.parse(hasZone ? iso : `${iso}Z`)
}

/** Liegezeit ab Phaseneintritt bis `now`. null bei fehlendem/kaputtem Zeitstempel. */
export function phaseAge(
  enteredAt: string | null | undefined, now: Date = new Date(),
): PhaseAge | null {
  if (!enteredAt) return null
  const t = parseUtc(enteredAt)
  if (Number.isNaN(t)) return null
  const days = Math.max(0, Math.floor((now.getTime() - t) / DAY_MS))
  const level: PhaseAgeLevel = days >= PHASE_AGE_ALERT_DAYS ? 'alert'
    : days >= PHASE_AGE_WARN_DAYS ? 'warn' : 'fresh'
  const short = days === 0 ? '< 1 Tag' : days === 1 ? '1 Tag' : `${days} Tage`
  const long = days === 0
    ? 'Liegt seit weniger als einem Tag in der aktuellen Phase'
    : `Liegt seit ${days === 1 ? '1 Tag' : `${days} Tagen`} in der aktuellen Phase`
  return { days, level, short, long }
}
