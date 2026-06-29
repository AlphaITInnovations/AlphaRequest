<script setup lang="ts">
import { inject, computed, type ComputedRef, type Ref } from 'vue'
import UserSelect from '@/components/UserSelect.vue'
import PhaseProgress from '@/components/tickets/PhaseProgress.vue'
import TicketWatchers from '@/components/tickets/TicketWatchers.vue'
import type { TicketPriority, WorkflowPhase, Watcher } from '@/types/ticket'

withDefaults(defineProps<{
  phase: 'create' | 'edit' | 'view'
  priority?: TicketPriority
  comment?: string
  accountable?: { id: string; name: string } | null
  accountableError?: boolean
  // Nur Fachabteilungen zuweisbar (keine Personen) – z.B. Basis-Tickets.
  groupsOnly?: boolean
  // Zuständigen-Auswahl gesperrt (z.B. Onboarding-Erstellung: automatisch Freigabe).
  accountableLocked?: boolean
  accountableLockedHint?: string
  // Auswahl auch außerhalb der Erstellungsphase editierbar (z.B. BackOffice wählt
  // den nächsten Bearbeiter).
  accountableEditable?: boolean
  // Optionaler Hinweis unter dem editierbaren Bearbeiter-Picker (z.B. BackOffice).
  accountableEditableHint?: string
}>(), {
  groupsOnly: false,
  accountableLocked: false,
  accountableEditable: false,
})

// Phasen werden vom Detail-View bereitgestellt (nur im Edit-/View-Kontext vorhanden)
const injectedPhases = inject<ComputedRef<WorkflowPhase[]> | null>('workflowPhases', null)
const phases = computed<WorkflowPhase[]>(() => injectedPhases?.value ?? [])

// Beobachter werden ebenfalls vom Detail-View bereitgestellt (nur im Edit-Kontext).
interface WatchersCtx {
  watchers: Ref<Watcher[]> | ComputedRef<Watcher[]>
  busy: Ref<boolean>
  add: (id: string, name: string) => void
  remove: (id: string) => void
}
const watchersCtx = inject<WatchersCtx | null>('ticketWatchers', null)
const watcherList = computed<Watcher[]>(() => watchersCtx?.watchers.value ?? [])
const watcherBusy = computed<boolean>(() => watchersCtx?.busy.value ?? false)

const emit = defineEmits<{
  'update:priority':    [v: TicketPriority]
  'update:comment':     [v: string]
  'update:accountable': [v: { id: string; name: string } | null]
}>()

const PRIORITIES: { value: TicketPriority; label: string }[] = [
  { value: 'low',      label: 'Niedrig'  },
  { value: 'medium',   label: 'Mittel'   },
  { value: 'high',     label: 'Hoch'     },
  { value: 'critical', label: 'Kritisch' },
]
</script>

<template>
  <div class="space-y-5">

    <!-- Phasen-Fortschritt (nur im Edit-Kontext) -->
    <template v-if="phases.length">
      <PhaseProgress :phases="phases" />
      <hr class="border-gray-100 dark:border-white/[0.06]" />
    </template>

    <h2 class="text-base font-semibold text-gray-900 dark:text-white">Details</h2>

    <!-- Verantwortlicher -->
    <div>
      <!-- Gesperrt: Zuständigkeit wird automatisch gesetzt (z.B. Freigabe Herr Lutz) -->
      <template v-if="accountableLocked">
        <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">
          Nächster Bearbeiter / Verantwortlicher
        </label>
        <div class="flex items-center gap-2 w-full rounded-xl border border-dashed
                    border-[#3EAAB8]/40 bg-[#3EAAB8]/5 px-3.5 py-2.5 text-sm
                    text-gray-600 dark:text-gray-300">
          <svg class="w-4 h-4 flex-shrink-0 text-[#3EAAB8]" viewBox="0 0 24 24" fill="none"
               stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0110 0v4"/>
          </svg>
          {{ accountableLockedHint || 'Wird automatisch zugewiesen.' }}
        </div>
      </template>

      <!-- Editierbar: in der Erstellungsphase oder explizit (BackOffice) -->
      <template v-else-if="phase === 'create' || accountableEditable">
        <div :class="accountableError ? 'ring-1 ring-red-400 rounded-xl' : ''">
          <UserSelect
            :label="groupsOnly ? 'Zuständige Fachabteilung *' : 'Nächster Bearbeiter / Verantwortlicher *'"
            :placeholder="groupsOnly ? 'Fachabteilung auswählen…' : 'Mitarbeiter:in auswählen…'"
            :model-value="accountable"
            :show-groups="true"
            :show-users="!groupsOnly"
            @update:model-value="emit('update:accountable', $event)"
          />
        </div>
        <p v-if="accountableError" class="mt-1 text-xs text-red-500">
          {{ groupsOnly ? 'Pflichtfeld – bitte eine Fachabteilung auswählen.' : 'Pflichtfeld – bitte einen Verantwortlichen auswählen.' }}
        </p>
        <p v-if="accountableEditableHint" class="mt-1.5 text-xs text-gray-500 dark:text-gray-400">
          {{ accountableEditableHint }}
        </p>
      </template>

      <template v-else>
        <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">
          Verantwortlicher
        </label>
        <div class="w-full rounded-xl border border-gray-200 dark:border-white/10
                    bg-gray-50 dark:bg-[#263040]
                    text-gray-700 dark:text-gray-300
                    px-3.5 py-2.5 text-sm">
          {{ accountable?.name ?? '–' }}
        </div>
      </template>
    </div>

    <!-- Beobachter (direkt unter Verantwortlicher, nur im Edit-Kontext) -->
    <TicketWatchers
      v-if="watchersCtx"
      :watchers="watcherList"
      :busy="watcherBusy"
      @add="watchersCtx.add"
      @remove="watchersCtx.remove"
    />

    <!-- Priorität -->
    <div>
      <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">
        Priorität
      </label>
      <select
        :value="priority ?? 'medium'"
        :disabled="phase === 'view'"
        @change="emit('update:priority', ($event.target as HTMLSelectElement).value as TicketPriority)"
        class="w-full rounded-xl border border-gray-200 dark:border-white/10
               bg-white dark:bg-[#263040]
               text-gray-900 dark:text-gray-100
               px-3.5 py-2.5 text-sm
               focus:outline-none focus:ring-2 focus:ring-[#3EAAB8]/30
               disabled:opacity-60 disabled:cursor-not-allowed
               transition"
      >
        <option v-for="p in PRIORITIES" :key="p.value" :value="p.value">
          {{ p.label }}
        </option>
      </select>
    </div>

    <!-- Kommentar -->
    <div v-if="phase !== 'view'">
      <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">
        Kommentar
      </label>
      <textarea
        :value="comment ?? ''"
        @input="emit('update:comment', ($event.target as HTMLTextAreaElement).value)"
        rows="4"
        placeholder="Optionaler Kommentar…"
        class="w-full rounded-xl border border-gray-200 dark:border-white/10
               bg-white dark:bg-[#263040]
               text-gray-900 dark:text-gray-100
               placeholder-gray-400 dark:placeholder-gray-500
               px-3.5 py-2.5 text-sm resize-none
               focus:outline-none focus:ring-2 focus:ring-[#3EAAB8]/30
               transition"
      />
    </div>
  </div>
</template>