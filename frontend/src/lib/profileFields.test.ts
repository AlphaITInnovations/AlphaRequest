import { describe, it, expect } from 'vitest'
import { fmtValue, employeeRows, labelFor } from './profileFields'

describe('fmtValue', () => {
  it('rendert leere Werte als Gedankenstrich', () => {
    expect(fmtValue(null)).toBe('–')
    expect(fmtValue(undefined)).toBe('–')
    expect(fmtValue('')).toBe('–')
    expect(fmtValue([])).toBe('–')
  })
  it('rendert Relationen (Objekt) über den Namen', () => {
    expect(fmtValue({ name: 'AlphaConsult KG', id: 3 })).toBe('AlphaConsult KG')
    expect(fmtValue({ nummer: 'AC 20' })).toBe('AC 20')
  })
  it('rendert Listen und Skalare', () => {
    expect(fmtValue(['a', 'b'])).toBe('a, b')
    expect(fmtValue(true)).toBe('Ja')
    expect(fmtValue(42)).toBe('42')
    expect(fmtValue('Popp')).toBe('Popp')
  })
})

describe('employeeRows', () => {
  it('ist leer ohne Datensatz', () => {
    expect(employeeRows(null)).toEqual([])
  })
  it('bringt bekannte Felder zuerst und übersetzt Labels', () => {
    const rows = employeeRows({ status: 'aktiv', last_name: 'Popp', first_name: 'Helmut',
                                irgendwas_neues: 'x' })
    // Reihenfolge: first_name, last_name, … , dann Unbekanntes
    expect(rows.map((r) => r.key)).toEqual(['first_name', 'last_name', 'status', 'irgendwas_neues'])
    expect(rows[0]).toEqual({ key: 'first_name', label: 'Vorname', value: 'Helmut' })
    expect(rows.find((r) => r.key === 'irgendwas_neues')!.label).toBe('irgendwas_neues')  // Fallback: roher Key
  })
})

describe('labelFor', () => {
  it('kennt bekannte Felder, fällt sonst auf den Key zurück', () => {
    expect(labelFor('cost_center')).toBe('Kostenstelle')
    expect(labelFor('unbekannt')).toBe('unbekannt')
  })
})
