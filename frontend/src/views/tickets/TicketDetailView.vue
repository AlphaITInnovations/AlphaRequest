<script setup lang="ts">
import { ref, provide, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppLayout from '@/components/AppLayout.vue'
import TicketActionBar from '@/components/TicketActionBar.vue'
import PhaseProgress from '@/components/tickets/PhaseProgress.vue'
import TicketWatchers from '@/components/tickets/TicketWatchers.vue'
import { TICKET_REGISTRY } from '@/utils/ticketRegistry'
import { useTicket } from '@/composables/useTicket'
import { ticketsApi } from '@/api/tickets'
import type { TicketType } from '@/types/ticket'

const route  = useRoute()
const router = useRouter()

const ticketType = route.params.type as TicketType
const ticketId   = Number(route.params.id)
const deptId     = route.query.department as string | undefined

const entry = TICKET_REGISTRY[ticketType]

// Always call composable during setup (needed for reactivity even when in dept-view mode)
const formCtx = entry?.useComposable('edit', ticketId)

const { ticket, loading, submitting, phases, currentView,
        isDeptReviewPhase, isRejected,
        description, activeDepartments, reviewDepartments, showReviewDepartments, watchers,
        load, markDepartmentDone, rejectTicket, addWatcher, removeWatcher } = useTicket(ticketId)

const watcherBusy = ref(false)
async function onAddWatcher(id: string, name: string) {
  watcherBusy.value = true
  try { await addWatcher(id, name) } finally { watcherBusy.value = false }
}
async function onRemoveWatcher(id: string) {
  watcherBusy.value = true
  try { await removeWatcher(id) } finally { watcherBusy.value = false }
}

// Notfall-Bearbeitung: macht die Felder in der aktuellen Ansicht editierbar,
// OHNE die Phase zu ändern. Speichern = PATCH, danach zurück zum Dashboard.
const emergencyEdit = ref(false)
provide('emergencyEdit', emergencyEdit)

// Phasen an die geteilte TicketDetails-Sidebar (im Formular) durchreichen
provide('workflowPhases', phases)
// Beobachter (Liste + Aktionen) an die geteilte TicketDetails-Sidebar durchreichen
provide('ticketWatchers', {
  watchers,
  busy: watcherBusy,
  add: onAddWatcher,
  remove: onRemoveWatcher,
})

// Reject modal state
const showRejectModal   = ref(false)
const rejectMessage     = ref('')
const rejectSubmitting  = ref(false)

// Export-Phase: Archivieren erst nach PDF-Export
const exported  = ref(false)
const archiving = ref(false)

async function handleArchive() {
  archiving.value = true
  try {
    await ticketsApi.submit(ticketId)   // schließt die letzte Phase ab → archiviert
    router.push('/dashboard')
  } finally {
    archiving.value = false
  }
}

// Freigabe-Phase: Freigeben (= Phase abschließen → BackOffice) bzw. Ablehnen.
const approving = ref(false)
async function handleApprove() {
  approving.value = true
  try {
    await ticketsApi.submit(ticketId)
    router.push('/dashboard')
  } finally {
    approving.value = false
  }
}

const STATUS_LABEL: Record<string, string> = {
  in_progress: 'In Bearbeitung', in_request: 'Zu bearbeiten',
  archived: 'Archiviert', rejected: 'Abgelehnt',
}
const PRIORITY_LABEL: Record<string, string> = {
  low: 'Niedrig', medium: 'Mittel', high: 'Hoch', critical: 'Kritisch',
}
const DEPT_STATUS_LABEL: Record<string, string> = {
  done: 'Ausgeführt', rejected: 'Abgelehnt', skipped: 'Übersprungen',
  open: 'Offen', in_progress: 'In Bearbeitung',
}
const DEPT_STATUS_CLASS: Record<string, string> = {
  done:        'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400',
  rejected:    'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400',
  in_progress: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400',
  skipped:     'bg-gray-100 text-gray-500 dark:bg-white/5 dark:text-gray-400',
  open:        'bg-[#3EAAB8]/10 text-[#3EAAB8]',
}
// Object.keys im Template verfügbar machen
const objectKeys = (o: Record<string, unknown>) => Object.keys(o ?? {})

onMounted(async () => {
  if (!entry) { router.replace('/dashboard'); return }

  await load()

  if (!ticket.value) { router.replace('/dashboard'); return }

  // Formular-Composable nur initialisieren, wenn die aktuelle Phase ein Formular zeigt
  if (currentView.value === 'form' && formCtx) {
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

async function goToEdit() {
  const ok = confirm(
    '⚠️ Notfall-Bearbeitung\n\n' +
    'Die Felder des Auftrags werden editierbar. Mit „Speichern" werden die ' +
    'Änderungen übernommen – die Phase bleibt unverändert.\n\n' +
    'Wirklich fortfahren?'
  )
  if (!ok) return
  if (formCtx) await formCtx.init()
  emergencyEdit.value = true
  window.scrollTo({ top: 0, behavior: 'smooth' })
}
</script>

<template>
  <AppLayout :title="entry?.label ?? 'Ticket'">

    <!-- Loading -->
    <div v-if="loading" class="flex items-center justify-center py-24">
      <div class="w-8 h-8 rounded-full border-2 border-[#3EAAB8] border-t-transparent animate-spin"/>
    </div>

    <template v-else-if="ticket">

      <!-- ═══════════════════════════════════════════════════════════════════
           VIEW = FORM — das Formular ist selbst-layoutend
           (Sidebar mit Fortschritt + Details links, Eingabefelder rechts).
           Wir reichen nur die Phasen via provide() in dessen Sidebar durch.
           Datengetrieben über phase.view, nicht mehr über den Phasen-Typ.
      ════════════════════════════════════════════════════════════════════ -->
      <div v-if="currentView === 'form' || emergencyEdit" class="space-y-6 pb-24">

        <div class="max-w-7xl mx-auto">
          <h1 class="text-xl font-semibold text-gray-900 dark:text-white">{{ ticket.title }}</h1>
          <p class="text-sm text-gray-400 mt-1">Erstellt am {{ ticket.created_at }}</p>
        </div>

        <!-- Notfall-Bearbeitung: Hinweis, dass die Phase unverändert bleibt -->
        <div v-if="emergencyEdit"
             class="max-w-7xl mx-auto rounded-2xl border border-yellow-300 dark:border-yellow-700/60
                    bg-yellow-50 dark:bg-yellow-900/20 px-4 py-3 flex items-start gap-3">
          <span class="text-lg leading-none">⚠️</span>
          <p class="text-sm text-yellow-800 dark:text-yellow-300">
            <span class="font-semibold">Notfall-Bearbeitung aktiv.</span>
            Die Felder sind editierbar. Mit „Speichern" werden die Änderungen übernommen –
            die Phase des Auftrags bleibt unverändert.
          </p>
        </div>

        <div v-if="isRejected && ticket.workflow_state?.rejected"
             class="max-w-7xl mx-auto rounded-2xl border border-red-300 bg-red-50 dark:bg-red-900/20
                    dark:border-red-700 p-4 text-sm">
          <p class="font-semibold text-red-700 dark:text-red-400 mb-1">
            Abgelehnt in Phase „{{ ticket.workflow_state.rejected.phase_key }}" von
            {{ ticket.workflow_state.rejected.rejected_by }}
          </p>
          <p class="text-red-600 dark:text-red-300 whitespace-pre-wrap">
            {{ ticket.workflow_state.rejected.message }}
          </p>
        </div>

        <!-- Beobachter erscheinen via provide() in der „Details"-Sidebar des Formulars,
             direkt unter „Verantwortlicher". -->
        <component
          v-if="formCtx && !formCtx.loading?.value"
          :is="entry!.form"
          :ctx="formCtx"
          phase="edit"
        />
      </div>

      <!-- ═══════════════════════════════════════════════════════════════════
           DEPT-REVIEW / COMPLETED / REJECTED — read-only Panel.
           Eine Sidebar links (Fortschritt + Meta), Panel rechts.
      ════════════════════════════════════════════════════════════════════ -->
      <div v-else class="max-w-7xl mx-auto space-y-6 pb-24">

        <div>
          <h1 class="text-xl font-semibold text-gray-900 dark:text-white">{{ ticket.title }}</h1>
          <p class="text-sm text-gray-400 mt-1">Erstellt am {{ ticket.created_at }}</p>
        </div>

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

        <div class="flex flex-col lg:flex-row gap-6">

          <!-- ── Sidebar: Fortschritt + Meta ── -->
          <aside class="w-full lg:w-[320px] flex-shrink-0">
            <div class="bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09]
                        rounded-2xl shadow-sm p-5 text-sm lg:sticky lg:top-4
                        divide-y divide-gray-100 dark:divide-white/[0.06]">

              <!-- Fortschritt -->
              <div v-if="phases.length" class="pb-5">
                <PhaseProgress :phases="phases" />
              </div>

              <!-- Meta -->
              <div class="py-5 first:pt-0 space-y-4">
                <div class="grid grid-cols-2 gap-4">
                  <div>
                    <p class="meta-label">Status</p>
                    <p class="meta-value">{{ STATUS_LABEL[ticket.status] ?? ticket.status }}</p>
                  </div>
                  <div>
                    <p class="meta-label">Priorität</p>
                    <p class="meta-value">{{ PRIORITY_LABEL[ticket.priority] ?? ticket.priority }}</p>
                  </div>
                </div>
                <div>
                  <p class="meta-label">Antragsteller</p>
                  <p class="meta-value">{{ ticket.owner_name }}</p>
                </div>
                <div>
                  <p class="meta-label">Verantwortlicher</p>
                  <p class="meta-value">{{ ticket.responsible?.name || '—' }}</p>
                </div>
              </div>

              <!-- Beobachter -->
              <div class="py-5">
                <TicketWatchers :watchers="watchers" :busy="watcherBusy"
                                @add="onAddWatcher" @remove="onRemoveWatcher" />
              </div>

              <!-- Fachabteilungen / Durchführung (erst ab Erreichen der Phase) -->
              <div v-if="showReviewDepartments && objectKeys(reviewDepartments).length" class="py-5">
                <p class="meta-label mb-2.5">Durchführung</p>
                <ul class="space-y-2">
                  <li v-for="(dept, gid) in reviewDepartments" :key="gid"
                      class="flex items-center justify-between gap-2">
                    <span class="flex items-center gap-1.5 min-w-0">
                      <span class="text-sm truncate"
                            :class="gid === deptId
                              ? 'font-semibold text-[#3EAAB8]'
                              : 'text-gray-900 dark:text-white'">
                        {{ dept.name }}
                      </span>
                      <span v-if="gid === deptId"
                            class="text-[10px] font-semibold uppercase tracking-wider text-[#3EAAB8]/70 flex-shrink-0">
                        (du)
                      </span>
                    </span>
                    <span class="text-[11px] font-semibold px-2 py-0.5 rounded-full flex-shrink-0"
                          :class="DEPT_STATUS_CLASS[dept.status] ?? DEPT_STATUS_CLASS.open">
                      {{ DEPT_STATUS_LABEL[dept.status] ?? dept.status }}
                    </span>
                  </li>
                </ul>
              </div>

              <!-- Kommentar -->
              <div v-if="ticket.comment" class="py-5 last:pb-0">
                <p class="meta-label mb-1">Kommentar</p>
                <p class="text-gray-900 dark:text-white whitespace-pre-wrap">{{ ticket.comment }}</p>
              </div>
            </div>
          </aside>

          <!-- ── Content: Export-Ansicht oder read-only Panel ── -->
          <section class="flex-1">
            <component
              v-if="currentView === 'export' && entry!.exportPanel"
              :is="entry!.exportPanel"
              :description="description"
              :owner-name="ticket.owner_name"
              :created-at="ticket.created_at"
              @exported="exported = true"
            />
            <component v-else :is="entry!.panel" :description="description" />
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

        <!-- Action bar (export mode): Archivieren nach dem Export -->
        <div v-else-if="currentView === 'export'" class="sticky bottom-4 z-40 mt-4">
          <div class="border border-gray-200 dark:border-white/[0.09] bg-white/95 dark:bg-[#212B3A]/95
                      backdrop-blur rounded-2xl shadow-lg py-3 px-4 flex items-center justify-between gap-4">
            <p class="text-sm text-gray-500 dark:text-gray-400">
              {{ exported ? 'PDF exportiert — bereit zum Archivieren.' : 'Bitte zuerst das PDF exportieren.' }}
            </p>
            <button @click="handleArchive" :disabled="!exported || archiving"
                    class="px-6 py-2 rounded-xl text-sm font-medium bg-gray-700 hover:bg-gray-800 text-white
                           disabled:opacity-50 disabled:cursor-not-allowed transition flex-shrink-0">
              {{ archiving ? 'Wird archiviert…' : 'Archivieren' }}
            </button>
          </div>
        </div>

        <!-- Action bar (approval mode): Freigeben / Ablehnen -->
        <div v-else-if="currentView === 'approval' && !isRejected" class="sticky bottom-4 z-40 mt-4">
          <div class="border border-gray-200 dark:border-white/[0.09] bg-white/95 dark:bg-[#212B3A]/95
                      backdrop-blur rounded-2xl shadow-lg py-3 px-4 flex items-center justify-between gap-4">
            <p class="text-sm text-gray-500 dark:text-gray-400">
              Antrag prüfen und freigeben oder ablehnen.
            </p>
            <div class="flex items-center gap-3 flex-shrink-0">
              <button @click="showRejectModal = true"
                      class="px-6 py-2 rounded-xl text-sm font-medium bg-red-600 hover:bg-red-700 text-white
                             transition">
                ✗ Ablehnen
              </button>
              <button @click="handleApprove" :disabled="approving"
                      class="px-6 py-2 rounded-xl text-sm font-medium bg-green-600 hover:bg-green-700 text-white
                             disabled:opacity-50 disabled:cursor-not-allowed transition">
                {{ approving ? 'Wird freigegeben…' : '✓ Freigeben' }}
              </button>
            </div>
          </div>
        </div>
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

<style scoped>
@reference "../../style.css";
.meta-label { @apply text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1; }
.meta-value { @apply font-medium text-gray-900 dark:text-white; }
</style>
