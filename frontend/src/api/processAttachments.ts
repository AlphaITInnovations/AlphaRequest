/**
 * API-Client für Datei-Anhänge von Prozess-Tickets
 * (/api/v1/process-tickets/{id}/attachments).
 *
 * Anhänge liegen in derselben Tabelle wie die des Alt-Systems, werden aber über
 * `entity_type` getrennt – deshalb ein eigener Client statt eines Flags im alten.
 * Download und Löschen laufen über die GEMEINSAMEN Endpunkte /attachments/{id},
 * die den Anhang über seine ID finden und selbst entscheiden, welche
 * Zugriffsprüfung greift.
 */
import { client } from '@/api/client'

export interface ProcessAttachment {
  id: number
  entity_type: string
  /** ID des Prozess-Tickets (die Spalte heißt historisch `ticket_id`). */
  ticket_id: number | null
  /** Anhang-Feld der Definition; null = allgemeiner Anhang. */
  field_key: string | null
  phase_key: string | null
  family_id: string
  version: number
  is_current: boolean
  original_filename: string
  content_type: string | null
  size_bytes: number
  size_human: string
  sha256: string | null
  uploaded_by_id: string | null
  uploaded_by_name: string | null
  uploaded_at: string | null
}

export interface ListAttachmentsParams {
  /** Auch ältere Versionen mitliefern (Standard: nur die aktuellen). */
  includeVersions?: boolean
  /** Nur Dateien dieses Anhang-Feldes; ohne Angabe alle des Auftrags. */
  fieldKey?: string | null
}

export async function listAttachments(
  ticketId: number, params: ListAttachmentsParams = {},
): Promise<ProcessAttachment[]> {
  const { data } = await client.get(`/process-tickets/${ticketId}/attachments`, {
    params: {
      include_versions: params.includeVersions ? true : undefined,
      field_key: params.fieldKey || undefined,
    },
  })
  return data.data
}

export interface UploadOptions {
  /** Anhang-Feld der Definition (muss widget='attachment' sein). */
  fieldKey?: string | null
  /** Gesetzt = neue VERSION einer bestehenden Datei (statt einer neuen Datei). */
  familyId?: string | null
}

export async function uploadAttachment(
  ticketId: number, file: File, opts: UploadOptions = {},
): Promise<ProcessAttachment> {
  const form = new FormData()
  form.append('file', file)
  if (opts.fieldKey) form.append('field_key', opts.fieldKey)
  if (opts.familyId) form.append('family_id', opts.familyId)
  // Content-Type NICHT selbst setzen: der Browser muss die multipart-Boundary
  // ergänzen. Der Axios-Client setzt global application/json – hier überschreiben
  // wir das mit undefined, damit axios den Header aus dem FormData ableitet.
  const { data } = await client.post(`/process-tickets/${ticketId}/attachments`, form, {
    headers: { 'Content-Type': undefined },
  })
  return data.data
}

/** Direkter Link (kein XHR) – der Browser lädt mit den Session-Cookies. */
export function downloadUrl(attachmentId: number): string {
  return `/api/v1/attachments/${attachmentId}/download`
}

export async function deleteAttachment(attachmentId: number): Promise<void> {
  await client.delete(`/attachments/${attachmentId}`)
}
