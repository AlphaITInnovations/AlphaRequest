<script setup lang="ts">
/**
 * Suchbares Dropdown für ein `directus`-Feld. Holt seine Optionen LIVE aus der
 * konfigurierten Quelle (anders als user/group/company, deren Listen der Host
 * durchreicht – Directus-Daten sind extern, groß und suchbar).
 *
 * Emittiert `select` mit {value, record} (bzw. null beim Leeren); der gewählte
 * Datensatz (`record`) trägt die zu ladenden Felder, damit der Host die
 * Zielfelder per Feld-Mapping befüllen kann (Snapshot).
 */
import { ref, watch, onMounted, onBeforeUnmount } from 'vue'
import type { FieldDef } from '@/types/process'
import { sourceOptions, type DirectusOption } from '@/api/directus'

const props = withDefaults(defineProps<{
  field: FieldDef
  modelValue: string
  disabled?: boolean
  invalid?: boolean
}>(), { disabled: false, invalid: false })

const emit = defineEmits<{ select: [sel: { value: string; record: Record<string, any> } | null] }>()

const query = ref('')
const options = ref<DirectusOption[]>([])
const open = ref(false)
const loading = ref(false)
const errorMsg = ref<string | null>(null)
const boxRef = ref<HTMLElement | null>(null)
let timer: ReturnType<typeof setTimeout> | null = null
let seq = 0

// Anzeige-Text. Wir merken uns das zuletzt gewählte Label samt zugehörigem Wert:
// nach dem Picken wechselt props.modelValue (asynchron) auf den rohen Wert; ohne
// dieses Merken würde der Watcher das gerade gesetzte Label mit dem Rohwert
// überschreiben. Passt der aktuelle Wert zum gemerkten Label, zeigen wir das
// Label, sonst den Rohwert (z. B. nach Reload – die gemappten Zielfelder tragen
// ohnehin die lesbaren Snapshots).
const display = ref('')
const selValue = ref('')
const selLabel = ref('')
function syncDisplay(v: string) {
  display.value = v && v === selValue.value && selLabel.value ? selLabel.value : (v ? String(v) : '')
}
syncDisplay(props.modelValue ? String(props.modelValue) : '')
watch(() => props.modelValue, (v) => { if (!open.value) syncDisplay(v ? String(v) : '') })

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

function onFocus() {
  if (props.disabled) return
  open.value = true
  fetchOptions(query.value)
}
function onInput(e: Event) {
  query.value = (e.target as HTMLInputElement).value
  display.value = query.value
  open.value = true
  if (timer) clearTimeout(timer)
  timer = setTimeout(() => fetchOptions(query.value), 250)
}
function pick(o: DirectusOption) {
  selValue.value = o.value
  selLabel.value = o.label
  emit('select', { value: o.value, record: o.record })
  display.value = o.label
  query.value = ''
  open.value = false
}
function clear() {
  selValue.value = ''
  selLabel.value = ''
  emit('select', null)
  display.value = ''
  query.value = ''
  options.value = []
}
function onClickOutside(e: MouseEvent) {
  if (boxRef.value && !boxRef.value.contains(e.target as Node) && open.value) {
    open.value = false
    // Abgebrochene Sucheingabe verwerfen und wieder den echten Wert anzeigen.
    syncDisplay(props.modelValue ? String(props.modelValue) : '')
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
    <div class="relative">
      <input
        :value="display"
        @focus="onFocus"
        @input="onInput"
        :disabled="disabled"
        :placeholder="field.placeholder || 'Suchen & auswählen…'"
        class="afi w-full pr-8 disabled:opacity-60 disabled:cursor-not-allowed"
        :class="invalid ? 'ring-1 ring-red-400' : ''"
        autocomplete="off"
      />
      <button v-if="modelValue && !disabled" @click="clear" type="button"
              class="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-red-500 text-lg leading-none">×</button>
    </div>
    <div v-if="open"
         class="absolute z-30 mt-1 w-full max-h-64 overflow-auto rounded-xl border border-gray-200
                dark:border-white/10 bg-white dark:bg-[#263040] shadow-lg">
      <p v-if="loading" class="px-3 py-2 text-sm text-gray-400">Lädt…</p>
      <p v-else-if="errorMsg" class="px-3 py-2 text-sm text-amber-600 dark:text-amber-400">{{ errorMsg }}</p>
      <p v-else-if="!options.length" class="px-3 py-2 text-sm text-gray-400">Keine Treffer.</p>
      <button v-for="(o, i) in options" :key="i" type="button" @click="pick(o)"
              class="w-full text-left px-3 py-2 text-sm hover:bg-gray-50 dark:hover:bg-white/5
                     flex items-center justify-between gap-3">
        <span class="truncate text-gray-800 dark:text-gray-100">{{ o.label }}</span>
        <span class="text-xs text-gray-400 whitespace-nowrap">{{ o.value }}</span>
      </button>
    </div>
  </div>
</template>
