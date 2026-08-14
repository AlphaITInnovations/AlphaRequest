<script setup lang="ts">
/**
 * Grafischer Editor für die Condition-DSL (siehe lib/conditionDsl.ts).
 * Pro Knoten genau EIN Operator; UND/ODER/NICHT rendern sich rekursiv selbst.
 *
 * Bewusst „unfertig erlaubt": Solange kein Feld gewählt ist, wird trotzdem ein
 * vollständiges Objekt emittiert (z.B. {'==': ['', '']}). processValidate
 * meldet das als Fehler – das ist die gewollte Rückmeldung, ein stiller
 * Null-Zustand würde die Eingabe des Nutzers verschlucken.
 */
import { computed } from 'vue'
import type { Condition } from '@/types/process'

defineOptions({ name: 'ConditionEditor' })

const props = defineProps<{
  modelValue: Condition | null
  fieldKeys: string[]
  label?: string
}>()

const emit = defineEmits<{ 'update:modelValue': [value: Condition | null] }>()

// ── Operatoren ────────────────────────────────────────────────────────────────

type Op = '==' | '!=' | 'in' | 'truthy' | 'and' | 'or' | 'not'

const OPS: readonly Op[] = ['==', '!=', 'in', 'truthy', 'and', 'or', 'not']

const OP_LABEL: Record<Op, string> = {
  '==': 'ist gleich',
  '!=': 'ist ungleich',
  in: 'ist eine von',
  truthy: 'ist gesetzt',
  and: 'UND',
  or: 'ODER',
  not: 'NICHT',
}

/** Startwert für neue (Unter-)Bedingungen. */
function blank(): Condition {
  return { '==': ['', ''] }
}

const keys = computed<string[]>(() => props.fieldKeys ?? [])

const op = computed<Op | null>(() => {
  const c = props.modelValue
  if (!c || typeof c !== 'object' || Array.isArray(c)) return null
  const k = Object.keys(c)
  if (k.length !== 1) return null
  return (OPS as readonly string[]).includes(k[0]) ? (k[0] as Op) : null
})

const arg = computed<any>(() => (op.value ? (props.modelValue as Condition)[op.value] : null))

const isLeaf = computed(() => op.value === '==' || op.value === '!=' || op.value === 'in' || op.value === 'truthy')
const isGroup = computed(() => op.value === 'and' || op.value === 'or')

/** Feld-Referenz des Knotens (nur bei Blatt-Operatoren vorhanden). */
const fieldKey = computed<string>(() => {
  const a = arg.value
  if (op.value === 'truthy') return typeof a === 'string' ? a : ''
  if (Array.isArray(a) && typeof a[0] === 'string') return a[0]
  return ''
})

/** Vergleichswert bei ==/!=. */
const rawValue = computed<unknown>(() => (Array.isArray(arg.value) ? arg.value[1] : ''))

/** Werteliste bei in. */
const listValues = computed<unknown[]>(() =>
  Array.isArray(arg.value) && Array.isArray(arg.value[1]) ? arg.value[1] : [])

/** Kinder bei and/or/not – not wird als einelementige Liste behandelt. */
const children = computed<Condition[]>(() => {
  if (isGroup.value) return Array.isArray(arg.value) ? (arg.value as Condition[]) : []
  if (op.value === 'not') {
    return arg.value && typeof arg.value === 'object' && !Array.isArray(arg.value)
      ? [arg.value as Condition]
      : []
  }
  return []
})

// ── Wert-Typ (Text/Zahl/Ja-Nein) ──────────────────────────────────────────────
// Kein eigener State: der Typ wird aus dem Wert abgeleitet, das Umschalten
// konvertiert den Wert. So können Anzeige und JSON nicht auseinanderlaufen.

type VType = 'text' | 'number' | 'bool'

const valueType = computed<VType>(() => {
  const v = rawValue.value
  if (typeof v === 'boolean') return 'bool'
  if (typeof v === 'number') return 'number'
  return 'text'
})

const VTYPE_LABEL: Record<VType, string> = { text: 'Text', number: 'Zahl', bool: 'Ja/Nein' }
const VTYPES: readonly VType[] = ['text', 'number', 'bool']

// ── Änderungen ────────────────────────────────────────────────────────────────

const val = (e: Event) => (e.target as HTMLInputElement | HTMLSelectElement).value

function push(c: Condition | null) {
  emit('update:modelValue', c)
}

function addRoot() {
  push(blank())
}

function setField(key: string) {
  if (op.value === 'truthy') { push({ truthy: key }); return }
  if (op.value === 'in') { push({ in: [key, listValues.value] }); return }
  if (op.value === '==' || op.value === '!=') { push({ [op.value]: [key, rawValue.value] }); return }
}

function setValue(v: unknown) {
  if (op.value !== '==' && op.value !== '!=') return
  push({ [op.value]: [fieldKey.value, v] })
}

function setValueType(t: VType) {
  const v = rawValue.value
  if (t === 'bool') { setValue(typeof v === 'boolean' ? v : true); return }
  if (t === 'number') { const n = Number(v); setValue(Number.isFinite(n) ? n : 0); return }
  setValue(v === null || v === undefined ? '' : String(v))
}

function setNumber(text: string) {
  const n = Number(text)
  setValue(text === '' || !Number.isFinite(n) ? 0 : n)
}

// ── Werteliste (in) ───────────────────────────────────────────────────────────

function addListValue(e: Event) {
  const input = e.target as HTMLInputElement
  const v = input.value.trim()
  if (!v) return
  push({ in: [fieldKey.value, [...listValues.value, v]] })
  input.value = ''
}

function removeListValue(i: number) {
  push({ in: [fieldKey.value, listValues.value.filter((_, j) => j !== i)] })
}

// ── Unter-Bedingungen ─────────────────────────────────────────────────────────

function addChild() {
  if (!isGroup.value || !op.value) return
  push({ [op.value]: [...children.value, blank()] })
}

/**
 * Ein Kind meldet null = „entferne mich". Bleibt keine Bedingung übrig, fällt
 * auch die Gruppe weg – eine leere UND-Gruppe wäre serverseitig ungültig.
 */
function updateChild(i: number, v: Condition | null) {
  // NICHT: das Kind MUSS wieder eingepackt werden – sonst verschwindet die
  // Negation und die Bedingung würde ins Gegenteil verkehrt gespeichert.
  if (op.value === 'not') { push(v ? { not: v } : null); return }
  if (!isGroup.value || !op.value) return
  const next = v === null
    ? children.value.filter((_, j) => j !== i)
    : children.value.map((c, j) => (j === i ? v : c))
  push(next.length ? { [op.value]: next } : null)
}

// ── Operator-Wechsel (überträgt so viel wie möglich) ──────────────────────────

function changeOp(next: Op) {
  if (next === op.value) return
  const key = fieldKey.value

  if (next === '==' || next === '!=') {
    let v: unknown = ''
    if (op.value === '==' || op.value === '!=') v = rawValue.value
    else if (op.value === 'in' && listValues.value.length) v = listValues.value[0]
    push({ [next]: [key, v] })
    return
  }
  if (next === 'in') {
    let list = listValues.value
    if (op.value === '==' || op.value === '!=') {
      const v = rawValue.value
      list = v === '' || v === null || v === undefined ? [] : [v]
    }
    push({ in: [key, list] })
    return
  }
  if (next === 'truthy') {
    push({ truthy: key })
    return
  }
  if (next === 'and' || next === 'or') {
    // Bestehende Bedingung wird zum ersten Kind der neuen Gruppe.
    const kids = children.value.length
      ? children.value
      : props.modelValue ? [props.modelValue] : []
    push({ [next]: kids.length ? kids : [blank()] })
    return
  }
  push({ not: children.value[0] ?? props.modelValue ?? blank() })
}
</script>

<template>
  <div>
    <label v-if="label" class="lbl">{{ label }}</label>

    <!-- Kein Ausdruck gesetzt -->
    <div v-if="!op" class="flex flex-wrap items-center gap-3">
      <span class="text-sm text-gray-400 italic">Keine Bedingung</span>
      <button type="button" class="btn-secondary" @click="addRoot">Bedingung hinzufügen</button>
    </div>

    <div v-else class="space-y-2">
      <div class="flex flex-wrap items-center gap-2">
        <select class="afi" :value="op ?? ''" @change="changeOp(val($event) as Op)">
          <option v-for="o in OPS" :key="o" :value="o">{{ OP_LABEL[o] }}</option>
        </select>

        <!-- Feld-Auswahl: nur Katalog-Schlüssel, nie Freitext -->
        <select v-if="isLeaf" class="afi" :value="fieldKey" @change="setField(val($event))">
          <option value="">Feld wählen…</option>
          <option v-for="k in keys" :key="k" :value="k">{{ k }}</option>
          <!-- Verwaister Verweis bleibt sichtbar, statt still zu verschwinden -->
          <option v-if="fieldKey && !keys.includes(fieldKey)" :value="fieldKey">
            {{ fieldKey }} (unbekannt)
          </option>
        </select>

        <!-- Vergleichswert bei ==/!= -->
        <template v-if="op === '==' || op === '!='">
          <select
            v-if="valueType === 'bool'"
            class="afi"
            :value="rawValue === true ? 'true' : 'false'"
            @change="setValue(val($event) === 'true')"
          >
            <option value="true">Ja</option>
            <option value="false">Nein</option>
          </select>
          <input
            v-else-if="valueType === 'number'"
            type="number"
            class="afi w-32"
            :value="typeof rawValue === 'number' ? String(rawValue) : ''"
            @input="setNumber(val($event))"
          />
          <input
            v-else
            type="text"
            class="afi w-48"
            placeholder="Wert"
            :value="rawValue === null || rawValue === undefined ? '' : String(rawValue)"
            @input="setValue(val($event))"
          />
          <select class="afi" :value="valueType" @change="setValueType(val($event) as VType)">
            <option v-for="t in VTYPES" :key="t" :value="t">{{ VTYPE_LABEL[t] }}</option>
          </select>
        </template>

        <button
          type="button"
          class="ml-auto text-sm text-gray-400 hover:text-red-500 transition px-1"
          title="Bedingung entfernen"
          @click="push(null)"
        >✕</button>
      </div>

      <!-- Werteliste bei in -->
      <div v-if="op === 'in'" class="space-y-2">
        <div v-if="listValues.length" class="flex flex-wrap gap-2">
          <span
            v-for="(v, i) in listValues"
            :key="`${String(v)}-${i}`"
            class="inline-flex items-center gap-1.5 rounded-full bg-[#3EAAB8]/10 text-[#3EAAB8] px-3 py-1 text-sm"
          >
            {{ String(v) }}
            <button type="button" class="hover:text-red-500 transition" @click="removeListValue(i)">✕</button>
          </span>
        </div>
        <p v-else class="text-sm text-gray-400 italic">Noch keine Werte</p>
        <input
          type="text"
          class="afi w-64"
          placeholder="Wert hinzufügen – Eingabetaste"
          @keydown.enter.prevent="addListValue($event)"
          @blur="addListValue($event)"
        />
      </div>

      <!-- Verschachtelte Bedingungen -->
      <div
        v-if="isGroup || op === 'not'"
        class="border-l-2 border-gray-200 dark:border-white/10 pl-3 space-y-2"
      >
        <ConditionEditor
          v-for="(c, i) in children"
          :key="i"
          :model-value="c"
          :field-keys="keys"
          @update:model-value="(v) => updateChild(i, v)"
        />
        <p v-if="!children.length" class="text-sm text-gray-400 italic">Keine Unter-Bedingung</p>
        <button v-if="isGroup" type="button" class="btn-secondary" @click="addChild">
          Bedingung hinzufügen
        </button>
      </div>
    </div>
  </div>
</template>

