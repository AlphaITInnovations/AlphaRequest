import { describe, it, expect } from 'vitest'
import {
  canonicalJson, cloneDefinition, isSameDefinition, normalizeDefinition, normalizeField,
  normalizeFieldRef,
} from './processNormalize'

describe('normalizeDefinition', () => {
  it('füllt fehlende Keys auf und ist idempotent', () => {
    const once = normalizeDefinition({ key: 'k', name: 'N' })
    const twice = normalizeDefinition(once)
    expect(canonicalJson(once)).toBe(canonicalJson(twice))
    expect(once.fields).toEqual([])
    expect(once.phases).toEqual([])
    expect(once.description).toBeNull()
    expect(once.schemaVersion).toBe(1)
  })

  it('akzeptiert from_ und gibt immer from aus (Python-Alias)', () => {
    const f = normalizeField({ key: 'a', widget: 'text', computed: { from_: 'b' } })
    expect(f.computed).toEqual({ from: 'b' })
    const g = normalizeField({ key: 'a', widget: 'text', computed: { from: 'c' } })
    expect(g.computed).toEqual({ from: 'c' })
  })

  it('kennt die gegensätzlichen required-Defaults', () => {
    // FieldRef.required → false
    expect(normalizeFieldRef({ ref: 'a' }).required).toBe(false)
    // DepartmentRule.required → true
    const d = normalizeDefinition({
      key: 'k', name: 'N',
      phases: [{ key: 'p', kind: 'review', responsibility: { kind: 'departments', rule: [{ group: 'g' }] } }],
    })
    expect(d.phases[0].responsibility.rule[0].required).toBe(true)
  })

  it('behält Extra-Keys in Phasen-Regeln (Server verbietet sie dort nicht)', () => {
    const d = normalizeDefinition({
      key: 'k', name: 'N',
      phases: [{ key: 'p', kind: 'start', responsibility: { kind: 'owner' },
        constraints: [{ when: { truthy: 'a' }, message: 'm', extra: 42 }] }],
    })
    expect((d.phases[0].constraints[0] as any).extra).toBe(42)
  })

  it('normalisiert String-Optionen zu {value,label}', () => {
    const f = normalizeField({ key: 'a', widget: 'select', options: ['Ja', { value: 'Nein', label: 'Nein!' }] })
    expect(f.options).toEqual([{ value: 'Ja', label: null }, { value: 'Nein', label: 'Nein!' }])
  })
})

describe('canonicalJson', () => {
  it('ist unabhängig von der Schlüssel-Reihenfolge', () => {
    expect(canonicalJson({ a: 1, b: { c: 2, d: 3 } }))
      .toBe(canonicalJson({ b: { d: 3, c: 2 }, a: 1 }))
  })

  it('erkennt echte Unterschiede', () => {
    expect(canonicalJson({ a: 1 })).not.toBe(canonicalJson({ a: 2 }))
  })
})

describe('isSameDefinition / cloneDefinition', () => {
  it('vergleicht über die normalisierte Form', () => {
    // Server liefert alle Keys, der Editor baut nur die nötigen – trotzdem gleich.
    expect(isSameDefinition({ key: 'k', name: 'N' },
      { key: 'k', name: 'N', description: null, icon: null, fields: [], phases: [],
        automations: [], schemaVersion: 1 })).toBe(true)
  })

  it('klont ohne geteilte Referenzen', () => {
    const a = normalizeDefinition({ key: 'k', name: 'N', fields: [{ key: 'f', widget: 'text' }] })
    const b = cloneDefinition(a)
    b.fields[0].key = 'geaendert'
    expect(a.fields[0].key).toBe('f')
  })
})
