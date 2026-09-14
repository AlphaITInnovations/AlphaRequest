import { describe, expect, it } from 'vitest'
import type { FieldDef } from '@/types/process'
import { fieldValueText, formatIsoDate, subValueText } from '@/lib/processFieldFormat'

const dateField = { key: 'd', widget: 'date' } as unknown as FieldDef
const textField = { key: 't', widget: 'text' } as unknown as FieldDef

describe('formatIsoDate', () => {
  it('wandelt ISO-Datum in deutsches Format', () => {
    expect(formatIsoDate('2026-08-24')).toBe('24.08.2026')
  })
  it('wandelt ISO-Datum+Zeit in deutsches Format', () => {
    expect(formatIsoDate('2026-08-24T09:05')).toBe('24.08.2026 09:05')
    expect(formatIsoDate('2026-08-24 09:05:00')).toBe('24.08.2026 09:05')
  })
  it('lässt Nicht-Datums-Strings unverändert', () => {
    expect(formatIsoDate('Nürnberg')).toBe('Nürnberg')
    expect(formatIsoDate('2026')).toBe('2026')
    expect(formatIsoDate('24.08.2026')).toBe('24.08.2026')
  })
})

describe('fieldValueText / subValueText mit Datum', () => {
  it('Datumsfeld wird deutsch dargestellt', () => {
    expect(fieldValueText(dateField, '2026-08-24')).toBe('24.08.2026')
  })
  it('ISO-artiger Wert wird auch ohne Datums-Widget deutsch dargestellt', () => {
    expect(fieldValueText(textField, '2026-08-24')).toBe('24.08.2026')
  })
  it('Unterfeld-Datum (Wiederholgruppe) wird deutsch dargestellt', () => {
    expect(subValueText('2026-08-24')).toBe('24.08.2026')
  })
})

describe('fieldValueText – Directus-Felder lösen die ID zum Label auf', () => {
  const dirField = { key: 'firma', widget: 'directus', directusSource: 'firmen' } as unknown as FieldDef
  const sources = {
    groups: [], users: [], companies: [],
    directusLabels: { firmen: { 'a1b2': 'Alpha GmbH' } },
  }

  it('zeigt das aufgelöste Label statt der gespeicherten ID', () => {
    expect(fieldValueText(dirField, 'a1b2', sources)).toBe('Alpha GmbH')
  })

  it('fällt auf die ID zurück, wenn kein Label vorliegt (Directus down / unbekannt)', () => {
    expect(fieldValueText(dirField, 'x9', sources)).toBe('x9')
    expect(fieldValueText(dirField, 'a1b2', { groups: [], users: [], companies: [] })).toBe('a1b2')
  })
})

describe('fieldValueText – directus_multi zeigt die Labels der Liste', () => {
  const multi = { key: 'nl', widget: 'directus_multi', directusSource: 'niederlassung' } as unknown as FieldDef
  const sources = {
    groups: [], users: [], companies: [],
    directusLabels: { niederlassung: { n1: 'Nürnberg', n2: 'München' } },
  }
  it('löst jede ID zum Label auf und verbindet mit Komma', () => {
    expect(fieldValueText(multi, ['n1', 'n2'], sources)).toBe('Nürnberg, München')
  })
  it('fällt je Eintrag auf die ID zurück, wenn kein Label vorliegt', () => {
    expect(fieldValueText(multi, ['n1', 'x9'], sources)).toBe('Nürnberg, x9')
  })
})
