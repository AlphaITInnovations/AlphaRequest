<script setup lang="ts">
/**
 * Phasen-Fortschritt eines Prozess-Auftrags: „Phase X von Y" plus die NAMEN
 * aller Phasen mit ihrem Stand.
 *
 * Optik und Aufbau folgen der früheren `components/tickets/PhaseProgress.vue`
 * (senkrechte Kette mit Punkten). Senkrecht statt waagerecht, weil die Namen
 * ausgeschrieben lesbar bleiben müssen – die waagerechte Kette, die vorher im
 * Kopf der Detailansicht stand, wurde bei mehr als vier Phasen unleserlich und
 * zeigte den Stand nur über die Farbe.
 *
 * Gerechnet wird in lib/processPhaseProgress.ts (ohne Vue, damit testbar).
 */
import { computed } from 'vue'
import {
  phaseProgress, phaseStepLabel, type PhaseStepInput, type PhaseStepStatus,
} from '@/lib/processPhaseProgress'

const props = withDefaults(defineProps<{
  /** Phasen der GEPINNTEN Definition – von dort kommen die Namen. */
  phases: readonly PhaseStepInput[]
  /** `runtime.current_index`; darf `phases.length` erreichen (Auftrag durch). */
  currentIndex: number
  /** `runtime.rejected` – dann steht die erreichte Phase still. */
  rejected?: boolean
}>(), { rejected: false })

const view = computed(() =>
  phaseProgress(props.phases, props.currentIndex, { rejected: props.rejected }))

/** Punkt-Farbe je Stand; „gestoppt" muss sich von „aktuell" unterscheiden. */
const DOT: Record<PhaseStepStatus, string> = {
  done: 'bg-green-500 text-white',
  current: 'bg-[#3EAAB8] text-white',
  stopped: 'bg-red-500 text-white',
  pending: 'bg-gray-100 dark:bg-white/10 text-gray-400 dark:text-gray-500',
}
const NAME: Record<PhaseStepStatus, string> = {
  done: 'text-green-700 dark:text-green-400',
  current: 'text-gray-900 dark:text-white',
  stopped: 'text-red-700 dark:text-red-400',
  pending: 'text-gray-400 dark:text-gray-500',
}
const STAND: Record<PhaseStepStatus, string> = {
  done: 'text-green-600 dark:text-green-500',
  current: 'text-[#3EAAB8] font-medium',
  stopped: 'text-red-600 dark:text-red-400 font-medium',
  pending: 'text-gray-400 dark:text-gray-600',
}
</script>

<template>
  <div>
    <div class="flex items-center justify-between gap-2 mb-3 flex-wrap">
      <p class="text-xs font-semibold text-gray-400 uppercase tracking-wider">Fortschritt</p>
      <span class="text-[11px] font-semibold px-2 py-0.5 rounded-full whitespace-nowrap"
            :class="view.rejected
              ? 'text-red-700 bg-red-100 dark:bg-red-900/30 dark:text-red-300'
              : 'text-[#3EAAB8] bg-[#3EAAB8]/10'">
        {{ view.text }}
      </span>
    </div>

    <p v-if="!view.steps.length" class="text-sm text-gray-400 italic">
      Dieser Prozess hat keine Phasen.
    </p>

    <ol v-else class="relative">
      <li v-for="(step, i) in view.steps" :key="step.key"
          class="relative flex gap-3"
          :class="{ 'pb-4': i < view.steps.length - 1 }">

        <!-- Verbindungslinie: grün nur, wo die Phase wirklich erledigt ist -->
        <div v-if="i < view.steps.length - 1"
             class="absolute left-[11px] top-6 bottom-0 w-px"
             :class="step.status === 'done' ? 'bg-green-400' : 'bg-gray-200 dark:bg-white/10'" />

        <div class="relative z-10 flex-shrink-0 w-6 h-6 rounded-full flex items-center
                    justify-center mt-0.5 ring-2 ring-white dark:ring-[#212B3A]"
             :class="DOT[step.status]">
          <svg v-if="step.status === 'done'" class="w-3.5 h-3.5" fill="none"
               stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7" />
          </svg>
          <span v-else-if="step.status === 'current'"
                class="w-2 h-2 rounded-full bg-white animate-pulse" />
          <span v-else-if="step.status === 'stopped'" class="text-[11px] font-bold leading-none">!</span>
          <span v-else class="text-[10px] font-bold leading-none">{{ step.number }}</span>
        </div>

        <div class="flex-1 min-w-0 mt-0.5">
          <p class="text-sm font-medium leading-tight break-words" :class="NAME[step.status]">
            {{ step.label }}
          </p>
          <p class="text-[11px] mt-0.5" :class="STAND[step.status]">
            {{ phaseStepLabel(step.status) }}
          </p>
        </div>
      </li>
    </ol>
  </div>
</template>
