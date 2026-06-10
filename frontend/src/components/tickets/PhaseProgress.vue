<script setup lang="ts">
import { computed } from 'vue'
import type { WorkflowPhase } from '@/types/ticket'

const props = defineProps<{ phases: WorkflowPhase[] }>()

const currentIndex = computed(() =>
  props.phases.findIndex(p => p.status === 'in_progress'),
)

// Display "Phase X von Y" — if all done, show last phase number
const displayIndex = computed(() => {
  if (currentIndex.value >= 0) return currentIndex.value + 1
  const doneIdx = [...props.phases].reverse().findIndex(p => p.status === 'done')
  return doneIdx >= 0 ? props.phases.length - doneIdx : 1
})
</script>

<template>
  <div class="bg-white dark:bg-[#212B3A] border border-gray-200/80 dark:border-white/[0.09]
              rounded-2xl shadow-sm p-5">

    <!-- Header: "Phase X von Y" -->
    <div class="flex items-center justify-between mb-4">
      <p class="text-xs font-semibold text-gray-400 uppercase tracking-wider">Bearbeitungsfortschritt</p>
      <span class="text-xs font-semibold text-[#3EAAB8] bg-[#3EAAB8]/10 px-2.5 py-1 rounded-full">
        Phase {{ displayIndex }} von {{ phases.length }}
      </span>
    </div>

    <!-- Timeline -->
    <ol class="relative">
      <li v-for="(phase, i) in phases" :key="phase.key"
          class="relative flex gap-4"
          :class="{ 'pb-5': i < phases.length - 1 }">

        <!-- Connector line (not on last item) -->
        <div v-if="i < phases.length - 1"
             class="absolute left-[13px] top-7 bottom-0 w-px"
             :class="{
               'bg-green-400': phase.status === 'done',
               'bg-gray-200 dark:bg-white/10': phase.status !== 'done',
             }"/>

        <!-- Step indicator -->
        <div class="relative z-10 flex-shrink-0 w-7 h-7 rounded-full flex items-center justify-center mt-0.5 ring-2 ring-white dark:ring-[#212B3A]"
             :class="{
               'bg-green-500 text-white':                  phase.status === 'done',
               'bg-[#3EAAB8] text-white':                  phase.status === 'in_progress',
               'bg-gray-100 dark:bg-white/10 text-gray-400 dark:text-gray-500': phase.status === 'pending',
             }">
          <!-- Done: checkmark -->
          <svg v-if="phase.status === 'done'" class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M5 13l4 4L19 7"/>
          </svg>
          <!-- In progress: pulse dot -->
          <span v-else-if="phase.status === 'in_progress'"
                class="w-2.5 h-2.5 rounded-full bg-white animate-pulse"/>
          <!-- Pending: phase number -->
          <span v-else class="text-[10px] font-bold leading-none">{{ i + 1 }}</span>
        </div>

        <!-- Label + badge -->
        <div class="flex-1 flex items-center justify-between min-w-0 mt-1">
          <p class="text-sm font-medium leading-tight"
             :class="{
               'text-gray-900 dark:text-white':   phase.status === 'in_progress',
               'text-green-700 dark:text-green-400': phase.status === 'done',
               'text-gray-400 dark:text-gray-500': phase.status === 'pending',
             }">
            {{ phase.label }}
          </p>
          <span v-if="phase.status === 'in_progress'"
                class="ml-3 flex-shrink-0 text-[10px] font-semibold uppercase tracking-wider
                       text-[#3EAAB8] bg-[#3EAAB8]/10 px-2 py-0.5 rounded-full">
            Aktuell
          </span>
          <span v-else-if="phase.status === 'done'"
                class="ml-3 flex-shrink-0 text-[10px] font-semibold uppercase tracking-wider
                       text-green-600 dark:text-green-400 bg-green-100 dark:bg-green-900/30 px-2 py-0.5 rounded-full">
            Erledigt
          </span>
        </div>
      </li>
    </ol>
  </div>
</template>
