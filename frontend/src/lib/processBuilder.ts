/**
 * Baukasten-Operationen des Formular-Editors: EIN Weg für „Feld hinzufügen",
 * „Feld entfernen" und „verschieben" – jede Operation hält die drei Ebenen der
 * Definition synchron, die vorher getrennt gepflegt wurden:
 *
 *   definition.fields  (WAS ein Feld ist   – der Katalog)
 *   phase.fields       (WIE es sich verhält – FieldRef mit mode/required/…)
 *   phase.layout       (WO es steht         – Abschnitte und Breiten)
 *
 * Der Baukasten zeigt das Formular so, wie es die Laufzeit rendert
 * (lib/processLayout.resolveLayout): die echten Abschnitte des Layouts plus
 * einen VIRTUELLEN Rest-Abschnitt für Felder der Phase, die nirgends platziert
 * sind. Deshalb braucht es keine Migration alter Definitionen – ein leeres
 * Layout bleibt leer (Standarddarstellung), bis die erste Platzierung es
 * materialisiert.
 *
 * Alle Funktionen arbeiten IMMUTABEL auf der GANZEN Definition und geben bei
 * unmöglichen Eingaben (Index daneben, unbekannter Key) die Eingabe
 * referenzgleich zurück – der Aufrufer kann sich das Emit dann sparen.
 */
import type {
  FieldDef, FieldRef, LayoutItem, LayoutSection, PhaseDef, ProcessDefinition, Widget,
} from '@/types/process'
import { blankFieldDef, blankFieldRef, blankLayoutItem, placedRefs } from '@/lib/processSchema'
import {
  addItem, moveItem, removeItem, unplacedRefs,
} from '@/lib/processLayoutEdit'

// ── Adressierung ──────────────────────────────────────────────────────────────

/** Position eines Elements im Baukasten. `section = -1` = virtueller
 *  Rest-Abschnitt („Weitere Angaben", nicht platzierte Felder). */
export interface BuilderPos {
  section: number
  item: number
}

export const REST_SECTION = -1

function phaseAt(defn: ProcessDefinition, phaseIndex: number): PhaseDef | null {
  return defn.phases[phaseIndex] ?? null
}

function withPhase(defn: ProcessDefinition, phaseIndex: number,
                   part: Partial<PhaseDef>): ProcessDefinition {
  return {
    ...defn,
    phases: defn.phases.map((p, i) => (i === phaseIndex ? { ...p, ...part } : p)),
  }
}

// ── Lesen ─────────────────────────────────────────────────────────────────────

/** Refs des virtuellen Rest-Abschnitts (Reihenfolge = phase.fields). */
export function restRefs(phase: PhaseDef): string[] {
  return unplacedRefs(phase.layout, phase.fields)
}

/** FieldRef zu einem Key (erste Fundstelle – Duplikate meldet die Validierung). */
export function refOf(phase: PhaseDef, key: string): FieldRef | null {
  return phase.fields.find((f) => f.ref === key) ?? null
}

/** In wie vielen Phasen ist das Feld eingebunden? (Für die Lösch-Rückfrage.) */
export function phasesUsing(defn: ProcessDefinition, key: string): string[] {
  return defn.phases
    .filter((p) => p.fields.some((f) => f.ref === key))
    .map((p) => p.label || p.key)
}

/** Freier Katalog-Schlüssel feld_1, feld_2, … – ein neues Feld ist sofort gültig. */
export function suggestFieldKey(defn: ProcessDefinition): string {
  const used = new Set(defn.fields.map((f) => f.key))
  let n = 1
  while (used.has(`feld_${n}`)) n++
  return `feld_${n}`
}

// ── Feld hinzufügen (die EINE Aktion) ─────────────────────────────────────────

/**
 * Neues Feld anlegen: Katalog-Eintrag + Einbindung in die Phase + Platzierung
 * im Ziel-Abschnitt – in einem Schritt. Ohne echten Abschnitt (oder Ziel
 * REST_SECTION) bleibt das Feld unplatziert und erscheint im Rest-Abschnitt.
 * Gibt den neuen Schlüssel mit zurück, damit der Editor das Feld aufklappen kann.
 */
export function addNewField(defn: ProcessDefinition, phaseIndex: number,
                            section: number, widget: Widget,
): { defn: ProcessDefinition; key: string } {
  const phase = phaseAt(defn, phaseIndex)
  if (!phase) return { defn, key: '' }
  const key = suggestFieldKey(defn)
  let next: ProcessDefinition = { ...defn, fields: [...defn.fields, blankFieldDef(key, widget)] }
  next = withPhase(next, phaseIndex, { fields: [...phase.fields, blankFieldRef(key)] })
  if (section !== REST_SECTION) {
    const layout = addItem(next.phases[phaseIndex].layout, section,
                           blankLayoutItem('field', key))
    next = withPhase(next, phaseIndex, { layout })
  }
  return { defn: next, key }
}

/** Vorhandenes Katalog-Feld in die Phase einbinden (+ platzieren). */
export function addExistingField(defn: ProcessDefinition, phaseIndex: number,
                                 section: number, key: string): ProcessDefinition {
  const phase = phaseAt(defn, phaseIndex)
  if (!phase || !defn.fields.some((f) => f.key === key)) return defn
  if (phase.fields.some((f) => f.ref === key)) return defn
  let next = withPhase(defn, phaseIndex, { fields: [...phase.fields, blankFieldRef(key)] })
  if (section !== REST_SECTION) {
    const layout = addItem(next.phases[phaseIndex].layout, section,
                           blankLayoutItem('field', key))
    next = withPhase(next, phaseIndex, { layout })
  }
  return next
}

// ── Feld entfernen ────────────────────────────────────────────────────────────

/** Alle Platzierungen eines Feldes aus dem Layout einer Phase nehmen. */
function stripFromLayout(layout: LayoutSection[], key: string): LayoutSection[] {
  return layout.map((sec) => ({
    ...sec,
    items: sec.items.filter((it) => !(it.type === 'field' && it.ref === key)),
  }))
}

/**
 * Feld aus DIESER Phase nehmen: Einbindung UND Platzierung. Der Katalog-Eintrag
 * bleibt – das Feld kann in anderen Phasen weiterleben oder neu eingebunden
 * werden (der Rest-Katalog erscheint im „+ Feld"-Menü).
 */
export function removeFieldFromPhase(defn: ProcessDefinition, phaseIndex: number,
                                     key: string): ProcessDefinition {
  const phase = phaseAt(defn, phaseIndex)
  if (!phase || !phase.fields.some((f) => f.ref === key)) return defn
  return withPhase(defn, phaseIndex, {
    fields: phase.fields.filter((f) => f.ref !== key),
    layout: stripFromLayout(phase.layout, key),
  })
}

/** Feld ÜBERALL entfernen: Katalog + jede Phase (Einbindung und Platzierung). */
export function deleteFieldEverywhere(defn: ProcessDefinition, key: string): ProcessDefinition {
  if (!defn.fields.some((f) => f.key === key)) return defn
  return {
    ...defn,
    fields: defn.fields.filter((f) => f.key !== key),
    phases: defn.phases.map((p) => ({
      ...p,
      fields: p.fields.filter((f) => f.ref !== key),
      layout: stripFromLayout(p.layout, key),
    })),
  }
}

// ── Verschieben (Drag & Drop) ─────────────────────────────────────────────────

function itemAt(phase: PhaseDef, pos: BuilderPos): LayoutItem | null {
  if (pos.section === REST_SECTION) return null
  return phase.layout[pos.section]?.items[pos.item] ?? null
}

/**
 * Element von `from` nach `to` verschieben – deckt alle vier Fälle ab:
 *   Abschnitt → Abschnitt (auch derselbe), Rest → Abschnitt (platzieren),
 *   Abschnitt → Rest (Platzierung lösen), Rest → Rest (phase.fields umsortieren).
 * `to.item` ist die Einfüge-Position im Ziel (0 = ganz oben; >= Länge = ans Ende).
 */
export function moveBuilderItem(defn: ProcessDefinition, phaseIndex: number,
                                from: BuilderPos, to: BuilderPos): ProcessDefinition {
  const phase = phaseAt(defn, phaseIndex)
  if (!phase) return defn

  // Rest → Rest: nur die Reihenfolge der (unplatzierten) FieldRefs ändern.
  if (from.section === REST_SECTION && to.section === REST_SECTION) {
    const rest = restRefs(phase)
    const key = rest[from.item]
    if (!key) return defn
    const ziel = rest[Math.min(to.item, rest.length - 1)]
    const fromIdx = phase.fields.findIndex((f) => f.ref === key)
    let toIdx = ziel ? phase.fields.findIndex((f) => f.ref === ziel) : phase.fields.length - 1
    if (fromIdx < 0 || toIdx < 0) return defn
    if (fromIdx === toIdx) return defn
    const next = moveItem(phase.fields, fromIdx, toIdx - fromIdx)
    if (next === phase.fields) return defn
    return withPhase(defn, phaseIndex, { fields: next })
  }

  // Rest → Abschnitt: platzieren (FieldRef bleibt, Layout-Item entsteht).
  if (from.section === REST_SECTION) {
    const key = restRefs(phase)[from.item]
    if (!key || !phase.layout[to.section]) return defn
    const item = blankLayoutItem('field', key)
    return withPhase(defn, phaseIndex, {
      layout: insertAt(phase.layout, to, item),
    })
  }

  const moved = itemAt(phase, from)
  if (!moved) return defn

  // Abschnitt → Rest: Platzierung lösen. Nur für Felder sinnvoll –
  // Deko-Elemente existieren außerhalb des Layouts nicht und werden gelöscht.
  if (to.section === REST_SECTION) {
    return withPhase(defn, phaseIndex, {
      layout: removeItem(phase.layout, from.section, from.item),
    })
  }

  // Abschnitt → Abschnitt: entfernen + einfügen (Index-Korrektur im selben
  // Abschnitt, wenn das Entfernen die Zielposition verschiebt).
  let layout = removeItem(phase.layout, from.section, from.item)
  const ziel: BuilderPos = { ...to }
  if (from.section === to.section && from.item < to.item) ziel.item -= 1
  layout = insertAt(layout, ziel, moved)
  return withPhase(defn, phaseIndex, { layout })
}

/** Item an Position einfügen (Position wird ans Listenende geklemmt). */
function insertAt(layout: LayoutSection[], pos: BuilderPos, item: LayoutItem): LayoutSection[] {
  const sec = layout[pos.section]
  if (!sec) return layout
  const items = [...sec.items]
  const at = Math.max(0, Math.min(pos.item, items.length))
  items.splice(at, 0, item)
  return layout.map((s, i) => (i === pos.section ? { ...s, items } : s))
}

// ── FieldRef-Einstellungen (WIE) am Key statt am Index ────────────────────────

export function patchRef(defn: ProcessDefinition, phaseIndex: number, key: string,
                         part: Partial<FieldRef>): ProcessDefinition {
  const phase = phaseAt(defn, phaseIndex)
  if (!phase || !phase.fields.some((f) => f.ref === key)) return defn
  return withPhase(defn, phaseIndex, {
    fields: phase.fields.map((f) => (f.ref === key ? { ...f, ...part } : f)),
  })
}

/** Katalog-Eintrag (WAS) ersetzen – Umbenennungen zieht der Aufrufer über
 *  renameFieldKey nach (strukturell, nicht hier). */
export function patchDef(defn: ProcessDefinition, key: string,
                         next: FieldDef): ProcessDefinition {
  if (!defn.fields.some((f) => f.key === key)) return defn
  return { ...defn, fields: defn.fields.map((f) => (f.key === key ? next : f)) }
}

// ── Aufräumen ─────────────────────────────────────────────────────────────────

/** Verwaiste Platzierungen (Layout-Ref ohne FieldRef) einer Phase entfernen. */
export function pruneOrphans(defn: ProcessDefinition, phaseIndex: number): ProcessDefinition {
  const phase = phaseAt(defn, phaseIndex)
  if (!phase) return defn
  const known = new Set(phase.fields.map((f) => f.ref))
  const layout = phase.layout.map((sec) => ({
    ...sec,
    items: sec.items.filter((it) => it.type !== 'field' || known.has(it.ref)),
  }))
  if (placedRefs(layout).size === placedRefs(phase.layout).size) return defn
  return withPhase(defn, phaseIndex, { layout })
}
