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
// Frontend-Darstellung einer Phase (datengetrieben vom Backend)
export type PhaseView   = 'form' | 'readonly'

export type DeptStatus = 'open' | 'in_progress' | 'done' | 'skipped' | 'rejected'

export interface Department {
  name:     string
  required: boolean
  status:   DeptStatus
}

export type ResponsibilityKind = 'owner' | 'user' | 'group' | 'departments' | 'none'

export interface PhaseResponsibility {
  kind: ResponsibilityKind
  id?:   string | null
  name?: string | null
}

export interface WorkflowPhase {
  key:         string
  label:       string
  type:        PhaseType
  view?:        PhaseView
  status:      PhaseStatus
  responsibility?: PhaseResponsibility
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

export interface Responsible {
  kind: 'user' | 'group'
  id:   string | null
  name: string | null
}

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
  workflow_state:      WorkflowState | null
  // Verantwortliche(r) aus dem Workflow (ersetzt assignee/accountable)
  responsible:         Responsible | null
  watchers?:           Watcher[]
}

export interface Watcher {
  id:   string
  name: string | null
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