<script setup lang="ts">
import { computed } from 'vue'
import type { WorkflowPhase } from '@/types/ticket'

const props = defineProps<{ phases: WorkflowPhase[] }>()

const currentIndex = computed(() =>
  props.phases.findIndex(p => p.status === 'in_progress'),
)

// "Phase X von Y" — falls alles erledigt, die letzte Phase anzeigen
const displayIndex = computed(() => {
  if (currentIndex.value >= 0) return currentIndex.value + 1
  const revDone = [...props.phases].reverse().findIndex(p => p.status === 'done')
  return revDone >= 0 ? props.phases.length - revDone : 1
})
</script>

<template>
  <div>
    <!-- Header: "Phase X von Y" -->
    <div class="flex items-center justify-between mb-3">
      <p class="text-xs font-semibold text-gray-400 uppercase tracking-wider">Fortschritt</p>
      <span class="text-[11px] font-semibold text-[#3EAAB8] bg-[#3EAAB8]/10 px-2 py-0.5 rounded-full whitespace-nowrap">
        Phase {{ displayIndex }} von {{ phases.length }}
      </span>
    </div>

    <!-- Timeline -->
    <ol class="relative">
      <li v-for="(phase, i) in phases" :key="phase.key"
          class="relative flex gap-3"
          :class="{ 'pb-4': i < phases.length - 1 }">

        <!-- Connector line -->
        <div v-if="i < phases.length - 1"
             class="absolute left-[11px] top-6 bottom-0 w-px"
             :class="phase.status === 'done' ? 'bg-green-400' : 'bg-gray-200 dark:bg-white/10'"/>

        <!-- Step indicator -->
        <div class="relative z-10 flex-shrink-0 w-6 h-6 rounded-full flex items-center justify-center mt-0.5
                    ring-2 ring-white dark:ring-[#212B3A]"
             :class="{
               'bg-green-500 text-white':   phase.status === 'done',
               'bg-[#3EAAB8] text-white':   phase.status === 'in_progress',
               'bg-gray-100 dark:bg-white/10 text-gray-400 dark:text-gray-500': phase.status === 'pending',
             }">
          <svg v-if="phase.status === 'done'" class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7"/>
          </svg>
          <span v-else-if="phase.status === 'in_progress'"
                class="w-2 h-2 rounded-full bg-white animate-pulse"/>
          <span v-else class="text-[10px] font-bold leading-none">{{ i + 1 }}</span>
        </div>

        <!-- Label + status -->
        <div class="flex-1 min-w-0 mt-0.5">
          <p class="text-sm font-medium leading-tight"
             :class="{
               'text-gray-900 dark:text-white':      phase.status === 'in_progress',
               'text-green-700 dark:text-green-400':  phase.status === 'done',
               'text-gray-400 dark:text-gray-500':    phase.status === 'pending',
             }">
            {{ phase.label }}
          </p>
          <p class="text-[11px] mt-0.5"
             :class="{
               'text-[#3EAAB8] font-medium':       phase.status === 'in_progress',
               'text-green-600 dark:text-green-500': phase.status === 'done',
               'text-gray-400 dark:text-gray-600':  phase.status === 'pending',
             }">
            {{ phase.status === 'in_progress' ? 'Aktuell' : phase.status === 'done' ? 'Erledigt' : 'Ausstehend' }}
          </p>
        </div>
      </li>
    </ol>
  </div>
</template>
