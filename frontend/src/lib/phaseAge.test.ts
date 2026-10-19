import { describe, it, expect } from 'vitest'
import { currentPhaseEnteredAt, phaseAge, PHASE_AGE_ALERT_DAYS, PHASE_AGE_WARN_DAYS } from './phaseAge'

const NOW = new Date('2026-10-19T12:00:00Z')
const vorTagen = (d: number, h = 0) =>
  new Date(NOW.getTime() - d * 86_400_000 - h * 3_600_000).toISOString()

describe('phaseAge', () => {
  it('unter einem Tag → „< 1 Tag", frisch', () => {
    expect(phaseAge(vorTagen(0, 5), NOW)).toMatchObject({ days: 0, level: 'fresh', short: '< 1 Tag' })
  })

  it('Einzahl/Mehrzahl', () => {
    expect(phaseAge(vorTagen(1), NOW)?.short).toBe('1 Tag')
    expect(phaseAge(vorTagen(1), NOW)?.long).toContain('seit 1 Tag ')
    expect(phaseAge(vorTagen(2), NOW)?.short).toBe('2 Tage')
    expect(phaseAge(vorTagen(2), NOW)?.long).toContain('seit 2 Tagen')
  })

  it('Schwellen: gelb ab 3, rot ab 7 vollen Tagen', () => {
    expect(phaseAge(vorTagen(PHASE_AGE_WARN_DAYS - 1, 23), NOW)?.level).toBe('fresh')
    expect(phaseAge(vorTagen(PHASE_AGE_WARN_DAYS), NOW)?.level).toBe('warn')
    expect(phaseAge(vorTagen(PHASE_AGE_ALERT_DAYS - 1, 23), NOW)?.level).toBe('warn')
    expect(phaseAge(vorTagen(PHASE_AGE_ALERT_DAYS), NOW)?.level).toBe('alert')
    expect(phaseAge(vorTagen(40), NOW)).toMatchObject({ days: 40, level: 'alert' })
  })

  it('Zeitstempel ohne Zone gilt als UTC (Altbestand)', () => {
    // 2026-10-16T12:00:00 (UTC) → genau 3 Tage vor NOW, unabhängig von der Browser-Zone.
    expect(phaseAge('2026-10-16T12:00:00', NOW)?.days).toBe(3)
    expect(phaseAge('2026-10-16T12:00:00+00:00', NOW)?.days).toBe(3)
  })

  it('fehlend/kaputt → null, Zukunft → 0', () => {
    expect(phaseAge(null, NOW)).toBeNull()
    expect(phaseAge('', NOW)).toBeNull()
    expect(phaseAge('kein-datum', NOW)).toBeNull()
    expect(phaseAge('2026-10-20T12:00:00Z', NOW)?.days).toBe(0)
  })
})

describe('currentPhaseEnteredAt', () => {
  const rt = {
    current_index: 1, epoch: 0, rejected: false, sla_paused_ms: 0,
    phases: [
      { key: 'a', status: 'done' as const, entered_at: '2026-10-01T00:00:00Z' },
      { key: 'b', status: 'open' as const, entered_at: '2026-10-10T00:00:00Z' },
    ],
  }

  it('liefert den Eintritt der AKTUELLEN Phase', () => {
    expect(currentPhaseEnteredAt(rt)).toBe('2026-10-10T00:00:00Z')
  })

  it('abgeschlossen, abgelehnt, ohne Runtime → null', () => {
    expect(currentPhaseEnteredAt({ ...rt, current_index: 2 })).toBeNull()
    expect(currentPhaseEnteredAt({ ...rt, rejected: true })).toBeNull()
    expect(currentPhaseEnteredAt(null)).toBeNull()
    expect(currentPhaseEnteredAt({})).toBeNull()
  })
})
