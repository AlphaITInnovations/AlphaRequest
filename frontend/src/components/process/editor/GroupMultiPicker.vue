<script setup lang="ts">
/**
 * Auswahl mehrerer Fachabteilungen (Werte = Gruppen-IDs), z. B. für
 * visibility.visibleToGroups.
 *
 * IDs, zu denen es keine Fachabteilung (mehr) gibt, werden als rote Chips
 * geführt statt still verworfen – sonst würde ein Speichern die Berechtigung
 * unbemerkt verändern.
 */
import { computed } from 'vue'

const props = defineProps<{
  modelValue: string[]
  groups: { id: string; name: string }[]
}>()

const emit = defineEmits<{ 'update:modelValue': [value: string[]] }>()

const selected = computed<string[]>(() => props.modelValue ?? [])
const list = computed(() => props.groups ?? [])

const unknownIds = computed(() =>
  selected.value.filter((id) => !list.value.some((g) => g.id === id)))

function toggle(id: string) {
  emit('update:modelValue', selected.value.includes(id)
    ? selected.value.filter((x) => x !== id)
    : [...selected.value, id])
}
function removeId(id: string) {
  emit('update:modelValue', selected.value.filter((x) => x !== id))
}
</script>

<template>
  <div class="space-y-2">
    <div v-if="list.length"
         class="max-h-48 overflow-y-auto rounded-xl border border-gray-200 dark:border-white/10
                divide-y divide-gray-100 dark:divide-white/[0.04]">
      <label v-for="g in list" :key="g.id"
             class="flex items-center gap-2.5 px-3 py-2 text-sm text-gray-600 dark:text-gray-300
                    hover:bg-gray-50 dark:hover:bg-[#263040] cursor-pointer select-none transition">
        <input type="checkbox" :checked="selected.includes(g.id)" @change="toggle(g.id)"
               class="h-4 w-4 rounded border-gray-300 dark:border-white/20 text-[#3EAAB8]
                      focus:ring-[#3EAAB8]/30 cursor-pointer" />
        <span class="truncate">{{ g.name }}</span>
      </label>
    </div>
    <p v-else class="text-sm text-gray-400 italic px-1">Keine Fachabteilungen vorhanden.</p>

    <div v-if="unknownIds.length" class="flex flex-wrap gap-2">
      <span v-for="id in unknownIds" :key="id"
            class="inline-flex items-center gap-1.5 rounded-full bg-red-100 dark:bg-red-900/30
                   text-red-700 dark:text-red-300 px-3 py-1 text-xs">
        Unbekannt: {{ id }}
        <button type="button" @click="removeId(id)" class="hover:text-red-900 dark:hover:text-red-100 transition">✕</button>
      </span>
    </div>
  </div>
</template>
