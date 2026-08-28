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

export async function listArchive(
  params: { q?: string; limit?: number; offset?: number } = {},
): Promise<ArchivePage> {
  const { data } = await client.get('/process-tickets/archive', { params })
  return data.data
}
