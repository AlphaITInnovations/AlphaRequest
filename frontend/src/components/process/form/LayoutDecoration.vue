<script setup lang="ts">
/**
 * Reine Deko-Elemente eines Layout-Abschnitts: Hinweisbox, Zwischen-Überschrift,
 * Trennlinie, Abstand.
 *
 * Tragen keinen Wert und keine Bedingung – ein Feld-Element wird hier bewusst
 * NICHT gerendert (dafür ist der Formular-Renderer zuständig).
 */
import { computed } from 'vue'
import type { LayoutItem, LayoutNoteItem, LayoutHeadingItem } from '@/types/process'
import { NOTE_STYLE } from '@/lib/processSchema'

const props = defineProps<{ item: LayoutItem }>()

// Eigene computed je Typ: im Template lässt sich die Union sonst nicht typsicher
// eingrenzen (props.item.text existiert nur bei note/heading).
const note = computed<LayoutNoteItem | null>(() =>
  props.item.type === 'note' ? props.item : null)
const heading = computed<LayoutHeadingItem | null>(() =>
  props.item.type === 'heading' ? props.item : null)

const tone = computed(() => (note.value ? NOTE_STYLE[note.value.tone] ?? NOTE_STYLE.neutral : null))
</script>

<template>
  <!-- Hinweisbox: Zeilenumbrüche des Admin-Textes bleiben erhalten -->
  <div v-if="note && tone" class="flex gap-2 rounded-xl border px-4 py-3 text-sm" :class="tone.box">
    <span class="leading-5" aria-hidden="true">{{ tone.icon }}</span>
    <p class="whitespace-pre-line">{{ note.text }}</p>
  </div>

  <p v-else-if="heading"
     class="border-b border-gray-200 dark:border-white/10 pb-1 text-xs font-semibold
            uppercase tracking-wide text-gray-500 dark:text-gray-400">
    {{ heading.text }}
  </p>

  <hr v-else-if="item.type === 'divider'"
      class="border-0 border-t border-gray-200 dark:border-white/10" />

  <div v-else-if="item.type === 'spacer'" class="h-6" aria-hidden="true" />
</template>
