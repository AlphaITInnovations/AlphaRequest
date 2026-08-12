/**
 * API-Client für Prozess-Definitionen (/api/v1/processes).
 *
 * Fallstricke, die hier gekapselt sind:
 *  - Listen-Routen liefern `definition: null` → der Editor lädt immer getVersion().
 *  - `:export` liefert die ROHE Definition, keinen ProcessOut.
 *  - DELETE liefert `{ok:true}` ohne data-Envelope.
 *  - If-Match ist der unquoted Integer-String aus ProcessOut.etag (Body!).
 *  - Der Doppelpunkt in `:publish`/`:export` darf NICHT URL-encodiert werden.
 */
import { client } from '@/api/client'
import type { FieldAccess, ProcessDefinition, ProcessOut } from '@/types/process'

/** Veröffentlichter Katalog (jede:r Angemeldete). Ohne `definition`. */
export async function listProcesses(): Promise<ProcessOut[]> {
  const { data } = await client.get('/processes')
  return data.data
}

/** Alle Versionen eines Prozesses (Manage/Admin). Ohne `definition`. */
export async function listVersions(key: string): Promise<ProcessOut[]> {
  const { data } = await client.get(`/processes/${encodeURIComponent(key)}/versions`)
  return data.data
}

/** Eine Version inkl. `definition` (Manage/Admin). */
export async function getVersion(key: string, version: number): Promise<ProcessOut> {
  const { data } = await client.get(`/processes/${encodeURIComponent(key)}/versions/${version}`)
  return data.data
}

/** Aktuell veröffentlichte Version inkl. `definition`. */
export async function getPublished(key: string): Promise<ProcessOut> {
  const { data } = await client.get(`/processes/${encodeURIComponent(key)}`)
  return data.data
}

/** Rohe Definition einer Version (Export-Datei). */
/**
 * Feld-Auskunft für den Anlege-Dialog. Beim Anlegen gibt es noch kein Ticket und
 * damit keine Antwort mit `visible_fields` – ohne diese Auskunft müsste das
 * Formular die Sichtbarkeit raten (es kennt die Gruppen-Mitgliedschaft nicht).
 */
export async function getFieldAccess(key: string): Promise<FieldAccess> {
  const { data } = await client.get(`/processes/${key}/field-access`)
  return data.data
}

export async function exportVersion(key: string, version: number): Promise<ProcessDefinition> {
  const { data } = await client.get(
    `/processes/${encodeURIComponent(key)}/versions/${version}:export`)
  return data.data
}

/** Neuen Prozess anlegen – Body ist die Definition selbst (nicht gewrappt). */
export async function createProcess(defn: ProcessDefinition): Promise<ProcessOut> {
  const { data } = await client.post('/processes', defn)
  return data.data
}

/** Bearbeitungs-Entwurf holen/anlegen (klont die veröffentlichte Version). */
export async function createDraft(key: string): Promise<ProcessOut> {
  const { data } = await client.post(`/processes/${encodeURIComponent(key)}/versions`, {})
  return data.data
}

/** Entwurf speichern. `etag` (aus ProcessOut.etag) schützt vor Lost-Update. */
export async function saveDraft(
  key: string, version: number, defn: ProcessDefinition, etag?: string | null,
): Promise<ProcessOut> {
  const { data } = await client.put(
    `/processes/${encodeURIComponent(key)}/versions/${version}`, defn,
    etag ? { headers: { 'If-Match': etag } } : undefined)
  return data.data
}

/** Veröffentlichen (idempotent). */
export async function publishVersion(key: string, version: number): Promise<ProcessOut> {
  const { data } = await client.post(
    `/processes/${encodeURIComponent(key)}/versions/${version}:publish`)
  return data.data
}

/** Unter neuem Key kopieren (Quelle: veröffentlichte Version, sonst höchste). */
export async function duplicateProcess(key: string, newKey: string): Promise<ProcessOut> {
  const { data } = await client.post(
    `/processes/${encodeURIComponent(key)}:duplicate`, { newKey })
  return data.data
}

/** Import: Ziel-Key muss explizit bestätigt werden (nie allein aus dem JSON). */
export async function importProcess(
  targetKey: string, definition: ProcessDefinition,
): Promise<ProcessOut> {
  const { data } = await client.post('/processes:import', { targetKey, definition })
  return data.data
}

/** Entwurfs-Version löschen. Antwort ist {ok:true} ohne data-Envelope. */
export async function deleteVersion(key: string, version: number): Promise<void> {
  await client.delete(`/processes/${encodeURIComponent(key)}/versions/${version}`)
}
