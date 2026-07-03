import { describe, it, expect } from 'vitest'
import {
  labelize, fieldLabel, formatVal, isText, commentVerb, flatten, descriptionDiff,
} from './historyDiff'

describe('labelize', () => {
  it('macht aus snake_case einen Titel', () => {
    expect(labelize('first_name')).toBe('First Name')
    expect(labelize('foo')).toBe('Foo')
  })
})

describe('fieldLabel', () => {
  it('nutzt FIELD_LABEL für Top-Level-Felder', () => {
    expect(fieldLabel('comment')).toBe('Kommentar')
    expect(fieldLabel('priority')).toBe('Priorität')
  })
  it('nutzt das letzte Segment aus DE_FIELD_LABELS', () => {
    expect(fieldLabel('it.software.datev')).toBe('DATEV-Zugriff')
    expect(fieldLabel('personal.first_name')).toBe('Vorname')
  })
  it('mappt *_name-Beziehungen lesbar', () => {
    expect(fieldLabel('personal.supervisor_hr_name')).toBe('Vorgesetzter')
  })
  it('fällt auf labelize zurück', () => {
    expect(fieldLabel('some.unknown_field')).toBe('Unknown Field')
  })
})

describe('formatVal', () => {
  it('leer/none → Strich', () => {
    expect(formatVal(null)).toBe('—')
    expect(formatVal(undefined)).toBe('—')
    expect(formatVal('')).toBe('—')
  })
  it('boolean → Ja/Nein', () => {
    expect(formatVal(true)).toBe('Ja')
    expect(formatVal(false)).toBe('Nein')
  })
  it('objekt → Strich', () => {
    expect(formatVal({ a: 1 })).toBe('—')
  })
  it('string/zahl unverändert', () => {
    expect(formatVal('x')).toBe('x')
    expect(formatVal(5)).toBe('5')
  })
})

describe('isText', () => {
  it('erkennt nicht-leeren Text', () => {
    expect(isText('hallo')).toBe(true)
    expect(isText('  x ')).toBe(true)
  })
  it('leer/whitespace/none → false', () => {
    expect(isText('')).toBe(false)
    expect(isText('   ')).toBe(false)
    expect(isText(null)).toBe(false)
    expect(isText(undefined)).toBe(false)
  })
})

describe('commentVerb', () => {
  it('leer → Text = hinzugefügt', () => {
    expect(commentVerb({ old: '', new: 'hi' })).toBe('Kommentar hinzugefügt')
  })
  it('Text → leer = entfernt', () => {
    expect(commentVerb({ old: 'hi', new: '' })).toBe('Kommentar entfernt')
  })
  it('Text → anderer Text = geändert', () => {
    expect(commentVerb({ old: 'a', new: 'b' })).toBe('Kommentar geändert')
  })
})

describe('flatten', () => {
  it('flacht verschachtelte Objekte auf Punkt-Pfade', () => {
    expect(flatten({ it: { software: { datev: true } } })).toEqual({ 'it.software.datev': true })
  })
  it('Arrays bleiben ganz', () => {
    expect(flatten({ tags: ['a', 'b'] })).toEqual({ tags: ['a', 'b'] })
  })
  it('null-Werte bleiben erhalten', () => {
    expect(flatten({ x: null })).toEqual({ x: null })
  })
})

describe('descriptionDiff', () => {
  it('liefert nur geänderte Felder', () => {
    const d = descriptionDiff({ a: '1', b: '2' }, { a: '1', b: '3' })
    expect(d.map(x => x.key)).toEqual(['b'])
    expect(d[0].newVal).toBe('3')
  })
  it('ignoriert interne _-Meta-Felder (z.B. _next_assignee)', () => {
    const d = descriptionDiff({}, { _next_assignee: { id: 'x', name: 'Max' } })
    expect(d).toEqual([])
  })
  it('ignoriert rohe ID-Felder', () => {
    const d = descriptionDiff(
      { personal: { supervisor_hr_id: 'A' } },
      { personal: { supervisor_hr_id: 'B' } },
    )
    expect(d).toEqual([])
  })
  it('zeigt die lesbare *_name-Änderung', () => {
    const d = descriptionDiff(
      { personal: { supervisor_hr_name: 'Alt' } },
      { personal: { supervisor_hr_name: 'Neu' } },
    )
    expect(d).toHaveLength(1)
    expect(d[0].label).toBe('Vorgesetzter')
    expect(d[0].newVal).toBe('Neu')
  })
  it('boolean false → true wird angezeigt', () => {
    const d = descriptionDiff(
      { it: { software: { datev: false } } },
      { it: { software: { datev: true } } },
    )
    expect(d).toHaveLength(1)
    expect(d[0].label).toBe('DATEV-Zugriff')
    expect(d[0].newVal).toBe(true)
  })
  it('leer → leer wird ignoriert', () => {
    expect(descriptionDiff({ x: '' }, { x: null })).toEqual([])
  })
  it('Wert → leer (sinnvoller Alt-Wert) wird gezeigt', () => {
    const d = descriptionDiff({ x: 'da' }, { x: '' })
    expect(d).toHaveLength(1)
  })
})
