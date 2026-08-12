<script setup lang="ts">
/**
 * Eine Zeile der Element-Liste eines Abschnitts.
 *
 * Absichtlich sehr ruhig gehalten: diese Liste wird bei großen Formularen lang,
 * darum eine Zeile pro Element (Symbol · Name · Breite · Werkzeuge) und die
 * Text-Eingaben von Hinweisbox/Überschrift nur als zweite, eingerückte Zeile.
 */
import { computed } from 'vue'
import type { LayoutItem, LayoutItemType, LayoutWidth, NoteTone } from '@/types/process'
import { LAYOUT_ITEM_LABEL, NOTE_STYLE, NOTE_TONES } from '@/lib/processSchema'
import WidthPicker from './WidthPicker.vue'

const props = defineProps<{
  item: LayoutItem
  label?: string
  readonly?: boolean
  /** Steuert nur die Pfeil-Knöpfe; ohne Angabe sind beide aktiv. */
  first?: boolean
  last?: boolean
  /** Feld-Ref existiert nicht (mehr) in PhaseDef.fields → Platzierung bleibt leer. */
  missing?: boolean
}>()

const emit = defineEmits<{
  'update:item': [value: LayoutItem]
  remove: []
  move: [delta: number]
}>()

// Aufgeteilte Sichten auf die Union – so bleibt die Vorlage typsicher, ohne
// überall `as` zu streuen.
const fieldItem = computed(() => (props.item.type === 'field' ? props.item : null))
const noteItem = computed(() => (props.item.type === 'note' ? props.item : null))
const headingItem = computed(() => (props.item.type === 'heading' ? props.item : null))
const sizable = computed(() => props.item.type === 'field' || props.item.type === 'note')

/** Symbol-Chip: Hinweisboxen tragen die Farbe ihres Tonfalls. */
const GLYPH: Record<LayoutItemType, string> = {
  field: '▤', note: 'ℹ', heading: 'H', divider: '—', spacer: '⇕',
}
const CHIP: Record<LayoutItemType, string> = {
  field: 'bg-[#3EACB6]/15 text-[#0F7683] dark:text-[#5FD3DE]',
  note: '',
  heading: 'bg-slate-500/15 text-slate-600 dark:text-slate-300',
  divider: 'bg-gray-500/10 text-gray-500 dark:text-gray-400',
  spacer: 'bg-gray-500/10 text-gray-400 dark:text-gray-500',
}

const glyph = computed(() => (noteItem.value ? NOTE_STYLE[noteItem.value.tone].icon : GLYPH[props.item.type]))
const chipClass = computed(() => (
  noteItem.value ? `border ${NOTE_STYLE[noteItem.value.tone].box}` : CHIP[props.item.type]
))

/** Anzeigename der Zeile – pro Elementart etwas anderes. */
const name = computed(() => {
  if (fieldItem.value) return props.label || fieldItem.value.ref
  if (noteItem.value) return noteItem.value.text.trim()
  if (headingItem.value) return headingItem.value.text.trim()
  return LAYOUT_ITEM_LABEL[props.item.type]
})

const namePlaceholder = computed(() => (
  noteItem.value ? '(kein Hinweistext)' : '(keine Überschrift)'
))

const width = computed<LayoutWidth>(() => (
  fieldItem.value?.width ?? noteItem.value?.width ?? 'full'
))

function setWidth(w: LayoutWidth) {
  const it = props.item
  if (it.type !== 'field' && it.type !== 'note') return
  emit('update:item', { ...it, width: w })
}
function setText(text: string) {
  const it = props.item
  if (it.type !== 'note' && it.type !== 'heading') return
  emit('update:item', { ...it, text })
}
function setTone(tone: NoteTone) {
  const it = props.item
  if (it.type !== 'note') return
  emit('update:item', { ...it, tone })
}
</script>

<template>
  <div class="rounded-xl border border-gray-200 dark:border-white/10
              bg-white dark:bg-[#1E2735] px-2 py-1.5">
    <div class="flex items-center gap-2">
      <span class="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-lg
                   text-[11px] leading-none" :class="chipClass" :title="LAYOUT_ITEM_LABEL[item.type]">
        {{ glyph }}
      </span>

      <div class="flex min-w-0 flex-1 items-center gap-2">
        <span class="truncate text-sm"
              :class="name
                ? 'text-gray-800 dark:text-gray-100'
                : 'italic text-gray-400 dark:text-gray-500'">
          {{ name || namePlaceholder }}
        </span>
        <code v-if="fieldItem" class="flex-shrink-0 font-mono text-[11px] text-gray-400">
          {{ fieldItem.ref }}
        </code>
        <span v-if="missing"
              class="flex-shrink-0 rounded bg-red-100 px-1.5 py-0.5 text-[10px] font-medium
                     text-red-700 dark:bg-red-500/20 dark:text-red-300">
          nicht in dieser Phase
        </span>
      </div>

      <WidthPicker v-if="sizable" :model-value="width" :disabled="readonly"
                   @update:model-value="setWidth" />

      <div v-if="!readonly" class="flex flex-shrink-0 items-center gap-0.5">
        <button type="button" :disabled="first" aria-label="Nach oben" title="Nach oben"
                class="lir-btn" @click="emit('move', -1)">▲</button>
        <button type="button" :disabled="last" aria-label="Nach unten" title="Nach unten"
                class="lir-btn" @click="emit('move', 1)">▼</button>
        <button type="button" aria-label="Element entfernen" title="Entfernen"
                class="lir-btn hover:text-red-500" @click="emit('remove')">✕</button>
      </div>
    </div>

    <!-- Zweite Zeile nur dort, wo es etwas zu tippen gibt. -->
    <div v-if="noteItem || headingItem" class="mt-1.5 flex items-center gap-2 pl-8">
      <input :value="noteItem ? noteItem.text : headingItem?.text ?? ''" :disabled="readonly"
             :placeholder="noteItem ? 'Hinweistext für die Bearbeitenden…' : 'Überschrift…'"
             class="lir-input min-w-0 flex-1"
             @input="setText(($event.target as HTMLInputElement).value)" />
      <select v-if="noteItem" :value="noteItem.tone" :disabled="readonly"
              class="lir-input flex-shrink-0" aria-label="Tonfall"
              @change="setTone(($event.target as HTMLSelectElement).value as NoteTone)">
        <option v-for="t in NOTE_TONES" :key="t" :value="t">
          {{ NOTE_STYLE[t].icon }} {{ NOTE_STYLE[t].label }}
        </option>
      </select>
    </div>
  </div>
</template>

<style scoped>
@reference "../../../style.css";
.lir-btn {
  @apply px-1 text-xs leading-none text-gray-400 transition
         hover:text-gray-700 dark:hover:text-gray-200
         disabled:cursor-not-allowed disabled:opacity-25;
}
.lir-input {
  @apply rounded-lg border border-gray-200 dark:border-white/10
         bg-white dark:bg-[#263040] text-gray-900 dark:text-gray-100
         px-2 py-1 text-xs focus:outline-none focus:ring-2 focus:ring-[#3EAAB8]/30
         transition disabled:opacity-60;
}
</style>
