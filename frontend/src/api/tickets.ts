

// ── api/tickets.ts ─────────────────────────────────────────────────────────────
import type {
  Ticket, TicketCreateRequest, TicketUpdateRequest, Watcher,
  DataResponse, ListResponse,
} from '@/types/ticket'
import {client} from "@/api/client.ts";

export const ticketsApi = {
  list:    ()                               => client.get<ListResponse<Ticket>>('/tickets'),
  listAll: (limit = 50, offset = 0)         => client.get<ListResponse<Ticket>>('/admin/tickets', { params: { limit, offset } }),
  get:     (id: number)                     => client.get<DataResponse<Ticket>>(`/tickets/${id}`),
  phases:  (type: string)                   => client.get<DataResponse<{ key: string; label: string; type: string }[]>>(`/ticket-phases/${type}`),
  create:  (data: TicketCreateRequest)      => client.post<DataResponse<Ticket>>('/tickets', data),
  update:  (id: number, data: TicketUpdateRequest) => client.patch<DataResponse<Ticket>>(`/tickets/${id}`, data),
  submit:  (id: number, body?: { assignee_id?: string; assignee_name?: string }) =>
    client.post<DataResponse<Ticket>>(`/tickets/${id}/submit`, body ?? {}),
  reject:  (id: number, message: string)    => client.post<DataResponse<Ticket>>(`/tickets/${id}/reject`, { message }),
  archive: (id: number)                     => client.post<DataResponse<Ticket>>(`/admin/tickets/${id}/archive`),
  remove:  (id: number)                     => client.delete(`/tickets/${id}`),

  getDepartments:    (id: number)                          => client.get(`/tickets/${id}/departments`),
  getAllDepartments:  (id: number)                          => client.get(`/tickets/${id}/departments/all`),
  setDepartmentStatus: (ticketId: number, groupId: string, status: string) =>
    client.patch(`/tickets/${ticketId}/departments/${groupId}`, { status }),

  // ── Beobachter ──
  getWatchers:    (id: number) => client.get<DataResponse<{ watchers: Watcher[] }>>(`/tickets/${id}/watchers`),
  addWatcher:     (id: number, userId: string, userName: string) =>
    client.post<DataResponse<{ watchers: Watcher[] }>>(`/tickets/${id}/watchers`, { user_id: userId, user_name: userName }),
  removeWatcher:  (id: number, userId: string) =>
    client.delete<DataResponse<{ watchers: Watcher[] }>>(`/tickets/${id}/watchers/${userId}`),
}


export interface UserEntry {
  id: string
  displayName: string
  mail: string | null
}

export const usersApi = {
  list: () => client.get<{ data: { users: UserEntry[] } }>('/users'),
}