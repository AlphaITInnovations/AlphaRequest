/**
 * API-Client für das persönliche Archiv (/api/v1/process-tickets/archive).
 *
 * Zeigt alle Aufträge (jeder Status), an denen die angemeldete Person je beteiligt
 * war: Aufsicht, Ersteller:in, Beobachter:in oder Mitglied einer je zuständigen
 * Gruppe/Fachabteilung (bedingte Abteilungen werden serverseitig gegen die
 * Auftragswerte geprüft). Die Zeilen tragen bewusst KEINE Feldwerte – Detailwerte
 * gibt es nur in der Detail-Ansicht, dort nach Sichtbarkeit gefiltert.
 */
import { client } from '@/api/client'

export interface ArchiveRow {
  id: number
  process_key: string
  process_version: number
  title: string
  status: string
  priority: string
  phase: string | null
  phase_label: string | null
  is_owner: boolean
  /** Ersteller:in (für das globale Archiv als Spalte/Filter). */
  owner_name: string
  created_at: string
  updated_at: string
}

export interface ArchivePage {
  items: ArchiveRow[]
  total: number
  limit: number
  offset: number
  /** Scan-Obergrenze erreicht – die Liste ist evtl. nicht vollständig. */
  truncated: boolean
}

export type ArchiveSort = 'updated_desc' | 'updated_asc' | 'created_desc' | 'created_asc'

export interface ImportReportRow { line: number; id: number | null; reason?: string }
export interface ImportReport {
  committed: boolean
  counts: { created: number; skipped: number; failed: number }
  created: ImportReportRow[]
  skipped: ImportReportRow[]
  failed: ImportReportRow[]
}

/** Die gleichen Filter wie die Liste – der Export umfasst den GANZEN gefilterten
 *  Satz (nicht nur die Seite). Antwort ist ein CSV-Blob (Download). Admin-only. */
export async function exportArchiveCsv(params: {
  q?: string; status?: string[]; process_key?: string
  created_by?: string; date_from?: string; date_to?: string
  date_field?: 'created' | 'updated'; sort?: ArchiveSort
} = {}): Promise<Blob> {
  const { status, ...rest } = params
  const query: Record<string, unknown> = { ...rest }
  if (status && status.length) query.status = status.join(',')
  try {
    const { data } = await client.get('/process-tickets/archive.csv',
      { params: query, responseType: 'blob' })
    return data as Blob
  } catch (e) {
    // Bei responseType:'blob' kommt AUCH der Fehler-Body als Blob an – den
    // JSON-Umschlag {error:{message}} zurückwandeln, damit errorMessage() die
    // Server-Meldung zeigt (z. B. 403 „Admins vorbehalten") statt der generischen
    // englischen axios-Meldung. Gleiche Konvention wie exportTicketDocument().
    const resp = (e as { response?: { data?: unknown } })?.response
    if (resp?.data instanceof Blob) {
      try { resp.data = JSON.parse(await resp.data.text()) } catch { /* kein JSON */ }
    }
    throw e
  }
}

/** CSV-Restore. `commit=false` = VORSCHAU (schreibt nichts, liefert nur den
 *  Bericht). Admin-only; legt fehlende Nummern an, vorhandene werden übersprungen. */
export async function importArchiveCsv(csv: string, commit: boolean): Promise<ImportReport> {
  const { data } = await client.post('/process-tickets/archive:import-csv', { csv, commit })
  return data.data
}

export async function listArchive(
  params: {
    q?: string; status?: string[]; process_key?: string
    /** Nur globales Archiv (Aufsicht): Ersteller-Substring, Datumsbereich, Sortierung. */
    created_by?: string; date_from?: string; date_to?: string
    date_field?: 'created' | 'updated'; sort?: ArchiveSort
    scope?: 'mine' | 'global'; limit?: number; offset?: number
  } = {},
): Promise<ArchivePage> {
  const { status, scope, ...rest } = params
  // Backend erwartet scope=all fürs globale Archiv (Aufsicht); Default = persönlich.
  if (scope === 'global') (rest as Record<string, unknown>).scope = 'all'
  const query: Record<string, unknown> = { ...rest }
  // Mehrere Status komma-separiert (der Server splittet) – vermeidet die
  // uneinheitliche Array-Serialisierung von axios.
  if (status && status.length) query.status = status.join(',')
  const { data } = await client.get('/process-tickets/archive', { params: query })
  return data.data
}
