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
  <div class="bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09]
              rounded-2xl shadow-sm p-5 text-sm">
    <p class="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">Beobachter</p>

    <div class="space-y-1.5 mb-3">
      <div v-for="w in watchers" :key="w.id"
           class="flex items-center justify-between gap-2 group">
        <span class="flex items-center gap-2 min-w-0">
          <span class="w-6 h-6 rounded-full bg-[#3EAAB8]/10 text-[#3EAAB8] flex items-center justify-center
                       text-[11px] font-semibold flex-shrink-0">
            {{ (w.name || w.id).slice(0, 1).toUpperCase() }}
          </span>
          <span class="text-gray-900 dark:text-white truncate">{{ w.name || w.id }}</span>
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
      <p v-if="!watchers.length" class="text-gray-400 italic">Noch keine Beobachter.</p>
    </div>

    <UserSelect
      placeholder="Beobachter hinzufügen…"
      :model-value="selected"
      @update:model-value="onSelect"
    />
  </div>
</template>
