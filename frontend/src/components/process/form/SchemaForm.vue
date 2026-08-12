<script setup lang="ts">
/**
 * Formular EINER Phase, vollständig aus der Prozess-Definition erzeugt.
 *
 * Was angezeigt, was bearbeitet und was verlangt wird, entscheidet
 * renderFields() – der Spiegel der Server-Laufzeit. Der Server bleibt
 * autoritativ; hier geht es nur um die Darstellung.
 *
 * WO die Felder stehen, entscheidet das optionale `phase.layout` über
 * resolveLayout() (lib/processLayout.ts). Ohne Layout bleibt es beim bisherigen
 * Bild: ein Abschnitt, alle sichtbaren Felder zweispaltig.
 */
import { computed } from 'vue'
import type {
  FieldDef, LayoutItem, LayoutSection as LayoutSectionDef, OptionSources, PhaseDef,
  ProcessDefinition,
} from '@/types/process'
import { colSpanClass, resolveLayout } from '@/lib/processLayout'
import type { RenderedField, SimFieldError, SimViewer } from '@/lib/processSim'
import LayoutSection from './LayoutSection.vue'
import LayoutDecoration from './LayoutDecoration.vue'
import SchemaWidget from './SchemaWidget.vue'
import CollectionWidget from './CollectionWidget.vue'

const props = withDefaults(defineProps<{
  definition: ProcessDefinition
  phase: PhaseDef
  modelValue: Record<string, unknown>
  viewer: SimViewer
  disabled?: boolean
  errors?: SimFieldError[]
  sources?: OptionSources
}>(), { disabled: false })

const emit = defineEmits<{ 'update:modelValue': [values: Record<string, unknown>] }>()

const values = computed<Record<string, unknown>>(() => props.modelValue ?? {})

// Zwei getrennte Zeilen-Sorten mit einem echten Unterscheidungsmerkmal (`kind`):
// so ist im Template klar, dass ein Feld-Eintrag immer ein RenderedField trägt.
interface FieldRow { kind: 'field'; key: string; cols: number; r: RenderedField }
interface DecoRow { kind: 'deco'; key: string; cols: number; item: LayoutItem }
type Row = FieldRow | DecoRow
interface Block { section: LayoutSectionDef; rows: Row[] }

/** Lange Eingaben brauchen die volle Breite, sonst wird das Raster unruhig. */
function isWide(f: FieldDef): boolean {
  return f.widget === 'textarea' || f.widget === 'collection' || f.widget === 'attachment'
}

const blocks = computed<Block[]>(() => {
  if (!props.definition || !props.phase) return []
  return resolveLayout(props.definition, props.phase, values.value, props.viewer)
    .map(({ section, items }) => ({
      section,
      rows: items.map((it, i): Row => (it.rendered
        // Mehrzeiliger Text, Wiederholgruppe und Anhang ignorieren die
        // konfigurierte Breite: ein zweizeiliges Textfeld in einer
        // Viertel-Spalte ist nicht bedienbar.
        ? { kind: 'field', key: `f:${it.rendered.field.key}`,
            cols: isWide(it.rendered.field) ? 12 : it.cols, r: it.rendered }
        : { kind: 'deco', key: `d:${i}`, cols: it.cols, item: it.item })),
    }))
})

/** Fallback-Hülle, damit „keine Felder" nicht als nackter Text im Nichts steht. */
const emptySection = computed<LayoutSectionDef>(() => ({
  type: 'section',
  title: props.phase?.label || props.phase?.key || 'Angaben',
  variant: 'base', badge: null, description: null, collapsed: false, items: [],
}))

const labelOf = (f: FieldDef) => f.label || f.key

function errorFor(key: string): string | null {
  const hit = (props.errors ?? []).find((e) => e.path === key)
  return hit ? hit.message : null
}

function setValue(key: string, value: unknown) {
  emit('update:modelValue', { ...values.value, [key]: value })
}
</script>

<template>
  <div class="space-y-6">
    <LayoutSection v-if="!blocks.length" :section="emptySection">
      <p class="text-sm text-gray-400 italic px-1">
        Diese Phase hat keine sichtbaren Felder.
      </p>
    </LayoutSection>

    <LayoutSection v-for="(b, bi) in blocks" :key="`${bi}:${b.section.title}`" :section="b.section">
      <!-- 12er-Raster: unten immer volle Breite, ab md die konfigurierte Breite.
           Die Spaltenklassen kommen aus einer festen Tabelle (colSpanClass),
           weil Tailwind dynamisch zusammengesetzte Klassennamen nicht findet. -->
      <div class="grid grid-cols-12 gap-4">
        <div v-for="row in b.rows" :key="row.key"
             class="col-span-12" :class="colSpanClass(row.cols)">
          <template v-if="row.kind === 'field'">
            <label class="label">
              {{ labelOf(row.r.field) }}<span v-if="row.r.required" class="text-red-500"> *</span>
            </label>

            <CollectionWidget
              v-if="row.r.field.widget === 'collection'"
              :field="row.r.field"
              :model-value="values[row.r.field.key]"
              :disabled="disabled || !row.r.editable"
              :append-only="row.r.ref.mode === 'append_only' || row.r.field.mode === 'append_only'"
              :sources="sources"
              @update:model-value="setValue(row.r.field.key, $event)"
            />
            <SchemaWidget
              v-else
              :field="row.r.field"
              :model-value="values[row.r.field.key]"
              :disabled="disabled || !row.r.editable"
              :invalid="!!errorFor(row.r.field.key)"
              :sources="sources"
              @update:model-value="setValue(row.r.field.key, $event)"
            />

            <p v-if="errorFor(row.r.field.key)" class="text-xs text-red-500 mt-1">
              {{ errorFor(row.r.field.key) }}
            </p>
            <p v-else-if="row.r.field.help" class="text-xs text-gray-400 mt-1">
              {{ row.r.field.help }}
            </p>
          </template>

          <LayoutDecoration v-else :item="row.item" />
        </div>
      </div>
    </LayoutSection>
  </div>
</template>
