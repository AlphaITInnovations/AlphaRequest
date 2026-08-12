<script setup lang="ts">
/**
 * Visueller Layout-Editor einer Phase.
 *
 * Links die Abschnitte (so, wie sie später im Ticket aussehen), rechts eine
 * klebende Ablage mit allen Feldern, die noch nicht platziert sind. Ein Klick
 * legt ein Feld im ausgewählten Abschnitt ab.
 *
 * WICHTIG – Zuständigkeit: hier wird ausschließlich DARSTELLUNG bearbeitet
 * (Reihenfolge, Breite, Dekoration). Ob ein Feld sichtbar oder Pflicht ist,
 * steht in PhaseDef.fields und wird hier weder gelesen noch verändert.
 *
 * Zwei Eigenschaften, die man beim Bauen kennen muss – der Editor sagt sie
 * darum auch an:
 *  - Ein LEERES Layout ist erlaubt: die Phase rendert dann wie bisher als
 *    einfaches zweispaltiges Formular.
 *  - Nicht platzierte Felder verschwinden NICHT, sie landen am Ende im
 *    Sammel-Abschnitt „Weitere Angaben".
 */
import { computed, ref } from 'vue'
import type { FieldMode, FieldRef, LayoutSection } from '@/types/process'
import { FIELD_MODE_LABEL } from '@/lib/processSchema'
import {
  addFieldRefs, addSection, clampIndex, moveSection, orphanRefs, patchSection,
  removeSection, sectionFieldRefs, unplacedRefs, layoutFromFields,
} from '@/lib/processLayoutEdit'
import LayoutSectionEditor from './LayoutSectionEditor.vue'

const props = defineProps<{
  modelValue: LayoutSection[]
  fields: FieldRef[]
  fieldLabels?: Record<string, string>
  readonly?: boolean
}>()

const emit = defineEmits<{ 'update:modelValue': [value: LayoutSection[]] }>()

// Defensiv: bei importierten Definitionen können beide Listen fehlen.
const sections = computed<LayoutSection[]>(() => props.modelValue ?? [])
const fieldList = computed<FieldRef[]>(() => props.fields ?? [])

/** Ziel für neue Elemente. Wird beim Löschen/Verschieben mitgeführt. */
const selected = ref(0)
const activeIndex = computed(() => clampIndex(selected.value, sections.value.length))

const unplaced = computed(() => unplacedRefs(sections.value, fieldList.value))
const orphans = computed(() => orphanRefs(sections.value, fieldList.value))
const placedCount = computed(() => fieldList.value.length - unplaced.value.length)

const modeOf = computed(() => {
  const out: Record<string, FieldMode> = {}
  for (const f of fieldList.value) if (f?.ref) out[f.ref] = f.mode
  return out
})

function labelFor(ref: string) {
  return props.fieldLabels?.[ref] || ref
}

/** Immer eine FRISCHE Liste nach außen – nie die Prop-Referenz. */
function commit(next: LayoutSection[]) {
  emit('update:modelValue', [...next])
}

// ── Abschnitte ──────────────────────────────────────────────────────────────

function onAddSection() {
  if (props.readonly) return
  selected.value = sections.value.length // der neue Abschnitt wird das Ziel
  commit(addSection(sections.value))
}

function onSectionUpdate(i: number, sec: LayoutSection) {
  if (props.readonly) return
  commit(patchSection(sections.value, i, sec))
}

function onSectionMove(i: number, delta: number) {
  if (props.readonly) return
  const next = moveSection(sections.value, i, delta)
  if (next === sections.value) return // am Rand
  selected.value = i + delta // Auswahl wandert mit dem Abschnitt
  commit(next)
}

function onSectionRemove(i: number) {
  if (props.readonly) return
  const sec = sections.value[i]
  if (!sec) return
  const n = sectionFieldRefs(sec).length
  if (n > 0) {
    const what = n === 1 ? '1 Feld' : `${n} Felder`
    const ok = confirm(
      `Abschnitt „${sec.title || 'ohne Titel'}“ enthält ${what}.\n\n`
      + 'Die Felder bleiben der Phase erhalten und kehren in die Ablage zurück – '
      + 'im Formular erscheinen sie dann unter „Weitere Angaben“.\n\nAbschnitt löschen?',
    )
    if (!ok) return
  }
  if (selected.value > i) selected.value -= 1
  commit(removeSection(sections.value, i))
}

function onClearLayout() {
  if (props.readonly || !sections.value.length) return
  if (!confirm(
    'Gesamtes Layout entfernen?\n\nDie Phase wird danach wieder als einfaches '
    + 'zweispaltiges Formular dargestellt. Felder und Regeln bleiben unberührt.',
  )) return
  selected.value = 0
  commit([])
}

function onGenerate() {
  if (props.readonly) return
  selected.value = 0
  commit(layoutFromFields(fieldList.value))
}

// ── Ablage → Abschnitt ──────────────────────────────────────────────────────

/** Ohne Abschnitt gibt es kein Ziel – dann legen wir gleich einen an. */
function placeInto(refs: string[]) {
  if (props.readonly || !refs.length) return
  let next = sections.value
  let target = activeIndex.value
  if (target < 0) {
    next = addSection(next)
    target = next.length - 1
    selected.value = target
  }
  commit(addFieldRefs(next, target, refs))
}
</script>

<template>
  <div class="space-y-3">
    <!-- Kopfzeile -->
    <div class="flex flex-wrap items-center gap-2">
      <h3 class="section-title mb-0">Darstellung</h3>
      <span class="rounded-full bg-gray-100 px-2 py-0.5 text-[11px] text-gray-500
                   dark:bg-white/5 dark:text-gray-400">
        {{ sections.length }} {{ sections.length === 1 ? 'Abschnitt' : 'Abschnitte' }}
        · {{ placedCount }}/{{ fieldList.length }} Felder platziert
      </span>
      <div v-if="!readonly" class="ml-auto flex flex-wrap items-center gap-2">
        <button v-if="sections.length" type="button" class="btn-secondary py-1 text-xs"
                @click="onClearLayout">
          Layout entfernen
        </button>
        <button type="button" class="btn-secondary py-1 text-xs" @click="onAddSection">
          + Abschnitt
        </button>
      </div>
    </div>

    <!-- Verwaiste Platzierungen: Feld wurde aus der Phase entfernt -->
    <div v-if="orphans.length"
         class="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs
                text-amber-800 dark:border-amber-500/30 dark:bg-amber-900/20 dark:text-amber-200">
      <span class="font-medium">Platzierung ohne Feld:</span>
      <span class="font-mono">{{ orphans.join(', ') }}</span> –
      diese Felder gehören nicht (mehr) zu dieser Phase und bleiben im Formular leer.
    </div>

    <div class="grid gap-4 lg:grid-cols-[minmax(0,1fr)_16rem]">
      <!-- Links: die Abschnitte -->
      <div class="space-y-3">
        <div v-if="!sections.length"
             class="rounded-2xl border border-dashed border-gray-300 p-5 text-center
                    dark:border-white/15">
          <p class="text-sm text-gray-600 dark:text-gray-300">
            Kein eigenes Layout – die Phase erscheint als einfaches zweispaltiges Formular.
          </p>
          <p class="mt-1 text-xs text-gray-400">
            Mit Abschnitten gruppierst du Felder, legst Breiten fest und fügst Hinweise ein.
          </p>
          <div v-if="!readonly" class="mt-3 flex flex-wrap justify-center gap-2">
            <button v-if="fieldList.length" type="button" class="btn-primary py-1.5 text-xs"
                    @click="onGenerate">
              Layout aus Feldern erzeugen
            </button>
            <button type="button" class="btn-secondary py-1.5 text-xs" @click="onAddSection">
              + Leerer Abschnitt
            </button>
          </div>
        </div>

        <LayoutSectionEditor v-for="(sec, i) in sections" :key="i" :section="sec" :index="i"
                             :total="sections.length" :selected="i === activeIndex"
                             :field-labels="fieldLabels" :missing-refs="orphans"
                             :readonly="readonly"
                             @update:section="onSectionUpdate(i, $event)"
                             @remove="onSectionRemove(i)" @move="onSectionMove(i, $event)"
                             @select="selected = i" />

        <button v-if="sections.length && !readonly" type="button"
                class="w-full rounded-2xl border border-dashed border-gray-300 py-2.5 text-xs
                       font-medium text-gray-500 transition hover:border-[#3EAAB8]/60
                       hover:text-[#0F7683] dark:border-white/15 dark:text-gray-400
                       dark:hover:text-[#5FD3DE]"
                @click="onAddSection">
          + Abschnitt
        </button>
      </div>

      <!-- Rechts: Ablage der nicht platzierten Felder -->
      <aside class="lg:sticky lg:top-4 lg:self-start">
        <div class="rounded-2xl border border-gray-200/80 bg-white p-3 shadow-sm
                    dark:border-white/[0.09] dark:bg-[#212B3A]">
          <div class="mb-2 flex items-center gap-2">
            <h4 class="text-sm font-semibold text-gray-900 dark:text-white">
              Nicht platzierte Felder
            </h4>
            <span class="ml-auto rounded-full bg-gray-100 px-2 py-0.5 text-[11px] font-medium
                         text-gray-500 dark:bg-white/5 dark:text-gray-400">
              {{ unplaced.length }}
            </span>
          </div>

          <p v-if="!unplaced.length" class="rounded-xl bg-green-50 px-3 py-3 text-xs text-green-700
                                            dark:bg-green-900/20 dark:text-green-300">
            ✅ Alle Felder sind platziert.
          </p>

          <template v-else>
            <p class="mb-2 text-[11px] leading-snug text-gray-400">
              Klick legt das Feld im ausgewählten Abschnitt ab.
              Nicht platzierte Felder erscheinen im Formular am Ende unter „Weitere Angaben“.
            </p>
            <div class="max-h-[26rem] space-y-1 overflow-y-auto pr-0.5">
              <!-- Alias absichtlich `fref`: `ref` würde den Vue-Import verdecken. -->
              <button v-for="fref in unplaced" :key="fref" type="button" :disabled="readonly"
                      :title="`„${labelFor(fref)}“ im ausgewählten Abschnitt ablegen`"
                      class="flex w-full items-center gap-2 rounded-xl border border-gray-200
                             px-2 py-1.5 text-left transition hover:border-[#3EAAB8]/60
                             hover:bg-[#3EACB6]/[0.07] disabled:cursor-not-allowed
                             disabled:opacity-60 dark:border-white/10
                             dark:hover:bg-white/[0.04]"
                      @click="placeInto([fref])">
                <span class="min-w-0 flex-1">
                  <span class="block truncate text-xs text-gray-800 dark:text-gray-100">
                    {{ labelFor(fref) }}
                  </span>
                  <span class="block truncate font-mono text-[10px] text-gray-400">{{ fref }}</span>
                </span>
                <span v-if="modeOf[fref] && modeOf[fref] !== 'editable'"
                      class="flex-shrink-0 rounded bg-gray-100 px-1.5 py-0.5 text-[10px]
                             text-gray-500 dark:bg-white/10 dark:text-gray-400">
                  {{ FIELD_MODE_LABEL[modeOf[fref]] }}
                </span>
                <span v-if="!readonly" class="flex-shrink-0 text-xs text-gray-300">+</span>
              </button>
            </div>
            <button v-if="!readonly" type="button" class="btn-secondary mt-2 w-full py-1 text-xs"
                    @click="placeInto(unplaced)">
              Alle übernehmen
            </button>
          </template>
        </div>
      </aside>
    </div>
  </div>
</template>
