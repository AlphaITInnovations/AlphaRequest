/**
 * Auswahl-Quellen für Prozess-Formulare und -Editor (Fachabteilungen, Personen,
 * Firmen).
 *
 * Bewusst EINE Stelle: die Envelope-Formen der drei Endpunkte unterscheiden sich
 * (`/settings/groups` → data: [...], `/users` → data.users, `/companies` →
 * data.companies). Drei Kopien dieser Logik hatten genau hier je einen Fehler,
 * der die Picker still leer ließ.
 */
import { client } from '@/api/client'
import type { OptionSources } from '@/types/process'

export function emptySources(): OptionSources {
  return { groups: [], users: [], companies: [] }
}

/**
 * Lädt alle Quellen. Einzelne Fehlschläge sind nicht fatal (dann fehlen nur
 * Namen), werden aber protokolliert – nie stumm verschluckt.
 * `adminGroups`: /settings/groups liefert auch versteckte Gruppen (nur Admin);
 * ohne Adminrechte auf den öffentlichen /groups-Endpunkt ausweichen.
 */
export async function loadOptionSources(adminGroups = true): Promise<OptionSources> {
  const out = emptySources()

  try {
    const { data } = await client.get(adminGroups ? '/settings/groups' : '/groups')
    const list = Array.isArray(data?.data) ? data.data : []
    out.groups = list
      .filter((g: any) => g && g.id)
      .map((g: any) => ({ id: String(g.id), name: String(g.name ?? g.id) }))
  } catch (e) {
    console.warn('Fachabteilungen konnten nicht geladen werden', e)
  }

  try {
    const { data } = await client.get('/users')
    const list = Array.isArray(data?.data?.users) ? data.data.users : []
    out.users = list
      .filter((u: any) => u && u.id)
      .map((u: any) => ({ id: String(u.id), displayName: String(u.displayName ?? u.mail ?? u.id) }))
  } catch (e) {
    console.warn('Personen konnten nicht geladen werden', e)
  }

  try {
    const { data } = await client.get('/companies')
    const list = Array.isArray(data?.data?.companies) ? data.data.companies : []
    out.companies = list
      .map((c: any) => (typeof c === 'string' ? c : c?.name))
      .filter((c: unknown): c is string => typeof c === 'string' && c.length > 0)
  } catch (e) {
    console.warn('Firmen konnten nicht geladen werden', e)
  }

  return out
}
