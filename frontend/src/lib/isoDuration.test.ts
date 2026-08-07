import { describe, it, expect } from 'vitest'
import { formatDuration, humanDuration, isValidDuration, parseDuration } from './isoDuration'

describe('parseDuration – muss mit backend/services/iso_duration.py übereinstimmen', () => {
  it.each([
    ['P7D', 7 * 86400], ['P14D', 14 * 86400], ['PT12H', 12 * 3600],
    ['P1W', 604800], ['PT30M', 1800], ['P1DT6H', 86400 + 6 * 3600], ['PT45S', 45],
  ])('%s → %i s', (txt, secs) => {
    expect(parseDuration(txt)).toBe(secs)
  })

  it.each(['', '7D', 'P', 'PT', 'abc', 'P1M1D', 'P1Y'])('lehnt %s ab', (bad) => {
    expect(parseDuration(bad)).toBeNull()
  })

  it('Monate/Jahre sind bewusst nicht unterstützt (variable Länge)', () => {
    expect(parseDuration('P1M')).toBeNull()
  })
})

describe('isValidDuration', () => {
  it('verlangt zusätzlich > 0 (wie der Server)', () => {
    expect(isValidDuration('P7D')).toBe(true)
    expect(isValidDuration('P0D')).toBe(false)
    expect(isValidDuration('PT0S')).toBe(false)
    expect(isValidDuration('P1M')).toBe(false)
  })
})

describe('formatDuration', () => {
  it('baut kompakte ISO-Dauern', () => {
    expect(formatDuration(7 * 86400)).toBe('P7D')
    expect(formatDuration(12 * 3600)).toBe('PT12H')
    expect(formatDuration(86400 + 6 * 3600)).toBe('P1DT6H')
    expect(formatDuration(90)).toBe('PT1M30S')
    expect(formatDuration(0)).toBe('')
  })

  it('ist zu parseDuration invers', () => {
    for (const s of [60, 3600, 86400, 7 * 86400, 90061]) {
      expect(parseDuration(formatDuration(s))).toBe(s)
    }
  })
})

describe('humanDuration', () => {
  it('schreibt es lesbar aus', () => {
    expect(humanDuration('P7D')).toBe('7 Tage')
    expect(humanDuration('P1D')).toBe('1 Tag')
    expect(humanDuration('PT12H')).toBe('12 Stunden')
    expect(humanDuration('P1DT6H')).toBe('1 Tag 6 Stunden')
    expect(humanDuration('kaputt')).toBe('—')
  })
})
