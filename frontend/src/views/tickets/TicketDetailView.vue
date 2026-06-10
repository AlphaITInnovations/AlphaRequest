<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppLayout from '@/components/AppLayout.vue'
import TicketActionBar from '@/components/TicketActionBar.vue'
import PhaseProgress from '@/components/tickets/PhaseProgress.vue'
import { TICKET_REGISTRY } from '@/utils/ticketRegistry'
import { useTicket } from '@/composables/useTicket'
import type { TicketType } from '@/types/ticket'

const route  = useRoute()
const router = useRouter()

const ticketType = route.params.type as TicketType
const ticketId   = Number(route.params.id)
const deptId     = route.query.department as string | undefined

const entry = TICKET_REGISTRY[ticketType]

// Always call composable during setup (needed for reactivity even when in dept-view mode)
const formCtx = entry?.useComposable('edit', ticketId)

const { ticket, loading, submitting, phases,
        isAssignmentPhase, isDeptReviewPhase, isRejected, isCompleted,
        description, activeDepartments,
        load, markDepartmentDone, rejectTicket } = useTicket(ticketId)

// Reject modal state
const showRejectModal   = ref(false)
const rejectMessage     = ref('')
const rejectSubmitting  = ref(false)

const STATUS_LABEL: Record<string, string> = {
  in_progress: 'In Bearbeitung', in_request: 'Zu bearbeiten',
  archived: 'Erledigt', rejected: 'Abgelehnt',
}
const PRIORITY_LABEL: Record<string, string> = {
  low: 'Niedrig', medium: 'Mittel', high: 'Hoch', critical: 'Kritisch',
}
const DEPT_STATUS_LABEL: Record<string, string> = {
  done: 'Ausgeführt', rejected: 'Abgelehnt', skipped: 'Übersprungen',
  open: 'Offen', in_progress: 'In Bearbeitung',
}

onMounted(async () => {
  if (!entry) { router.replace('/dashboard'); return }

  await load()

  if (!ticket.value) { router.replace('/dashboard'); return }

  // Initialize form composable only when in assignment phase
  if (isAssignmentPhase.value && formCtx) {
    await formCtx.init()
  }
})

// My dept info (for dept-review mode)
const myDept = () => deptId ? activeDepartments.value[deptId] : null

async function handleDeptDone() {
  if (!deptId) return
  await markDepartmentDone(deptId)
  router.push('/dashboard')
}

async function handleReject() {
  if (!rejectMessage.value.trim()) return
  rejectSubmitting.value = true
  try {
    await rejectTicket(rejectMessage.value.trim())
    showRejectModal.value = false
    rejectMessage.value = ''
    router.push('/dashboard')
  } finally {
    rejectSubmitting.value = false
  }
}

function goToEdit() {
  const ok = confirm('⚠️ In dieser Phase soll das Ticket nur im Notfall bearbeitet werden.\n\nMöchten Sie wirklich fortfahren?')
  if (ok) router.push(`/tickets/view/${ticketType}/${ticketId}`)
}
</script>

<template>
  <AppLayout :title="entry?.label ?? 'Ticket'">

    <!-- Loading -->
    <div v-if="loading" class="flex items-center justify-center py-24">
      <div class="w-8 h-8 rounded-full border-2 border-[#3EAAB8] border-t-transparent animate-spin"/>
    </div>

    <template v-else-if="ticket">
      <div class="max-w-7xl mx-auto space-y-6 pb-24">

        <!-- Header -->
        <div>
          <h1 class="text-xl font-semibold text-gray-900 dark:text-white">{{ ticket.title }}</h1>
          <p class="text-sm text-gray-400 mt-1">Erstellt am {{ ticket.created_at }}</p>
        </div>

        <!-- Phase progress -->
        <PhaseProgress v-if="phases.length" :phases="phases" />

        <!-- Rejection banner -->
        <div v-if="isRejected && ticket.workflow_state?.rejected"
             class="rounded-2xl border border-red-300 bg-red-50 dark:bg-red-900/20 dark:border-red-700 p-4 text-sm">
          <p class="font-semibold text-red-700 dark:text-red-400 mb-1">
            Abgelehnt in Phase „{{ ticket.workflow_state.rejected.phase_key }}" von
            {{ ticket.workflow_state.rejected.rejected_by }}
          </p>
          <p class="text-red-600 dark:text-red-300 whitespace-pre-wrap">
            {{ ticket.workflow_state.rejected.message }}
          </p>
        </div>

        <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">

          <!-- Meta Sidebar -->
          <aside class="space-y-4">
            <div class="bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09]
                        rounded-2xl shadow-sm p-5 space-y-4 text-sm">
              <div>
                <p class="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1">Status</p>
                <p class="font-medium text-gray-900 dark:text-white">
                  {{ STATUS_LABEL[ticket.status] ?? ticket.status }}
                </p>
              </div>
              <div>
                <p class="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1">Priorität</p>
                <p class="font-medium text-gray-900 dark:text-white">
                  {{ PRIORITY_LABEL[ticket.priority] ?? ticket.priority }}
                </p>
              </div>
              <div>
                <p class="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1">Antragsteller</p>
                <p class="font-medium text-gray-900 dark:text-white">{{ ticket.owner_name }}</p>
              </div>
              <div class="pt-3 border-t border-gray-100 dark:border-white/[0.06] space-y-3">
                <div>
                  <p class="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1">Verantwortlicher</p>
                  <p class="text-gray-900 dark:text-white">{{ ticket.accountable_name || '—' }}</p>
                </div>
                <div v-if="ticket.comment">
                  <p class="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1">Kommentar</p>
                  <p class="text-gray-900 dark:text-white whitespace-pre-wrap">{{ ticket.comment }}</p>
                </div>
              </div>
            </div>

            <!-- Dept status card (dept-review mode) -->
            <div v-if="isDeptReviewPhase && myDept()"
                 class="bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09]
                        rounded-2xl shadow-sm p-5 text-sm">
              <p class="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">Meine Fachabteilung</p>
              <p class="font-semibold text-[#3EAAB8] mb-2">{{ myDept()!.name }}</p>
              <p class="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1">Bearbeitungsstatus</p>
              <span class="inline-flex items-center gap-1.5 text-sm font-medium"
                    :class="{
                      'text-green-600':  myDept()!.status === 'done',
                      'text-red-500':    myDept()!.status === 'rejected',
                      'text-[#3EAAB8]':  ['open','in_progress'].includes(myDept()!.status),
                    }">
                {{ DEPT_STATUS_LABEL[myDept()!.status] ?? myDept()!.status }}
              </span>
            </div>
          </aside>

          <!-- Content area -->
          <section class="lg:col-span-2 space-y-5">

            <!-- Assignment phase: editable form -->
            <component
              v-if="isAssignmentPhase && formCtx && !formCtx.loading?.value"
              :is="entry!.form"
              :ctx="formCtx"
              phase="edit"
            />

            <!-- Dept review phase: read-only panel -->
            <component
              v-else-if="isDeptReviewPhase || isCompleted || isRejected"
              :is="entry!.panel"
              :description="description"
            />

          </section>
        </div>

        <!-- Action bar (dept-review mode) -->
        <TicketActionBar
          v-if="isDeptReviewPhase && deptId && myDept()"
          phase="view"
          :loading="submitting"
          :department-name="myDept()!.name"
          :department-status="myDept()!.status"
          :can-complete="myDept()!.status !== 'done'"
          @department-done="handleDeptDone"
          @department-edit="goToEdit"
        />

      </div>
    </template>

    <!-- Reject modal -->
    <Teleport to="body">
      <div v-if="showRejectModal"
           class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
        <div class="bg-white dark:bg-[#1C2535] rounded-2xl shadow-xl p-6 w-full max-w-md mx-4 space-y-4">
          <h2 class="text-lg font-semibold text-gray-900 dark:text-white">Ticket ablehnen</h2>
          <p class="text-sm text-gray-500 dark:text-gray-400">
            Bitte gib einen Ablehnungsgrund an. Dieser ist für den Antragsteller sichtbar.
          </p>
          <textarea
            v-model="rejectMessage"
            rows="4"
            placeholder="Ablehnungsgrund..."
            class="w-full rounded-xl border border-gray-200 dark:border-white/10 px-3.5 py-2.5 text-sm
                   bg-white dark:bg-[#263040] text-gray-900 dark:text-gray-100
                   focus:outline-none focus:ring-2 focus:ring-red-400/30 focus:border-red-400/50"
          />
          <div class="flex gap-3 justify-end">
            <button @click="showRejectModal = false"
                    class="px-4 py-2 text-sm rounded-xl border border-gray-200 dark:border-white/10
                           text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-white/5">
              Abbrechen
            </button>
            <button @click="handleReject"
                    :disabled="!rejectMessage.trim() || rejectSubmitting"
                    class="px-4 py-2 text-sm rounded-xl bg-red-500 text-white font-medium
                           hover:bg-red-600 disabled:opacity-50 disabled:cursor-not-allowed">
              {{ rejectSubmitting ? 'Wird abgelehnt…' : 'Ablehnen' }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>

  </AppLayout>
</template>
