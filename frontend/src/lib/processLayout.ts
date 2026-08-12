/**
 * Layout-Auflösung: aus `PhaseDef.layout` + Laufzeit-Sichtbarkeit wird die
 * fertige Anzeige-Struktur (Abschnitte → Elemente → Spaltenbreite).
 *
 * Trennung der Zuständigkeiten – bitte beibehalten:
 *  - VERHALTEN (sichtbar/pflicht/bearbeitbar) kommt AUSSCHLIESSLICH aus
 *    renderFields(), also aus PhaseDef.fields. Aus dem Layout wird NICHTS
 *    davon abgeleitet.
 *  - Das Layout bestimmt nur Reihenfolge, Breite und Dekoration.
 *
 * Zwei Sicherheitsnetze, damit Admins sich nicht selbst aussperren:
 *  1. Ein Feld der Phase, das im Layout NICHT platziert wurde, landet im
 *     Sammel-Abschnitt „Weitere Angaben" – es verschwindet nie.
 *  2. Ein Feld darf höchstens EINMAL erscheinen (Doppelplatzierung im Layout
 *     wird ignoriert), sonst gäbe es zwei Eingaben für denselben Wert.
 */
import type {
  LayoutItem, LayoutSection, PhaseDef, ProcessDefinition,
} from '@/types/process'
import { WIDTH_COLS } from '@/lib/processSchema'
import { renderFields } from '@/lib/processSim'
import type { RenderedField, SimViewer } from '@/lib/processSim'

export interface ResolvedItem {
  item: LayoutItem
  /** Nur bei item.type === 'field' gesetzt. */
  rendered?: RenderedField
  /** Spalten im 12er-Raster. */
  cols: number
}

export interface ResolvedSection {
  section: LayoutSection
  items: ResolvedItem[]
}

/** Titel des Sammel-Abschnitts – auch der Editor zeigt diesen Text als Warnung. */
export const REST_SECTION_TITLE = 'Weitere Angaben'

/**
 * Spalten → feste Tailwind-Klasse. Tailwind scannt den Quelltext statisch und
 * kennt zusammengesetzte Klassennamen wie `md:col-span-${n}` NICHT – deshalb
 * müssen alle Varianten wörtlich im Code stehen.
 */
export const MD_COL_SPAN: Record<number, string> = {
  3: 'md:col-span-3',
  4: 'md:col-span-4',
  6: 'md:col-span-6',
  8: 'md:col-span-8',
  12: 'md:col-span-12',
}

/** Mobile-first: unten immer volle Breite, ab `md` die konfigurierte Breite. */
export function colSpanClass(cols: number): string {
  return MD_COL_SPAN[cols] ?? MD_COL_SPAN[12]
}

function itemCols(item: LayoutItem): number {
  // Überschrift/Trennlinie/Abstand haben keine Breite – sie trennen immer über
  // die ganze Zeile, sonst rutscht das folgende Feld daneben.
  if (item.type === 'field' || item.type === 'note') return WIDTH_COLS[item.width] ?? WIDTH_COLS.full
  return WIDTH_COLS.full
}

function fieldItem(ref: string): LayoutItem {
  return { type: 'field', ref, width: 'half' }
}

function restSection(): LayoutSection {
  return {
    type: 'section', title: REST_SECTION_TITLE, variant: 'default',
    badge: null, description: null, collapsed: false, items: [],
  }
}

function fallbackSection(phase: PhaseDef): LayoutSection {
  return {
    type: 'section', title: phase.label || phase.key || 'Angaben', variant: 'base',
    badge: null, description: null, collapsed: false, items: [],
  }
}

/** Zwei Felder pro Zeile – die Darstellung vor dem Layout-Layer. */
function asHalfItems(rows: RenderedField[]): ResolvedItem[] {
  return rows.map((r) => ({ item: fieldItem(r.ref.ref), rendered: r, cols: WIDTH_COLS.half }))
}

/**
 * Trennlinie und Abstand allein füllen keinen Abschnitt: eine Karte, in der nur
 * ein Strich steht (weil alle Felder unsichtbar sind), ist visueller Müll.
 */
function hasContent(items: ResolvedItem[]): boolean {
  return items.some((i) => i.item.type === 'field' || i.item.type === 'note'
    || i.item.type === 'heading')
}

export function resolveLayout(
  defn: ProcessDefinition,
  phase: PhaseDef,
  values: Record<string, unknown>,
  viewer: SimViewer,
): ResolvedSection[] {
  if (!defn || !phase) return []

  // Einmal auswerten und wiederverwenden – renderFields wertet Bedingungen aus.
  const seenRef = new Set<string>()
  const visible: RenderedField[] = []
  for (const r of renderFields(defn, phase, values, viewer)) {
    if (!r.visible || seenRef.has(r.ref.ref)) continue
    seenRef.add(r.ref.ref)
    visible.push(r)
  }
  const byRef = new Map(visible.map((r) => [r.ref.ref, r]))

  const layout = phase.layout ?? []
  if (!layout.length) {
    // Kein Layout gepflegt → genau wie früher: ein Abschnitt, alles zweispaltig.
    return visible.length ? [{ section: fallbackSection(phase), items: asHalfItems(visible) }] : []
  }

  const placed = new Set<string>()
  const out: ResolvedSection[] = []
  for (const section of layout) {
    const items: ResolvedItem[] = []
    for (const item of section.items ?? []) {
      if (item.type === 'field') {
        const rendered = byRef.get(item.ref)
        // Unsichtbar, nicht in dieser Phase oder schon platziert → auslassen.
        if (!rendered || placed.has(item.ref)) continue
        placed.add(item.ref)
        items.push({ item, rendered, cols: itemCols(item) })
      } else {
        items.push({ item, cols: itemCols(item) })
      }
    }
    if (!hasContent(items)) continue
    out.push({ section, items })
  }

  const rest = visible.filter((r) => !placed.has(r.ref.ref))
  if (rest.length) out.push({ section: restSection(), items: asHalfItems(rest) })
  return out
}
