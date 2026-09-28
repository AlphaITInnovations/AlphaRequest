<script setup lang="ts">
/**
 * Segmentierte Auswahl der Feldbreite (¼ ⅓ ½ ⅔ Ganz).
 *
 * Bewusst als Knopfleiste und nicht als <select>: die Breite wird beim Bauen
 * eines Formulars laufend verändert, ein Klick ist schneller als zwei.
 * Der Titel nennt zusätzlich die Spalten im 12er-Raster – das erklärt, warum
 * ⅓ + ⅔ eine Zeile füllt, ¼ + ½ aber nicht.
 */
import type { LayoutWidth } from '@/types/process'
import { LAYOUT_WIDTHS, WIDTH_COLS, WIDTH_LABEL } from '@/lib/processSchema'

const props = defineProps<{ modelValue: LayoutWidth; disabled?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: LayoutWidth] }>()

function pick(w: LayoutWidth) {
  if (props.disabled || w === props.modelValue) return
  emit('update:modelValue', w)
}
</script>

<template>
  <div class="inline-flex items-center rounded-lg border border-gray-200 dark:border-white/10
              overflow-hidden bg-white dark:bg-[#263040]"
       role="group" aria-label="Breite">
    <button v-for="w in LAYOUT_WIDTHS" :key="w" type="button" :disabled="disabled"
            :aria-pressed="w === modelValue"
            :title="`Breite ${WIDTH_LABEL[w]} – ${WIDTH_COLS[w]} von 12 Spalten`"
            class="px-2 py-1 text-[11px] leading-none font-medium tabular-nums transition
                   border-r border-gray-200 dark:border-white/10 last:border-r-0
                   disabled:cursor-not-allowed"
            :class="w === modelValue
              ? 'bg-[#3EAAB8] text-white'
              : 'text-gray-500 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-white/5'"
            @click="pick(w)">
      {{ WIDTH_LABEL[w] }}
    </button>
  </div>
</template>
