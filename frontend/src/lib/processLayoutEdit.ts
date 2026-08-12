/**
 * Reine Bearbeitungs-Helfer für die Layout-Ebene einer Phase.
 *
 * Ausgelagert aus den Editor-Komponenten, weil es in diesem Projekt bewusst
 * keine Komponenten-Tests gibt (kein @vue/test-utils): die nicht-triviale
 * Listen-Arithmetik ist damit trotzdem testbar, die .vue-Dateien bleiben
 * reine Darstellung.
 *
 * Alle Funktionen arbeiten IMMUTABEL – sie geben stets eine neue Struktur
 * zurück und fassen die Eingabe nie an (der Editor bekommt `layout` als Prop).
 * Ist eine Bearbeitung nicht möglich (Index außerhalb der Liste), kommt die
 * Eingabe unverändert – und referenzgleich – zurück; der Aufrufer kann so auf
 * das Emit verzichten.
 *
 * WICHTIG: Hier steckt ausschließlich Darstellung. Pflicht/Sichtbarkeit eines
 * Feldes leben in PhaseDef.fields und werden hier nie berührt.
 */
import type {
  FieldRef, LayoutItem, LayoutSection, LayoutWidth,
} from '@/types/process'
import { blankLayoutItem, blankSection, placedRefs } from '@/lib/processSchema'

type MaybeLayout = LayoutSection[] | null | undefined
type MaybeFields = FieldRef[] | null | undefined

/** Defensiv: importierte Definitionen dürfen `layout`/`items` ganz weglassen. */
function asLayout(layout: MaybeLayout): LayoutSection[] {
  return Array.isArray(layout) ? layout : []
}

function asItems(section: LayoutSection | undefined): LayoutItem[] {
  const items = section?.items
  return Array.isArray(items) ? items : []
}

// ── Listen-Arithmetik ─────────────────────────────────────────────────────────

/**
 * Verschiebt `list[from]` um `delta` Positionen.
 * Am Rand (oder delta=0) bleibt die Liste unverändert und referenzgleich.
 */
export function moveItem<T>(list: T[] | null | undefined, from: number, delta: number): T[] {
  if (!Array.isArray(list)) return []
  const to = from + delta
  if (delta === 0) return list
  if (from < 0 || from >= list.length) return list
  if (to < 0 || to >= list.length) return list
  const next = [...list]
  const [moved] = next.splice(from, 1)
  next.splice(to, 0, moved)
  return next
}

/** Index in eine gültige Position zwängen; -1 bei leerer Liste. */
export function clampIndex(index: number, length: number): number {
  if (length <= 0) return -1
  if (!Number.isFinite(index) || index < 0) return 0
  return Math.min(Math.trunc(index), length - 1)
}

// ── Platzierung ───────────────────────────────────────────────────────────────

/**
 * Felder der Phase, die im Layout NICHT vorkommen – in der Reihenfolge von
 * `fields`, ohne Duplikate. Sie landen zur Laufzeit im Sammel-Abschnitt
 * „Weitere Angaben"; hier sind sie die Ablage („Nicht platzierte Felder").
 */
export function unplacedRefs(layout: MaybeLayout, fields: MaybeFields): string[] {
  const placed = placedRefs(asLayout(layout))
  const seen = new Set<string>()
  const out: string[] = []
  for (const f of Array.isArray(fields) ? fields : []) {
    const ref = f?.ref
    if (!ref || placed.has(ref) || seen.has(ref)) continue
    seen.add(ref)
    out.push(ref)
  }
  return out
}

/**
 * Umgekehrter Fall: im Layout platzierte Refs, die es in `fields` nicht (mehr)
 * gibt – z. B. nachdem ein Feld aus der Phase entfernt wurde. Diese
 * Platzierungen bleiben zur Laufzeit leer, der Editor warnt deshalb.
 */
export function orphanRefs(layout: MaybeLayout, fields: MaybeFields): string[] {
  const known = new Set<string>()
  for (const f of Array.isArray(fields) ? fields : []) if (f?.ref) known.add(f.ref)
  const seen = new Set<string>()
  const out: string[] = []
  for (const sec of asLayout(layout)) {
    for (const it of asItems(sec)) {
      if (it.type !== 'field') continue
      if (known.has(it.ref) || seen.has(it.ref)) continue
      seen.add(it.ref)
      out.push(it.ref)
    }
  }
  return out
}

/** Feld-Refs eines Abschnitts (für Lösch-Rückfrage und Zähler). */
export function sectionFieldRefs(section: LayoutSection | undefined): string[] {
  return asItems(section).flatMap((it) => (it.type === 'field' ? [it.ref] : []))
}

// ── Abschnitte ────────────────────────────────────────────────────────────────

export function addSection(layout: MaybeLayout, section?: LayoutSection): LayoutSection[] {
  const list = asLayout(layout)
  return [...list, section ?? blankSection(`Abschnitt ${list.length + 1}`)]
}

export function patchSection(layout: MaybeLayout, index: number,
                             part: Partial<LayoutSection>): LayoutSection[] {
  const list = asLayout(layout)
  if (index < 0 || index >= list.length) return list
  return list.map((sec, i) => (i === index ? { ...sec, ...part } : sec))
}

export function removeSection(layout: MaybeLayout, index: number): LayoutSection[] {
  const list = asLayout(layout)
  if (index < 0 || index >= list.length) return list
  return list.filter((_, i) => i !== index)
}

export function moveSection(layout: MaybeLayout, index: number, delta: number): LayoutSection[] {
  return moveItem(asLayout(layout), index, delta)
}

// ── Elemente innerhalb eines Abschnitts ───────────────────────────────────────

export function addItems(layout: MaybeLayout, sectionIndex: number,
                         items: LayoutItem[]): LayoutSection[] {
  const list = asLayout(layout)
  if (sectionIndex < 0 || sectionIndex >= list.length || !items.length) return list
  return list.map((sec, i) => (
    i === sectionIndex ? { ...sec, items: [...asItems(sec), ...items] } : sec
  ))
}

export function addItem(layout: MaybeLayout, sectionIndex: number,
                        item: LayoutItem): LayoutSection[] {
  return addItems(layout, sectionIndex, [item])
}

/** Bequemer Weg aus der Ablage in einen Abschnitt. */
export function addFieldRefs(layout: MaybeLayout, sectionIndex: number, refs: string[],
                             width: LayoutWidth = 'half'): LayoutSection[] {
  const items: LayoutItem[] = refs.map((ref) => {
    const it = blankLayoutItem('field', ref)
    return it.type === 'field' ? { ...it, width } : it
  })
  return addItems(layout, sectionIndex, items)
}

export function patchItem(layout: MaybeLayout, sectionIndex: number, itemIndex: number,
                          item: LayoutItem): LayoutSection[] {
  const list = asLayout(layout)
  const sec = list[sectionIndex]
  if (!sec) return list
  const items = asItems(sec)
  if (itemIndex < 0 || itemIndex >= items.length) return list
  return list.map((s, i) => (
    i === sectionIndex ? { ...s, items: items.map((it, j) => (j === itemIndex ? item : it)) } : s
  ))
}

export function removeItem(layout: MaybeLayout, sectionIndex: number,
                           itemIndex: number): LayoutSection[] {
  const list = asLayout(layout)
  const sec = list[sectionIndex]
  if (!sec) return list
  const items = asItems(sec)
  if (itemIndex < 0 || itemIndex >= items.length) return list
  return list.map((s, i) => (
    i === sectionIndex ? { ...s, items: items.filter((_, j) => j !== itemIndex) } : s
  ))
}

export function moveItemInSection(layout: MaybeLayout, sectionIndex: number, itemIndex: number,
                                  delta: number): LayoutSection[] {
  const list = asLayout(layout)
  const sec = list[sectionIndex]
  if (!sec) return list
  const items = asItems(sec)
  const moved = moveItem(items, itemIndex, delta)
  if (moved === items) return list
  return list.map((s, i) => (i === sectionIndex ? { ...s, items: moved } : s))
}

// ── Startpunkt ────────────────────────────────────────────────────────────────

/**
 * Erzeugt aus den Feldern der Phase EINEN Abschnitt – der übliche Einstieg,
 * damit niemand ein leeres Layout von Hand füllen muss. Ohne Felder bleibt das
 * Layout leer (leeres Layout = Standarddarstellung, kein leerer Abschnitt).
 */
export function layoutFromFields(fields: MaybeFields, title = 'Angaben',
                                 width: LayoutWidth = 'half'): LayoutSection[] {
  const refs = unplacedRefs([], fields)
  if (!refs.length) return []
  return addFieldRefs([blankSection(title, 'base')], 0, refs, width)
}
