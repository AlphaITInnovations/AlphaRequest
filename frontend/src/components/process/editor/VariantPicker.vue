<script setup lang="ts">
/**
 * Auswahl der Abschnitts-Variante.
 *
 * Jede Variante wird in IHRER eigenen Farbe angezeigt (VARIANT_STYLE.chip –
 * dieselbe Palette wie die Abschnitte im Formular). Der Admin sieht damit direkt, welchen
 * Akzent er wählt, statt nur einen Namen zu lesen.
 */
import type { SectionVariant } from '@/types/process'
import { SECTION_VARIANTS, VARIANT_STYLE } from '@/lib/processSchema'

const props = defineProps<{ modelValue: SectionVariant; disabled?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: SectionVariant] }>()

function pick(v: SectionVariant) {
  if (props.disabled || v === props.modelValue) return
  emit('update:modelValue', v)
}
</script>

<template>
  <div class="flex flex-wrap gap-1.5" role="group" aria-label="Variante">
    <button v-for="v in SECTION_VARIANTS" :key="v" type="button" :disabled="disabled"
            :aria-pressed="v === modelValue"
            :title="`Variante „${VARIANT_STYLE[v].label}“`"
            class="inline-flex items-center gap-1.5 rounded-full pl-1.5 pr-2.5 py-1
                   text-[11px] font-medium transition disabled:cursor-not-allowed
                   disabled:opacity-60"
            :class="[VARIANT_STYLE[v].chip,
                     v === modelValue
                       ? 'ring-2 ring-[#3EAAB8] ring-offset-1 ring-offset-white dark:ring-offset-[#212B3A]'
                       : 'opacity-70 hover:opacity-100']"
            @click="pick(v)">
      <span class="text-sm leading-none">{{ VARIANT_STYLE[v].icon }}</span>
      <span>{{ VARIANT_STYLE[v].label }}</span>
    </button>
  </div>
</template>
