

// ── stores/ticketStore.ts ──────────────────────────────────────────────────────
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { ticketsApi } from '@/api/tickets'
import type { Ticket, TicketCreateRequest, TicketUpdateRequest } from '@/types/ticket'

export const useTicketStore = defineStore('tickets', () => {
  const tickets  = ref<Ticket[]>([])
  const total    = ref(0)
  const loading  = ref(false)
  const error    = ref<string | null>(null)

  async function fetchMyTickets() {
    loading.value = true
    error.value = null
    try {
      const { data } = await ticketsApi.list()
      tickets.value = data.data
      total.value   = data.meta.total
    } catch {
      error.value = 'Tickets konnten nicht geladen werden.'
    } finally {
      loading.value = false
    }
  }

  async function fetchAllTickets(limit = 50, offset = 0) {
    loading.value = true
    error.value = null
    try {
      const { data } = await ticketsApi.listAll(limit, offset)
      tickets.value = data.data
      total.value   = data.meta.total
    } catch {
      error.value = 'Tickets konnten nicht geladen werden.'
    } finally {
      loading.value = false
    }
  }

  async function createTicket(payload: TicketCreateRequest): Promise<Ticket> {
    const { data } = await ticketsApi.create(payload)
    tickets.value.unshift(data.data)
    total.value++
    return data.data
  }

  async function updateTicket(id: number, payload: TicketUpdateRequest): Promise<Ticket> {
    const { data } = await ticketsApi.update(id, payload)
    _replaceInList(data.data)
    return data.data
  }

  async function submitTicket(id: number): Promise<Ticket> {
    const { data } = await ticketsApi.submit(id)
    _replaceInList(data.data)
    return data.data
  }

  async function archiveTicket(id: number): Promise<Ticket> {
    const { data } = await ticketsApi.archive(id)
    _replaceInList(data.data)
    return data.data
  }

  async function deleteTicket(id: number) {
    await ticketsApi.remove(id)
    tickets.value = tickets.value.filter(t => t.id !== id)
    total.value--
  }

  function _replaceInList(updated: Ticket) {
    const idx = tickets.value.findIndex(t => t.id === updated.id)
    if (idx !== -1) tickets.value[idx] = updated
  }

  return {
    tickets, total, loading, error,
    fetchMyTickets, fetchAllTickets,
    createTicket, updateTicket, submitTicket, archiveTicket, deleteTicket,
  }
})