import { ref, computed } from 'vue'
import { ticketsApi } from '@/api/tickets'
import type { Ticket, WorkflowPhase } from '@/types/ticket'

export function useTicket(ticketId: number) {
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

  const description = computed<Record<string, unknown>>(() => {
    try { return JSON.parse(ticket.value?.description ?? '{}') }
    catch { return {} }
  })

  // Departments of the active department_review phase
  const activeDepartments = computed(() =>
    isDeptReviewPhase.value ? (currentPhase.value?.departments ?? {}) : {}
  )

  async function load() {
    loading.value = true
    try {
      const res = await ticketsApi.get(ticketId)
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
    workflow, phases, currentPhase,
    isAssignmentPhase, isDeptReviewPhase, isRejected, isCompleted,
    description, activeDepartments,
    load, markDepartmentDone, rejectTicket,
  }
}
