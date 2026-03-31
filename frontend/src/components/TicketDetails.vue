<script setup lang="ts">
import UserSelect from '@/components/UserSelect.vue'
import type { TicketPriority } from '@/types/ticket'

// ── DEV: auf false setzen um das echte UserSelect zu verwenden ──
const DEV_MOCK_USER = true
const DEV_USERS = [
  { id: 'd5b75d5f-bb6c-4553-b46e-13ffad7ef910', name: 'Monika Gericke-Müller' },
  { id: 'a2046db5-4d1d-46aa-8bf6-49a867aabdad', name: 'Marco Schneider' },
  { id: 'ba747ea7-5eeb-461f-b72c-6dbc60f0d4a8', name: 'Marco Hertwich' },
  { id: 'c981b8a4-3e46-4f19-80e9-f36213088a02', name: 'Markus Homberger' },
  { id: '6ae1614e-cfc4-4e64-a1dd-b31e2032f515', name: 'Thomas Lang' },
]
// ───────────────────────────────────────────────────────────────

const props = defineProps<{
  phase: 'create' | 'edit' | 'view'
  priority?: TicketPriority
  comment?: string
  accountable?: { id: string; name: string } | null
  accountableError?: boolean
}>()

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
    <h2 class="text-base font-semibold text-gray-900 dark:text-white">Details</h2>

    <!-- ── Verantwortlicher ── -->
    <div>
      <template v-if="phase === 'create'">

        <!-- DEV: fixe Benutzer -->
        <template v-if="DEV_MOCK_USER">
          <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">
            Verantwortlicher *
          </label>
          <select
            @change="emit('update:accountable', ($event.target as HTMLSelectElement).value ? DEV_USERS.find(u => u.id === ($event.target as HTMLSelectElement).value) ?? null : null)"
            class="w-full rounded-xl border border-gray-200 dark:border-white/10
                   bg-white dark:bg-[#263040]
                   text-gray-900 dark:text-gray-100
                   px-3.5 py-2.5 text-sm
                   focus:outline-none focus:ring-2 focus:ring-[#3EAAB8]/30 transition"
          >
            <option value="">– Bitte wählen –</option>
            <option v-for="(u, i) in DEV_USERS" :key="`${u.id}-${i}`" :value="u.id">{{ u.name }}</option>
          </select>
        </template>

        <!-- PROD: echtes UserSelect -->
        <template v-else>
          <div :class="accountableError ? 'ring-1 ring-red-400 rounded-xl' : ''">
            <UserSelect
              label="Verantwortlicher *"
              :model-value="accountable"
              @update:model-value="emit('update:accountable', $event)"
            />
          </div>
          <p v-if="accountableError" class="mt-1 text-xs text-red-500">
            Pflichtfeld – bitte einen Verantwortlichen auswählen.
          </p>
        </template>

      </template>

      <!-- Edit & View: read-only -->
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

    <!-- ── Priorität ── -->
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

    <!-- ── Kommentar ── -->
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