import { describe, it, expect } from 'vitest'
import { evaluate, isEmpty, applyComputed } from './conditionDsl'

describe('evaluate (condition DSL, mirror of backend)', () => {
  const v = { 'fuhrpark.car': 'Ja', 'it.datev': true }

  it('handles all operators', () => {
    expect(evaluate({ '==': ['fuhrpark.car', 'Ja'] }, v)).toBe(true)
    expect(evaluate({ '!=': ['fuhrpark.car', 'Nein'] }, v)).toBe(true)
    expect(evaluate({ truthy: 'it.datev' }, v)).toBe(true)
    expect(evaluate({ truthy: 'missing' }, v)).toBe(false)
    expect(evaluate({ in: ['fuhrpark.car', ['Ja', 'X']] }, v)).toBe(true)
    expect(evaluate({ and: [{ truthy: 'it.datev' }, { '==': ['fuhrpark.car', 'Ja'] }] }, v)).toBe(true)
    expect(evaluate({ or: [{ truthy: 'missing' }, { '==': ['fuhrpark.car', 'Nein'] }] }, v)).toBe(false)
    expect(evaluate({ not: { truthy: 'missing' } }, v)).toBe(true)
  })

  it('rejects malformed conditions', () => {
    expect(evaluate(null, v)).toBe(false)
    expect(evaluate({} as any, v)).toBe(false)
    expect(evaluate({ '==': ['a', 1], or: [] } as any, v)).toBe(false)
    expect(evaluate({ unknown: [1] } as any, v)).toBe(false)
  })

  it('matches Python semantics (truthy of empties, value-equality)', () => {
    // truthy: [] und {} und 0 und false sind falsy (wie Python bool())
    expect(evaluate({ truthy: 'e' }, { e: [] })).toBe(false)
    expect(evaluate({ truthy: 'e' }, { e: {} })).toBe(false)
    expect(evaluate({ truthy: 'e' }, { e: 0 })).toBe(false)
    expect(evaluate({ truthy: 'e' }, { e: false })).toBe(false)
    expect(evaluate({ truthy: 'e' }, { e: 'x' })).toBe(true)
    // == mit fehlendem Key == null; Arrays wertgleich
    expect(evaluate({ '==': ['missing', null] }, {})).toBe(true)
    expect(evaluate({ '==': ['a', [1, 2]] }, { a: [1, 2] })).toBe(true)
    expect(evaluate({ in: ['a', [[1], [2]]] }, { a: [2] })).toBe(true)
  })
})

describe('isEmpty', () => {
  it('detects empties', () => {
    for (const e of [null, undefined, '', [], {}]) expect(isEmpty(e)).toBe(true)
    for (const x of ['x', 0, false, [1], { a: 1 }]) expect(isEmpty(x)).toBe(false)
  })
})

describe('applyComputed (mirror of backend)', () => {
  const fields = [
    { key: 'sig.title', computed: { from: 'base.title' }, overridable: true },
    { key: 'mirror.title', computed: { from: 'base.title' } },
    { key: 'plain', computed: null },
  ]

  it('fills overridable when empty, keeps manual value', () => {
    expect(applyComputed(fields, { 'base.title': 'Dr.' })['sig.title']).toBe('Dr.')
    expect(applyComputed(fields, { 'base.title': 'Dr.', 'sig.title': 'Prof.' })['sig.title']).toBe('Prof.')
  })

  it('non-overridable always derives', () => {
    expect(applyComputed(fields, { 'base.title': 'Dr.', 'mirror.title': 'x' })['mirror.title']).toBe('Dr.')
  })

  it('map übersetzt den Quellwert; nicht gemappt / Nicht-String / Prototype → null', () => {
    const mapped = [{ key: 'grp', computed: { from: 'pos', map: { Disposition: 'Gruppe 1' } } }]
    expect(applyComputed(mapped, { pos: 'Disposition' }).grp).toBe('Gruppe 1')
    expect(applyComputed(mapped, { pos: 'Werkstudium' }).grp).toBeNull()
    // Parität zum Backend (map.get): Nicht-String und Prototype-Namen treffen NICHT
    expect(applyComputed(mapped, { pos: 2 as unknown as string }).grp).toBeNull()
    expect(applyComputed(mapped, { pos: 'toString' }).grp).toBeNull()
  })
})
