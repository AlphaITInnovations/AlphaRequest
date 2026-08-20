/**
 * Tests der Layout-Auflösung.
 *
 * Geprüft wird genau das, was Admins sich im Editor kaputtmachen könnten:
 * fehlendes Layout, nicht platzierte Felder, unsichtbare Felder, leere
 * Abschnitte und Doppelplatzierungen.
 */
import { describe, it, expect } from 'vitest'
import { normalizeDefinition } from './processNormalize'
import { colSpanClass, mergedSections, resolveLayout, REST_SECTION_TITLE } from './processLayout'
import type { ResolvedItem } from './processLayout'
import type { SimViewer } from './processSim'

const VIEWER: SimViewer = { fullView: true, isAdmin: true, groupIds: [] }

/** Definition mit vier Feldern; `plate` hängt an einer Sichtbarkeitsbedingung. */
function build(layout: unknown[]) {
  return normalizeDefinition({
    key: 'demo', name: 'Demo',
    fields: [
      { key: 'name', widget: 'text' },
      { key: 'car', widget: 'select', options: [{ value: 'Ja' }, { value: 'Nein' }] },
      { key: 'plate', widget: 'text' },
      { key: 'grund', widget: 'textarea' },
    ],
    phases: [{
      key: 'start', label: 'Erstellung', kind: 'start',
      fields: [
        { ref: 'name', required: true },
        { ref: 'car' },
        { ref: 'plate', visibleWhen: { '==': ['car', 'Ja'] } },
        { ref: 'grund' },
      ],
      layout,
    }],
  })
}

function refsOf(items: ResolvedItem[]): string[] {
  return items.filter((i) => i.item.type === 'field')
    .map((i) => (i.item as { ref: string }).ref)
}

function run(layout: unknown[], values: Record<string, unknown> = {}) {
  const defn = build(layout)
  return resolveLayout(defn, defn.phases[0], values, VIEWER)
}

describe('Ohne Layout', () => {
  it('liefert einen Abschnitt mit allen sichtbaren Feldern, halbe Breite', () => {
    const secs = run([], { car: 'Nein' })
    expect(secs.length).toBe(1)
    expect(secs[0].section.title).toBe('Erstellung')
    expect(secs[0].section.variant).toBe('base')
    expect(refsOf(secs[0].items)).toEqual(['name', 'car', 'grund'])
    expect(secs[0].items.every((i) => i.cols === 6)).toBe(true)
  })

  it('nutzt den Phasen-Key, wenn kein Label gepflegt ist', () => {
    const defn = normalizeDefinition({
      key: 'demo', name: 'Demo',
      fields: [{ key: 'name', widget: 'text' }],
      phases: [{ key: 'pruefung', fields: [{ ref: 'name' }] }],
    })
    expect(resolveLayout(defn, defn.phases[0], {}, VIEWER)[0].section.title).toBe('pruefung')
  })

  it('liefert gar keinen Abschnitt, wenn nichts sichtbar ist', () => {
    const defn = normalizeDefinition({
      key: 'demo', name: 'Demo',
      fields: [{ key: 'name', widget: 'text' }],
      phases: [{ key: 'start', fields: [{ ref: 'name', mode: 'hidden' }] }],
    })
    expect(resolveLayout(defn, defn.phases[0], {}, VIEWER)).toEqual([])
  })
})

describe('Nicht platzierte Felder', () => {
  it('landen im Sammel-Abschnitt am Ende', () => {
    const secs = run([{ type: 'section', title: 'Basis', variant: 'base',
      items: [{ type: 'field', ref: 'name', width: 'full' }] }], { car: 'Nein' })
    expect(secs.map((s) => s.section.title)).toEqual(['Basis', REST_SECTION_TITLE])
    expect(secs[1].section.variant).toBe('default')
    expect(refsOf(secs[1].items)).toEqual(['car', 'grund'])
  })

  it('entfällt, sobald alles platziert ist', () => {
    const secs = run([{ type: 'section', title: 'Alles', items: [
      { type: 'field', ref: 'name', width: 'half' },
      { type: 'field', ref: 'car', width: 'half' },
      { type: 'field', ref: 'grund', width: 'full' },
    ] }], { car: 'Nein' })
    expect(secs.length).toBe(1)
  })
})

describe('Sichtbarkeit', () => {
  it('lässt Felder aus, deren visibleWhen nicht greift', () => {
    const layout = [{ type: 'section', title: 'Fuhrpark', items: [
      { type: 'field', ref: 'car', width: 'half' },
      { type: 'field', ref: 'plate', width: 'half' },
    ] }]
    expect(refsOf(run(layout, { car: 'Nein' })[0].items)).toEqual(['car'])
    expect(refsOf(run(layout, { car: 'Ja' })[0].items)).toEqual(['car', 'plate'])
  })

  it('leitet Pflicht und Bearbeitbarkeit weiter, ohne sie neu zu berechnen', () => {
    const secs = run([{ type: 'section', title: 'Basis',
      items: [{ type: 'field', ref: 'name', width: 'quarter' }] }])
    expect(secs[0].items[0].rendered?.required).toBe(true)
    expect(secs[0].items[0].rendered?.editable).toBe(true)
  })
})

describe('Leere Abschnitte', () => {
  it('werden weggelassen, wenn kein Feld sichtbar ist', () => {
    const secs = run([
      { type: 'section', title: 'Nur Kennzeichen',
        items: [{ type: 'field', ref: 'plate', width: 'half' }] },
      { type: 'section', title: 'Basis',
        items: [{ type: 'field', ref: 'name', width: 'half' }] },
    ], { car: 'Nein' })
    expect(secs.map((s) => s.section.title)).toEqual(['Basis', REST_SECTION_TITLE])
  })

  it('werden auch weggelassen, wenn nur Trennlinie/Abstand übrig bleiben', () => {
    const secs = run([{ type: 'section', title: 'Deko', items: [
      { type: 'field', ref: 'plate', width: 'half' },
      { type: 'divider' }, { type: 'spacer' },
    ] }], { car: 'Nein' })
    expect(secs.map((s) => s.section.title)).toEqual([REST_SECTION_TITLE])
  })

  it('bleiben stehen, wenn eine Hinweisbox oder Überschrift darin steht', () => {
    const secs = run([{ type: 'section', title: 'Hinweise', items: [
      { type: 'note', text: 'Bitte beachten', tone: 'warning', width: 'full' },
    ] }], { car: 'Nein' })
    expect(secs[0].section.title).toBe('Hinweise')
    expect(secs[0].items[0].item.type).toBe('note')
  })

  it('bedingte Notiz erscheint nur, wenn visibleWhen erfüllt ist', () => {
    const layout = [{ type: 'section', title: 'H', items: [
      { type: 'note', text: 'Kein Dienstwagen', tone: 'warning', width: 'full',
        visibleWhen: { '==': ['car', 'Nein'] } },
    ] }]
    // erfüllt → Abschnitt mit Notiz
    const shown = run(layout, { car: 'Nein' })
    expect(shown[0]?.items[0]?.item.type).toBe('note')
    // nicht erfüllt → Notiz weg, Abschnitt hat keinen Inhalt und entfällt
    const hidden = run(layout, { car: 'Ja' })
    expect(hidden.map((s) => s.section.title)).not.toContain('H')
  })
})

describe('Breiten', () => {
  it('rechnet die Layout-Breite auf das 12er-Raster um', () => {
    const secs = run([{ type: 'section', title: 'Raster', items: [
      { type: 'field', ref: 'name', width: 'quarter' },
      { type: 'field', ref: 'car', width: 'third' },
      { type: 'field', ref: 'grund', width: 'twothirds' },
      { type: 'note', text: 'x', tone: 'info', width: 'half' },
      { type: 'heading', text: 'Abschnitt' },
      { type: 'divider' },
    ] }], { car: 'Nein' })
    expect(secs[0].items.map((i) => i.cols)).toEqual([3, 4, 8, 6, 12, 12])
  })

  it('bildet Spalten auf feste Tailwind-Klassen ab', () => {
    expect(colSpanClass(3)).toBe('md:col-span-3')
    expect(colSpanClass(8)).toBe('md:col-span-8')
    // Unbekannte Spaltenzahl darf nie eine leere Klasse ergeben.
    expect(colSpanClass(7)).toBe('md:col-span-12')
  })
})

describe('Kein Feld doppelt', () => {
  it('ignoriert eine zweite Platzierung desselben Feldes', () => {
    const secs = run([
      { type: 'section', title: 'A', items: [{ type: 'field', ref: 'name', width: 'half' }] },
      { type: 'section', title: 'B', items: [{ type: 'field', ref: 'name', width: 'full' }] },
    ], { car: 'Nein' })
    expect(secs.map((s) => s.section.title)).toEqual(['A', REST_SECTION_TITLE])
    expect(refsOf(secs[0].items)).toEqual(['name'])
    const all = secs.flatMap((s) => refsOf(s.items))
    expect(all.filter((r) => r === 'name').length).toBe(1)
    // Platziertes Feld darf NICHT zusätzlich im Sammel-Abschnitt auftauchen.
    expect(refsOf(secs[1].items)).toEqual(['car', 'grund'])
  })

  it('rendert ein doppelt referenziertes Phasenfeld nur einmal', () => {
    const defn = normalizeDefinition({
      key: 'demo', name: 'Demo',
      fields: [{ key: 'name', widget: 'text' }],
      phases: [{ key: 'start', fields: [{ ref: 'name' }, { ref: 'name' }] }],
    })
    const secs = resolveLayout(defn, defn.phases[0], {}, VIEWER)
    expect(refsOf(secs[0].items)).toEqual(['name'])
  })
})

describe('mergedSections', () => {
  // Prozess mit mehreren Phasen: dieselben Abschnitte tauchen in mehreren Phasen
  // auf, ein Feld kommt in mehreren Phasen vor – es zählt der ERSTE Fund.
  const defn = () => normalizeDefinition({
    key: 'onb', name: 'Onboarding',
    fields: [
      { key: 'base.vorname', widget: 'text' },
      { key: 'base.nachname', widget: 'text' },
      { key: 'it.sig', widget: 'text' },
      { key: 'lose', widget: 'text' },
    ],
    phases: [
      { key: 'p1', kind: 'start',
        fields: [{ ref: 'base.vorname' }, { ref: 'base.nachname' }, { ref: 'lose' }],
        layout: [{ type: 'section', title: 'Basisdaten', variant: 'base',
                   items: [{ type: 'field', ref: 'base.vorname' },
                           { type: 'field', ref: 'base.nachname' }] }] },
      { key: 'p2', kind: 'task',
        fields: [{ ref: 'base.vorname' }, { ref: 'it.sig' }],
        layout: [
          { type: 'section', title: 'Basisdaten', variant: 'base',
            items: [{ type: 'field', ref: 'base.vorname' }] },
          { type: 'section', title: 'IT', variant: 'it',
            items: [{ type: 'field', ref: 'it.sig' }] },
        ] },
    ],
  })

  it('führt gleichnamige Abschnitte zusammen und platziert jedes Feld beim ersten Auftreten', () => {
    const secs = mergedSections(defn())
    expect(secs.map((s) => s.title)).toEqual(['Basisdaten', 'IT'])
    expect(secs[0].refs).toEqual(['base.vorname', 'base.nachname'])   // vorname nur EINMAL
    expect(secs[1]).toMatchObject({ variant: 'it', refs: ['it.sig'] })
    // `lose` ist nirgends platziert → gehört NICHT zu einem Abschnitt.
    expect(secs.flatMap((s) => s.refs)).not.toContain('lose')
  })

  it('ohne Layout leer (Leseansicht fällt dann auf eine Sammel-Liste zurück)', () => {
    const flat = normalizeDefinition({
      key: 'x', name: 'X', fields: [{ key: 'a', widget: 'text' }],
      phases: [{ key: 'p', kind: 'start', fields: [{ ref: 'a' }] }],
    })
    expect(mergedSections(flat)).toEqual([])
    expect(mergedSections(null)).toEqual([])
  })
})
