<script lang="ts">
/**
 * Reine Hilfsfunktionen der Wiederholgruppe.
 *
 * Bewusst im normalen <script>-Block: so sind sie ohne Mounting testbar
 * (das Projekt hat kein @vue/test-utils) und bleiben trotzdem im <script setup>
 * verwendbar – beide Blöcke werden zu einem Modul zusammengeführt.
 */

/** Alles, was keine Objekt-Zeile ist, wird zu {} – damit bleiben die Indizes stabil. */
export function toEntries(v: unknown): Record<string, unknown>[] {
  if (!Array.isArray(v)) return []
  return v.map((e) =>
    e && typeof e === 'object' && !Array.isArray(e) ? (e as Record<string, unknown>) : {})
}

/**
 * Bei mode='append_only' lehnt der Server jede Änderung an bereits gespeicherten
 * Einträgen ab. Alles vor `initialCount` ist deshalb gesperrt.
 */
export function isLockedEntry(index: number, initialCount: number, appendOnly: boolean): boolean {
  return appendOnly && index < initialCount
}

/** Unveränderliche Aktualisierung eines Unterfeldes. */
export function withSubValue(
  entries: Record<string, unknown>[], index: number, key: string, value: unknown,
): Record<string, unknown>[] {
  return entries.map((e, i) => (i === index ? { ...e, [key]: value } : { ...e }))
}

export function withNewEntry(entries: Record<string, unknown>[]): Record<string, unknown>[] {
  return [...entries.map((e) => ({ ...e })), {}]
}

export function withoutEntry(
  entries: Record<string, unknown>[], index: number,
): Record<string, unknown>[] {
  return entries.filter((_, i) => i !== index).map((e) => ({ ...e }))
}
</script>

<script setup lang="ts">
/**
 * Wiederholgruppe (widget='collection'): eine Liste gleichartiger Einträge.
 *
 * Der Wert ist immer ein Array von Objekten – ein Objekt je Eintrag, die Keys
 * sind die Unterfeld-Keys aus field.item.
 */
import { computed, ref, watch } from 'vue'
import type { FieldDef, OptionSources, SubField } from '@/types/process'
import { blankFieldDef } from '@/lib/processSchema'
import SchemaWidget from './SchemaWidget.vue'

const props = withDefaults(defineProps<{
  field: FieldDef
  modelValue: unknown
  disabled?: boolean
  appendOnly?: boolean
  sources?: OptionSources
}>(), { disabled: false, appendOnly: false })

const emit = defineEmits<{ 'update:modelValue': [value: Record<string, unknown>[]] }>()

const entries = computed(() => toEntries(props.modelValue))
const subFields = computed<SubField[]>(() => props.field?.item ?? [])

// ── Sperre für bereits gespeicherte Einträge ─────────────────────────────────

// Anzahl der Einträge beim ersten Laden. Die Werte können asynchron nachkommen,
// darum wird erst gemerkt, wenn überhaupt ein Array anliegt.
const initialCount = ref(entries.value.length)
const counted = ref(Array.isArray(props.modelValue))

watch(() => props.modelValue, (v) => {
  if (!counted.value && Array.isArray(v)) {
    initialCount.value = toEntries(v).length
    counted.value = true
  }
})

const locked = (i: number) => isLockedEntry(i, initialCount.value, props.appendOnly)
/** Neu hinzugefügt = noch nicht gespeichert – Systemstempel gibt es erst danach. */
const isNew = (i: number) => i >= initialCount.value

// ── Unterfelder ──────────────────────────────────────────────────────────────

/** Aus einem SubField ein vollständiges FieldDef bauen, das SchemaWidget versteht. */
function subDef(sf: SubField): FieldDef {
  return { ...blankFieldDef(sf.key, sf.widget), label: sf.label }
}

function displayValue(v: unknown): string {
  if (v === null || v === undefined || v === '') return '—'
  if (typeof v === 'boolean') return v ? 'Ja' : 'Nein'
  if (Array.isArray(v)) return v.length ? v.map((x) => String(x)).join(', ') : '—'
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}

// ── Mutationen (immer unveränderlich, damit v-model sauber reagiert) ─────────

function setSub(index: number, key: string, value: unknown) {
  emit('update:modelValue', withSubValue(entries.value, index, key, value))
}

function addEntry() {
  emit('update:modelValue', withNewEntry(entries.value))
}

function removeEntry(index: number) {
  if (locked(index)) return
  emit('update:modelValue', withoutEntry(entries.value, index))
}
</script>

<template>
  <div class="space-y-3">
    <p v-if="!entries.length" class="text-sm text-gray-400 italic px-1">Noch keine Einträge</p>

    <div
      v-for="(entry, i) in entries" :key="i"
      class="rounded-xl border border-gray-200 dark:border-white/10 p-4 space-y-3"
      :class="locked(i) ? 'bg-gray-50 dark:bg-white/[0.03]' : ''"
    >
      <div class="flex items-center gap-2">
        <span class="text-xs font-semibold text-gray-400 uppercase tracking-wider">
          Eintrag {{ i + 1 }}
        </span>
        <span
          v-if="locked(i)"
          class="text-[11px] px-2 py-0.5 rounded-full bg-gray-100 dark:bg-white/10
                 text-gray-500 dark:text-gray-400"
        >Gespeichert – nicht änderbar</span>
        <button
          v-if="!locked(i) && !disabled"
          type="button"
          class="ml-auto text-sm text-red-500 hover:text-red-600 hover:underline transition"
          @click="removeEntry(i)"
        >Entfernen</button>
      </div>

      <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
        <div
          v-for="sf in subFields" :key="sf.key"
          :class="sf.widget === 'textarea' ? 'md:col-span-2' : ''"
        >
          <label class="lbl">{{ sf.label || sf.key }}</label>

          <!-- Systemstempel setzt der Server (actor/now) – nie bearbeitbar. -->
          <template v-if="sf.widget === 'server_stamped'">
            <p v-if="isNew(i)" class="text-sm text-gray-400 italic">wird beim Speichern gesetzt</p>
            <p v-else class="text-sm text-gray-900 dark:text-white">
              {{ displayValue(entry[sf.key]) }}
            </p>
          </template>

          <!-- Gespeicherte Einträge bei „Nur anhängen": nur lesen -->
          <p
            v-else-if="locked(i)"
            class="text-sm text-gray-900 dark:text-white whitespace-pre-wrap"
          >{{ displayValue(entry[sf.key]) }}</p>

          <SchemaWidget
            v-else
            :field="subDef(sf)"
            :model-value="entry[sf.key]"
            :disabled="disabled"
            :sources="sources"
            @update:model-value="setSub(i, sf.key, $event)"
          />
        </div>

        <p v-if="!subFields.length" class="text-sm text-gray-400 italic md:col-span-2">
          Für diese Wiederholgruppe sind keine Unterfelder hinterlegt.
        </p>
      </div>
    </div>

    <button v-if="!disabled" type="button" class="btn-secondary" @click="addEntry">
      Eintrag hinzufügen
    </button>
  </div>
</template>
