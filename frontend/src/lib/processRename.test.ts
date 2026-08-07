import { describe, it, expect } from 'vitest'
import { normalizeDefinition } from './processNormalize'
import { renameRefsInCondition, renameRefsInDefinition } from './processRename'

/**
 * Regression: früher wurde per JSON.parse-Reviver JEDER String ersetzt, der dem
 * alten Schlüssel glich – das benannte fremde Felder, Phasen-Schlüssel,
 * Options-Werte und sogar den Prozess-Key still mit um.
 */
const DEFN = normalizeDefinition({
  key: 'urlaub',
  name: 'Urlaub',
  fields: [
    { key: 'urlaub', widget: 'text' },                       // gleicht dem Prozess-Key
    { key: 'pruefung', widget: 'select',
      options: [{ value: 'urlaub' }, { value: 'sonstiges' }] },  // Options-WERT gleicht dem Feld-Key
    { key: 'kopie', widget: 'text', computed: { from: 'urlaub' } },
  ],
  phases: [
    { key: 'pruefung', kind: 'start', responsibility: { kind: 'owner' },   // Phasen-Key = Feld-Key
      fields: [
        { ref: 'urlaub', required: true },
        { ref: 'pruefung', visibleWhen: { '==': ['urlaub', 'urlaub'] } },   // ref UND Wert gleich
      ],
      constraints: [{ when: { truthy: 'urlaub' }, message: 'urlaub fehlt' }],
      automations: [{ id: 'a1', trigger: { type: 'on_field_change', field: 'urlaub' },
        guard: { in: ['urlaub', ['urlaub']] },
        action: { type: 'set_field', field: 'urlaub', value: 'urlaub' } }] },
  ],
})

const R = renameRefsInDefinition(DEFN, 'urlaub', 'urlaubstage')

describe('renameRefsInDefinition – benennt nur echte Referenzen um', () => {
  it('benennt den Feld-Schlüssel um', () => {
    expect(R.fields[0].key).toBe('urlaubstage')
  })

  it('lässt den Prozess-Key unangetastet', () => {
    expect(R.key).toBe('urlaub')
  })

  it('lässt gleichnamige Phasen-Schlüssel unangetastet', () => {
    expect(R.phases[0].key).toBe('pruefung')
  })

  it('lässt Options-Werte unangetastet', () => {
    expect(R.fields[1].options.map((o) => o.value)).toEqual(['urlaub', 'sonstiges'])
  })

  it('lässt Meldungstexte unangetastet', () => {
    expect(R.phases[0].constraints[0].message).toBe('urlaub fehlt')
  })

  it('zieht Phasen-Referenzen nach', () => {
    expect(R.phases[0].fields[0].ref).toBe('urlaubstage')
    expect(R.phases[0].fields[1].ref).toBe('pruefung')     // fremdes Feld unberührt
  })

  it('zieht computed.from nach', () => {
    expect(R.fields[2].computed).toEqual({ from: 'urlaubstage' })
  })

  it('ersetzt in Bedingungen NUR die Feld-Referenz, nicht den Vergleichswert', () => {
    expect(R.phases[0].fields[1].visibleWhen).toEqual({ '==': ['urlaubstage', 'urlaub'] })
    expect(R.phases[0].constraints[0].when).toEqual({ truthy: 'urlaubstage' })
  })

  it('zieht Automations-Referenzen nach, aber nicht action.value', () => {
    const a = R.phases[0].automations[0]
    expect(a.trigger.field).toBe('urlaubstage')
    expect(a.guard).toEqual({ in: ['urlaubstage', ['urlaub']] })   // Wertliste bleibt
    expect(a.action.field).toBe('urlaubstage')
    expect(a.action.value).toBe('urlaub')                          // Wert bleibt
  })
})

describe('renameRefsInCondition – rekursiv', () => {
  it('geht durch and/or/not', () => {
    const c = { and: [{ truthy: 'a' }, { or: [{ '==': ['a', 'a'] }, { not: { truthy: 'a' } }] }] }
    expect(renameRefsInCondition(c, 'a', 'b')).toEqual({
      and: [{ truthy: 'b' }, { or: [{ '==': ['b', 'a'] }, { not: { truthy: 'b' } }] }],
    })
  })

  it('lässt Unbekanntes unverändert', () => {
    expect(renameRefsInCondition(null, 'a', 'b')).toBeNull()
    expect(renameRefsInCondition({ komisch: 1 } as any, 'a', 'b')).toEqual({ komisch: 1 })
  })
})
