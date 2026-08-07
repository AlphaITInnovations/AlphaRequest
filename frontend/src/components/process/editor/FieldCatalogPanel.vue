<script setup lang="ts">
/**
 * Der Feld-Katalog eines Prozesses: Liste aller Felder, jeweils aufklappbar in
 * den FieldDefEditor.
 *
 * Jede Zeile trägt den Anker `pe-catalog-<index>` – die Fehlerliste des Editors
 * springt genau dorthin (siehe validateDefinition/ProcessIssue.anchor).
 *
 * Umbenennungen werden nur GEMELDET (`renamed`), nicht selbst nachgezogen: Die
 * Verweise stecken in Phasen, Bedingungen und Automationen und damit außerhalb
 * dieses Panels.
 */
import { computed, ref } from 'vue'
import type { FieldDef } from '@/types/process'
import { WIDGET_LABEL, blankFieldDef } from '@/lib/processSchema'
import FieldDefEditor from '@/components/process/editor/FieldDefEditor.vue'

const props = defineProps<{
  modelValue: FieldDef[]
  groups: { id: string; name: string }[]
}>()

const emit = defineEmits<{
  'update:modelValue': [value: FieldDef[]]
  renamed: [payload: { from: string; to: string }]
}>()

const list = computed<FieldDef[]>(() => props.modelValue ?? [])
const allKeys = computed(() => list.value.map((f) => f.key))

const search = ref('')

/** Sichtbare Zeilen inkl. ihres ECHTEN Index – Anker und Mutationen brauchen ihn. */
const visibleRows = computed(() => {
  const needle = search.value.trim().toLowerCase()
  return list.value
    .map((f, i) => ({ f, i }))
    .filter(({ f }) => !needle
      || f.key.toLowerCase().includes(needle)
      || (f.label ?? '').toLowerCase().includes(needle))
})

// ── Aufgeklappte Zeilen (nach Index; bei jeder Umsortierung mitgeführt) ───────

const expanded = ref<number[]>([])
const isOpen = (i: number) => expanded.value.includes(i)
function toggleRow(i: number) {
  expanded.value = isOpen(i) ? expanded.value.filter((x) => x !== i) : [...expanded.value, i]
}

// ── Änderungen ────────────────────────────────────────────────────────────────

function commit(next: FieldDef[]) {
  emit('update:modelValue', next)
}

function onUpdate(i: number, next: FieldDef) {
  const prev = list.value[i]
  commit(list.value.map((f, j) => (j === i ? next : f)))
  // Nur bei zwei nicht-leeren Schlüsseln melden – sonst würden bestehende
  // Verweise beim Tippen auf einen leeren Schlüssel zeigen.
  if (prev && prev.key && next.key && prev.key !== next.key) {
    emit('renamed', { from: prev.key, to: next.key })
  }
}

/** Freier Vorschlag feld_1, feld_2 … damit ein neues Feld sofort gültig ist. */
function suggestKey(): string {
  const used = new Set(allKeys.value)
  let n = 1
  while (used.has(`feld_${n}`)) n++
  return `feld_${n}`
}

function addField() {
  const idx = list.value.length
  commit([...list.value, blankFieldDef(suggestKey())])
  expanded.value = [...expanded.value, idx]
  search.value = ''
}

function removeField(i: number) {
  const f = list.value[i]
  if (!confirm(`Feld „${f?.key || 'ohne Schlüssel'}“ wirklich entfernen? `
    + 'Verweise in Phasen, Bedingungen und Automationen bleiben bestehen und werden '
    + 'als Fehler angezeigt.')) return
  commit(list.value.filter((_, j) => j !== i))
  expanded.value = expanded.value.filter((x) => x !== i).map((x) => (x > i ? x - 1 : x))
}

function move(i: number, d: -1 | 1) {
  const j = i + d
  if (j < 0 || j >= list.value.length) return
  const next = [...list.value]
  const tmp = next[i]
  next[i] = next[j]
  next[j] = tmp
  commit(next)
  expanded.value = expanded.value.map((x) => (x === i ? j : x === j ? i : x))
}

function widgetLabel(f: FieldDef): string {
  return WIDGET_LABEL[f.widget] ?? f.widget
}
</script>

<template>
  <section class="space-y-3">
    <div class="flex flex-wrap items-center gap-3">
      <h3 class="text-lg font-semibold text-gray-900 dark:text-white">Feld-Katalog</h3>
      <span class="text-xs px-2 py-0.5 rounded-full bg-gray-100 dark:bg-white/10
                   text-gray-500 dark:text-gray-400">{{ list.length }}</span>
      <input v-model="search" placeholder="Feld suchen…" class="pfi flex-1 min-w-[180px] max-w-xs" />
      <button type="button" @click="addField" class="btn-primary ml-auto">+ Feld hinzufügen</button>
    </div>

    <!-- Leerer Katalog: erklären, wozu er da ist -->
    <div v-if="list.length === 0"
         class="rounded-xl border border-gray-200 dark:border-white/10 px-4 py-8 text-center space-y-2">
      <p class="text-sm text-gray-500 dark:text-gray-400 max-w-xl mx-auto">
        Der Feld-Katalog beschreibt alle Angaben, die dieser Prozess kennt – einmal definiert und
        danach in beliebig vielen Phasen einsetzbar. Ob ein Feld in einer Phase sichtbar,
        bearbeitbar oder Pflicht ist, wird erst dort festgelegt.
      </p>
      <p class="text-sm text-gray-400 italic">Noch keine Felder angelegt.</p>
    </div>

    <p v-else-if="visibleRows.length === 0" class="text-sm text-gray-400 italic px-1">
      Kein Feld passt zur Suche.
    </p>

    <div v-else class="space-y-2">
      <div v-for="{ f, i } in visibleRows" :key="i" :id="`pe-catalog-${i}`"
           class="rounded-xl border border-gray-200 dark:border-white/10 overflow-hidden">
        <div class="flex items-center gap-2 pr-2">
          <button type="button" @click="toggleRow(i)"
                  class="flex-1 min-w-0 flex items-center gap-2 px-3 py-2.5 text-left
                         hover:bg-gray-50 dark:hover:bg-[#263040] transition">
            <span class="w-3 text-xs text-gray-400">{{ isOpen(i) ? '▾' : '▸' }}</span>
            <span class="font-mono text-sm text-gray-900 dark:text-white truncate">
              {{ f.key || '—' }}
            </span>
            <span v-if="f.label" class="text-sm text-gray-500 dark:text-gray-400 truncate">
              {{ f.label }}
            </span>
            <span class="ml-auto flex items-center gap-1.5 shrink-0">
              <span class="text-xs px-2 py-0.5 rounded-full bg-gray-100 dark:bg-white/10
                           text-gray-500 dark:text-gray-400 whitespace-nowrap">
                {{ widgetLabel(f) }}
              </span>
              <span v-if="f.visibility?.confidential"
                    class="text-xs px-2 py-0.5 rounded-full bg-red-100 dark:bg-red-900/30
                           text-red-700 dark:text-red-300 whitespace-nowrap">vertraulich</span>
              <span v-if="f.computed"
                    class="text-xs px-2 py-0.5 rounded-full bg-[#3EAAB8]/15 text-[#3EAAB8]
                           whitespace-nowrap">berechnet</span>
            </span>
          </button>
          <div class="flex gap-1 shrink-0">
            <button type="button" @click="move(i, -1)" :disabled="i === 0" title="Nach oben"
                    class="pbtn">↑</button>
            <button type="button" @click="move(i, 1)" :disabled="i === list.length - 1"
                    title="Nach unten" class="pbtn">↓</button>
            <button type="button" @click="removeField(i)" title="Feld entfernen"
                    class="pbtn hover:text-red-500">✕</button>
          </div>
        </div>

        <div v-if="isOpen(i)"
             class="border-t border-gray-200 dark:border-white/10 p-3 bg-gray-50/60 dark:bg-[#1A2130]">
          <FieldDefEditor :model-value="f" :groups="groups" :field-keys="allKeys"
                          @update:model-value="onUpdate(i, $event)"
                          @remove="removeField(i)" />
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
@reference "../../../style.css";
.pfi {
  @apply rounded-xl border border-gray-200 dark:border-white/10
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
