

// ── api/tickets.ts ─────────────────────────────────────────────────────────────
import type {
  Ticket, TicketCreateRequest, TicketUpdateRequest,
  DataResponse, ListResponse,
} from '@/types/ticket'
import {client} from "@/api/client.ts";

export const ticketsApi = {
  list:    ()                               => client.get<ListResponse<Ticket>>('/tickets'),
  listAll: (limit = 50, offset = 0)         => client.get<ListResponse<Ticket>>('/admin/tickets', { params: { limit, offset } }),
  get:     (id: number)                     => client.get<DataResponse<Ticket>>(`/tickets/${id}`),
  create:  (data: TicketCreateRequest)      => client.post<DataResponse<Ticket>>('/tickets', data),
  update:  (id: number, data: TicketUpdateRequest) => client.patch<DataResponse<Ticket>>(`/tickets/${id}`, data),
  submit:  (id: number)                     => client.post<DataResponse<Ticket>>(`/tickets/${id}/submit`),
  archive: (id: number)                     => client.post<DataResponse<Ticket>>(`/admin/tickets/${id}/archive`),
  remove:  (id: number)                     => client.delete(`/tickets/${id}`),

  getDepartments:    (id: number)                          => client.get(`/tickets/${id}/departments`),
  getAllDepartments:  (id: number)                          => client.get(`/tickets/${id}/departments/all`),
  setDepartmentStatus: (ticketId: number, groupId: string, status: string) =>
    client.patch(`/tickets/${ticketId}/departments/${groupId}`, { status }),
}


export interface UserEntry {
  id: string
  displayName: string
  mail: string | null
}

export const usersApi = {
  list: () => client.get<{ data: { users: UserEntry[] } }>('/users'),
}