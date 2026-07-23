<script setup lang="ts">
withDefaults(defineProps<{
  label: string
  value?: string | number | null
  wide?: boolean
  mono?: boolean
  pre?: boolean
}>(), { value: null, wide: false, mono: false, pre: false })

function display(v: unknown): string {
  if (v === null || v === undefined || v === '') return '—'
  return String(v)
}
</script>

<template>
  <div :class="wide ? 'md:col-span-2' : ''">
    <p class="ro-label">{{ label }}</p>
    <p class="ro-value" :class="[mono ? 'font-mono' : '', pre ? 'whitespace-pre-wrap' : '']">
      <slot>{{ display(value) }}</slot>
    </p>
  </div>
</template>

<style scoped>
@reference "../../style.css";
.ro-label { @apply text-xs font-semibold text-gray-400 uppercase tracking-wider mb-0.5; }
.ro-value { @apply text-sm text-gray-900 dark:text-white; }
</style>
