/**
 * Gruppen-Referenzen einer Prozess-Definition: sammeln, prüfen, gezielt ersetzen.
 *
 * Die ausgelieferten Vorlagen (backend/seeds/processes/) enthalten statt
 * Gruppen-IDs Platzhalter (`HIER_GRUPPEN_ID_*_EINSETZEN`), Exporte aus anderen
 * Installationen echte, hier unbekannte IDs. Beides sammelt der Import-Dialog
 * hier ein und lässt es per Dropdown den bestehenden Fachabteilungen zuordnen.
 *
 * Ersetzt wird NUR an den Stellen, an denen strukturell eine Gruppen-ID steht
 * (Feld-Sichtbarkeit, Phasen-Zuständigkeit, Abteilungs-Regeln,
 * Automations-Empfänger, Erstellrechte) – nie per Text-Ersetzung, sonst
 * mutierte ein im Hilfetext ERWÄHNTER Platzhalter zu einer ID. Spiegelbild von
 * backend/services/seed_definitions.py (collect_group_refs,
 * PLACEHOLDER_GROUP_NAMES).
 */
import type { ProcessDefinition } from '@/types/process'

const PLACEHOLDER_RE = /^HIER_[A-Z0-9_]*_EINSETZEN$/

/**
 * Platzhalter → Klartext-Name der Fachabteilung. Bewusst eine Konstante und
 * keine Ableitung aus dem Platzhalter-Text („SEKRETARIAT_GL" → „Sekretariat GL"
 * klappte zufällig, „FREIGABEHERRLUTZ" → „FreigabeHerrLutz" nicht mehr).
 * Muss mit dem Backend übereinstimmen (seed_definitions.PLACEHOLDER_GROUP_NAMES).
 */
export const PLACEHOLDER_GROUP_NAMES: Record<string, string> = {
  HIER_GRUPPEN_ID_IT_EINSETZEN: 'IT',
  HIER_GRUPPEN_ID_PERSONALABTEILUNG_EINSETZEN: 'Personalabteilung',
  HIER_GRUPPEN_ID_FUHRPARK_EINSETZEN: 'Fuhrpark',
  HIER_GRUPPEN_ID_VERWALTUNG_EINSETZEN: 'Verwaltung',
  HIER_GRUPPEN_ID_MARKETING_EINSETZEN: 'Marketing',
  HIER_GRUPPEN_ID_HOTELBUCHUNG_EINSETZEN: 'Hotelbuchung',
  HIER_GRUPPEN_ID_REISESTELLE_EINSETZEN: 'Reisestelle',
  HIER_GRUPPEN_ID_SEKRETARIAT_GL_EINSETZEN: 'Sekretariat GL',
  HIER_GRUPPEN_ID_FREIGABEHERRLUTZ_EINSETZEN: 'FreigabeHerrLutz',
}

export function isGroupPlaceholder(value: string): boolean {
  return PLACEHOLDER_RE.test(value)
}

export interface GroupRefSite {
  path: string
  value: string
}

/** Alle Stellen, an denen eine Gruppen-ID STEHT (Pfad, Wert). */
export function collectGroupRefs(d: ProcessDefinition): GroupRefSite[] {
  const out: GroupRefSite[] = []

  const autos = (items: ProcessDefinition['automations'], base: string) => {
    items.forEach((a, i) => {
      const to = a.action?.to
      if (typeof to === 'string' && to.startsWith('group:')) {
        out.push({ path: `${base}.${i}.action.to`, value: to.slice(6) })
      }
    })
  }

  d.fields.forEach((f, i) => {
    f.visibility?.visibleToGroups.forEach((g, j) => {
      out.push({ path: `fields.${i}.visibility.visibleToGroups.${j}`, value: g })
    })
  })

  autos(d.automations, 'automations')

  d.phases.forEach((p, i) => {
    const r = p.responsibility
    if (r.group) out.push({ path: `phases.${i}.responsibility.group`, value: r.group })
    r.rule.forEach((dr, j) => {
      if (dr.group) out.push({ path: `phases.${i}.responsibility.rule.${j}.group`, value: dr.group })
    })
    autos(p.automations, `phases.${i}.automations`)
  })

  d.createPermissions.groups.forEach((g, j) => {
    out.push({ path: `createPermissions.groups.${j}`, value: g })
  })

  return out
}

export interface UnknownGroupRef {
  /** Der fremde Wert, wie er in der Definition steht (Platzhalter oder ID). */
  value: string
  placeholder: boolean
  /** Lesbarer Name: Platzhalter → Klartext, sonst der rohe Wert. */
  label: string
  /** Anzahl Fundstellen in der Definition. */
  sites: number
  /** Gruppen-ID mit passendem Namen (case-insensitiv) – Vorbelegung fürs Dropdown. */
  suggestion: string | null
}

/**
 * Alle fremden Gruppen-Referenzen der Definition, je Wert EIN Eintrag.
 * Reihenfolge: Platzhalter zuerst (die blockieren den Import), dann IDs,
 * innerhalb dessen nach Fundreihenfolge.
 */
export function unknownGroupRefs(
  d: ProcessDefinition, groups: { id: string; name: string }[],
): UnknownGroupRef[] {
  const known = new Set(groups.map((g) => g.id))

  // Name (kleingeschrieben, getrimmt) → ID; mehrdeutige Namen geben keinen
  // Vorschlag – lieber keine Vorbelegung als die falsche Gruppe.
  const byName = new Map<string, string | null>()
  for (const g of groups) {
    const name = g.name.trim().toLowerCase()
    if (!name) continue
    byName.set(name, byName.has(name) && byName.get(name) !== g.id ? null : g.id)
  }

  const counts = new Map<string, number>()
  for (const { value } of collectGroupRefs(d)) {
    if (!known.has(value)) counts.set(value, (counts.get(value) ?? 0) + 1)
  }

  const rows: UnknownGroupRef[] = []
  for (const [value, sites] of counts) {
    const placeholder = isGroupPlaceholder(value)
    const label = PLACEHOLDER_GROUP_NAMES[value] ?? value
    const suggestion = placeholder
      ? (byName.get(label.trim().toLowerCase()) ?? null)
      : null
    rows.push({ value, placeholder, label, sites, suggestion })
  }
  return rows.sort((a, b) => Number(b.placeholder) - Number(a.placeholder))
}

/**
 * Klont den Baum und ersetzt dabei String-Blätter, die EXAKT einem
 * Mapping-Schlüssel entsprechen. Bewusst ein eigener Klon statt
 * `structuredClone`: das Modal übergibt `parsed` aus einem tiefen ref(), also
 * einen Reactive-Proxy – den kann structuredClone nicht klonen (DataCloneError).
 */
function replaceLeaves(node: unknown, mapping: Record<string, string>): unknown {
  if (Array.isArray(node)) return node.map((v) => replaceLeaves(v, mapping))
  if (node && typeof node === 'object') {
    const out: Record<string, unknown> = {}
    for (const [k, v] of Object.entries(node)) out[k] = replaceLeaves(v, mapping)
    return out
  }
  if (typeof node === 'string') return mapping[node] ?? node
  return node
}

/**
 * Ersetzt fremde Gruppen-Referenzen gemäß `mapping` (fremder Wert → Gruppen-ID).
 * Werte ohne Eintrag in `mapping` bleiben unverändert; die Eingabe wird nicht
 * mutiert.
 *
 * Echte IDs werden NUR an den Gruppen-Stellen ersetzt, die `collectGroupRefs`
 * kennt – eine zufällig gleichlautende Options- oder Vergleichs-Konstante darf
 * nicht mutieren. Zugeordnete PLATZHALTER dagegen an jedem exakten String-Blatt:
 * das spiegelt das serverseitige `replace_placeholders`, sonst entschiede der
 * Server bei einem Platzhalter an einer Nicht-Gruppen-Stelle per Namens-Lookup
 * ANDERS als die hier getroffene Zuordnung.
 */
export function replaceGroupRefs(
  d: ProcessDefinition, mapping: Record<string, string>,
): ProcessDefinition {
  const platzhalter = Object.fromEntries(
    Object.entries(mapping).filter(([wert]) => isGroupPlaceholder(wert)))
  const out = replaceLeaves(d, platzhalter) as ProcessDefinition
  const swap = (v: string) => mapping[v] ?? v

  const autos = (items: ProcessDefinition['automations']) => {
    for (const a of items) {
      const to = a.action?.to
      if (typeof to === 'string' && to.startsWith('group:')) {
        a.action.to = `group:${swap(to.slice(6))}`
      }
    }
  }

  for (const f of out.fields) {
    if (f.visibility) f.visibility.visibleToGroups = f.visibility.visibleToGroups.map(swap)
  }
  autos(out.automations)
  for (const p of out.phases) {
    const r = p.responsibility
    if (r.group) r.group = swap(r.group)
    for (const dr of r.rule) {
      if (dr.group) dr.group = swap(dr.group)
    }
    autos(p.automations)
  }
  out.createPermissions.groups = out.createPermissions.groups.map(swap)

  return out
}
