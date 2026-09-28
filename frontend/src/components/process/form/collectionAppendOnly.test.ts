import { describe, it, expect } from 'vitest'
import {
  isLockedEntry, toEntries, withNewEntry, withSubValue, withoutEntry,
} from './CollectionWidget.vue'

/**
 * Regression: die Sperre für „nur anhängen" darf sich NUR auf bereits
 * gespeicherte Einträge beziehen. Früher übernahm ein Watcher die Länge des
 * ersten eintreffenden Arrays – und das war das Array, das das Widget beim
 * Klick auf „Eintrag hinzufügen" selbst erzeugt hatte. Ergebnis: der allererste
 * Eintrag sperrte sich sofort selbst und war weder ausfüllbar noch löschbar.
 */
describe('isLockedEntry', () => {
  it('sperrt nur, was schon gespeichert war', () => {
    // Grundlinie 0 (neues Formular): nichts ist gesperrt
    expect(isLockedEntry(0, 0, true)).toBe(false)
    expect(isLockedEntry(3, 0, true)).toBe(false)
    // Grundlinie 2 (zwei gespeicherte Einträge): die ersten beiden sind fix
    expect(isLockedEntry(0, 2, true)).toBe(true)
    expect(isLockedEntry(1, 2, true)).toBe(true)
    expect(isLockedEntry(2, 2, true)).toBe(false)
  })

  it('sperrt nie, wenn append_only aus ist', () => {
    expect(isLockedEntry(0, 5, false)).toBe(false)
  })
})

describe('Listen-Operationen sind unveränderlich', () => {
  const base = [{ text: 'a' }, { text: 'b' }]

  it('toEntries macht aus Unbrauchbarem stabile Zeilen', () => {
    expect(toEntries(null)).toEqual([])
    expect(toEntries('quatsch')).toEqual([])
    expect(toEntries([{ a: 1 }, 'x', null])).toEqual([{ a: 1 }, {}, {}])
  })

  it('withNewEntry hängt an, ohne das Original zu ändern', () => {
    const next = withNewEntry(base)
    expect(next).toHaveLength(3)
    expect(next[2]).toEqual({})
    expect(base).toHaveLength(2)
    expect(next[0]).not.toBe(base[0])
  })

  it('withSubValue ändert nur die gemeinte Zeile', () => {
    const next = withSubValue(base, 1, 'text', 'neu')
    expect(next[1].text).toBe('neu')
    expect(base[1].text).toBe('b')
  })

  it('withoutEntry entfernt genau eine Zeile', () => {
    expect(withoutEntry(base, 0)).toEqual([{ text: 'b' }])
    expect(base).toHaveLength(2)
  })
})
