/**
 * „Phase X von Y".
 *
 * Der Fall, der schnell falsch wird: `runtime.current_index` DARF die Anzahl der
 * Phasen erreichen (so beendet die Laufzeit einen Auftrag). Ohne Kappen stünde
 * dann „Phase 5 von 4" im Panel.
 */
import { describe, expect, it } from 'vitest'
import {
  phaseProgress, phaseStepLabel, type PhaseStepInput,
} from '@/lib/processPhaseProgress'

const PHASEN: PhaseStepInput[] = [
  { key: 'antrag', label: 'Antrag' },
  { key: 'pruefung', label: 'Prüfung' },
  { key: 'umsetzung', label: 'Umsetzung' },
]

describe('phaseProgress – laufender Auftrag', () => {
  it('zählt ab 1 und markiert genau eine Phase als aktuell', () => {
    const v = phaseProgress(PHASEN, 1)
    expect(v.text).toBe('Phase 2 von 3')
    expect(v.position).toBe(2)
    expect(v.total).toBe(3)
    expect(v.finished).toBe(false)
    expect(v.steps.map((s) => s.status)).toEqual(['done', 'current', 'pending'])
    expect(v.steps.map((s) => s.number)).toEqual([1, 2, 3])
  })

  it('nimmt die Namen aus der Definition und fällt auf den Schlüssel zurück', () => {
    const v = phaseProgress([{ key: 'ohne_label' }, { key: 'x', label: '' }], 0)
    expect(v.steps.map((s) => s.label)).toEqual(['ohne_label', 'x'])
  })
})

describe('phaseProgress – fertiger Auftrag', () => {
  it('kappt „Phase X von Y" beim Index == Anzahl Phasen', () => {
    const v = phaseProgress(PHASEN, 3)
    expect(v.finished).toBe(true)
    expect(v.position).toBe(3)
    expect(v.text).toBe('Alle 3 Phasen durchlaufen')
    expect(v.steps.every((s) => s.status === 'done')).toBe(true)
  })

  it('formuliert den Einphasen-Prozess ohne Zahl', () => {
    expect(phaseProgress([{ key: 'nur_eine' }], 1).text).toBe('Phase durchlaufen')
  })

  it('kappt auch einen zu großen Index (Definition gekürzt)', () => {
    const v = phaseProgress(PHASEN, 99)
    expect(v.position).toBe(3)
    expect(v.finished).toBe(true)
  })
})

describe('phaseProgress – abgelehnter Auftrag', () => {
  it('zeigt die erreichte Phase als gestoppt, nicht als aktuell', () => {
    const v = phaseProgress(PHASEN, 1, { rejected: true })
    expect(v.rejected).toBe(true)
    expect(v.text).toBe('Abgelehnt in Phase 2 von 3')
    expect(v.steps.map((s) => s.status)).toEqual(['done', 'stopped', 'pending'])
  })
})

describe('phaseProgress – kaputte Eingaben', () => {
  it('ohne Phasen keine erfundene Zählung', () => {
    const v = phaseProgress([], 0)
    expect(v.total).toBe(0)
    expect(v.position).toBe(0)
    expect(v.finished).toBe(false)
    expect(v.text).toBe('Keine Phasen hinterlegt')
  })

  it('null/undefined und unbrauchbare Indizes landen bei Phase 1', () => {
    expect(phaseProgress(null, null).text).toBe('Keine Phasen hinterlegt')
    expect(phaseProgress(PHASEN, undefined).position).toBe(1)
    expect(phaseProgress(PHASEN, -5).position).toBe(1)
    expect(phaseProgress(PHASEN, Number.NaN).position).toBe(1)
    expect(phaseProgress(PHASEN, 1.7).position).toBe(2)
  })

  it('überspringt Einträge ohne Schlüssel (sonst kein stabiles :key)', () => {
    const kaputt = [{ key: 'a' }, null, { key: '' }, { key: 'b' }] as unknown as PhaseStepInput[]
    expect(phaseProgress(kaputt, 0).steps.map((s) => s.key)).toEqual(['a', 'b'])
  })
})

describe('phaseStepLabel', () => {
  it('beschriftet jeden Stand deutsch', () => {
    expect(phaseStepLabel('done')).toBe('Erledigt')
    expect(phaseStepLabel('current')).toBe('Aktuell')
    expect(phaseStepLabel('stopped')).toBe('Hier gestoppt')
    expect(phaseStepLabel('pending')).toBe('Ausstehend')
  })
})
