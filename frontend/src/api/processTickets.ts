/**
 * API-Client für Prozess-Tickets (/api/v1/process-tickets).
 *
 * Zugriff regelt der Server: Aufsicht, Ersteller:in, aktuell Zuständige und
 * Beobachter:innen dürfen lesen; die gelieferten `values` sind bereits nach
 * Sichtbarkeit gefiltert. Was die angemeldete Person tun darf, steht in
 * `abilities` der Antwort – Verlauf/Nachträge/Beobachter in `api/processEvents`.
 */
import { client } from '@/api/client'
import type { ProcessTicketOut } from '@/types/process'

export interface TicketListParams {
  status?: string
  process_key?: string
  q?: string
  limit?: number
  offset?: number
}

export async function listTickets(
  params: TicketListParams = {},
): Promise<{ items: ProcessTicketOut[]; total: number }> {
  const { data } = await client.get('/process-tickets', { params })
  return { items: data.data, total: data.meta?.total ?? data.data.length }
}

export async function getTicket(id: number): Promise<ProcessTicketOut> {
  const { data } = await client.get(`/process-tickets/${id}`)
  return data.data
}

export async function createTicket(body: {
  processKey: string
  title?: string | null
  priority?: string | null
  values?: Record<string, unknown> | null
}): Promise<ProcessTicketOut> {
  const { data } = await client.post('/process-tickets', body)
  return data.data
}

export async function patchTicket(id: number, body: {
  title?: string | null
  values?: Record<string, unknown> | null
}): Promise<ProcessTicketOut> {
  const { data } = await client.patch(`/process-tickets/${id}`, body)
  return data.data
}

export async function advanceTicket(id: number): Promise<ProcessTicketOut> {
  const { data } = await client.post(`/process-tickets/${id}:advance`)
  return data.data
}

/** Begründung ist PFLICHT – ohne sie antwortet der Server mit 422. */
export async function rejectTicket(id: number, reason: string): Promise<ProcessTicketOut> {
  const { data } = await client.post(`/process-tickets/${id}:reject`, { reason })
  return data.data
}

/**
 * Die GEPINNTE Definition dieses Auftrags. Bewusst NICHT über
 * /processes/{key}/versions/{v}: das verlangt Verwaltungsrechte (dort kommt man
 * auch an unveröffentlichte Entwürfe). Hier entscheidet der Zugriff auf den
 * AUFTRAG – wer ihn sehen darf, darf auch wissen, wie er aufgebaut ist.
 */
/** Admin-Notfalleingriff: hängenden Auftrag zwangsweise abschließen (Grund Pflicht). */
export async function archiveTicket(id: number, reason: string): Promise<ProcessTicketOut> {
  const { data } = await client.post(`/process-tickets/${id}:archive`, { reason })
  return data.data
}

/** Admin: Auftrag endgültig löschen. Der Audit-Eintrag überlebt die Löschung. */
export async function deleteTicket(id: number): Promise<void> {
  await client.delete(`/process-tickets/${id}`)
}

export async function getPinnedDefinition(id: number): Promise<unknown> {
  const { data } = await client.get(`/process-tickets/${id}/definition`)
  return data.data
}

// ── Admin-Werkzeuge (Reparatur) ───────────────────────────────────────────────
// Alle drei sind HART auf Admins beschränkt – der Server antwortet sonst mit
// 403 ADMIN_REQUIRED, egal was die Oberfläche anzeigt.

/** Aktiven Auftrag auf eine beliebige Phase stellen (vor/zurück; Grund Pflicht). */
export async function setTicketPhase(
  id: number, phase: string, reason: string,
): Promise<ProcessTicketOut> {
  const { data } = await client.post(`/process-tickets/${id}:set-phase`, { phase, reason })
  return data.data
}

/** UNGEFILTERTE Roh-Werte für den Admin-Editor – die normale Ticket-Antwort
 *  filtert auf Katalog-Felder, ein Editor darauf würde unsichtbare
 *  Alt-Schlüssel beim nächsten Speichern zerstören. */
export async function getRawValues(id: number): Promise<Record<string, unknown>> {
  const { data } = await client.get(`/process-tickets/${id}/raw-values`)
  return data.data.values
}

/** Roh-Werte VERBATIM ersetzen (Grund Pflicht). Liefert den neuen Bestand. */
export async function setRawValues(
  id: number, values: Record<string, unknown>, reason: string,
): Promise<Record<string, unknown>> {
  const { data } = await client.put(`/process-tickets/${id}/raw-values`, { values, reason })
  return data.data.values
}

// ── Fachabteilungen einzeln quittieren ───────────────────────────────────────
//
// Eine Fachabteilungs-Phase ist erst fertig, wenn jede PFLICHT-Abteilung
// quittiert hat; bis dahin lehnt `:advance` mit 409 DEPARTMENT_FORBIDDEN ab.
// Wer quittieren darf, entscheidet ausschließlich der Server (Mitgliedschaft in
// genau dieser Abteilung oder Aufsicht) – sonst 403 DEPARTMENT_FORBIDDEN.
// Alle drei Endpunkte liefern den AKTUALISIERTEN Auftrag zurück.

/**
 * Gruppen-IDs kommen aus dem Verzeichnisdienst und dürfen Sonderzeichen
 * enthalten – nur die ID kodieren, das `:aktion`-Suffix gehört zur Route.
 */
function departmentUrl(ticketId: number, groupId: string, aktion: string): string {
  return `/process-tickets/${ticketId}/departments/${encodeURIComponent(groupId)}:${aktion}`
}

/** Diese Fachabteilung hat ihren Teil erledigt. */
export async function completeDepartment(
  ticketId: number, groupId: string, note?: string | null,
): Promise<ProcessTicketOut> {
  const { data } = await client.post(departmentUrl(ticketId, groupId, 'complete'),
                                     { note: note || null })
  return data.data
}

/** Nicht zuständig / nichts zu tun – gilt als erledigt, ohne Bearbeitung. */
export async function skipDepartment(
  ticketId: number, groupId: string, note?: string | null,
): Promise<ProcessTicketOut> {
  const { data } = await client.post(departmentUrl(ticketId, groupId, 'skip'),
                                     { note: note || null })
  return data.data
}

/**
 * Ablehnung durch eine Fachabteilung – beendet den GESAMTEN Auftrag, nicht nur
 * den Teil dieser Abteilung. Die Begründung ist Pflicht (ohne: 422).
 */
export async function rejectDepartment(
  ticketId: number, groupId: string, note: string,
): Promise<ProcessTicketOut> {
  const { data } = await client.post(departmentUrl(ticketId, groupId, 'reject'), { note })
  return data.data
}
