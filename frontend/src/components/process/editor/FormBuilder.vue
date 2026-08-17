<script setup lang="ts">
/**
 * Der Formular-Baukasten einer Phase – EIN Ort statt drei.
 *
 * Vorher pflegte man dasselbe Feld an drei Stellen (Feld-Katalog, „Felder in
 * dieser Phase", „Darstellung") mit vier verschiedenen „Hinzufügen"-Wegen und
 * fünf Sortier-Mechanismen. Hier gibt es genau EINE Fläche: das Formular, wie
 * es die Laufzeit rendert – echte Abschnitte plus den virtuellen Rest-Abschnitt
 * „Weitere Angaben" für unplatzierte Felder (dieselbe Semantik wie
 * lib/processLayout.resolveLayout, deshalb braucht es keine Migration).
 *
 *   „+ Feld"      legt Katalog-Eintrag, Einbindung und Platzierung in EINEM an
 *   Ziehen        ordnet um, platziert und löst Platzierungen (Drag & Drop)
 *   Aufklappen    zeigt ALLES zu einem Feld an einem Ort: Verhalten in dieser
 *                 Phase (Modus/Pflicht/Bedingungen) + die Feld-Definition
 *   Entfernen     nimmt Einbindung UND Platzierung; wird das Feld nirgends mehr
 *                 genutzt, wird das endgültige Löschen angeboten
 *
 * Die Mutationen liegen in lib/processBuilder.ts (rein, getestet) – diese
 * Komponente ist nur Darstellung.
 */
import { computed, ref } from 'vue'
import type {
  Condition, FieldDef, FieldMode, LayoutItem, LayoutSection, NoteTone,
  PhaseDef, ProcessDefinition, Widget,
} from '@/types/process'
import {
  FIELD_MODES, FIELD_MODE_LABEL, LAYOUT_ITEM_LABEL, NOTE_STYLE, NOTE_TONES,
  VARIANT_STYLE, WIDGETS_TOP, WIDGET_LABEL, blankLayoutItem,
} from '@/lib/processSchema'
import {
  addItem, addSection, moveSection, patchItem, patchSection, removeItem, removeSection,
} from '@/lib/processLayoutEdit'
import {
  REST_SECTION, addExistingField, addNewField, deleteFieldEverywhere, moveBuilderItem,
  patchDef, patchRef, phasesUsing, refOf, removeFieldFromPhase, restRefs,
  type BuilderPos,
} from '@/lib/processBuilder'
import FieldDefEditor from './FieldDefEditor.vue'
import ConditionEditor from './ConditionEditor.vue'
import ConditionSummary from './ConditionSummary.vue'
import WidthPicker from './WidthPicker.vue'

const props = defineProps<{
  definition: ProcessDefinition
  phaseIndex: number
  groups: { id: string; name: string }[]
  fieldKeys: string[]
  fieldLabels?: Record<string, string>
  readonly?: boolean
}>()

const emit = defineEmits<{
  'update:definition': [value: ProcessDefinition]
  renamed: [payload: { from: string; to: string }]
}>()

const phase = computed<PhaseDef>(() => props.definition.phases[props.phaseIndex])
const layout = computed<LayoutSection[]>(() => phase.value?.layout ?? [])
const rest = computed(() => restRefs(phase.value))

const katalog = computed(() => new Map(props.definition.fields.map((f) => [f.key, f])))
/** Katalog-Felder, die in DIESER Phase noch nicht eingebunden sind. */
const wiederverwendbar = computed(() => {
  const drin = new Set(phase.value.fields.map((f) => f.ref))
  return props.definition.fields.filter((f) => !drin.has(f.key))
})

function commit(next: ProcessDefinition) {
  if (next !== props.definition) emit('update:definition', next)
}

function patchPhase(part: Partial<PhaseDef>) {
  commit({
    ...props.definition,
    phases: props.definition.phases.map((p, i) => (
      i === props.phaseIndex ? { ...p, ...part } : p)),
  })
}

function labelFor(key: string) { return props.fieldLabels?.[key] || key }
function widgetFor(key: string) {
  const w = katalog.value.get(key)?.widget
  return w ? (WIDGET_LABEL[w] ?? w) : '?'
}
/** Anker für die Fehlerliste (pe-catalog-<Index im Katalog>). */
function katalogAnker(key: string) {
  const i = props.definition.fields.findIndex((f) => f.key === key)
  return i >= 0 ? `pe-catalog-${i}` : undefined
}

// ── Aufgeklapptes Feld (alles an einem Ort) ───────────────────────────────────

const offenKey = ref<string | null>(null)
function toggle(key: string) { offenKey.value = offenKey.value === key ? null : key }

function onDefUpdate(key: string, next: FieldDef) {
  commit(patchDef(props.definition, key, next))
  // Umbenennung strukturell nachziehen lassen (useProcessEditor.renameFieldKey).
  if (key && next.key && key !== next.key) {
    emit('renamed', { from: key, to: next.key })
    if (offenKey.value === key) offenKey.value = next.key
  }
}

function refPatch(key: string, part: Record<string, unknown>) {
  commit(patchRef(props.definition, props.phaseIndex, key, part))
}

// ── Feld hinzufügen (die EINE Aktion) ─────────────────────────────────────────

/** Abschnitt, dessen „+ Feld"-Menü offen ist (REST_SECTION = Rest-Abschnitt). */
const menueOffen = ref<number | null>(null)

function neuesFeld(section: number, widget: Widget) {
  const { defn, key } = addNewField(props.definition, props.phaseIndex, section, widget)
  commit(defn)
  menueOffen.value = null
  offenKey.value = key            // direkt aufklappen: Label/Details vergeben
}

function vorhandenesFeld(section: number, key: string) {
  commit(addExistingField(props.definition, props.phaseIndex, section, key))
  menueOffen.value = null
}

function dekoHinzu(section: number, type: LayoutItem['type']) {
  patchPhase({ layout: addItem(layout.value, section, blankLayoutItem(type)) })
  menueOffen.value = null
}

// ── Feld entfernen ────────────────────────────────────────────────────────────

function feldEntfernen(key: string) {
  const woNoch = phasesUsing(props.definition, key)
    .filter((name) => name !== (phase.value.label || phase.value.key))
  let next = removeFieldFromPhase(props.definition, props.phaseIndex, key)
  if (!woNoch.length) {
    // Nirgends mehr genutzt: anbieten, den Karteileichen-Katalog zu vermeiden.
    if (confirm(`„${labelFor(key)}" wird danach in keiner Phase mehr genutzt.\n\n`
      + 'Auch endgültig aus dem Prozess löschen? (Abbrechen = nur aus dieser '
      + 'Phase nehmen, die Definition bleibt wiederverwendbar.)')) {
      next = deleteFieldEverywhere(props.definition, key)
    }
  }
  commit(next)
  if (offenKey.value === key) offenKey.value = null
}

// ── Abschnitte ────────────────────────────────────────────────────────────────

function abschnittHinzu() {
  patchPhase({ layout: addSection(layout.value) })
}
function abschnittPatch(i: number, part: Partial<LayoutSection>) {
  patchPhase({ layout: patchSection(layout.value, i, part) })
}
function abschnittWeg(i: number) {
  const felder = layout.value[i]?.items.filter((it) => it.type === 'field').length ?? 0
  if (felder && !confirm(`Abschnitt löschen? Die ${felder} enthaltenen Felder bleiben `
    + 'im Formular und wandern in „Weitere Angaben".')) return
  patchPhase({ layout: removeSection(layout.value, i) })
}
function abschnittSchieben(i: number, delta: number) {
  patchPhase({ layout: moveSection(layout.value, i, delta) })
}

// ── Deko-Elemente inline bearbeiten ───────────────────────────────────────────

function itemPatch(si: number, ii: number, part: Record<string, unknown>) {
  const it = layout.value[si]?.items[ii]
  if (!it) return
  patchPhase({ layout: patchItem(layout.value, si, ii, { ...it, ...part } as LayoutItem) })
}
function itemWeg(si: number, ii: number) {
  patchPhase({ layout: removeItem(layout.value, si, ii) })
}

// ── Drag & Drop ───────────────────────────────────────────────────────────────

const drag = ref<BuilderPos | null>(null)
/** Ziel-Markierung: „<section>:<item>" bzw. „<section>:end". */
const over = ref<string | null>(null)

/**
 * Einfüge-Linie am OBEREN Rand des Ziel-Elements – als Inset-Box-Shadow, damit
 * sie KEINEN Platz einnimmt. Frühere Marker-Divs (h-1 -my-1, nur `v-if=drag`)
 * erschienen erst beim Drag-Start und schoben mit `space-y` jedes Feld nach
 * unten (kumuliert je Feld) – ab dem 4./5. Feld lag das Drop-Ziel dann nicht
 * mehr unter dem Cursor. Ein Box-Shadow verschiebt nichts.
 */
const DROP_LINE = 'box-shadow: inset 0 3px 0 0 #3EAAB8'
const DROP_BELOW = 'box-shadow: inset 0 -3px 0 0 #3EAAB8'

function dropStyle(section: number, item: number | 'end') {
  if (!drag.value) return undefined
  if (over.value === marke(section, item)) return item === 'end' ? DROP_BELOW : DROP_LINE
  return undefined
}
/** Wird gerade GENAU dieses Element gezogen? (halbtransparent darstellen). */
function isDragged(section: number, item: number) {
  return !!drag.value && drag.value.section === section && drag.value.item === item
}

function dragStart(pos: BuilderPos, e: DragEvent) {
  if (props.readonly) { e.preventDefault(); return }
  drag.value = pos
  e.dataTransfer?.setData('text/plain', '')       // Firefox braucht Daten
  if (e.dataTransfer) e.dataTransfer.effectAllowed = 'move'
}
function dragEnd() { drag.value = null; over.value = null }

function dropAt(target: BuilderPos) {
  if (!drag.value) return
  // Drop auf die eigene Position ist kein Verschieben – sonst entstünde eine
  // neue (inhaltsgleiche) Definition und der Editor gälte grundlos als geändert.
  const same = drag.value.section === target.section && drag.value.item === target.item
  if (!same) commit(moveBuilderItem(props.definition, props.phaseIndex, drag.value, target))
  dragEnd()
}

function marke(section: number, item: number | 'end') { return `${section}:${item}` }
</script>

<template>
  <section class="card-section" :id="`pe-phase-${phaseIndex}-form`">
    <div class="flex items-center justify-between gap-3 flex-wrap mb-1">
      <h3 class="section-title mb-0">Formular dieser Phase</h3>
      <button v-if="!readonly" @click="abschnittHinzu" class="btn-secondary text-xs py-1">
        + Abschnitt
      </button>
    </div>
    <p class="text-sm text-gray-500 dark:text-gray-400 mb-4">
      So sieht die Phase aus. Felder hinzufügen, ziehen zum Umsortieren,
      aufklappen für alle Einstellungen – alles an einem Ort.
    </p>

    <!-- Echte Abschnitte -->
    <div v-for="(sec, si) in layout" :key="si" :id="`pe-layout-${si}`"
         class="rounded-2xl border border-gray-200 dark:border-white/10 mb-3 overflow-visible">
      <!-- Abschnitts-Kopf -->
      <div class="flex items-center gap-2 px-3 py-2 border-b border-gray-100 dark:border-white/[0.06]
                  bg-gray-50/60 dark:bg-white/[0.03] rounded-t-2xl">
        <span class="w-1 self-stretch rounded-full" :class="VARIANT_STYLE[sec.variant].bar" />
        <span class="text-base leading-none">{{ VARIANT_STYLE[sec.variant].icon }}</span>
        <input :value="sec.title" :disabled="readonly"
               class="afi !py-1 !px-2 text-sm font-medium flex-1 min-w-[10rem]"
               placeholder="Abschnitts-Titel"
               @input="abschnittPatch(si, { title: ($event.target as HTMLInputElement).value })" />
        <template v-if="!readonly">
          <select :value="sec.variant" class="afi !py-1 !px-2 text-xs w-auto"
                  title="Farbakzent des Abschnitts"
                  @change="abschnittPatch(si, { variant: ($event.target as HTMLSelectElement).value as LayoutSection['variant'] })">
            <option v-for="(v, k) in VARIANT_STYLE" :key="k" :value="k">{{ v.label }}</option>
          </select>
          <button @click="abschnittSchieben(si, -1)" :disabled="si === 0" aria-label="Abschnitt nach oben"
                  class="px-1.5 text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 disabled:opacity-30">▲</button>
          <button @click="abschnittSchieben(si, 1)" :disabled="si === layout.length - 1"
                  aria-label="Abschnitt nach unten"
                  class="px-1.5 text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 disabled:opacity-30">▼</button>
          <button @click="abschnittWeg(si)" aria-label="Abschnitt löschen"
                  class="px-1.5 text-gray-400 hover:text-red-500">✕</button>
        </template>
      </div>

      <!-- Elemente -->
      <div class="p-2.5 space-y-1.5">
        <template v-for="(it, ii) in sec.items"
                  :key="it.type === 'field' ? `f-${it.ref}` : `k-${si}-${ii}`">
          <!-- Feld -->
          <div v-if="it.type === 'field'"
               class="rounded-xl border border-gray-200 dark:border-white/10 bg-white dark:bg-[#212B3A] transition-shadow"
               :style="dropStyle(si, ii)"
               :class="isDragged(si, ii) ? 'opacity-40' : ''"
               :draggable="!readonly && offenKey !== it.ref"
               @dragstart="dragStart({ section: si, item: ii }, $event)" @dragend="dragEnd"
               @dragover.prevent="over = marke(si, ii)"
               @drop.prevent="dropAt({ section: si, item: ii })">
            <div class="flex items-center gap-2 px-2.5 py-2 flex-wrap">
              <span v-if="!readonly" class="cursor-grab text-gray-300 dark:text-gray-600 select-none"
                    title="Ziehen zum Umsortieren">⠿</span>
              <button class="min-w-0 flex items-center gap-2 text-left flex-1"
                      @click="toggle(it.ref)">
                <span class="text-sm font-medium text-gray-900 dark:text-white truncate">
                  {{ labelFor(it.ref) }}
                </span>
                <span class="text-[11px] font-mono text-gray-400 truncate">{{ it.ref }}</span>
                <span class="text-[11px] px-1.5 py-0.5 rounded-full bg-gray-100 dark:bg-white/10
                             text-gray-500 dark:text-gray-400 whitespace-nowrap">
                  {{ widgetFor(it.ref) }}
                </span>
                <span v-if="!katalog.has(it.ref)"
                      class="text-[11px] px-1.5 py-0.5 rounded bg-red-100 text-red-700">
                  Feld fehlt
                </span>
                <span v-if="refOf(phase, it.ref)?.required"
                      class="text-[11px] px-1.5 py-0.5 rounded-full bg-amber-100 text-amber-700
                             dark:bg-amber-900/30 dark:text-amber-300 whitespace-nowrap">Pflicht</span>
              </button>
              <div class="ml-auto flex items-center gap-1.5 shrink-0">
                <WidthPicker :model-value="it.width" :disabled="readonly"
                             @update:model-value="itemPatch(si, ii, { width: $event })" />
                <button @click="toggle(it.ref)" :aria-expanded="offenKey === it.ref"
                        class="px-1.5 text-gray-400 hover:text-[#3EAAB8]"
                        :title="offenKey === it.ref ? 'Zuklappen' : 'Alle Einstellungen'">
                  {{ offenKey === it.ref ? '▾' : '⚙' }}
                </button>
                <button v-if="!readonly" @click="feldEntfernen(it.ref)"
                        class="px-1.5 text-gray-400 hover:text-red-500" title="Aus dieser Phase entfernen">✕</button>
              </div>
            </div>

            <!-- Aufgeklappt: ALLES zu diesem Feld an einem Ort -->
            <div v-if="offenKey === it.ref" :id="katalogAnker(it.ref)"
                 class="border-t border-gray-100 dark:border-white/[0.06] p-3 space-y-4
                        bg-gray-50/60 dark:bg-[#1A2130] rounded-b-xl">
              <div v-if="refOf(phase, it.ref)" class="space-y-2">
                <p class="text-[11px] font-semibold uppercase tracking-wider text-gray-400">
                  In dieser Phase
                </p>
                <div class="flex flex-wrap items-center gap-4">
                  <label class="text-sm text-gray-600 dark:text-gray-300 flex items-center gap-2">
                    Bearbeitbarkeit
                    <select :value="refOf(phase, it.ref)!.mode" :disabled="readonly"
                            class="afi !py-1 text-sm w-auto"
                            @change="refPatch(it.ref, { mode: ($event.target as HTMLSelectElement).value as FieldMode })">
                      <option v-for="m in FIELD_MODES" :key="m" :value="m">{{ FIELD_MODE_LABEL[m] }}</option>
                    </select>
                  </label>
                  <label class="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-200">
                    <input type="checkbox" :checked="refOf(phase, it.ref)!.required" :disabled="readonly"
                           class="h-4 w-4 rounded border-gray-300 dark:border-white/20 text-[#3EAAB8]"
                           @change="refPatch(it.ref, { required: ($event.target as HTMLInputElement).checked })" />
                    Pflichtfeld
                  </label>
                </div>
                <details class="text-sm">
                  <summary class="cursor-pointer text-xs text-gray-500 dark:text-gray-400 select-none">
                    Bedingungen · sichtbar wenn:
                    <ConditionSummary :condition="refOf(phase, it.ref)!.visibleWhen" :field-labels="fieldLabels" />
                    · Pflicht wenn:
                    <ConditionSummary :condition="refOf(phase, it.ref)!.requiredWhen" :field-labels="fieldLabels" />
                  </summary>
                  <div class="mt-2 space-y-3 pl-1">
                    <div>
                      <div class="text-[11px] text-gray-500 mb-1">Nur anzeigen, wenn</div>
                      <ConditionEditor :model-value="refOf(phase, it.ref)!.visibleWhen" :field-keys="fieldKeys"
                                       @update:model-value="refPatch(it.ref, { visibleWhen: $event as Condition | null })" />
                    </div>
                    <div>
                      <div class="text-[11px] text-gray-500 mb-1">Nur Pflicht, wenn</div>
                      <ConditionEditor :model-value="refOf(phase, it.ref)!.requiredWhen" :field-keys="fieldKeys"
                                       @update:model-value="refPatch(it.ref, { requiredWhen: $event as Condition | null })" />
                    </div>
                  </div>
                </details>
              </div>

              <div v-if="katalog.has(it.ref)">
                <p class="text-[11px] font-semibold uppercase tracking-wider text-gray-400 mb-2">
                  Feld-Definition (gilt in allen Phasen)
                </p>
                <FieldDefEditor :model-value="katalog.get(it.ref)!" :groups="groups"
                                :field-keys="fieldKeys"
                                @update:model-value="onDefUpdate(it.ref, $event)"
                                @remove="feldEntfernen(it.ref)" />
              </div>
            </div>
          </div>

          <!-- Überschrift -->
          <div v-else-if="it.type === 'heading'"
               class="flex items-center gap-2 rounded-xl border border-dashed border-gray-200
                      dark:border-white/10 px-2.5 py-1.5 transition-shadow"
               :style="dropStyle(si, ii)" :class="isDragged(si, ii) ? 'opacity-40' : ''"
               :draggable="!readonly" @dragstart="dragStart({ section: si, item: ii }, $event)"
               @dragend="dragEnd" @dragover.prevent="over = marke(si, ii)"
               @drop.prevent="dropAt({ section: si, item: ii })">
            <span v-if="!readonly" class="cursor-grab text-gray-300 select-none">⠿</span>
            <span class="text-[11px] text-gray-400 whitespace-nowrap">Überschrift</span>
            <input :value="it.text" :disabled="readonly" class="afi !py-1 !px-2 text-sm font-semibold flex-1"
                   placeholder="Zwischen-Überschrift…"
                   @input="itemPatch(si, ii, { text: ($event.target as HTMLInputElement).value })" />
            <button v-if="!readonly" @click="itemWeg(si, ii)" class="px-1 text-gray-400 hover:text-red-500">✕</button>
          </div>

          <!-- Hinweisbox -->
          <div v-else-if="it.type === 'note'"
               class="rounded-xl border px-2.5 py-2 space-y-1.5 transition-shadow"
               :class="[NOTE_STYLE[it.tone as NoteTone].box, isDragged(si, ii) ? 'opacity-40' : '']"
               :style="dropStyle(si, ii)"
               :draggable="!readonly" @dragstart="dragStart({ section: si, item: ii }, $event)"
               @dragend="dragEnd" @dragover.prevent="over = marke(si, ii)"
               @drop.prevent="dropAt({ section: si, item: ii })">
            <div class="flex items-center gap-2">
              <span v-if="!readonly" class="cursor-grab opacity-50 select-none">⠿</span>
              <span class="text-[11px] whitespace-nowrap">{{ NOTE_STYLE[it.tone as NoteTone].icon }} Hinweisbox</span>
              <select :value="it.tone" :disabled="readonly" class="afi !py-0.5 !px-1.5 text-xs w-auto ml-auto"
                      @change="itemPatch(si, ii, { tone: ($event.target as HTMLSelectElement).value })">
                <option v-for="t in NOTE_TONES" :key="t" :value="t">{{ NOTE_STYLE[t].label }}</option>
              </select>
              <button v-if="!readonly" @click="itemWeg(si, ii)" class="px-1 opacity-60 hover:opacity-100">✕</button>
            </div>
            <textarea :value="it.text" :disabled="readonly" rows="2" class="afi w-full text-sm"
                      placeholder="Text des Hinweises…"
                      @input="itemPatch(si, ii, { text: ($event.target as HTMLTextAreaElement).value })" />
          </div>

          <!-- Trenner / Abstand -->
          <div v-else class="flex items-center gap-2 px-2.5 py-1 text-[11px] text-gray-400 transition-shadow"
               :style="dropStyle(si, ii)" :class="isDragged(si, ii) ? 'opacity-40' : ''"
               :draggable="!readonly" @dragstart="dragStart({ section: si, item: ii }, $event)"
               @dragend="dragEnd" @dragover.prevent="over = marke(si, ii)"
               @drop.prevent="dropAt({ section: si, item: ii })">
            <span v-if="!readonly" class="cursor-grab text-gray-300 select-none">⠿</span>
            <span class="whitespace-nowrap">{{ LAYOUT_ITEM_LABEL[it.type] }}</span>
            <span class="flex-1 border-t"
                  :class="it.type === 'divider' ? 'border-gray-300 dark:border-white/20' : 'border-transparent'" />
            <button v-if="!readonly" @click="itemWeg(si, ii)" class="px-1 text-gray-400 hover:text-red-500">✕</button>
          </div>
        </template>

        <!-- Ende-Ablagezone + „+ Feld" -->
        <div class="pt-1"
             @dragover.prevent="over = marke(si, 'end')"
             @drop.prevent="dropAt({ section: si, item: sec.items.length })">
          <div v-if="drag" class="h-6 rounded-lg border border-dashed text-center text-[11px]
                                  text-gray-400 leading-6 transition-colors"
               :class="over === marke(si, 'end') ? 'border-[#3EAAB8] bg-[#3EAAB8]/5' : 'border-gray-200 dark:border-white/10'">
            hierhin ziehen
          </div>
          <div v-else-if="!readonly" class="relative">
            <button @click="menueOffen = menueOffen === si ? null : si"
                    class="text-sm text-[#3EAAB8] hover:underline">+ Feld oder Element</button>
            <div v-if="menueOffen === si"
                 class="absolute z-20 mt-1 w-80 rounded-xl border border-gray-200 dark:border-white/10
                        bg-white dark:bg-[#212B3A] shadow-lg p-3 space-y-3">
              <div>
                <p class="text-[11px] font-semibold uppercase tracking-wider text-gray-400 mb-1.5">
                  Neues Feld
                </p>
                <div class="flex flex-wrap gap-1.5">
                  <button v-for="w in WIDGETS_TOP" :key="w" @click="neuesFeld(si, w)"
                          class="text-xs px-2 py-1 rounded-lg border border-gray-200 dark:border-white/10
                                 text-gray-600 dark:text-gray-300 hover:border-[#3EAAB8] hover:text-[#3EAAB8] transition">
                    {{ WIDGET_LABEL[w] }}
                  </button>
                </div>
              </div>
              <div v-if="wiederverwendbar.length">
                <p class="text-[11px] font-semibold uppercase tracking-wider text-gray-400 mb-1.5">
                  Vorhandenes Feld wiederverwenden
                </p>
                <div class="max-h-40 overflow-auto space-y-0.5">
                  <button v-for="f in wiederverwendbar" :key="f.key" @click="vorhandenesFeld(si, f.key)"
                          class="w-full text-left text-sm px-2 py-1 rounded-lg
                                 hover:bg-gray-50 dark:hover:bg-white/5 flex items-center gap-2">
                    <span class="truncate">{{ f.label || f.key }}</span>
                    <span class="text-[11px] font-mono text-gray-400 truncate">{{ f.key }}</span>
                  </button>
                </div>
              </div>
              <div>
                <p class="text-[11px] font-semibold uppercase tracking-wider text-gray-400 mb-1.5">
                  Gestaltung
                </p>
                <div class="flex flex-wrap gap-1.5">
                  <button v-for="t in (['heading', 'note', 'divider', 'spacer'] as const)" :key="t"
                          @click="dekoHinzu(si, t)"
                          class="text-xs px-2 py-1 rounded-lg border border-gray-200 dark:border-white/10
                                 text-gray-600 dark:text-gray-300 hover:border-[#3EAAB8] hover:text-[#3EAAB8] transition">
                    {{ LAYOUT_ITEM_LABEL[t] }}
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Virtueller Rest-Abschnitt: unplatzierte Felder (Laufzeit: „Weitere Angaben") -->
    <div v-if="rest.length || !layout.length"
         class="rounded-2xl border border-dashed border-gray-300 dark:border-white/15 mb-3">
      <div class="px-3 py-2 border-b border-dashed border-gray-200 dark:border-white/10">
        <span class="text-sm font-medium text-gray-600 dark:text-gray-300">
          {{ layout.length ? 'Weitere Angaben' : 'Felder' }}
        </span>
        <span class="text-[11px] text-gray-400 ml-2">
          <template v-if="layout.length">
            nicht platziert – erscheint als eigener Abschnitt am Ende; per Ziehen in
            einen Abschnitt einordnen
          </template>
          <template v-else>
            Standarddarstellung (zweispaltig). Mit „+ Abschnitt" lässt sich das
            Formular frei gestalten.
          </template>
        </span>
      </div>
      <div class="p-2.5 space-y-1.5">
        <template v-for="(key, ri) in rest" :key="key">
          <div class="rounded-xl border border-gray-200 dark:border-white/10 bg-white dark:bg-[#212B3A] transition-shadow"
               :style="dropStyle(REST_SECTION, ri)"
               :class="isDragged(REST_SECTION, ri) ? 'opacity-40' : ''"
               :draggable="!readonly && offenKey !== key"
               @dragstart="dragStart({ section: REST_SECTION, item: ri }, $event)" @dragend="dragEnd"
               @dragover.prevent="over = marke(REST_SECTION, ri)"
               @drop.prevent="dropAt({ section: REST_SECTION, item: ri })">
            <div class="flex items-center gap-2 px-2.5 py-2 flex-wrap">
              <span v-if="!readonly" class="cursor-grab text-gray-300 dark:text-gray-600 select-none"
                    title="Ziehen zum Umsortieren oder Platzieren">⠿</span>
              <button class="min-w-0 flex items-center gap-2 text-left flex-1" @click="toggle(key)">
                <span class="text-sm font-medium text-gray-900 dark:text-white truncate">{{ labelFor(key) }}</span>
                <span class="text-[11px] font-mono text-gray-400 truncate">{{ key }}</span>
                <span class="text-[11px] px-1.5 py-0.5 rounded-full bg-gray-100 dark:bg-white/10
                             text-gray-500 dark:text-gray-400 whitespace-nowrap">{{ widgetFor(key) }}</span>
                <span v-if="refOf(phase, key)?.required"
                      class="text-[11px] px-1.5 py-0.5 rounded-full bg-amber-100 text-amber-700
                             dark:bg-amber-900/30 dark:text-amber-300 whitespace-nowrap">Pflicht</span>
              </button>
              <div class="ml-auto flex items-center gap-1.5 shrink-0">
                <button @click="toggle(key)" class="px-1.5 text-gray-400 hover:text-[#3EAAB8]"
                        :title="offenKey === key ? 'Zuklappen' : 'Alle Einstellungen'">
                  {{ offenKey === key ? '▾' : '⚙' }}
                </button>
                <button v-if="!readonly" @click="feldEntfernen(key)"
                        class="px-1.5 text-gray-400 hover:text-red-500" title="Aus dieser Phase entfernen">✕</button>
              </div>
            </div>
            <div v-if="offenKey === key" :id="katalogAnker(key)"
                 class="border-t border-gray-100 dark:border-white/[0.06] p-3 space-y-4
                        bg-gray-50/60 dark:bg-[#1A2130] rounded-b-xl">
              <div v-if="refOf(phase, key)" class="space-y-2">
                <p class="text-[11px] font-semibold uppercase tracking-wider text-gray-400">In dieser Phase</p>
                <div class="flex flex-wrap items-center gap-4">
                  <label class="text-sm text-gray-600 dark:text-gray-300 flex items-center gap-2">
                    Bearbeitbarkeit
                    <select :value="refOf(phase, key)!.mode" :disabled="readonly"
                            class="afi !py-1 text-sm w-auto"
                            @change="refPatch(key, { mode: ($event.target as HTMLSelectElement).value as FieldMode })">
                      <option v-for="m in FIELD_MODES" :key="m" :value="m">{{ FIELD_MODE_LABEL[m] }}</option>
                    </select>
                  </label>
                  <label class="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-200">
                    <input type="checkbox" :checked="refOf(phase, key)!.required" :disabled="readonly"
                           class="h-4 w-4 rounded border-gray-300 dark:border-white/20 text-[#3EAAB8]"
                           @change="refPatch(key, { required: ($event.target as HTMLInputElement).checked })" />
                    Pflichtfeld
                  </label>
                </div>
                <details class="text-sm">
                  <summary class="cursor-pointer text-xs text-gray-500 dark:text-gray-400 select-none">
                    Bedingungen · sichtbar wenn:
                    <ConditionSummary :condition="refOf(phase, key)!.visibleWhen" :field-labels="fieldLabels" />
                    · Pflicht wenn:
                    <ConditionSummary :condition="refOf(phase, key)!.requiredWhen" :field-labels="fieldLabels" />
                  </summary>
                  <div class="mt-2 space-y-3 pl-1">
                    <div>
                      <div class="text-[11px] text-gray-500 mb-1">Nur anzeigen, wenn</div>
                      <ConditionEditor :model-value="refOf(phase, key)!.visibleWhen" :field-keys="fieldKeys"
                                       @update:model-value="refPatch(key, { visibleWhen: $event as Condition | null })" />
                    </div>
                    <div>
                      <div class="text-[11px] text-gray-500 mb-1">Nur Pflicht, wenn</div>
                      <ConditionEditor :model-value="refOf(phase, key)!.requiredWhen" :field-keys="fieldKeys"
                                       @update:model-value="refPatch(key, { requiredWhen: $event as Condition | null })" />
                    </div>
                  </div>
                </details>
              </div>
              <div v-if="katalog.has(key)">
                <p class="text-[11px] font-semibold uppercase tracking-wider text-gray-400 mb-2">
                  Feld-Definition (gilt in allen Phasen)
                </p>
                <FieldDefEditor :model-value="katalog.get(key)!" :groups="groups" :field-keys="fieldKeys"
                                @update:model-value="onDefUpdate(key, $event)"
                                @remove="feldEntfernen(key)" />
              </div>
            </div>
          </div>
        </template>

        <div class="pt-1"
             @dragover.prevent="over = marke(REST_SECTION, 'end')"
             @drop.prevent="dropAt({ section: REST_SECTION, item: rest.length })">
          <div v-if="drag" class="h-6 rounded-lg border border-dashed text-center text-[11px]
                                  text-gray-400 leading-6 transition-colors"
               :class="over === marke(REST_SECTION, 'end') ? 'border-[#3EAAB8] bg-[#3EAAB8]/5' : 'border-gray-200 dark:border-white/10'">
            Platzierung lösen (zurück zu „Weitere Angaben")
          </div>
          <div v-else-if="!readonly" class="relative">
            <button @click="menueOffen = menueOffen === REST_SECTION ? null : REST_SECTION"
                    class="text-sm text-[#3EAAB8] hover:underline">+ Feld</button>
            <div v-if="menueOffen === REST_SECTION"
                 class="absolute z-20 mt-1 w-80 rounded-xl border border-gray-200 dark:border-white/10
                        bg-white dark:bg-[#212B3A] shadow-lg p-3 space-y-3">
              <div>
                <p class="text-[11px] font-semibold uppercase tracking-wider text-gray-400 mb-1.5">Neues Feld</p>
                <div class="flex flex-wrap gap-1.5">
                  <button v-for="w in WIDGETS_TOP" :key="w" @click="neuesFeld(REST_SECTION, w)"
                          class="text-xs px-2 py-1 rounded-lg border border-gray-200 dark:border-white/10
                                 text-gray-600 dark:text-gray-300 hover:border-[#3EAAB8] hover:text-[#3EAAB8] transition">
                    {{ WIDGET_LABEL[w] }}
                  </button>
                </div>
              </div>
              <div v-if="wiederverwendbar.length">
                <p class="text-[11px] font-semibold uppercase tracking-wider text-gray-400 mb-1.5">
                  Vorhandenes Feld wiederverwenden
                </p>
                <div class="max-h-40 overflow-auto space-y-0.5">
                  <button v-for="f in wiederverwendbar" :key="f.key" @click="vorhandenesFeld(REST_SECTION, f.key)"
                          class="w-full text-left text-sm px-2 py-1 rounded-lg
                                 hover:bg-gray-50 dark:hover:bg-white/5 flex items-center gap-2">
                    <span class="truncate">{{ f.label || f.key }}</span>
                    <span class="text-[11px] font-mono text-gray-400 truncate">{{ f.key }}</span>
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <p v-if="!layout.length && !rest.length && !phase.fields.length"
       class="text-sm text-gray-400 italic">
      Noch keine Felder – in dieser Phase wird (noch) nichts ausgefüllt.
    </p>
  </section>
</template>
