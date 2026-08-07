<script setup lang="ts">
/**
 * Liste von Automationen als aufklappbare Karten.
 * Der Kartenkopf fasst zusammen, was die Automation tut, damit man eine lange
 * Liste lesen kann, ohne jede Karte zu öffnen.
 */
import { ref, computed } from 'vue'
import type { Automation } from '@/types/process'
import { ACTION_LABEL, TRIGGER_LABEL, blankAutomation } from '@/lib/processSchema'
import { humanDuration } from '@/lib/isoDuration'
import AutomationEditor from './AutomationEditor.vue'
import ConditionSummary from './ConditionSummary.vue'

const props = defineProps<{
  modelValue: Automation[]
  fieldKeys: string[]
  fieldLabels?: Record<string, string>
  groups?: { id: string; name: string }[]
  title?: string
}>()

const emit = defineEmits<{ 'update:modelValue': [value: Automation[]] }>()

const list = computed<Automation[]>(() => props.modelValue ?? [])

/** Akkordeon: höchstens eine Karte offen – hält lange Phasen-Editoren übersichtlich. */
const open = ref(-1)
function toggle(i: number) {
  open.value = open.value === i ? -1 : i
}

// ── Kopfzeilen-Texte ──────────────────────────────────────────────────────────

function label(key: string | null): string {
  if (!key) return '—'
  return props.fieldLabels?.[key] ?? key
}

function triggerSummary(a: Automation): string {
  const t = a?.trigger
  if (!t) return '—'
  const base = TRIGGER_LABEL[t.type] ?? t.type
  if (t.type === 'timer') {
    const parts = [`nach ${t.after ? humanDuration(t.after) : '—'}`]
    if (t.repeat) parts.push(`alle ${humanDuration(t.repeat)}`)
    return `${base} ${parts.join(', ')}`
  }
  if (t.type === 'on_field_change') return `${base}: ${label(t.field)}`
  return base
}

function actionSummary(a: Automation): string {
  const type = a?.action?.type
  if (!type) return '—'
  return ACTION_LABEL[type] ?? type
}

// ── Schreiben ─────────────────────────────────────────────────────────────────

function update(i: number, v: Automation) {
  emit('update:modelValue', list.value.map((a, j) => (j === i ? v : a)))
}

function remove(i: number) {
  if (open.value === i) open.value = -1
  else if (open.value > i) open.value -= 1
  emit('update:modelValue', list.value.filter((_, j) => j !== i))
}

/** Freie Kennung suchen, damit keine doppelten IDs entstehen (Server lehnt ab). */
function add() {
  const taken = new Set(list.value.map((a) => a?.id))
  let n = 1
  while (taken.has(`auto-${n}`)) n++
  emit('update:modelValue', [...list.value, blankAutomation(`auto-${n}`)])
  open.value = list.value.length
}
</script>

<template>
  <div class="space-y-3">
    <p v-if="title" class="text-sm font-semibold text-gray-900 dark:text-white">{{ title }}</p>

    <p v-if="!list.length" class="text-sm text-gray-400 italic px-1">Keine Automationen</p>

    <div
      v-for="(a, i) in list"
      :key="i"
      class="rounded-xl border border-gray-200 dark:border-white/10 overflow-hidden"
    >
      <button
        type="button"
        class="w-full flex items-start gap-3 text-left px-4 py-3 hover:bg-gray-50 dark:hover:bg-[#263040] transition"
        @click="toggle(i)"
      >
        <span class="text-gray-400 text-xs mt-0.5 w-3 shrink-0">{{ open === i ? '▾' : '▸' }}</span>
        <span class="flex-1 min-w-0">
          <span class="flex flex-wrap items-center gap-2">
            <span class="text-sm font-medium text-gray-900 dark:text-white truncate">
              {{ a?.id || 'Ohne Kennung' }}
            </span>
            <span class="text-xs px-2 py-0.5 rounded-full bg-[#3EAAB8]/10 text-[#3EAAB8] whitespace-nowrap">
              {{ actionSummary(a) }}
            </span>
          </span>
          <span class="block text-xs text-gray-500 dark:text-gray-400 truncate mt-0.5">
            {{ triggerSummary(a) }}
          </span>
          <span class="block truncate mt-0.5">
            <span class="text-xs text-gray-400">Wenn:</span>
            <ConditionSummary :condition="a?.guard ?? null" :field-labels="fieldLabels" />
          </span>
        </span>
      </button>

      <div v-if="open === i" class="border-t border-gray-200 dark:border-white/10 p-4">
        <AutomationEditor
          :model-value="a"
          :field-keys="fieldKeys ?? []"
          :field-labels="fieldLabels"
          :groups="groups"
          @update:model-value="(v) => update(i, v)"
          @remove="remove(i)"
        />
      </div>
    </div>

    <button type="button" class="btn-secondary" @click="add">Automation hinzufügen</button>
  </div>
</template>
