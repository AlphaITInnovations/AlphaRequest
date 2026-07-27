<script setup lang="ts">
import { ref } from 'vue'
import UserSelect from '@/components/UserSelect.vue'
import type { Watcher } from '@/types/ticket'

defineProps<{ watchers: Watcher[]; busy?: boolean }>()
const emit = defineEmits<{ add: [id: string, name: string]; remove: [id: string] }>()

const selected = ref<{ id: string; name: string } | null>(null)

function onSelect(v: { id: string; name: string } | null) {
  if (!v) return
  selected.value = null          // Auswahl zurücksetzen, damit weiter hinzugefügt werden kann
  emit('add', v.id, v.name)
}
</script>

<template>
  <!-- chrome-los: wird in die Details-/Meta-Karte eingebettet -->
  <div>
    <p class="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">Beobachter</p>

    <div v-if="watchers.length" class="space-y-1.5 mb-2.5">
      <div v-for="w in watchers" :key="w.id" class="flex items-center justify-between gap-2">
        <span class="flex items-center gap-2 min-w-0">
          <span class="w-6 h-6 rounded-full bg-[#3EAAB8]/10 text-[#3EAAB8] flex items-center justify-center
                       text-[11px] font-semibold flex-shrink-0">
            {{ (w.name || w.id).slice(0, 1).toUpperCase() }}
          </span>
          <span class="text-sm text-gray-900 dark:text-white truncate">{{ w.name || w.id }}</span>
        </span>
        <button @click="emit('remove', w.id)" :disabled="busy"
                class="text-gray-300 dark:text-gray-600 hover:text-red-500 transition flex-shrink-0
                       disabled:opacity-50"
                title="Beobachter entfernen">
          <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/>
          </svg>
        </button>
      </div>
    </div>
    <p v-else class="text-sm text-gray-400 italic mb-2.5">Noch keine Beobachter.</p>

    <UserSelect
      label=""
      placeholder="Beobachter hinzufügen…"
      :model-value="selected"
      @update:model-value="onSelect"
    />

    <!-- Datenschutz-Hinweis: Beobachter haben Voll-Sicht auf den Auftrag -->
    <p class="mt-2 flex items-start gap-1.5 text-xs text-amber-600 dark:text-amber-400/90">
      <svg class="w-3.5 h-3.5 flex-shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
        <path stroke-linecap="round" stroke-linejoin="round" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
      <span>Beobachter sehen <strong>alle Informationen</strong> des Auftrags.</span>
    </p>
  </div>
</template>
