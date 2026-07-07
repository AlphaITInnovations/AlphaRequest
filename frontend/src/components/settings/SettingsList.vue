<script setup lang="ts">
import { ref, computed } from 'vue'

// Standardisierte, durchsuchbare Liste für die Settings-Master-Detail-Panels.
const props = defineProps<{
  title: string
  items: any[]
  loading?: boolean
  addLabel?: string
  emptyText?: string
  searchPlaceholder?: string
  filterText: (item: any) => string   // durchsuchbarer Text je Eintrag
}>()
const emit = defineEmits<{ (e: 'add'): void; (e: 'select', index: number): void }>()

const q = ref('')
const filtered = computed(() => {
  const query = q.value.toLowerCase().trim()
  return props.items
    .map((it, i) => ({ it, i }))
    .filter(({ it }) => !query || props.filterText(it).toLowerCase().includes(query))
})
</script>

<template>
  <div>
    <div class="flex items-center justify-between gap-3 mb-4 flex-wrap">
      <div class="flex items-baseline gap-2">
        <h2 class="section-title mb-0">{{ title }}</h2>
        <span class="text-xs text-gray-400">{{ items.length }}</span>
      </div>
      <button v-if="addLabel" @click="emit('add')" class="btn-primary">{{ addLabel }}</button>
    </div>

    <slot name="hint" />

    <div class="relative mb-3">
      <svg class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none"
           fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
        <circle cx="11" cy="11" r="8" /><path d="m21 21-4.3-4.3" />
      </svg>
      <input v-model="q" :placeholder="searchPlaceholder ?? 'Suchen…'" class="set-input w-full !pl-10" />
    </div>

    <div v-if="loading" class="flex items-center justify-center py-16">
      <div class="w-7 h-7 rounded-full border-2 border-[#3EAAB8] border-t-transparent animate-spin" />
    </div>
    <div v-else class="space-y-2">
      <p v-if="items.length === 0" class="text-sm text-gray-400 italic px-1">{{ emptyText ?? 'Keine Einträge.' }}</p>
      <p v-else-if="filtered.length === 0" class="text-sm text-gray-400 italic px-1">Keine Treffer.</p>
      <button v-for="{ it, i } in filtered" :key="i" @click="emit('select', i)"
              class="group w-full flex items-center gap-3 text-left rounded-xl border border-gray-200 dark:border-white/10
                     bg-white dark:bg-[#212B3A] hover:border-[#3EAAB8]/50 hover:shadow-sm
                     hover:bg-[#3EAAB8]/[0.03] transition px-4 py-3">
        <slot name="row" :item="it" :index="i" />
        <span class="text-gray-300 dark:text-gray-600 group-hover:text-[#3EAAB8] transition text-lg leading-none">›</span>
      </button>
    </div>
  </div>
</template>
