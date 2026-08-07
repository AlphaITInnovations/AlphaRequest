<script setup lang="ts">
/**
 * Editor für die feste Optionsliste eines Auswahl-Feldes (optionsSource='static').
 *
 * Der Wert („value") landet im Ticket, der Text („label") nur in der Oberfläche.
 * Leerer Text wird bewusst als `null` zurückgegeben – der Server normalisiert
 * genauso, sonst wäre der Entwurf sofort „dirty".
 */
import { computed } from 'vue'
import type { StaticOption } from '@/types/process'

const props = defineProps<{ modelValue: StaticOption[] }>()
const emit = defineEmits<{ 'update:modelValue': [value: StaticOption[]] }>()

// Defensiv: importierte Definitionen können `options` ganz weglassen.
const rows = computed<StaticOption[]>(() => props.modelValue ?? [])

function commit(next: StaticOption[]) {
  emit('update:modelValue', next)
}

function setValue(i: number, v: string) {
  commit(rows.value.map((o, j) => (j === i ? { ...o, value: v } : o)))
}
function setLabel(i: number, v: string) {
  commit(rows.value.map((o, j) => (j === i ? { ...o, label: v.trim() === '' ? null : v } : o)))
}
function add() {
  commit([...rows.value, { value: '', label: null }])
}
function remove(i: number) {
  commit(rows.value.filter((_, j) => j !== i))
}
function move(i: number, d: -1 | 1) {
  const j = i + d
  if (j < 0 || j >= rows.value.length) return
  const next = [...rows.value]
  const tmp = next[i]
  next[i] = next[j]
  next[j] = tmp
  commit(next)
}

/** Werte, die mehrfach vorkommen – im Ticket wäre die Auswahl dann mehrdeutig. */
const duplicates = computed(() => {
  const seen = new Set<string>()
  const dup = new Set<string>()
  for (const o of rows.value) {
    if (!o.value) continue
    if (seen.has(o.value)) dup.add(o.value)
    seen.add(o.value)
  }
  return dup
})

function rowError(o: StaticOption): string | null {
  if (!o.value.trim()) return 'Wert fehlt.'
  if (duplicates.value.has(o.value)) return 'Wert kommt mehrfach vor.'
  return null
}
</script>

<template>
  <div class="space-y-2">
    <div class="grid grid-cols-[1fr_1fr_auto] gap-2 px-1">
      <span class="text-xs font-medium text-gray-400">Wert</span>
      <span class="text-xs font-medium text-gray-400">Anzeigetext (optional)</span>
      <span class="w-[86px]"></span>
    </div>

    <div v-for="(o, i) in rows" :key="i" class="space-y-1">
      <div class="grid grid-cols-[1fr_1fr_auto] gap-2 items-center">
        <input :value="o.value" @input="setValue(i, ($event.target as HTMLInputElement).value)"
               placeholder="z. B. ja" class="pfi font-mono"
               :class="rowError(o) ? 'border-red-400 bg-red-50 dark:bg-red-900/20' : ''" />
        <input :value="o.label ?? ''" @input="setLabel(i, ($event.target as HTMLInputElement).value)"
               placeholder="z. B. Ja, bitte" class="pfi" />
        <div class="flex gap-1">
          <button type="button" @click="move(i, -1)" :disabled="i === 0" title="Nach oben"
                  class="pbtn">↑</button>
          <button type="button" @click="move(i, 1)" :disabled="i === rows.length - 1" title="Nach unten"
                  class="pbtn">↓</button>
          <button type="button" @click="remove(i)" title="Option entfernen"
                  class="pbtn hover:text-red-500">✕</button>
        </div>
      </div>
      <p v-if="rowError(o)" class="text-xs text-red-500 px-1">{{ rowError(o) }}</p>
    </div>

    <p v-if="rows.length === 0" class="text-sm text-gray-400 italic px-1">
      Noch keine Optionen. Ohne Optionen bleibt die Auswahl im Formular leer.
    </p>

    <button type="button" @click="add" class="btn-secondary">+ Option</button>
  </div>
</template>

<style scoped>
@reference "../../../style.css";
.pfi {
  @apply w-full rounded-xl border border-gray-200 dark:border-white/10
         bg-white dark:bg-[#263040] text-gray-900 dark:text-gray-100
         px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-[#3EAAB8]/30 transition;
}
.pbtn {
  @apply px-2 py-1.5 rounded-lg border border-gray-200 dark:border-white/10
         text-gray-500 dark:text-gray-400 text-xs leading-none
         hover:bg-gray-50 dark:hover:bg-white/5 disabled:opacity-30
         disabled:cursor-not-allowed transition;
}
</style>
