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
import { applyComputed } from '@/lib/conditionDsl'
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

describe('Berechnete Übernachtungen werden sofort angezeigt', () => {
  // Nachbildung des Hotelbuchung-Musters: Nächte = days_between(Anreise, Abreise),
  // read-only. normalizeDefinition läuft hier mit – der Test deckt damit auch ab,
  // dass der Normalizer op/to erhält (sonst käme statt der Zahl das Rohdatum).
  const reise = normalizeDefinition({
    schemaVersion: 1, key: 'reise', name: 'Reise',
    fields: [
      { key: 'an', widget: 'date', label: 'Anreise' },
      { key: 'ab', widget: 'date', label: 'Abreise' },
      { key: 'naechte', widget: 'number', label: 'Übernachtungen', overridable: false,
        computed: { from: 'an', to: 'ab', op: 'days_between' } },
    ],
    phases: [{
      key: 'start', kind: 'start',
      fields: [{ ref: 'an' }, { ref: 'ab' }, { ref: 'naechte', mode: 'readonly' }],
    }],
  })
  const p = reise.phases[0]
  const wer: SimViewer = { fullView: true, isAdmin: true, groupIds: [] }
  const naechteRow = (values: Record<string, unknown>) =>
    renderFields(reise, p, values, wer).find((r) => r.field.key === 'naechte')

  it('zeigt das Nächte-Feld an (sichtbar, aber nicht editierbar)', () => {
    const r = naechteRow({})
    expect(r?.visible).toBe(true)   // wird also gerendert (disabled)
    expect(r?.editable).toBe(false)
  })

  it('füllt den angezeigten Wert, sobald beide Daten gewählt sind', () => {
    // genau das, was onValues() im Anlege-Formular tut
    const after = applyComputed(reise.fields, { an: '2026-09-16', ab: '2026-09-18' })
    expect(after.naechte).toBe(2)               // Zahl, nicht das Rohdatum → Normalizer ok
    expect(naechteRow(after)?.visible).toBe(true)
    // gleicher Tag → 0 (wird als „0" angezeigt, nicht leer)
    expect(applyComputed(reise.fields, { an: '2026-09-16', ab: '2026-09-16' }).naechte).toBe(0)
  })

  it('bleibt leer, solange nur ein Datum gewählt ist', () => {
    expect(applyComputed(reise.fields, { an: '2026-09-16' }).naechte ?? null).toBeNull()
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
