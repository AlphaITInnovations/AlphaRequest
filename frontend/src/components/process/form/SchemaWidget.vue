<script setup lang="ts">
/**
 * Ein einzelnes Eingabefeld, gesteuert vom Widget-Typ des Feld-Katalogs.
 *
 * Bewusst „dumm": kein Wissen über Phasen, Pflichtfelder oder Sichtbarkeit –
 * das entscheidet SchemaForm. Hier geht es nur um Darstellung und darum, dass
 * der emittierte Wert die Form hat, die der Server erwartet (Zahl bleibt Zahl,
 * Mehrfachauswahl bleibt Liste) – siehe validateValues in lib/processSim.ts.
 */
import { computed, ref, watch } from 'vue'
import type { FieldDef, OptionSources } from '@/types/process'
import UserSelect from '@/components/UserSelect.vue'

const props = withDefaults(defineProps<{
  field: FieldDef
  modelValue: unknown
  disabled?: boolean
  invalid?: boolean
  sources?: OptionSources
}>(), { disabled: false, invalid: false })

const emit = defineEmits<{ 'update:modelValue': [value: unknown] }>()

/** Sentinel für „Sonstiges" – kein gültiger Optionswert, daher kollisionsfrei. */
const OTHER = '__sonstiges__'

// ── Optionen ─────────────────────────────────────────────────────────────────

interface Opt { value: string; label: string }

const groupOpts = (): Opt[] =>
  (props.sources?.groups ?? []).map((g) => ({ value: g.id, label: g.name || g.id }))
const userOpts = (): Opt[] =>
  (props.sources?.users ?? []).map((u) => ({ value: u.id, label: u.displayName || u.id }))
const companyOpts = (): Opt[] =>
  (props.sources?.companies ?? []).map((c) => ({ value: c, label: c }))

/**
 * Die Widgets user/company/group haben eine feste Quelle, alle anderen richten
 * sich nach optionsSource (Default: die statische Optionsliste des Feldes).
 */
const optionList = computed<Opt[]>(() => {
  const f = props.field
  if (!f) return []
  if (f.widget === 'group') return groupOpts()
  if (f.widget === 'user') return userOpts()
  if (f.widget === 'company') return companyOpts()
  if (f.optionsSource === 'groups') return groupOpts()
  if (f.optionsSource === 'users') return userOpts()
  if (f.optionsSource === 'companies') return companyOpts()
  return (f.options ?? []).map((o) => ({ value: o.value, label: o.label ?? o.value }))
})

// ── Wert-Adapter ─────────────────────────────────────────────────────────────

const textModel = computed<string>({
  get: () => (props.modelValue === null || props.modelValue === undefined ? '' : String(props.modelValue)),
  set: (v) => emit('update:modelValue', v),
})

/** Mehrfachauswahl/Ankreuzliste geben IMMER eine Liste zurück, nie null. */
const arrayModel = computed<string[]>({
  get: () => (Array.isArray(props.modelValue) ? props.modelValue.map((v) => String(v)) : []),
  set: (v) => emit('update:modelValue', v),
})

const boolModel = computed<boolean>({
  get: () => props.modelValue === true,
  set: (v) => emit('update:modelValue', v),
})

const numberText = computed(() =>
  props.modelValue === null || props.modelValue === undefined ? '' : String(props.modelValue))

/** Leere Eingabe wird zu null, sonst zu einer echten Zahl (der Server prüft den Typ). */
function onNumberInput(e: Event) {
  const raw = (e.target as HTMLInputElement).value
  if (raw.trim() === '') { emit('update:modelValue', null); return }
  const n = Number(raw)
  emit('update:modelValue', Number.isNaN(n) ? null : n)
}

// ── „Sonstiges" bei Auswahlfeldern ───────────────────────────────────────────

const otherPicked = ref(false)

/**
 * Freitext ist aktiv, wenn er ausgewählt wurde ODER der gespeicherte Wert gar
 * nicht in der Liste steht (z. B. weil er früher als Freitext erfasst wurde).
 */
const otherActive = computed(() =>
  !!props.field?.allowOther
  && (otherPicked.value
    || (textModel.value !== '' && !optionList.value.some((o) => o.value === textModel.value))))

const selectValue = computed(() => (otherActive.value ? OTHER : textModel.value))

function onSelect(e: Event) {
  const v = (e.target as HTMLSelectElement).value
  if (v === OTHER) { otherPicked.value = true; emit('update:modelValue', ''); return }
  otherPicked.value = false
  emit('update:modelValue', v)
}

// Beim Feldwechsel (Wiederverwendung der Komponente in einer v-for-Liste) den
// Freitext-Modus zurücksetzen, sonst „klebt" er am nächsten Feld.
watch(() => props.field?.key, () => { otherPicked.value = false })

// ── Personen-/Gruppen-Auswahl ────────────────────────────────────────────────
// user/group nutzen die Suchauswahl der ganzen Anwendung (UserSelect). Die
// arbeitet mit {id, name} – gespeichert wird aber nur die ID; der Name wird
// beim Anzeigen aus den Quellen aufgelöst.

const pickModel = computed<{ id: string; name: string } | null>(() => {
  const id = textModel.value
  if (!id) return null
  const label = optionList.value.find((o) => o.value === id)?.label ?? id
  return { id, name: label }
})

function onPick(v: { id: string; name: string } | null) {
  emit('update:modelValue', v ? v.id : null)
}

// ── Darstellung ──────────────────────────────────────────────────────────────

const inputClass = computed(() => [
  'afi w-full disabled:opacity-60 disabled:cursor-not-allowed',
  props.invalid ? 'ring-1 ring-red-400' : '',
])

/** Nur-Lesen-Anzeige für server_generated/server_stamped. */
const readonlyText = computed(() => {
  const v = props.modelValue
  if (v === null || v === undefined || v === '') return '—'
  if (typeof v === 'boolean') return v ? 'Ja' : 'Nein'
  if (Array.isArray(v)) return v.length ? v.map((x) => String(x)).join(', ') : '—'
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
})
</script>

<template>
  <div>
    <!-- Text / Datum -->
    <input
      v-if="field.widget === 'text' || field.widget === 'date'"
      :type="field.widget === 'date' ? 'date' : 'text'"
      v-model="textModel"
      :placeholder="field.placeholder || ''"
      :disabled="disabled"
      :class="inputClass"
    />

    <!-- Mehrzeiliger Text -->
    <textarea
      v-else-if="field.widget === 'textarea'"
      v-model="textModel"
      rows="3"
      :placeholder="field.placeholder || ''"
      :disabled="disabled"
      :class="[inputClass, 'resize-none']"
    />

    <!-- Zahl: es wird eine Zahl (oder null) emittiert, kein String -->
    <input
      v-else-if="field.widget === 'number'"
      type="number"
      :value="numberText"
      :placeholder="field.placeholder || ''"
      :disabled="disabled"
      :class="inputClass"
      @input="onNumberInput"
    />

    <!-- Auswahl (inkl. Freitext „Sonstiges", wenn erlaubt) -->
    <div v-else-if="field.widget === 'select'" class="space-y-2">
      <select :value="selectValue" :disabled="disabled" :class="inputClass" @change="onSelect">
        <option value="">{{ field.placeholder || 'Bitte wählen' }}</option>
        <option v-for="o in optionList" :key="o.value" :value="o.value">{{ o.label }}</option>
        <option v-if="field.allowOther" :value="OTHER">Sonstiges …</option>
      </select>
      <input
        v-if="otherActive"
        v-model="textModel"
        type="text"
        placeholder="Sonstiges – bitte eintragen"
        :disabled="disabled"
        :class="inputClass"
      />
    </div>

    <!-- Mehrfachauswahl -->
    <select
      v-else-if="field.widget === 'multiselect'"
      v-model="arrayModel"
      multiple
      size="4"
      :disabled="disabled"
      :class="inputClass"
    >
      <option v-for="o in optionList" :key="o.value" :value="o.value">{{ o.label }}</option>
    </select>

    <!-- Ankreuzliste -->
    <div
      v-else-if="field.widget === 'checkbox-group'"
      class="grid grid-cols-1 sm:grid-cols-2 gap-2"
      :class="invalid ? 'rounded-xl ring-1 ring-red-400 p-2' : ''"
    >
      <label
        v-for="o in optionList" :key="o.value"
        class="flex items-center gap-2.5 text-sm text-gray-600 dark:text-gray-300 cursor-pointer select-none"
      >
        <input
          type="checkbox" :value="o.value" v-model="arrayModel" :disabled="disabled"
          class="h-4 w-4 rounded border-gray-300 dark:border-white/20 text-[#3EAAB8]
                 focus:ring-[#3EAAB8]/30 cursor-pointer"
        />
        <span>{{ o.label }}</span>
      </label>
      <p v-if="!optionList.length" class="text-sm text-gray-400 italic">Keine Auswahl hinterlegt.</p>
    </div>

    <!-- Ja/Nein -->
    <label
      v-else-if="field.widget === 'checkbox'"
      class="flex items-center gap-2.5 text-sm text-gray-600 dark:text-gray-300 cursor-pointer select-none w-fit"
    >
      <input
        type="checkbox" v-model="boolModel" :disabled="disabled"
        class="h-4 w-4 rounded border-gray-300 dark:border-white/20 text-[#3EAAB8]
               focus:ring-[#3EAAB8]/30 cursor-pointer"
      />
      <span>{{ field.placeholder || 'Ja' }}</span>
    </label>

    <!-- Person / Fachabteilung – dieselbe Suchauswahl wie überall sonst.
         Die Quellen kommen vom Host durch, damit nicht jedes Feld selbst lädt. -->
    <UserSelect
      v-else-if="field.widget === 'user' || field.widget === 'group'"
      :model-value="pickModel"
      label=""
      :placeholder="field.placeholder
        || (field.widget === 'group' ? 'Fachabteilung auswählen…' : 'Mitarbeiter:in auswählen…')"
      :show-users="field.widget === 'user'"
      :show-groups="field.widget === 'group'"
      :users="sources?.users ?? []"
      :groups="sources?.groups ?? []"
      :disabled="disabled"
      :class="invalid ? 'rounded-xl ring-1 ring-red-400' : ''"
      @update:model-value="onPick"
    />

    <!-- Firma – Auswahl aus den Stammdaten -->
    <select
      v-else-if="field.widget === 'company'"
      v-model="textModel"
      :disabled="disabled"
      :class="inputClass"
    >
      <option value="">{{ field.placeholder || 'Bitte wählen' }}</option>
      <option v-for="o in optionList" :key="o.value" :value="o.value">{{ o.label }}</option>
    </select>

    <!-- Datei-Anhang: Stufe 6 speichert für dieses Widget bewusst NICHTS.
         Anhänge hängen am klassischen Ticket, nicht an den Prozess-Werten –
         daher nur ein deaktivierter Hinweis statt einer Upload-Fläche. -->
    <div
      v-else-if="field.widget === 'attachment'"
      class="rounded-xl border border-dashed border-gray-300 dark:border-white/15
             bg-gray-50 dark:bg-white/5 px-4 py-3 text-sm text-gray-500 dark:text-gray-400"
    >
      Datei-Anhänge sind für Prozess-Aufträge noch nicht verfügbar
    </div>

    <!-- Wiederholgruppe wird von CollectionWidget gerendert, nicht hier -->
    <p v-else-if="field.widget === 'collection'" class="text-sm text-gray-400 italic">
      Wiederholgruppe
    </p>

    <!-- Systemwerte: immer nur lesbar -->
    <div
      v-else
      class="rounded-xl border border-gray-200 dark:border-white/10 bg-gray-50 dark:bg-white/5
             px-3.5 py-2 text-sm text-gray-500 dark:text-gray-400"
    >
      {{ readonlyText }}
    </div>
  </div>
</template>

