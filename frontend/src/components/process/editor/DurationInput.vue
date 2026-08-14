<script setup lang="ts">
/**
 * Eingabe einer ISO-8601-Dauer (P…/PT…) – Spiegel von lib/isoDuration.ts.
 *
 * Zwei Wege zum selben Wert:
 *  - bequem: Anzahl + Einheit (Minuten/Stunden/Tage/Wochen) werden zu einer
 *    kanonischen Dauer zusammengesetzt;
 *  - Rohtext für Fachkundige, die z.B. „PT90M" direkt eintippen wollen.
 * Leer ⇒ null (das Backend unterscheidet „keine Dauer" von „0").
 */
import { ref, computed, watch } from 'vue'
import { formatDuration, humanDuration, isValidDuration, parseDuration } from '@/lib/isoDuration'

const props = defineProps<{
  modelValue: string | null
  placeholder?: string
}>()

const emit = defineEmits<{ 'update:modelValue': [value: string | null] }>()

// ── Einheiten ─────────────────────────────────────────────────────────────────

type UnitKey = 'minutes' | 'hours' | 'days' | 'weeks'

const UNITS: readonly { key: UnitKey; label: string; sec: number }[] = [
  { key: 'minutes', label: 'Minuten', sec: 60 },
  { key: 'hours', label: 'Stunden', sec: 3600 },
  { key: 'days', label: 'Tage', sec: 86400 },
  { key: 'weeks', label: 'Wochen', sec: 604800 },
]

const secondsOf = (u: UnitKey): number => UNITS.find((x) => x.key === u)?.sec ?? 86400

// ── Zustand ───────────────────────────────────────────────────────────────────

const amount = ref('')
const unit = ref<UnitKey>('days')
const raw = ref('')

/** Aktuelle Auswahl als ISO-Dauer ('' wenn keine sinnvolle Anzahl gesetzt). */
function composed(): string {
  const n = Number(amount.value)
  if (amount.value === '' || !Number.isFinite(n) || n <= 0) return ''
  return formatDuration(n * secondsOf(unit.value))
}

/** ISO → Anzahl/Einheit: größte Einheit, die restlos aufgeht. Sonst null. */
function split(iso: string | null): { amount: string; unit: UnitKey } | null {
  if (!iso) return null
  const total = parseDuration(iso)
  if (total === null || total <= 0) return null
  for (let i = UNITS.length - 1; i >= 0; i--) {
    const u = UNITS[i]
    if (total % u.sec === 0) return { amount: String(total / u.sec), unit: u.key }
  }
  return null
}

watch(
  () => props.modelValue,
  (v) => {
    raw.value = v ?? ''
    // Eigene Eingabe nicht umdeuten: „7 Tage" darf nicht zu „1 Woche" werden.
    if (composed() === (v ?? '')) return
    const d = split(v)
    if (d) {
      amount.value = d.amount
      unit.value = d.unit
    } else if (!v) {
      amount.value = ''
    }
  },
  { immediate: true },
)

// ── Ausgabe ───────────────────────────────────────────────────────────────────

function pushIso(iso: string) {
  raw.value = iso
  emit('update:modelValue', iso === '' ? null : iso)
}

function onAmount(e: Event) {
  amount.value = (e.target as HTMLInputElement).value
  pushIso(composed())
}

function onUnit(e: Event) {
  unit.value = (e.target as HTMLSelectElement).value as UnitKey
  pushIso(composed())
}

function onRaw(e: Event) {
  const v = (e.target as HTMLInputElement).value.trim()
  raw.value = v
  emit('update:modelValue', v === '' ? null : v)
}

const invalid = computed(() => raw.value !== '' && !isValidDuration(raw.value))
const human = computed(() => (raw.value === '' ? '—' : humanDuration(raw.value)))
</script>

<template>
  <div class="space-y-1.5">
    <div class="flex flex-wrap items-center gap-2">
      <input
        type="number"
        min="0"
        step="1"
        inputmode="numeric"
        class="afi w-24"
        placeholder="0"
        :value="amount"
        @input="onAmount"
      />
      <select class="afi" :value="unit" @change="onUnit">
        <option v-for="u in UNITS" :key="u.key" :value="u.key">{{ u.label }}</option>
      </select>
      <input
        type="text"
        class="afi w-36 font-mono"
        :placeholder="placeholder || 'z. B. P7D'"
        :value="raw"
        @input="onRaw"
      />
      <span class="text-xs" :class="invalid ? 'text-red-500' : 'text-gray-400'">{{ human }}</span>
    </div>
    <p v-if="invalid" class="text-xs text-red-500">
      Ungültige Dauer – möglich sind Wochen, Tage, Stunden, Minuten, Sekunden
      (z.&nbsp;B. P7D, PT12H). Monate und Jahre sind nicht erlaubt.
    </p>
  </div>
</template>

