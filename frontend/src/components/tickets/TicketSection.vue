<script setup lang="ts">
import { computed } from 'vue'

export type SectionVariant = 'base' | 'hr' | 'it' | 'fuhrpark' | 'marketing' | 'travel' | 'default'

const props = withDefaults(defineProps<{
  title: string
  variant?: SectionVariant
  badge?: string
}>(), { variant: 'default' })

// Akzentfarbe + Icon je Zielgruppe. Kartenfläche bleibt neutral – Farbe steckt nur
// im Icon-Chip, dem optionalen Badge und der schmalen Kopfleiste (dezent, corporate).
const VARIANTS: Record<SectionVariant, { icon: string; chip: string; badge: string; bar: string }> = {
  base:      { icon: '📋', chip: 'bg-[#3EACB6]/15 text-[#0F7683] dark:text-[#5FD3DE]', badge: 'bg-[#3EACB6]/15 text-[#0F7683] dark:text-[#5FD3DE]', bar: 'bg-[#3EACB6]' },
  hr:        { icon: '👤', chip: 'bg-blue-500/15 text-blue-700 dark:text-blue-300',     badge: 'bg-blue-500/15 text-blue-700 dark:text-blue-300',     bar: 'bg-blue-500' },
  it:        { icon: '💻', chip: 'bg-purple-500/15 text-purple-700 dark:text-purple-300', badge: 'bg-purple-500/15 text-purple-700 dark:text-purple-300', bar: 'bg-purple-500' },
  fuhrpark:  { icon: '🚗', chip: 'bg-amber-500/15 text-amber-700 dark:text-amber-300',   badge: 'bg-amber-500/15 text-amber-700 dark:text-amber-300',   bar: 'bg-amber-500' },
  marketing: { icon: '📣', chip: 'bg-pink-500/15 text-pink-700 dark:text-pink-300',       badge: 'bg-pink-500/15 text-pink-700 dark:text-pink-300',       bar: 'bg-pink-500' },
  travel:    { icon: '✈️', chip: 'bg-teal-500/15 text-teal-700 dark:text-teal-300',       badge: 'bg-teal-500/15 text-teal-700 dark:text-teal-300',       bar: 'bg-teal-500' },
  default:   { icon: '🗂', chip: 'bg-slate-500/15 text-slate-600 dark:text-slate-300',   badge: 'bg-slate-500/15 text-slate-600 dark:text-slate-300',   bar: 'bg-slate-400' },
}

const v = computed(() => VARIANTS[props.variant])
</script>

<template>
  <section class="relative overflow-hidden rounded-2xl border border-gray-200/80 dark:border-white/[0.09]
                  bg-white dark:bg-[#212B3A] shadow-sm">
    <span class="absolute inset-x-0 top-0 h-1" :class="v.bar" />
    <div class="p-6 space-y-4">
      <div class="flex items-center gap-3">
        <span class="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-xl text-base leading-none"
              :class="v.chip">{{ v.icon }}</span>
        <h2 class="text-base font-semibold text-gray-900 dark:text-white">{{ title }}</h2>
        <span v-if="badge"
              class="ml-auto text-[11px] font-medium px-2 py-0.5 rounded-full whitespace-nowrap"
              :class="v.badge">{{ badge }}</span>
      </div>
      <div class="space-y-4">
        <slot />
      </div>
    </div>
  </section>
</template>
