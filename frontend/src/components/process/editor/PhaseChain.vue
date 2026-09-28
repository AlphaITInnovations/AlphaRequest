<script setup lang="ts">
/**
 * Visuelle Phasen-Pipeline: anlegen, auswählen, umsortieren, löschen.
 * Der Ablauf ist bewusst LINEAR (wie die Backend-Engine) – die Reihenfolge in
 * dieser Liste IST der Ablauf. Farbe/Symbol je Phasenart kommen aus
 * PHASE_KIND_META, damit Pipeline und Kontext-Kopf konsistent aussehen.
 */
import { computed } from 'vue'
import type { PhaseDef } from '@/types/process'
import {
  PHASE_KIND_LABEL, PHASE_KIND_META, blankPhase, suggestPhaseKey,
} from '@/lib/processSchema'

const props = defineProps<{
  modelValue: PhaseDef[]
  selected: number
  readonly?: boolean
  errorPhases?: Set<number>
}>()

const emit = defineEmits<{
  'update:modelValue': [value: PhaseDef[]]
  select: [index: number]
}>()

const phases = computed(() => props.modelValue)

function uniquePhaseKey(base: string): string {
  const taken = new Set(phases.value.map((p) => p.key))
  if (!taken.has(base)) return base
  let i = 2
  while (taken.has(`${base}_${i}`)) i++
  return `${base}_${i}`
}

function addPhase() {
  // Die erste Phase ist immer die Start-Phase; weitere sind Bearbeitungsphasen.
  const isFirst = phases.value.length === 0
  const key = uniquePhaseKey(isFirst ? 'erstellung' : suggestPhaseKey(`phase ${phases.value.length + 1}`))
  const next = [...phases.value, blankPhase(key, isFirst ? 'start' : 'task')]
  emit('update:modelValue', next)
  emit('select', next.length - 1)
}

function move(index: number, delta: number) {
  const target = index + delta
  if (target < 0 || target >= phases.value.length) return
  const next = [...phases.value]
  const [item] = next.splice(index, 1)
  next.splice(target, 0, item)
  emit('update:modelValue', next)
  emit('select', target)
}

function remove(index: number) {
  const p = phases.value[index]
  if (!confirm(`Phase „${p.label || p.key}" wirklich entfernen?`)) return
  const next = phases.value.filter((_, i) => i !== index)
  emit('update:modelValue', next)
  emit('select', Math.max(0, Math.min(index, next.length - 1)))
}
</script>

<template>
  <div>
    <div class="flex items-center justify-between mb-3">
      <h3 class="text-sm font-semibold text-gray-700 dark:text-gray-200">Ablauf</h3>
      <button v-if="!readonly" @click="addPhase"
              class="inline-flex items-center gap-1 text-xs font-medium px-2.5 py-1 rounded-lg
                     text-[#3EAAB8] hover:bg-[#3EAAB8]/10 transition">
        <span class="text-sm leading-none">+</span> Phase
      </button>
    </div>

    <p v-if="!phases.length" class="text-sm text-gray-400 italic py-4">
      Noch keine Phasen. Die erste Phase ist die Start-Phase, in der der Auftrag angelegt wird.
    </p>

    <ol class="space-y-0">
      <li v-for="(p, i) in phases" :key="i">
        <div
          :id="`pe-phase-${i}`"
          @click="emit('select', i)"
          class="group relative flex items-center gap-3 rounded-xl border px-2.5 py-2.5 cursor-pointer transition"
          :class="[
            i === selected
              ? 'border-[#3EAAB8] bg-[#3EAAB8]/[0.08] shadow-sm'
              : 'border-transparent hover:bg-gray-50 dark:hover:bg-white/5',
            errorPhases?.has(i) ? 'ring-1 ring-red-400/70' : '',
          ]"
        >
          <!-- Aktiv-Akzent links -->
          <span v-if="i === selected"
                class="absolute left-0 top-2 bottom-2 w-[3px] rounded-full bg-[#3EAAB8]" />

          <!-- Art-Symbol -->
          <span class="w-8 h-8 shrink-0 rounded-lg flex items-center justify-center text-[13px] leading-none"
                :class="PHASE_KIND_META[p.kind].badge">
            {{ PHASE_KIND_META[p.kind].icon }}
          </span>

          <div class="min-w-0 flex-1">
            <div class="truncate text-sm font-medium text-gray-800 dark:text-gray-100">
              {{ p.label || p.key || '(ohne Namen)' }}
            </div>
            <div class="truncate text-[11px] text-gray-400">
              Schritt {{ i + 1 }} · {{ PHASE_KIND_LABEL[p.kind] }}
              <span class="font-mono">· {{ p.key }}</span>
            </div>
          </div>

          <span v-if="errorPhases?.has(i)" class="shrink-0 text-red-500 text-xs"
                title="Fehler in dieser Phase">●</span>

          <div v-if="!readonly"
               class="shrink-0 flex items-center gap-0.5 opacity-0 group-hover:opacity-100
                      focus-within:opacity-100 transition">
            <button @click.stop="move(i, -1)" :disabled="i === 0" aria-label="Nach oben"
                    class="w-6 h-6 rounded-md flex items-center justify-center text-gray-400
                           hover:text-gray-700 hover:bg-gray-100 dark:hover:text-gray-200
                           dark:hover:bg-white/10 disabled:opacity-30 disabled:hover:bg-transparent">▲</button>
            <button @click.stop="move(i, 1)" :disabled="i === phases.length - 1" aria-label="Nach unten"
                    class="w-6 h-6 rounded-md flex items-center justify-center text-gray-400
                           hover:text-gray-700 hover:bg-gray-100 dark:hover:text-gray-200
                           dark:hover:bg-white/10 disabled:opacity-30 disabled:hover:bg-transparent">▼</button>
            <button @click.stop="remove(i)" aria-label="Phase entfernen"
                    class="w-6 h-6 rounded-md flex items-center justify-center text-gray-400
                           hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20">✕</button>
          </div>
        </div>

        <!-- Verbinder zwischen den Phasen (unter dem Symbol zentriert) -->
        <div v-if="i < phases.length - 1"
             class="ml-[26px] h-2.5 w-px bg-gray-200 dark:bg-white/15" />
      </li>
    </ol>
  </div>
</template>
