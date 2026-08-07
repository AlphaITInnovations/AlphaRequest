/** API-Client für Prozess-Tickets (/api/v1/process-tickets). Aktuell Admin-only. */
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

export async function rejectTicket(id: number): Promise<ProcessTicketOut> {
  const { data } = await client.post(`/process-tickets/${id}:reject`)
  return data.data
}
