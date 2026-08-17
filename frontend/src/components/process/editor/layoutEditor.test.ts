/**
 * Tests der reinen Layout-Bearbeitungs-Logik (lib/processLayoutEdit) – genutzt
 * vom Formular-Baukasten (FormBuilder.vue).
 *
 * Es gibt in diesem Projekt bewusst keine Komponenten-Tests (kein
 * @vue/test-utils, kein jsdom) – geprüft wird deshalb das ausgelagerte
 * Modul lib/processLayoutEdit.ts.
 */
import { describe, it, expect } from 'vitest'
import type { FieldRef, LayoutSection } from '../../../types/process'
import { blankFieldRef, blankLayoutItem, blankSection, placedRefs } from '../../../lib/processSchema'
import {
  addFieldRefs, addItem, addSection, clampIndex, layoutFromFields, moveItem,
  moveItemInSection, moveSection, orphanRefs, patchItem, patchSection, removeItem,
  removeSection, sectionFieldRefs, unplacedRefs,
} from '../../../lib/processLayoutEdit'

function fields(...refs: string[]): FieldRef[] {
  return refs.map((r) => blankFieldRef(r))
}

/** Zwei Abschnitte: „A" mit hr.name + einer Hinweisbox, „B" mit it.rechte. */
function demoLayout(): LayoutSection[] {
  const a: LayoutSection = {
    ...blankSection('A', 'hr'),
    items: [blankLayoutItem('field', 'hr.name'), blankLayoutItem('note')],
  }
  const b: LayoutSection = {
    ...blankSection('B', 'it'),
    items: [blankLayoutItem('field', 'it.rechte')],
  }
  return [a, b]
}

describe('moveItem – Ränder und Immutabilität', () => {
  const list = ['a', 'b', 'c']

  it('verschiebt nach oben und unten', () => {
    expect(moveItem(list, 1, -1)).toEqual(['b', 'a', 'c'])
    expect(moveItem(list, 1, 1)).toEqual(['a', 'c', 'b'])
    expect(moveItem(list, 0, 2)).toEqual(['b', 'c', 'a'])
  })

  it('am Rand bleibt die Liste unverändert und referenzgleich', () => {
    expect(moveItem(list, 0, -1)).toBe(list)
    expect(moveItem(list, 2, 1)).toBe(list)
    expect(moveItem(list, 1, 0)).toBe(list)
    expect(moveItem(list, -1, 1)).toBe(list)
    expect(moveItem(list, 9, -1)).toBe(list)
  })

  it('fasst die Eingabe nie an', () => {
    const next = moveItem(list, 0, 1)
    expect(next).not.toBe(list)
    expect(list).toEqual(['a', 'b', 'c'])
  })

  it('verträgt fehlende Listen', () => {
    expect(moveItem(undefined, 0, 1)).toEqual([])
    expect(moveItem(null, 0, 1)).toEqual([])
  })
})

describe('clampIndex', () => {
  it('leere Liste hat keinen gültigen Index', () => {
    expect(clampIndex(0, 0)).toBe(-1)
    expect(clampIndex(3, 0)).toBe(-1)
  })

  it('zwängt in die Liste', () => {
    expect(clampIndex(5, 3)).toBe(2)
    expect(clampIndex(-2, 3)).toBe(0)
    expect(clampIndex(1, 3)).toBe(1)
    expect(clampIndex(NaN, 3)).toBe(0)
  })
})

describe('unplacedRefs – was noch in der Ablage liegt', () => {
  it('meldet nur nicht platzierte Felder, in der Reihenfolge der Phase', () => {
    const layout = demoLayout()
    const phase = fields('hr.name', 'hr.eintritt', 'it.rechte', 'fuhrpark.car')
    expect(unplacedRefs(layout, phase)).toEqual(['hr.eintritt', 'fuhrpark.car'])
  })

  it('ohne Layout ist alles unplatziert', () => {
    expect(unplacedRefs([], fields('a', 'b'))).toEqual(['a', 'b'])
    expect(unplacedRefs(undefined, fields('a'))).toEqual(['a'])
  })

  it('ohne Felder ist die Ablage leer', () => {
    expect(unplacedRefs(demoLayout(), [])).toEqual([])
    expect(unplacedRefs(demoLayout(), undefined)).toEqual([])
  })

  it('ignoriert Dubletten und leere Refs', () => {
    const phase = [...fields('a', 'a'), blankFieldRef('')]
    expect(unplacedRefs([], phase)).toEqual(['a'])
  })

  it('Nicht-Feld-Elemente belegen keinen Ref', () => {
    const only: LayoutSection[] = [{
      ...blankSection(),
      items: [blankLayoutItem('note'), blankLayoutItem('divider'), blankLayoutItem('spacer')],
    }]
    expect(unplacedRefs(only, fields('a'))).toEqual(['a'])
  })
})

describe('orphanRefs – Platzierung ohne Feld', () => {
  it('findet Refs, die die Phase nicht (mehr) kennt', () => {
    expect(orphanRefs(demoLayout(), fields('hr.name'))).toEqual(['it.rechte'])
  })

  it('leer, wenn alles bekannt ist', () => {
    expect(orphanRefs(demoLayout(), fields('hr.name', 'it.rechte'))).toEqual([])
  })
})

describe('Abschnitte hinzufügen, verschieben, löschen', () => {
  it('addSection hängt hinten an und nummeriert den Titel', () => {
    const next = addSection([])
    expect(next).toHaveLength(1)
    expect(next[0].title).toBe('Abschnitt 1')
    expect(addSection(next)[1].title).toBe('Abschnitt 2')
  })

  it('addSection verträgt fehlendes Layout', () => {
    expect(addSection(undefined)).toHaveLength(1)
  })

  it('patchSection ändert nur den gewählten Abschnitt', () => {
    const layout = demoLayout()
    const next = patchSection(layout, 1, { title: 'IT-Prüfung', collapsed: true })
    expect(next[1].title).toBe('IT-Prüfung')
    expect(next[1].collapsed).toBe(true)
    expect(next[1].items).toEqual(layout[1].items)
    expect(next[0]).toBe(layout[0])
    // Eingabe unberührt
    expect(layout[1].title).toBe('B')
  })

  it('patchSection mit ungültigem Index tut nichts', () => {
    const layout = demoLayout()
    expect(patchSection(layout, 5, { title: 'X' })).toBe(layout)
  })

  it('moveSection tauscht die Reihenfolge, am Rand nicht', () => {
    const layout = demoLayout()
    expect(moveSection(layout, 1, -1).map((s) => s.title)).toEqual(['B', 'A'])
    expect(moveSection(layout, 0, -1)).toBe(layout)
    expect(moveSection(layout, 1, 1)).toBe(layout)
  })

  it('removeSection gibt die Felder in die Ablage zurück', () => {
    const layout = demoLayout()
    const phase = fields('hr.name', 'it.rechte')
    expect(unplacedRefs(layout, phase)).toEqual([])

    const next = removeSection(layout, 0)
    expect(next).toHaveLength(1)
    expect(next[0].title).toBe('B')
    // hr.name war in Abschnitt A – es ist jetzt wieder unplatziert …
    expect(unplacedRefs(next, phase)).toEqual(['hr.name'])
    // … und gehört zu keinem Abschnitt mehr.
    expect(placedRefs(next).has('hr.name')).toBe(false)
    // Die Eingabe wurde nicht verändert.
    expect(layout).toHaveLength(2)
    expect(unplacedRefs(layout, phase)).toEqual([])
  })

  it('removeSection mit ungültigem Index tut nichts', () => {
    const layout = demoLayout()
    expect(removeSection(layout, -1)).toBe(layout)
    expect(removeSection(layout, 2)).toBe(layout)
  })
})

describe('Elemente in einem Abschnitt', () => {
  it('addItem hängt an den gewählten Abschnitt an', () => {
    const layout = demoLayout()
    const next = addItem(layout, 1, blankLayoutItem('field', 'hr.eintritt'))
    expect(next[1].items).toHaveLength(2)
    expect(next[1].items[1]).toEqual({ type: 'field', ref: 'hr.eintritt', width: 'half' })
    // andere Abschnitte und die Eingabe bleiben, wie sie waren
    expect(next[0]).toBe(layout[0])
    expect(layout[1].items).toHaveLength(1)
  })

  it('addItem mit ungültigem Abschnitt tut nichts', () => {
    const layout = demoLayout()
    expect(addItem(layout, 7, blankLayoutItem('divider'))).toBe(layout)
    expect(addItem([], 0, blankLayoutItem('divider'))).toEqual([])
  })

  it('addFieldRefs platziert mehrere Felder mit einer Breite', () => {
    const next = addFieldRefs(addSection([]), 0, ['a', 'b'], 'third')
    expect(next[0].items).toEqual([
      { type: 'field', ref: 'a', width: 'third' },
      { type: 'field', ref: 'b', width: 'third' },
    ])
    expect(unplacedRefs(next, fields('a', 'b'))).toEqual([])
  })

  it('patchItem ersetzt genau ein Element', () => {
    const layout = demoLayout()
    const next = patchItem(layout, 0, 0, { type: 'field', ref: 'hr.name', width: 'full' })
    expect(next[0].items[0]).toEqual({ type: 'field', ref: 'hr.name', width: 'full' })
    expect(next[0].items[1]).toBe(layout[0].items[1])
    expect(patchItem(layout, 0, 9, blankLayoutItem('divider'))).toBe(layout)
    expect(patchItem(layout, 9, 0, blankLayoutItem('divider'))).toBe(layout)
  })

  it('removeItem entfernt und lässt den Ref wieder frei', () => {
    const layout = demoLayout()
    const next = removeItem(layout, 0, 0)
    expect(next[0].items).toHaveLength(1)
    expect(unplacedRefs(next, fields('hr.name'))).toEqual(['hr.name'])
    expect(removeItem(layout, 0, 5)).toBe(layout)
  })

  it('moveItemInSection verschiebt nur innerhalb des Abschnitts', () => {
    const layout = demoLayout()
    const next = moveItemInSection(layout, 0, 0, 1)
    expect(next[0].items.map((i) => i.type)).toEqual(['note', 'field'])
    expect(next[1]).toBe(layout[1])
    // am Rand: unverändert und referenzgleich
    expect(moveItemInSection(layout, 0, 0, -1)).toBe(layout)
    expect(moveItemInSection(layout, 1, 0, 1)).toBe(layout)
    expect(moveItemInSection(layout, 3, 0, 1)).toBe(layout)
  })
})

describe('sectionFieldRefs – Grundlage der Lösch-Rückfrage', () => {
  it('zählt nur Felder, keine Design-Elemente', () => {
    expect(sectionFieldRefs(demoLayout()[0])).toEqual(['hr.name'])
    expect(sectionFieldRefs(blankSection())).toEqual([])
    expect(sectionFieldRefs(undefined)).toEqual([])
  })
})

describe('layoutFromFields – Startpunkt aus den Feldern der Phase', () => {
  it('erzeugt einen Abschnitt mit allen Feldern', () => {
    const next = layoutFromFields(fields('a', 'b', 'c'))
    expect(next).toHaveLength(1)
    expect(next[0].variant).toBe('base')
    expect(next[0].items).toHaveLength(3)
    expect(unplacedRefs(next, fields('a', 'b', 'c'))).toEqual([])
  })

  it('ohne Felder bleibt das Layout leer (= Standarddarstellung)', () => {
    expect(layoutFromFields([])).toEqual([])
    expect(layoutFromFields(undefined)).toEqual([])
  })
})
