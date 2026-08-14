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

async function fetchGroups(pfad: '/settings/groups' | '/groups') {
  const { data } = await client.get(pfad)
  const list = Array.isArray(data?.data) ? data.data : []
  return list
    .filter((g: any) => g && g.id)
    .map((g: any) => ({ id: String(g.id), name: String(g.name ?? g.id) }))
}

/**
 * Lädt alle Quellen. Einzelne Fehlschläge sind nicht fatal (dann fehlen nur
 * Namen), werden aber protokolliert – nie stumm verschluckt.
 * `adminGroups`: /settings/groups liefert auch versteckte Gruppen (nur Admin).
 * Schlägt der Admin-Endpunkt fehl (typisch: 403 ohne Adminrechte), wird auf den
 * öffentlichen /groups-Endpunkt AUSGEWICHEN statt leer weiterzumachen – ohne
 * Namen zeigte die Oberfläche rohe Gruppen-IDs an.
 */
export async function loadOptionSources(adminGroups = true): Promise<OptionSources> {
  const out = emptySources()

  try {
    out.groups = await fetchGroups(adminGroups ? '/settings/groups' : '/groups')
  } catch (e) {
    if (adminGroups) {
      try {
        out.groups = await fetchGroups('/groups')
      } catch (e2) {
        console.warn('Fachabteilungen konnten nicht geladen werden', e2)
      }
    } else {
      console.warn('Fachabteilungen konnten nicht geladen werden', e)
    }
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
