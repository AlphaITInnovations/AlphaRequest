/**
 * Directus-Labels für den Verlauf auflösen.
 *
 * `sources.directusLabels` kennt nur die AKTUELLEN Werte eines Auftrags. Ein im
 * Verlauf geänderter directus-Wert würde seinen alten (und teils neuen) Stand sonst
 * als rohe ID zeigen. Diese Helfer sammeln die im Verlauf vorkommenden IDs ein und
 * mischen die dazu aufgelösten Labels in die Quellen – rein (ohne Vue/Netz), damit
 * die Komponente schlank und die Logik testbar bleibt.
 */
import type { FieldDef, OptionSources } from '@/types/process'

type ChangeVal = { from?: unknown; to?: unknown }
interface HistoryEvent {
  action?: string
  details?: { changes?: Record<string, ChangeVal> | null } | null
}

/** directus-IDs (alt UND neu) aus allen „updated"-Verlaufseinträgen je Quelle. */
export function collectDirectusIds(
  events: HistoryEvent[], fieldByKey: Record<string, FieldDef>,
): Record<string, string[]> {
  const bySource: Record<string, Set<string>> = {}
  for (const ev of events) {
    if (ev.action !== 'updated') continue
    const changes = ev.details?.changes ?? {}
    for (const [key, ch] of Object.entries(changes)) {
      const field = fieldByKey[key]
      if (!field?.directusSource) continue
      if (field.widget !== 'directus' && field.widget !== 'directus_multi') continue
      const set = (bySource[field.directusSource] ??= new Set<string>())
      for (const val of [ch?.from, ch?.to]) {
        for (const v of Array.isArray(val) ? val : [val]) {
          if (v !== null && v !== undefined && v !== '') set.add(String(v))
        }
      }
    }
  }
  const out: Record<string, string[]> = {}
  for (const [src, ids] of Object.entries(bySource)) out[src] = [...ids]
  return out
}

/** Verlaufs-Labels mit den Quell-Labels mischen. Die AKTUELLEN (`base`) haben
 *  Vorrang – ohne Verlaufs-Labels bleibt `base` unverändert. */
export function mergeDirectusLabels(
  base: OptionSources | undefined,
  history: Record<string, Record<string, string>>,
): OptionSources | undefined {
  if (!Object.keys(history).length) return base
  const merged: Record<string, Record<string, string>> = {}
  for (const [src, labels] of Object.entries(history)) merged[src] = { ...labels }
  for (const [src, labels] of Object.entries(base?.directusLabels ?? {})) {
    merged[src] = { ...(merged[src] ?? {}), ...labels }
  }
  return { ...(base ?? {}), directusLabels: merged } as OptionSources
}
