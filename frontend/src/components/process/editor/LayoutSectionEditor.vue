<script setup lang="ts">
/**
 * Ein Abschnitt („Karte") im Layout-Editor.
 *
 * Die Karte sieht absichtlich so aus wie das Ergebnis im Ticket
 * (components/tickets/TicketSection.vue): Akzentleiste oben, Symbol-Chip,
 * Titel, optionales Badge. Wer hier baut, sieht damit direkt, was später
 * herauskommt – die kleine Raster-Vorschau am Fuß der Karte zeigt zusätzlich
 * die gewählten Breiten.
 */
import { computed } from 'vue'
import type {
  LayoutItem, LayoutItemType, LayoutSection, LayoutWidth,
} from '@/types/process'
import {
  LAYOUT_ITEM_LABEL, NOTE_STYLE, VARIANT_STYLE, blankLayoutItem,
} from '@/lib/processSchema'
import { moveItem, sectionFieldRefs } from '@/lib/processLayoutEdit'
import LayoutItemRow from './LayoutItemRow.vue'
import VariantPicker from './VariantPicker.vue'

const props = defineProps<{
  section: LayoutSection
  index: number
  total: number
  selected: boolean
  fieldLabels?: Record<string, string>
  /** Refs, die es in PhaseDef.fields nicht (mehr) gibt – nur zur Warnung. */
  missingRefs?: string[]
  readonly?: boolean
}>()

const emit = defineEmits<{
  'update:section': [value: LayoutSection]
  remove: []
  move: [delta: number]
  select: []
}>()

// Defensiv: importierte Definitionen dürfen `items` weglassen.
const items = computed<LayoutItem[]>(() => props.section.items ?? [])
const style = computed(() => VARIANT_STYLE[props.section.variant] ?? VARIANT_STYLE.default)
const fieldCount = computed(() => sectionFieldRefs(props.section).length)
const decorCount = computed(() => items.value.length - fieldCount.value)

/**
 * Tailwind liest Klassennamen STATISCH aus dem Quelltext – ein dynamisch
 * gebauter Name wie `md:col-span-${n}` wird nie erzeugt. Darum die vollständige
 * Zuordnung als Nachschlagetabelle. Mobil ist alles ganzbreit (mobile-first),
 * ab `md` gilt die konfigurierte Breite – genau wie im Renderer.
 */
const SPAN_CLASS: Record<LayoutWidth, string> = {
  quarter: 'col-span-12 md:col-span-3',
  third: 'col-span-12 md:col-span-4',
  half: 'col-span-12 md:col-span-6',
  twothirds: 'col-span-12 md:col-span-8',
  full: 'col-span-12',
}

const DESIGN_ITEMS: readonly LayoutItemType[] = ['note', 'heading', 'divider', 'spacer']

function patch(part: Partial<LayoutSection>) {
  emit('update:section', { ...props.section, ...part })
}
function patchItems(next: LayoutItem[]) {
  patch({ items: next })
}

function updateItem(i: number, item: LayoutItem) {
  patchItems(items.value.map((it, j) => (j === i ? item : it)))
}
function removeItem(i: number) {
  patchItems(items.value.filter((_, j) => j !== i))
}
function moveItemAt(i: number, delta: number) {
  const next = moveItem(items.value, i, delta)
  if (next === items.value) return // am Rand: nichts zu tun, kein Emit
  patchItems(next)
}
function addDesignItem(type: LayoutItemType) {
  patchItems([...items.value, blankLayoutItem(type)])
}

function labelFor(ref: string) {
  return props.fieldLabels?.[ref] || ref
}
function isMissing(ref: string) {
  return (props.missingRefs ?? []).includes(ref)
}

/** Vorschau-Kästchen: Breite + Beschriftung + Farbe je Elementart. */
function previewLabel(it: LayoutItem): string {
  if (it.type === 'field') return labelFor(it.ref)
  if (it.type === 'note') return it.text.trim() || NOTE_STYLE[it.tone].label
  if (it.type === 'heading') return it.text.trim() || LAYOUT_ITEM_LABEL.heading
  return LAYOUT_ITEM_LABEL[it.type]
}
function previewSpan(it: LayoutItem): string {
  return it.type === 'field' || it.type === 'note' ? SPAN_CLASS[it.width] : 'col-span-12'
}
</script>

<template>
  <!-- Anker für die Sprungmarken der Issue-Liste; scroll-mt hält die Karte
       unter der klebenden Kopfzeile sichtbar. -->
  <section :id="`pe-layout-${index}`"
           class="relative scroll-mt-24 rounded-2xl border bg-white dark:bg-[#212B3A]
                  shadow-sm transition"
           :class="selected
             ? 'border-[#3EAAB8]/60 ring-2 ring-[#3EAAB8]/30'
             : 'border-gray-200/80 dark:border-white/[0.09] hover:border-gray-300 dark:hover:border-white/20'"
           @click="emit('select')">
    <span class="absolute inset-x-0 top-0 h-1 rounded-t-2xl" :class="style.bar" />

    <div class="space-y-3 p-4 pt-5">
      <!-- Kopf: Symbol, Titel, Badge, Werkzeuge -->
      <div class="flex items-start gap-3">
        <span class="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-xl
                     text-base leading-none" :class="style.chip">{{ style.icon }}</span>

        <div class="min-w-0 flex-1 space-y-1">
          <input :value="section.title" :disabled="readonly" placeholder="Abschnitts-Titel…"
                 class="w-full rounded-lg border border-transparent bg-transparent px-1 py-0.5
                        text-base font-semibold text-gray-900 dark:text-white
                        hover:border-gray-200 dark:hover:border-white/10
                        focus:border-gray-200 dark:focus:border-white/10
                        focus:outline-none focus:ring-2 focus:ring-[#3EAAB8]/30
                        disabled:opacity-70"
                 @input="patch({ title: ($event.target as HTMLInputElement).value })" />
          <div class="flex items-center gap-2 px-1 text-[11px] text-gray-400">
            <span>{{ fieldCount }} {{ fieldCount === 1 ? 'Feld' : 'Felder' }}</span>
            <span v-if="decorCount > 0">· {{ decorCount }} Design-Element{{ decorCount === 1 ? '' : 'e' }}</span>
            <span v-if="selected"
                  class="rounded-full bg-[#3EAAB8]/15 px-2 py-0.5 font-medium text-[#0F7683] dark:text-[#5FD3DE]">
              Ziel für neue Felder
            </span>
          </div>
        </div>

        <div class="flex flex-shrink-0 items-center gap-2">
          <input :value="section.badge ?? ''" :disabled="readonly" placeholder="Badge…"
                 class="lse-input w-24 text-right"
                 @input="patch({ badge: ($event.target as HTMLInputElement).value || null })" />
          <!-- .stop: sonst würde der Klick zusätzlich als „Abschnitt auswählen"
               nach oben blubbern und die mitwandernde Auswahl überschreiben. -->
          <div v-if="!readonly" class="flex items-center gap-0.5">
            <button type="button" :disabled="index === 0" aria-label="Abschnitt nach oben"
                    title="Nach oben" class="lse-btn" @click.stop="emit('move', -1)">▲</button>
            <button type="button" :disabled="index === total - 1" aria-label="Abschnitt nach unten"
                    title="Nach unten" class="lse-btn" @click.stop="emit('move', 1)">▼</button>
            <button type="button" aria-label="Abschnitt entfernen" title="Abschnitt entfernen"
                    class="lse-btn hover:text-red-500" @click.stop="emit('remove')">✕</button>
          </div>
        </div>
      </div>

      <!-- Beschreibung -->
      <input :value="section.description ?? ''" :disabled="readonly"
             placeholder="Beschreibung des Abschnitts (optional, erscheint unter dem Titel)"
             class="lse-input w-full"
             @input="patch({ description: ($event.target as HTMLInputElement).value || null })" />

      <!-- Variante + Startzustand -->
      <div class="flex flex-wrap items-center justify-between gap-2">
        <VariantPicker :model-value="section.variant" :disabled="readonly"
                       @update:model-value="patch({ variant: $event })" />
        <label class="flex flex-shrink-0 items-center gap-2 text-xs text-gray-600 dark:text-gray-300">
          <input type="checkbox" :checked="section.collapsed" :disabled="readonly"
                 class="h-4 w-4 rounded border-gray-300 text-[#3EAAB8] dark:border-white/20"
                 @change="patch({ collapsed: ($event.target as HTMLInputElement).checked })" />
          startet eingeklappt
        </label>
      </div>

      <!-- Elemente -->
      <div class="space-y-1.5">
        <p v-if="!items.length" class="rounded-xl border border-dashed border-gray-200
                                       px-3 py-4 text-center text-xs text-gray-400
                                       dark:border-white/10">
          Noch leer – Feld aus der Ablage anklicken oder ein Design-Element einfügen.
        </p>
        <LayoutItemRow v-for="(it, i) in items" :key="i" :item="it"
                       :label="it.type === 'field' ? labelFor(it.ref) : undefined"
                       :missing="it.type === 'field' && isMissing(it.ref)"
                       :first="i === 0" :last="i === items.length - 1" :readonly="readonly"
                       @update:item="updateItem(i, $event)" @remove="removeItem(i)"
                       @move="moveItemAt(i, $event)" />
      </div>

      <!-- Werkzeugleiste für Design-Elemente -->
      <div v-if="!readonly" class="flex flex-wrap items-center gap-1.5">
        <button v-for="t in DESIGN_ITEMS" :key="t" type="button" class="lse-add"
                @click="addDesignItem(t)">
          + {{ LAYOUT_ITEM_LABEL[t] }}
        </button>
      </div>

      <!-- Live-Vorschau der Breiten im 12er-Raster -->
      <div v-if="items.length" class="rounded-xl border border-gray-200/80 bg-gray-50 p-2
                                      dark:border-white/[0.09] dark:bg-white/[0.03]">
        <div class="mb-1.5 px-0.5 text-[10px] font-medium uppercase tracking-wide text-gray-400">
          Vorschau der Anordnung
        </div>
        <div class="grid grid-cols-12 gap-1">
          <template v-for="(it, i) in items" :key="i">
            <div v-if="it.type === 'divider'" class="col-span-12 py-1.5">
              <div class="border-t border-gray-300 dark:border-white/15" />
            </div>
            <div v-else-if="it.type === 'spacer'"
                 class="col-span-12 h-4 rounded border border-dashed border-gray-300
                        dark:border-white/15" />
            <div v-else-if="it.type === 'heading'"
                 class="col-span-12 truncate pt-1 text-[11px] font-semibold
                        text-gray-600 dark:text-gray-300">
              {{ previewLabel(it) }}
            </div>
            <div v-else-if="it.type === 'note'"
                 class="truncate rounded border px-1.5 py-1 text-[10px] leading-tight"
                 :class="[previewSpan(it), NOTE_STYLE[it.tone].box]">
              {{ NOTE_STYLE[it.tone].icon }} {{ previewLabel(it) }}
            </div>
            <div v-else
                 class="truncate rounded bg-[#3EACB6]/15 px-1.5 py-1 text-[10px] leading-tight
                        text-[#0F7683] dark:text-[#5FD3DE]"
                 :class="previewSpan(it)" :title="previewLabel(it)">
              {{ previewLabel(it) }}
            </div>
          </template>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
@reference "../../../style.css";
.lse-input {
  @apply rounded-lg border border-gray-200 dark:border-white/10
         bg-white dark:bg-[#263040] text-gray-900 dark:text-gray-100
         px-2 py-1 text-xs focus:outline-none focus:ring-2 focus:ring-[#3EAAB8]/30
         transition disabled:opacity-60;
}
.lse-btn {
  @apply px-1 text-xs leading-none text-gray-400 transition
         hover:text-gray-700 dark:hover:text-gray-200
         disabled:cursor-not-allowed disabled:opacity-25;
}
.lse-add {
  @apply rounded-lg border border-dashed border-gray-300 dark:border-white/15
         px-2 py-1 text-[11px] font-medium text-gray-500 dark:text-gray-400
         hover:border-[#3EAAB8]/60 hover:text-[#0F7683] dark:hover:text-[#5FD3DE] transition;
}
</style>
