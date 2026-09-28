<script setup lang="ts">
/**
 * Mehrfach-Auswahl aus einer Directus-Quelle (widget='directus_multi'): Chips der
 * gewählten Einträge + suchbares Dropdown zum Hinzufügen. Gespeichert wird eine
 * Liste von IDs (valueField der Quelle). Labels kommen frisch beim Picken bzw. aus
 * `initialLabels` (vorab aufgelöst, siehe sources.directusLabels); unbekannt ⇒ ID.
 *
 * Bewusst ein eigenes Widget statt DirectusSelect zu überladen: der Einzelfall hat
 * die Snapshot-/Feld-Mapping-Logik, der Mehrfachfall braucht sie nicht.
 */
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import type { FieldDef } from '@/types/process'
import { sourceOptions, type DirectusOption } from '@/api/directus'

const props = withDefaults(defineProps<{
  field: FieldDef
  modelValue: string[]
  /** Vorab aufgelöste Labels der bereits gewählten IDs (für die Chips beim Laden). */
  initialLabels?: Record<string, string>
  disabled?: boolean
  invalid?: boolean
}>(), { initialLabels: () => ({}), disabled: false, invalid: false })

const emit = defineEmits<{ 'update:modelValue': [v: string[]] }>()

const query = ref('')
const options = ref<DirectusOption[]>([])
const open = ref(false)
const loading = ref(false)
const errorMsg = ref<string | null>(null)
const boxRef = ref<HTMLElement | null>(null)
let timer: ReturnType<typeof setTimeout> | null = null
let seq = 0

// Gemerkte Labels: initial (vorab aufgelöst) + beim Picken ergänzt.
const labels = ref<Record<string, string>>({ ...props.initialLabels })
const selected = computed<string[]>(() => props.modelValue ?? [])
const labelFor = (id: string) => labels.value[id] || id
const sourceKey = () => props.field.directusSource || ''

async function fetchOptions(search: string) {
  if (!sourceKey()) return
  const mine = ++seq
  loading.value = true
  errorMsg.value = null
  try {
    const res = await sourceOptions(sourceKey(), search)
    if (mine !== seq) return                 // veraltete Antwort verwerfen (latest-wins)
    options.value = res.options
    errorMsg.value = res.error
  } catch (e: any) {
    if (mine !== seq) return
    options.value = []
    errorMsg.value = e?.response?.data?.error?.message || 'Directus-Optionen nicht ladbar.'
  } finally {
    if (mine === seq) loading.value = false
  }
}

// Bereits Gewählte nicht erneut anbieten.
const available = computed(() => options.value.filter((o) => !selected.value.includes(o.value)))

function onFocus() {
  if (props.disabled) return
  open.value = true
  fetchOptions(query.value)
}
function onInput(e: Event) {
  query.value = (e.target as HTMLInputElement).value
  open.value = true
  if (timer) clearTimeout(timer)
  timer = setTimeout(() => fetchOptions(query.value), 250)
}
function add(o: DirectusOption) {
  labels.value = { ...labels.value, [o.value]: o.label }
  if (!selected.value.includes(o.value)) emit('update:modelValue', [...selected.value, o.value])
  query.value = ''
  fetchOptions('')                           // offen lassen für weitere Auswahl
}
function remove(id: string) {
  emit('update:modelValue', selected.value.filter((x) => x !== id))
}
function onClickOutside(e: MouseEvent) {
  if (boxRef.value && !boxRef.value.contains(e.target as Node) && open.value) {
    open.value = false
    query.value = ''
  }
}
onMounted(() => document.addEventListener('click', onClickOutside))
onBeforeUnmount(() => {
  document.removeEventListener('click', onClickOutside)
  if (timer) clearTimeout(timer)
})
</script>

<template>
  <div ref="boxRef" class="relative">
    <div v-if="selected.length" class="flex flex-wrap gap-1.5 mb-1.5">
      <span v-for="id in selected" :key="id"
            class="inline-flex items-center gap-1 rounded-lg bg-[#3EAAB8]/10
                   text-[#237e8a] dark:text-[#7fd3de] text-xs px-2 py-1">
        {{ labelFor(id) }}
        <button v-if="!disabled" type="button" @click="remove(id)"
                class="text-[#3EAAB8] hover:text-red-500 text-sm leading-none">×</button>
      </span>
    </div>
    <input
      :value="query"
      @focus="onFocus"
      @input="onInput"
      :disabled="disabled"
      :placeholder="field.placeholder || 'Suchen & hinzufügen…'"
      class="afi w-full disabled:opacity-60 disabled:cursor-not-allowed"
      :class="invalid ? 'ring-1 ring-red-400' : ''"
      autocomplete="off"
    />
    <div v-if="open"
         class="absolute z-30 mt-1 w-full max-h-64 overflow-auto rounded-xl border border-gray-200
                dark:border-white/10 bg-white dark:bg-[#263040] shadow-lg">
      <p v-if="loading" class="px-3 py-2 text-sm text-gray-400">Lädt…</p>
      <p v-else-if="errorMsg" class="px-3 py-2 text-sm text-amber-600 dark:text-amber-400">{{ errorMsg }}</p>
      <p v-else-if="!available.length" class="px-3 py-2 text-sm text-gray-400">Keine weiteren Treffer.</p>
      <button v-for="(o, i) in available" :key="i" type="button" @click="add(o)"
              class="w-full text-left px-3 py-2 text-sm hover:bg-gray-50 dark:hover:bg-white/5
                     flex items-center justify-between gap-3">
        <span class="truncate text-gray-800 dark:text-gray-100">{{ o.label }}</span>
        <span class="text-xs text-gray-400 whitespace-nowrap">{{ o.value }}</span>
      </button>
    </div>
  </div>
</template>
