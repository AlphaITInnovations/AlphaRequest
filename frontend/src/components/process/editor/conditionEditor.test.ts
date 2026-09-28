/**
 * Tests der reinen Logik hinter ConditionEditor/ConditionSummary.
 *
 * Es gibt in diesem Projekt bewusst keine Komponenten-Tests (kein
 * @vue/test-utils, kein jsdom) – geprüft wird deshalb das ausgelagerte
 * Modul lib/conditionSummary.ts.
 */
import { describe, it, expect } from 'vitest'
import {
  CONDITION_ALWAYS, CONDITION_INVALID, formatConditionValue, summarizeCondition,
} from '../../../lib/conditionSummary'

const LABELS: Record<string, string> = {
  'fuhrpark.car': 'Dienstwagen',
  'it.rechte': 'IT-Rechte',
}

describe('summarizeCondition – Grundfälle', () => {
  it('ohne Bedingung „immer"', () => {
    expect(summarizeCondition(null)).toBe(CONDITION_ALWAYS)
    expect(summarizeCondition(undefined)).toBe(CONDITION_ALWAYS)
  })

  it('nutzt den Schlüssel, wenn es kein Label gibt', () => {
    expect(summarizeCondition({ '==': ['fuhrpark.car', 'Ja'] })).toBe('fuhrpark.car ist gleich "Ja"')
  })

  it('nutzt das Label, wenn vorhanden', () => {
    expect(summarizeCondition({ '==': ['fuhrpark.car', 'Ja'] }, LABELS))
      .toBe('Dienstwagen ist gleich "Ja"')
    expect(summarizeCondition({ truthy: 'it.rechte' }, LABELS)).toBe('IT-Rechte ist gesetzt')
  })

  it('markiert ein noch nicht gewähltes Feld', () => {
    expect(summarizeCondition({ truthy: '' })).toBe('(kein Feld) ist gesetzt')
    expect(summarizeCondition({ '==': ['', ''] })).toBe('(kein Feld) ist gleich ""')
  })
})

describe('summarizeCondition – alle Operatoren', () => {
  it('== und !=', () => {
    expect(summarizeCondition({ '==': ['a', 'x'] })).toBe('a ist gleich "x"')
    expect(summarizeCondition({ '!=': ['a', 'x'] })).toBe('a ist ungleich "x"')
  })

  it('in mit Werteliste', () => {
    expect(summarizeCondition({ in: ['a', ['x', 'y']] })).toBe('a ist eine von "x", "y"')
    expect(summarizeCondition({ in: ['a', []] })).toBe('a ist eine von (leere Liste)')
  })

  it('truthy', () => {
    expect(summarizeCondition({ truthy: 'a' })).toBe('a ist gesetzt')
  })

  it('and und or klammern', () => {
    const and = { and: [{ truthy: 'a' }, { truthy: 'b' }] }
    expect(summarizeCondition(and)).toBe('(a ist gesetzt UND b ist gesetzt)')
    const or = { or: [{ truthy: 'a' }, { truthy: 'b' }] }
    expect(summarizeCondition(or)).toBe('(a ist gesetzt ODER b ist gesetzt)')
  })

  it('leere Gruppe bleibt lesbar', () => {
    expect(summarizeCondition({ and: [] })).toBe('(leer)')
  })

  it('not', () => {
    expect(summarizeCondition({ not: { truthy: 'a' } })).toBe('NICHT a ist gesetzt')
  })
})

describe('summarizeCondition – Verschachtelung', () => {
  it('verschachtelte Gruppen behalten ihre Klammern', () => {
    const cond = {
      and: [
        { '==': ['fuhrpark.car', 'Ja'] },
        { or: [{ truthy: 'it.rechte' }, { not: { truthy: 'hr.abschluss' } }] },
      ],
    }
    expect(summarizeCondition(cond, LABELS)).toBe(
      '(Dienstwagen ist gleich "Ja" UND (IT-Rechte ist gesetzt ODER NICHT hr.abschluss ist gesetzt))',
    )
  })

  it('drei Ebenen', () => {
    const cond = { not: { and: [{ or: [{ truthy: 'a' }] }, { truthy: 'b' }] } }
    expect(summarizeCondition(cond)).toBe('NICHT ((a ist gesetzt) UND b ist gesetzt)')
  })
})

describe('summarizeCondition – ungültige Formen', () => {
  it('mehr als ein Operator-Key', () => {
    expect(summarizeCondition({ '==': ['a', 1], truthy: 'b' })).toBe(CONDITION_INVALID)
  })

  it('leeres Objekt und unbekannter Operator', () => {
    expect(summarizeCondition({})).toBe(CONDITION_INVALID)
    expect(summarizeCondition({ gt: ['a', 1] })).toBe(CONDITION_INVALID)
  })

  it('falsch geformte Argumente', () => {
    expect(summarizeCondition({ '==': 'a' })).toBe(CONDITION_INVALID)
    expect(summarizeCondition({ in: ['a', 'x'] })).toBe(CONDITION_INVALID)
    expect(summarizeCondition({ and: 'a' })).toBe(CONDITION_INVALID)
    expect(summarizeCondition({ not: null })).toBe(CONDITION_INVALID)
  })

  it('Arrays sind keine Bedingung', () => {
    expect(summarizeCondition([{ truthy: 'a' }] as unknown as Record<string, any>))
      .toBe(CONDITION_INVALID)
  })
})

describe('formatConditionValue – Typen bleiben unterscheidbar', () => {
  it('Text in Anführungszeichen, Boolean als Ja/Nein', () => {
    expect(formatConditionValue('Ja')).toBe('"Ja"')
    expect(formatConditionValue(true)).toBe('Ja')
    expect(formatConditionValue(false)).toBe('Nein')
  })

  it('Zahlen ohne Anführungszeichen, leer für null', () => {
    expect(formatConditionValue(7)).toBe('7')
    expect(formatConditionValue(0)).toBe('0')
    expect(formatConditionValue(null)).toBe('leer')
    expect(formatConditionValue(undefined)).toBe('leer')
  })

  it('Listen als JSON', () => {
    expect(formatConditionValue(['a', 'b'])).toBe('["a","b"]')
  })

  it('wirkt sich auf die Zusammenfassung aus', () => {
    expect(summarizeCondition({ '==': ['a', true] })).toBe('a ist gleich Ja')
    expect(summarizeCondition({ '==': ['a', 7] })).toBe('a ist gleich 7')
    expect(summarizeCondition({ '==': ['a', '7'] })).toBe('a ist gleich "7"')
  })
})
