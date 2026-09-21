/**
 * Directus-Anbindung: Verbindungsstatus, Schema-Introspektion, Quellen-CRUD,
 * Vorschau und Live-Optionen. Dünn – nur das Auspacken des DataResponse-Envelopes.
 */
import { client } from '@/api/client'

export interface DirectusSource {
  key: string
  label: string
  collection: string
  valueField: string
  labelTemplate: string
  fields: string[]
  filter: Record<string, unknown> | null
  sort: string[]
  limit: number
}

export interface DirectusStatus { configured: boolean; ok: boolean; error: string | null }
export interface DirectusCollection { collection: string; note?: string | null; icon?: string | null; hidden?: boolean }
export interface DirectusField {
  field: string; type?: string | null; note?: string | null
  primaryKey?: boolean; relatedCollection?: string | null
}
export interface DirectusOption { value: string; label: string; record: Record<string, any> }

export async function getStatus(): Promise<DirectusStatus> {
  const { data } = await client.get('/directus/status')
  return data.data
}

export async function listSources(): Promise<DirectusSource[]> {
  const { data } = await client.get('/directus/sources')
  return data.data ?? []
}

export async function saveSources(sources: DirectusSource[]): Promise<DirectusSource[]> {
  const { data } = await client.put('/directus/sources', { sources })
  return data.data ?? []
}

export async function listCollections(): Promise<DirectusCollection[]> {
  const { data } = await client.get('/directus/collections')
  return data.data ?? []
}

export async function listFields(collection: string): Promise<DirectusField[]> {
  const { data } = await client.get(`/directus/collections/${encodeURIComponent(collection)}/fields`)
  return data.data ?? []
}

export async function previewSource(src: DirectusSource): Promise<{ options: DirectusOption[]; fields: string[] }> {
  const { data } = await client.post('/directus/sources:preview', src)
  return data.data
}

/** process/field/phase: lässt den Server die directusFieldMap-Quellfelder dieses
 *  Feldes mitladen, damit die Snapshot-Zielfelder LIVE (bei der Auswahl) füllen. */
export async function sourceOptions(
  key: string,
  search = '',
  ctx?: { process?: string | null; field?: string | null; phase?: string | null },
): Promise<{ options: DirectusOption[]; error: string | null }> {
  const params: Record<string, string> = {}
  if (search) params.search = search
  if (ctx?.process) params.process = ctx.process
  if (ctx?.field) params.field = ctx.field
  if (ctx?.phase) params.phase = ctx.phase
  const { data } = await client.get(`/directus/sources/${encodeURIComponent(key)}/options`, { params })
  return data.data
}

/**
 * Labels zu bereits gespeicherten Directus-Werten (IDs) auflösen – für die Lese-/
 * Druckansicht, die nur die ID kennt. fail-soft: eine leere Map (Aufrufer zeigt
 * dann die ID). Antwort-Form {labels: {id: label}}.
 */
export async function resolveLabels(key: string, values: string[]): Promise<Record<string, string>> {
  const uniq = Array.from(new Set(values.filter((v) => v != null && v !== '').map(String)))
  if (!uniq.length) return {}
  try {
    const { data } = await client.get(`/directus/sources/${encodeURIComponent(key)}/resolve`,
      { params: { values: uniq.join(',') } })
    return data.data?.labels ?? {}
  } catch {
    return {}   // fail-soft: ohne Auflösung bleibt die ID stehen
  }
}
