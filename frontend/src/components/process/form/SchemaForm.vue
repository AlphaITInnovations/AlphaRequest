<script setup lang="ts">
/**
 * Formular EINER Phase, vollständig aus der Prozess-Definition erzeugt.
 *
 * Was angezeigt, was bearbeitet und was verlangt wird, entscheidet
 * renderFields() – der Spiegel der Server-Laufzeit. Der Server bleibt
 * autoritativ; hier geht es nur um die Darstellung.
 */
import { computed } from 'vue'
import type {
  FieldDef, OptionSources, PhaseDef, ProcessDefinition,
} from '@/types/process'
import { renderFields } from '@/lib/processSim'
import type { RenderedField, SimFieldError, SimViewer } from '@/lib/processSim'
import TicketSection from '@/components/tickets/TicketSection.vue'
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

/** Nur sichtbare Felder – unsichtbare dürfen gar nicht erst im DOM landen. */
const rows = computed<RenderedField[]>(() => {
  if (!props.definition || !props.phase) return []
  return renderFields(props.definition, props.phase, values.value, props.viewer)
    .filter((r) => r.visible)
})

const title = computed(() => props.phase?.label || props.phase?.key || 'Angaben')

const labelOf = (f: FieldDef) => f.label || f.key

/** Lange Eingaben brauchen die volle Breite, sonst wird das Raster unruhig. */
function isWide(f: FieldDef): boolean {
  return f.widget === 'textarea' || f.widget === 'collection' || f.widget === 'attachment'
}

function errorFor(key: string): string | null {
  const hit = (props.errors ?? []).find((e) => e.path === key)
  return hit ? hit.message : null
}

function setValue(key: string, value: unknown) {
  emit('update:modelValue', { ...values.value, [key]: value })
}
</script>

<template>
  <TicketSection :title="title" variant="base">
    <p v-if="!rows.length" class="text-sm text-gray-400 italic px-1">
      Diese Phase hat keine sichtbaren Felder.
    </p>

    <div v-else class="grid grid-cols-1 md:grid-cols-2 gap-4">
      <div
        v-for="r in rows" :key="r.field.key"
        :class="isWide(r.field) ? 'md:col-span-2' : ''"
      >
        <label class="label">
          {{ labelOf(r.field) }}<span v-if="r.required" class="text-red-500"> *</span>
        </label>

        <CollectionWidget
          v-if="r.field.widget === 'collection'"
          :field="r.field"
          :model-value="values[r.field.key]"
          :disabled="disabled || !r.editable"
          :append-only="r.ref.mode === 'append_only' || r.field.mode === 'append_only'"
          :sources="sources"
          @update:model-value="setValue(r.field.key, $event)"
        />
        <SchemaWidget
          v-else
          :field="r.field"
          :model-value="values[r.field.key]"
          :disabled="disabled || !r.editable"
          :invalid="!!errorFor(r.field.key)"
          :sources="sources"
          @update:model-value="setValue(r.field.key, $event)"
        />

        <p v-if="errorFor(r.field.key)" class="text-xs text-red-500 mt-1">
          {{ errorFor(r.field.key) }}
        </p>
        <p v-else-if="r.field.help" class="text-xs text-gray-400 mt-1">{{ r.field.help }}</p>
      </div>
    </div>
  </TicketSection>
</template>
