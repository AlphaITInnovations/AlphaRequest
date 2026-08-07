<script setup lang="ts">
/**
 * Editor für die Unterfelder einer Wiederholgruppe (widget='collection').
 *
 * Nur WIDGETS_SUB ist hier erlaubt: kein verschachteltes 'collection', dafür
 * 'server_stamped' (vom System gesetzter Stempel). Bei einem Stempel verlangt
 * das Backend genau eine der Quellen 'actor' oder 'now'.
 */
import { computed } from 'vue'
import type { SubField, Widget } from '@/types/process'
import { WIDGETS_SUB, WIDGET_LABEL, blankSubField, isValidFieldKey } from '@/lib/processSchema'

const props = defineProps<{ modelValue: SubField[] }>()
const emit = defineEmits<{ 'update:modelValue': [value: SubField[]] }>()

/** Die einzigen serverseitig gültigen Quellen eines Systemstempels. */
const STAMP_VALUES: { value: string; label: string }[] = [
  { value: 'actor', label: 'Autor' },
  { value: 'now', label: 'Zeitpunkt' },
]

// Defensiv: importierte Definitionen können `item` ganz weglassen.
const rows = computed<SubField[]>(() => props.modelValue ?? [])

function commit(next: SubField[]) {
  emit('update:modelValue', next)
}
function patchRow(i: number, p: Partial<SubField>) {
  commit(rows.value.map((sf, j) => (j === i ? { ...sf, ...p } : sf)))
}

function setKey(i: number, v: string) {
  patchRow(i, { key: v })
}
function setLabel(i: number, v: string) {
  patchRow(i, { label: v.trim() === '' ? null : v })
}
function setWidget(i: number, w: Widget) {
  // Ein Stempel braucht sofort eine gültige Quelle, sonst lehnt der Server ab;
  // bei jedem anderen Typ ist `value` nicht erlaubt und wird geleert.
  patchRow(i, { widget: w, value: w === 'server_stamped' ? (rows.value[i].value ?? 'actor') : null })
}
function setStampValue(i: number, v: string) {
  patchRow(i, { value: v })
}

function add() {
  commit([...rows.value, blankSubField()])
}
function remove(i: number) {
  commit(rows.value.filter((_, j) => j !== i))
}
function move(i: number, d: -1 | 1) {
  const j = i + d
  if (j < 0 || j >= rows.value.length) return
  const next = [...rows.value]
  const tmp = next[i]
  next[i] = next[j]
  next[j] = tmp
  commit(next)
}

/** Schlüssel, die mehrfach vorkommen – die Einträge wären sonst nicht zuordenbar. */
const duplicates = computed(() => {
  const seen = new Set<string>()
  const dup = new Set<string>()
  for (const sf of rows.value) {
    if (!sf.key) continue
    if (seen.has(sf.key)) dup.add(sf.key)
    seen.add(sf.key)
  }
  return dup
})

function keyError(sf: SubField): string | null {
  if (!sf.key.trim()) return 'Unterfeld braucht einen Schlüssel.'
  if (!isValidFieldKey(sf.key)) return 'Erlaubt sind Buchstaben, Ziffern und „_".'
  if (duplicates.value.has(sf.key)) return `Schlüssel „${sf.key}" kommt mehrfach vor.`
  return null
}

/** Ein aus einem Import stammendes Widget, das hier nicht angeboten wird. */
function isUnknownWidget(w: Widget): boolean {
  return !WIDGETS_SUB.includes(w)
}
</script>

<template>
  <div class="space-y-2">
    <div v-for="(sf, i) in rows" :key="i"
         class="rounded-xl border border-gray-200 dark:border-white/10 p-2.5 space-y-2">
      <div class="grid md:grid-cols-3 gap-2">
        <div>
          <label class="lbl">Schlüssel</label>
          <input :value="sf.key" @input="setKey(i, ($event.target as HTMLInputElement).value)"
                 placeholder="z. B. bemerkung" class="pfi font-mono"
                 :class="keyError(sf) ? 'border-red-400 bg-red-50 dark:bg-red-900/20' : ''" />
        </div>
        <div>
          <label class="lbl">Bezeichnung <span class="text-gray-400 font-normal">(optional)</span></label>
          <input :value="sf.label ?? ''" @input="setLabel(i, ($event.target as HTMLInputElement).value)"
                 placeholder="z. B. Bemerkung" class="pfi" />
        </div>
        <div>
          <label class="lbl">Feldtyp</label>
          <select :value="sf.widget"
                  @change="setWidget(i, ($event.target as HTMLSelectElement).value as Widget)"
                  class="pfi">
            <option v-for="w in WIDGETS_SUB" :key="w" :value="w">{{ WIDGET_LABEL[w] }}</option>
            <option v-if="isUnknownWidget(sf.widget)" :value="sf.widget" class="text-red-600">
              Unbekannt: {{ sf.widget }}
            </option>
          </select>
        </div>
      </div>

      <div v-if="sf.widget === 'server_stamped'" class="grid md:grid-cols-3 gap-2">
        <div>
          <label class="lbl">Quelle des Stempels</label>
          <select :value="sf.value ?? ''"
                  @change="setStampValue(i, ($event.target as HTMLSelectElement).value)"
                  class="pfi"
                  :class="sf.value !== 'actor' && sf.value !== 'now'
                    ? 'border-red-400 bg-red-50 dark:bg-red-900/20' : ''">
            <option value="" disabled>— bitte wählen —</option>
            <option v-for="v in STAMP_VALUES" :key="v.value" :value="v.value">{{ v.label }}</option>
          </select>
        </div>
        <p class="md:col-span-2 text-xs text-gray-500 dark:text-gray-400 md:mt-5">
          Der Wert wird beim Anlegen eines Eintrags automatisch gesetzt und lässt sich nicht
          bearbeiten.
        </p>
      </div>

      <div class="flex items-center justify-between">
        <p v-if="keyError(sf)" class="text-xs text-red-500">{{ keyError(sf) }}</p>
        <span v-else></span>
        <div class="flex gap-1">
          <button type="button" @click="move(i, -1)" :disabled="i === 0" title="Nach oben"
                  class="pbtn">↑</button>
          <button type="button" @click="move(i, 1)" :disabled="i === rows.length - 1" title="Nach unten"
                  class="pbtn">↓</button>
          <button type="button" @click="remove(i)" title="Unterfeld entfernen"
                  class="pbtn hover:text-red-500">✕</button>
        </div>
      </div>
    </div>

    <p v-if="rows.length === 0" class="text-sm text-gray-400 italic px-1">
      Noch keine Unterfelder. Eine Wiederholgruppe braucht mindestens ein Unterfeld.
    </p>

    <button type="button" @click="add" class="btn-secondary">+ Unterfeld</button>
  </div>
</template>

<style scoped>
@reference "../../../style.css";
.pfi {
  @apply w-full rounded-xl border border-gray-200 dark:border-white/10
         bg-white dark:bg-[#263040] text-gray-900 dark:text-gray-100
         px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-[#3EAAB8]/30 transition;
}
.pbtn {
  @apply px-2 py-1.5 rounded-lg border border-gray-200 dark:border-white/10
         text-gray-500 dark:text-gray-400 text-xs leading-none
         hover:bg-gray-50 dark:hover:bg-white/5 disabled:opacity-30
         disabled:cursor-not-allowed transition;
}
</style>
