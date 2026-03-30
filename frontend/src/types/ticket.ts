export type TicketStatus   = 'in_progress' | 'in_request' | 'archived' | 'rejected'
export type TicketPriority = 'low' | 'medium' | 'high' | 'critical'
export type TicketType =
  | 'hardware'
  | 'niederlassung-anmelden'
  | 'niederlassung-schliessen'
  | 'niederlassung-umzug'
  | 'zugang-beantragen'
  | 'zugang-sperren'
  | 'marketing-stellenanzeige'

// ── Permissions ───────────────────────────────────────────────────────────────

export type Permission = 'view' | 'manage' | 'admin' | `create_${TicketType}` | (string & {})

export interface User {
  id:          string
  displayName: string
  mail:        string | null
  permissions: Permission[]
}

// ── Tickets ───────────────────────────────────────────────────────────────────

export interface Ticket {
  id:                  number
  title:               string
  ticket_type:         TicketType
  description:         string
  owner_id:            string
  owner_name:          string
  comment:             string
  status:              TicketStatus
  priority:            TicketPriority
  created_at:          string
  updated_at:          string | null
  assignee_id:         string | null
  assignee_name:       string | null
  accountable_id:      string | null
  accountable_name:    string | null
  assignee_group_id:   string | null
  assignee_group_name: string | null
}

export interface TicketCreateRequest {
  ticket_type:      TicketType
  description:      string
  assignee_id:      string
  assignee_name:    string
  accountable_id:   string
  accountable_name: string
  comment?:         string
  priority?:        TicketPriority
}

export interface TicketUpdateRequest {
  description?:     string
  comment?:         string
  assignee_id?:     string
  assignee_name?:   string
  accountable_id?:  string
  accountable_name?: string
  priority?:        TicketPriority
}

// ── API Response Wrapper ──────────────────────────────────────────────────────

export interface Meta {
  total:  number
  limit:  number
  offset: number
}

export interface DataResponse<T> {
  data: T
}

export interface ListResponse<T> {
  data: T[]
  meta: Meta
}