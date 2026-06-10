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
  | 'hotelbuchung'
  | 'basis-ticket'

// ── Permissions ───────────────────────────────────────────────────────────────

export type Permission = 'view' | 'manage' | 'admin' | `create_${TicketType}` | (string & {})

export interface User {
  id:          string
  displayName: string
  mail:        string | null
  permissions: Permission[]
}

// ── Tickets ───────────────────────────────────────────────────────────────────

// ── Workflow / Phase types ────────────────────────────────────────────────────

export type PhaseType   = 'creation' | 'assignment' | 'department_review'
export type PhaseStatus = 'pending' | 'in_progress' | 'done'

export type DeptStatus = 'open' | 'in_progress' | 'done' | 'skipped' | 'rejected'

export interface Department {
  name:     string
  required: boolean
  status:   DeptStatus
}

export interface WorkflowPhase {
  key:         string
  label:       string
  type:        PhaseType
  status:      PhaseStatus
  departments?: Record<string, Department>
}

export interface WorkflowRejection {
  phase_key:   string
  phase_index: number
  message:     string
  rejected_by: string
  rejected_at: string
}

export interface WorkflowState {
  current_phase_index: number
  phases:              WorkflowPhase[]
  rejected:            WorkflowRejection | null
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
  workflow_state:      WorkflowState | null
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