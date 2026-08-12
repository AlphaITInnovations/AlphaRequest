/**
 * API-Client für Verlauf, Nachträge, Wiederaufnahme und Beobachter:innen eines
 * Prozess-Auftrags.
 *
 * Der Verlauf kommt vom Server bereits REDIGIERT: Einträge über Felder, die die
 * lesende Person nicht sehen darf, fehlen ganz; interne Nachträge liefert er nur
 * an die bearbeitende Seite. Die Oberfläche muss (und kann) hier nichts filtern.
 */
import { client } from '@/api/client'
import type { ProcessTicketOut } from '@/types/process'

/** Kanonische Aktions-Namen (Backend: backend/services/process_events.py). */
export type EventAction =
  | 'created' | 'updated' | 'advanced' | 'rejected' | 'reopened' | 'comment'
  | 'department_done' | 'department_skipped' | 'department_rejected'
  | 'watcher_added' | 'watcher_removed' | 'automation_fired' | 'priority_changed'
  | (string & {})

export interface ProcessEvent {
  id: number
  action: EventAction
  phase_key: string | null
  epoch: number
  actor_id: string | null
  actor_name: string | null
  actor_type: 'user' | 'system' | (string & {})
  internal: boolean
  /** Freitext: Nachtrag bzw. Notiz/Grund einer Aktion. */
  body: string | null
  details: Record<string, unknown>
  created_at: string | null
}

export interface ProcessWatcher {
  id: string
  name: string | null
  added_by: string | null
  created_at: string | null
}

export async function listEvents(
  ticketId: number, params: { limit?: number; offset?: number } = {},
): Promise<{ items: ProcessEvent[]; total: number }> {
  const { data } = await client.get(`/process-tickets/${ticketId}/events`, { params })
  return { items: data.data, total: data.meta?.total ?? data.data.length }
}

export async function addComment(
  ticketId: number, body: string, internal = false,
): Promise<ProcessEvent> {
  const { data } = await client.post(`/process-tickets/${ticketId}/comments`, { body, internal })
  return data.data
}

/** Wiederaufnahme eines abgeschlossenen/abgelehnten Auftrags (nur Admin). */
export async function reopenTicket(
  ticketId: number, reason: string, phase?: string | null,
): Promise<ProcessTicketOut> {
  const { data } = await client.post(`/process-tickets/${ticketId}:reopen`,
                                     { reason, phase: phase || null })
  return data.data
}

export async function listWatchers(ticketId: number): Promise<ProcessWatcher[]> {
  const { data } = await client.get(`/process-tickets/${ticketId}/watchers`)
  return data.data
}

/** Ohne `userId`: sich selbst eintragen. */
export async function addWatcher(
  ticketId: number, userId?: string | null,
): Promise<ProcessWatcher[]> {
  const { data } = await client.post(`/process-tickets/${ticketId}/watchers`,
                                     { userId: userId || null })
  return data.data
}

export async function removeWatcher(
  ticketId: number, userId: string,
): Promise<ProcessWatcher[]> {
  const { data } = await client.delete(`/process-tickets/${ticketId}/watchers/${userId}`)
  return data.data
}
