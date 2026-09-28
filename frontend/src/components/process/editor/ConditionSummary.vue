<script setup lang="ts">
/**
 * Einzeilige Klartext-Anzeige einer Bedingung (Kartenköpfe, Übersichten).
 * Die Logik liegt in lib/conditionSummary.ts, damit sie testbar bleibt.
 */
import { computed } from 'vue'
import type { Condition } from '@/types/process'
import { summarizeCondition } from '@/lib/conditionSummary'

const props = defineProps<{
  condition: Condition | null
  fieldLabels?: Record<string, string>
}>()

const text = computed(() => summarizeCondition(props.condition, props.fieldLabels))
</script>

<template>
  <span class="text-xs text-gray-500 dark:text-gray-400 truncate" :title="text">{{ text }}</span>
</template>
