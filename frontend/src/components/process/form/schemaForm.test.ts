/**
 * Tests des schema-getriebenen Formular-Renderers.
 *
 * Das Projekt hat kein @vue/test-utils (und kein jsdom), deshalb wird nicht
 * gemountet, sondern genau die Logik geprüft, die die Komponenten steuert:
 * renderFields/validateValues aus lib/processSim und die reinen Helfer der
 * Wiederholgruppe aus CollectionWidget.vue.
 */
import { describe, it, expect } from 'vitest'
import { normalizeDefinition } from '@/lib/processNormalize'
import {
  renderFields, validateValues, validatePhaseCompletion, visibleFieldKeys,
} from '@/lib/processSim'
import type { SimViewer } from '@/lib/processSim'
import {
  toEntries, isLockedEntry, withSubValue, withNewEntry, withoutEntry,
} from './CollectionWidget.vue'

const defn = normalizeDefinition({
  schemaVersion: 1,
  key: 'test-prozess',
  name: 'Testprozess',
  fields: [
    { key: 'art', widget: 'select', options: [{ value: 'neu' }, { value: 'alt' }] },
    { key: 'grund', widget: 'textarea', label: 'Grund' },
    { key: 'gehalt', widget: 'number', visibility: { confidential: true, visibleToGroups: ['hr'] } },
    { key: 'tags', widget: 'multiselect', options: [{ value: 'a' }, { value: 'b' }] },
    { key: 'haken', widget: 'checkbox-group', options: [{ value: 'x' }, { value: 'y' }] },
    {
      key: 'verlauf',
      widget: 'collection',
      item: [
        { key: 'text', widget: 'text' },
        { key: 'wer', widget: 'server_stamped', value: 'actor' },
      ],
    },
  ],
  phases: [{
    key: 'start',
    kind: 'start',
    fields: [
      { ref: 'art' },
      { ref: 'grund', requiredWhen: { '==': ['art', 'alt'] } },
      { ref: 'gehalt', visibleWhen: { '==': ['art', 'neu'] } },
      { ref: 'tags' },
      { ref: 'haken', mode: 'readonly' },
      { ref: 'verlauf', mode: 'append_only' },
    ],
  }],
})

const phase = defn.phases[0]

/** Personalabteilung: Mitglied der vertraulichen Gruppe, aber ohne Vollsicht. */
const hr: SimViewer = { fullView: false, isAdmin: false, groupIds: ['hr'] }
/** Fachabteilung mit Vollsicht – das vertrauliche Feld bleibt trotzdem zu. */
const fremd: SimViewer = { fullView: true, isAdmin: false, groupIds: ['it'] }

function row(values: Record<string, unknown>, ctx: SimViewer, key: string) {
  return renderFields(defn, phase, values, ctx).find((r) => r.field.key === key)
}

describe('renderFields – Pflicht per Bedingung', () => {
  it('markiert das Feld erst, wenn requiredWhen zutrifft', () => {
    expect(row({ art: 'neu' }, hr, 'grund')?.required).toBe(false)
    expect(row({ art: 'alt' }, hr, 'grund')?.required).toBe(true)
  })

  it('meldet das leere Pflichtfeld beim Phasenabschluss', () => {
    const errs = validatePhaseCompletion(defn, phase, { art: 'alt' })
    expect(errs.some((e) => e.path === 'grund' && e.code === 'REQUIRED')).toBe(true)
    expect(validatePhaseCompletion(defn, phase, { art: 'neu' }).length).toBe(0)
  })
})

describe('renderFields – visibleWhen', () => {
  it('blendet das Feld aus, solange die Bedingung nicht erfüllt ist', () => {
    expect(row({ art: 'alt' }, hr, 'gehalt')?.visible).toBe(false)
    expect(row({ art: 'neu' }, hr, 'gehalt')?.visible).toBe(true)
  })

  it('mode=readonly bleibt sichtbar, aber nicht bearbeitbar', () => {
    const r = row({ art: 'neu' }, hr, 'haken')
    expect(r?.visible).toBe(true)
    expect(r?.editable).toBe(false)
  })
})

describe('Vertrauliche Felder', () => {
  it('verbirgt sie vor Nicht-Mitgliedern – auch bei Vollsicht', () => {
    expect(visibleFieldKeys(defn, fremd).has('gehalt')).toBe(false)
    expect(row({ art: 'neu' }, fremd, 'gehalt')?.visible).toBe(false)
  })

  it('zeigt sie Mitgliedern der berechtigten Gruppe', () => {
    expect(visibleFieldKeys(defn, hr).has('gehalt')).toBe(true)
  })
})

describe('Listen-Widgets senden immer ein Array', () => {
  it('lehnt Einzelwerte für multiselect/checkbox-group/collection ab', () => {
    const errs = validateValues(defn, { tags: 'a', haken: 'x', verlauf: {} })
    expect(errs.filter((e) => e.code === 'TYPE').map((e) => e.path).sort())
      .toEqual(['haken', 'tags', 'verlauf'])
  })

  it('akzeptiert Arrays – auch leere', () => {
    expect(validateValues(defn, { tags: [], haken: ['x'], verlauf: [] })).toEqual([])
  })

  it('prüft die Auswahlwerte gegen die Optionsliste', () => {
    const errs = validateValues(defn, { tags: ['a', 'unbekannt'] })
    expect(errs.some((e) => e.path === 'tags' && e.code === 'OPTION')).toBe(true)
  })

  it('erwartet für number eine echte Zahl, keinen String', () => {
    expect(validateValues(defn, { gehalt: '1000' })[0]?.code).toBe('TYPE')
    expect(validateValues(defn, { gehalt: 1000 })).toEqual([])
  })
})

describe('Wiederholgruppe – Nur-anhängen', () => {
  it('ist bearbeitbar, obwohl der Modus nicht editable heißt', () => {
    expect(row({}, hr, 'verlauf')?.editable).toBe(true)
  })

  it('sperrt genau die beim Laden vorhandenen Einträge', () => {
    expect(isLockedEntry(0, 1, true)).toBe(true)
    expect(isLockedEntry(1, 1, true)).toBe(false)
    // Ohne append_only ist nichts gesperrt.
    expect(isLockedEntry(0, 1, false)).toBe(false)
  })

  it('normalisiert kaputte Werte zu Objekt-Zeilen', () => {
    expect(toEntries(null)).toEqual([])
    expect(toEntries(['unsinn', { text: 'ok' }])).toEqual([{}, { text: 'ok' }])
  })

  it('ändert beim Anhängen und Bearbeiten keine fremde Zeile', () => {
    const before = [{ text: 'alt', wer: 'ml' }]
    const appended = withNewEntry(toEntries(before))
    expect(appended).toEqual([{ text: 'alt', wer: 'ml' }, {}])

    const edited = withSubValue(appended, 1, 'text', 'neu')
    expect(edited[0]).toEqual({ text: 'alt', wer: 'ml' })
    expect(edited[1]).toEqual({ text: 'neu' })
    // Unveränderlich: die Ausgangsliste bleibt unberührt.
    expect(before).toEqual([{ text: 'alt', wer: 'ml' }])

    expect(withoutEntry(edited, 1)).toEqual([{ text: 'alt', wer: 'ml' }])
  })
})
