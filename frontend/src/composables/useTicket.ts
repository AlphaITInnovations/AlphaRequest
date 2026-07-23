import { ref, computed } from 'vue'
import { ticketsApi } from '@/api/tickets'
import type { Ticket, WorkflowPhase, Watcher, Department } from '@/types/ticket'

export function useTicket(ticketId: number, department?: string) {
  const ticket    = ref<Ticket | null>(null)
  const loading   = ref(false)
  const submitting = ref(false)

  const workflow = computed(() => ticket.value?.workflow_state ?? null)

  const phases = computed<WorkflowPhase[]>(() => workflow.value?.phases ?? [])

  const currentPhase = computed<WorkflowPhase | null>(() => {
    const idx = workflow.value?.current_phase_index ?? 0
    return phases.value[idx] ?? null
  })

  const isAssignmentPhase  = computed(() => currentPhase.value?.type === 'assignment')
  const isDeptReviewPhase  = computed(() => currentPhase.value?.type === 'department_review')
  const isRejected         = computed(() => !!workflow.value?.rejected)
  const isCompleted        = computed(() => ticket.value?.status === 'archived')

  // Datengetriebene Frontend-Ansicht der aktuellen Phase.
  // rejected/archived erzwingen read-only; sonst phase.view (Fallback aus type).
  const currentView = computed<'form' | 'readonly' | 'export' | 'approval'>(() => {
    if (isRejected.value || isCompleted.value) return 'readonly'
    const p = currentPhase.value
    if (!p) return 'readonly'
    if (p.view === 'form' || p.view === 'readonly' || p.view === 'export' || p.view === 'approval') return p.view
    return p.type === 'assignment' ? 'form' : 'readonly'
  })

  const description = computed<Record<string, unknown>>(() => {
    try { return JSON.parse(ticket.value?.description ?? '{}') }
    catch { return {} }
  })

  // Departments of the active department_review phase
  const activeDepartments = computed(() =>
    isDeptReviewPhase.value ? (currentPhase.value?.departments ?? {}) : {}
  )

  // Alle Reviewing-Fachabteilungen (aus der department_review-Phase, unabhängig
  // davon ob sie gerade aktiv ist) – für die Status-Übersicht in den Details.
  const reviewDepartments = computed<Record<string, Department>>(() => {
    const p = phases.value.find(ph => ph.type === 'department_review')
    return p?.departments ?? {}
  })

  // Fachabteilungen erst anzeigen, wenn die Durchführungs-Phase erreicht ist
  // (nicht mehr 'pending') – vorher (z.B. Freigabe/BackOffice) sind sie noch
  // nicht „offen" und sollen nicht angezeigt werden.
  const showReviewDepartments = computed(() => {
    const p = phases.value.find(ph => ph.type === 'department_review')
    return !!p && p.status !== 'pending'
  })

  // Beobachter
  const watchers = computed<Watcher[]>(() => ticket.value?.watchers ?? [])

  async function addWatcher(userId: string, userName: string) {
    await ticketsApi.addWatcher(ticketId, userId, userName)
    await load()
  }

  async function removeWatcher(userId: string) {
    await ticketsApi.removeWatcher(ticketId, userId)
    await load()
  }

  async function load() {
    loading.value = true
    try {
      const res = await ticketsApi.get(ticketId, department)
      ticket.value = res.data.data
    } finally {
      loading.value = false
    }
  }

  async function markDepartmentDone(groupId: string) {
    submitting.value = true
    try {
      await ticketsApi.setDepartmentStatus(ticketId, groupId, 'done')
      await load()
    } finally {
      submitting.value = false
    }
  }

  async function rejectTicket(message: string) {
    submitting.value = true
    try {
      await ticketsApi.reject(ticketId, message)
      await load()
    } finally {
      submitting.value = false
    }
  }

  return {
    ticket, loading, submitting,
    workflow, phases, currentPhase, currentView,
    isAssignmentPhase, isDeptReviewPhase, isRejected, isCompleted,
    description, activeDepartments, reviewDepartments, showReviewDepartments, watchers,
    load, markDepartmentDone, rejectTicket, addWatcher, removeWatcher,
  }
}
