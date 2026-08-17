/**
 * Baukasten-Operationen: die EINE Aktion je Absicht muss alle drei Ebenen
 * (Katalog · Phasen-Einbindung · Platzierung) synchron halten – genau die
 * Auseinanderläufe, die der alte Editor mit vier getrennten „Hinzufügen"-Wegen
 * produziert hat.
 */
import { describe, expect, it } from 'vitest'
import {
  REST_SECTION, addExistingField, addNewField, deleteFieldEverywhere,
  moveBuilderItem, patchRef, phasesUsing, pruneOrphans, removeFieldFromPhase,
  restRefs, suggestFieldKey,
} from '@/lib/processBuilder'
import { normalizeDefinition } from '@/lib/processNormalize'
import type { ProcessDefinition } from '@/types/process'

function defn(over: Record<string, unknown> = {}): ProcessDefinition {
  return normalizeDefinition({
    key: 'p', name: 'P',
    fields: [{ key: 'a', widget: 'text' }, { key: 'b', widget: 'number' }],
    phases: [
      {
        key: 'eins', kind: 'start', responsibility: { kind: 'owner' },
        fields: [{ ref: 'a' }, { ref: 'b' }],
        layout: [{ type: 'section', title: 'S1', items: [{ type: 'field', ref: 'a' }] }],
      },
      { key: 'zwei', kind: 'task', responsibility: { kind: 'owner' }, fields: [{ ref: 'a' }] },
    ],
    ...over,
  })
}

describe('restRefs', () => {
  it('nennt die Felder der Phase, die nirgends platziert sind', () => {
    expect(restRefs(defn().phases[0])).toEqual(['b'])
    // Phase ohne Layout: ALLES ist Rest (Standarddarstellung).
    expect(restRefs(defn().phases[1])).toEqual(['a'])
  })
})

describe('addNewField', () => {
  it('legt Katalog-Eintrag, Einbindung und Platzierung in EINEM Schritt an', () => {
    const { defn: d, key } = addNewField(defn(), 0, 0, 'date')
    expect(key).toBe('feld_1')
    expect(d.fields.map((f) => f.key)).toEqual(['a', 'b', 'feld_1'])
    expect(d.fields[2].widget).toBe('date')
    expect(d.phases[0].fields.map((f) => f.ref)).toEqual(['a', 'b', 'feld_1'])
    expect(d.phases[0].layout[0].items.at(-1)).toMatchObject({ type: 'field', ref: 'feld_1' })
  })

  it('Ziel Rest-Abschnitt: eingebunden, aber unplatziert', () => {
    const { defn: d } = addNewField(defn(), 0, REST_SECTION, 'text')
    expect(restRefs(d.phases[0])).toEqual(['b', 'feld_1'])
    // andere Phasen bleiben unangetastet
    expect(d.phases[1].fields.map((f) => f.ref)).toEqual(['a'])
  })

  it('schlägt fortlaufend freie Schlüssel vor', () => {
    const d = defn({ fields: [{ key: 'feld_1', widget: 'text' }] })
    expect(suggestFieldKey(d)).toBe('feld_2')
  })
})

describe('addExistingField', () => {
  it('bindet ein Katalog-Feld ein und platziert es', () => {
    const d = addExistingField(defn(), 1, REST_SECTION, 'b')
    expect(d.phases[1].fields.map((f) => f.ref)).toEqual(['a', 'b'])
  })

  it('lehnt Unbekanntes und Doppeltes referenzgleich ab', () => {
    const d = defn()
    expect(addExistingField(d, 0, 0, 'gibtsnicht')).toBe(d)
    expect(addExistingField(d, 0, 0, 'a')).toBe(d)
  })
})

describe('removeFieldFromPhase / deleteFieldEverywhere', () => {
  it('nimmt Einbindung UND Platzierung aus der Phase, lässt den Katalog stehen', () => {
    const d = removeFieldFromPhase(defn(), 0, 'a')
    expect(d.fields.map((f) => f.key)).toEqual(['a', 'b'])
    expect(d.phases[0].fields.map((f) => f.ref)).toEqual(['b'])
    expect(d.phases[0].layout[0].items).toEqual([])
    // Phase 2 nutzt „a" weiter.
    expect(d.phases[1].fields.map((f) => f.ref)).toEqual(['a'])
  })

  it('löscht überall: Katalog, jede Einbindung, jede Platzierung', () => {
    const d = deleteFieldEverywhere(defn(), 'a')
    expect(d.fields.map((f) => f.key)).toEqual(['b'])
    expect(d.phases[0].fields.map((f) => f.ref)).toEqual(['b'])
    expect(d.phases[1].fields).toEqual([])
    expect(d.phases[0].layout[0].items).toEqual([])
  })

  it('phasesUsing beantwortet die Lösch-Rückfrage', () => {
    expect(phasesUsing(defn(), 'a')).toEqual(['eins', 'zwei'])
    expect(phasesUsing(defn(), 'b')).toEqual(['eins'])
  })
})

describe('moveBuilderItem', () => {
  it('Rest → Abschnitt platziert das Feld an der Zielposition', () => {
    const d = moveBuilderItem(defn(), 0, { section: REST_SECTION, item: 0 },
                              { section: 0, item: 0 })
    expect(d.phases[0].layout[0].items.map((it) => it.type === 'field' ? it.ref : '?'))
      .toEqual(['b', 'a'])
    expect(restRefs(d.phases[0])).toEqual([])
  })

  it('Abschnitt → Rest löst die Platzierung, behält die Einbindung', () => {
    const d = moveBuilderItem(defn(), 0, { section: 0, item: 0 },
                              { section: REST_SECTION, item: 0 })
    expect(d.phases[0].layout[0].items).toEqual([])
    expect(restRefs(d.phases[0])).toEqual(['a', 'b'])
  })

  it('verschiebt innerhalb eines Abschnitts mit Index-Korrektur', () => {
    let d = moveBuilderItem(defn(), 0, { section: REST_SECTION, item: 0 },
                            { section: 0, item: 1 })   // S1: [a, b]
    d = moveBuilderItem(d, 0, { section: 0, item: 0 }, { section: 0, item: 2 })
    expect(d.phases[0].layout[0].items.map((it) => it.type === 'field' ? it.ref : '?'))
      .toEqual(['b', 'a'])
  })

  it('Rest → Rest sortiert die unplatzierten FieldRefs um', () => {
    const base = defn({
      phases: [{ key: 'eins', kind: 'start', responsibility: { kind: 'owner' },
                 fields: [{ ref: 'a' }, { ref: 'b' }] }],
    })
    const d = moveBuilderItem(base, 0, { section: REST_SECTION, item: 1 },
                              { section: REST_SECTION, item: 0 })
    expect(d.phases[0].fields.map((f) => f.ref)).toEqual(['b', 'a'])
  })
})

describe('patchRef / pruneOrphans', () => {
  it('ändert die Einstellungen einer Einbindung über den Key', () => {
    const d = patchRef(defn(), 0, 'b', { required: true, mode: 'readonly' })
    const ref = d.phases[0].fields.find((f) => f.ref === 'b')
    expect(ref).toMatchObject({ required: true, mode: 'readonly' })
  })

  it('räumt verwaiste Platzierungen auf, fasst Intaktes nicht an', () => {
    const kaputt = defn({
      phases: [{
        key: 'eins', kind: 'start', responsibility: { kind: 'owner' },
        fields: [{ ref: 'a' }],
        layout: [{ type: 'section', title: 'S1',
                   items: [{ type: 'field', ref: 'a' }, { type: 'field', ref: 'tot' }] }],
      }],
    })
    const d = pruneOrphans(kaputt, 0)
    expect(d.phases[0].layout[0].items.map((it) => it.type === 'field' ? it.ref : '?'))
      .toEqual(['a'])
    // Ohne Waisen: referenzgleich (kein unnötiges dirty).
    expect(pruneOrphans(d, 0)).toBe(d)
  })
})
