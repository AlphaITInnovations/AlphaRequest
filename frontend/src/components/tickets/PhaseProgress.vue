<script setup lang="ts">
import type { WorkflowPhase } from '@/types/ticket'

defineProps<{ phases: WorkflowPhase[] }>()
</script>

<template>
  <div class="flex items-center gap-1 text-sm">
    <template v-for="(phase, i) in phases" :key="phase.key">

      <div class="flex items-center gap-1.5 px-2.5 py-1 rounded-full font-medium transition-colors"
           :class="{
             'bg-[#3EAAB8]/10 text-[#3EAAB8]':               phase.status === 'in_progress',
             'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400': phase.status === 'done',
             'bg-gray-100 text-gray-400 dark:bg-white/5 dark:text-gray-500':         phase.status === 'pending',
           }">
        <svg v-if="phase.status === 'done'" class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M5 13l4 4L19 7"/>
        </svg>
        <span v-else class="w-3.5 h-3.5 rounded-full border-2 inline-block"
              :class="{
                'border-[#3EAAB8] bg-[#3EAAB8]': phase.status === 'in_progress',
                'border-gray-300 dark:border-gray-600': phase.status === 'pending',
              }"/>
        {{ phase.label }}
      </div>

      <div v-if="i < phases.length - 1"
           class="flex-1 h-px min-w-[1.5rem] bg-gray-200 dark:bg-white/10"/>
    </template>
  </div>
</template>
