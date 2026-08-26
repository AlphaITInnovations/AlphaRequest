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

export async function sourceOptions(key: string, search = ''): Promise<{ options: DirectusOption[]; error: string | null }> {
  const { data } = await client.get(`/directus/sources/${encodeURIComponent(key)}/options`,
    { params: search ? { search } : {} })
  return data.data
}
