<script setup lang="ts">
/**
 * Editor für EIN Feld des Prozess-Katalogs.
 *
 * Grundsatz: Es wird immer eine vollständige FieldDef nach oben gemeldet
 * (Spread + Änderung). Der Editor mutiert das Prop nie selbst – so bleibt der
 * Dirty-Vergleich des Elternteils (canonicalJson) verlässlich.
 *
 * Leere Teil-Objekte werden bewusst auf `null` zurückgesetzt (constraints,
 * visibility, computed): Der Server liefert genau diese Form zurück, und ein
 * leeres Objekt statt `null` würde den Entwurf dauerhaft als geändert zeigen.
 */
import { computed, ref, watch } from 'vue'
import type {
  AssignSpec, FieldConstraints, FieldDef, FieldVisibility, OptionsSource, Widget,
} from '@/types/process'
import {
  COUNTER_LABEL, OPTIONS_SOURCES, SEQUENCE_COUNTERS, WIDGETS_TOP, WIDGET_LABEL,
  blankAssign, blankConstraints, isValidFieldKey,
} from '@/lib/processSchema'
import OptionListEditor from '@/components/process/editor/OptionListEditor.vue'
import SubFieldEditor from '@/components/process/editor/SubFieldEditor.vue'
import GroupMultiPicker from '@/components/process/editor/GroupMultiPicker.vue'

const props = defineProps<{
  modelValue: FieldDef
  groups: { id: string; name: string }[]
  fieldKeys: string[]
}>()

const emit = defineEmits<{
  'update:modelValue': [value: FieldDef]
  remove: []
}>()

// ── Beschriftungen, die es nicht als Konstante gibt (Werte kommen aus der Whitelist) ──

const SOURCE_LABEL: Record<OptionsSource, string> = {
  static: 'Feste Liste', groups: 'Fachabteilungen', companies: 'Firmen', users: 'Personen',
}

/** Widgets, bei denen eine Optionsquelle überhaupt ausgewertet wird. */
const OPTION_WIDGETS: readonly Widget[] =
  ['select', 'multiselect', 'checkbox-group', 'user', 'company', 'group']
/** Widgets mit Text-Regeln (Muster/Länge). */
const TEXT_WIDGETS: readonly Widget[] = ['text', 'textarea']

// ── Sichere Zugriffe (importierte Definitionen können Keys weglassen) ─────────

const opts = computed(() => props.modelValue.options ?? [])
const items = computed(() => props.modelValue.item ?? [])
const cons = computed<FieldConstraints | null>(() => props.modelValue.constraints ?? null)
const vis = computed<FieldVisibility>(() =>
  props.modelValue.visibility ?? { confidential: false, visibleToGroups: [] })
const allKeys = computed(() => props.fieldKeys ?? [])

// ── Aufklappbare Abschnitte: offen, wenn es dort schon etwas zu sehen gibt ────

type SectionKey = 'options' | 'sub' | 'assign' | 'rules' | 'visibility' | 'computed'
const open = ref<Record<SectionKey, boolean>>({
  options: opts.value.length > 0 || props.modelValue.optionsSource !== null,
  sub: items.value.length > 0,
  assign: props.modelValue.widget === 'server_generated',
  rules: props.modelValue.constraints !== null,
  visibility: props.modelValue.visibility !== null,
  computed: props.modelValue.computed !== null,
})
function toggle(k: SectionKey) {
  open.value[k] = !open.value[k]
}

// ── Änderungen ────────────────────────────────────────────────────────────────

function patch(p: Partial<FieldDef>) {
  emit('update:modelValue', { ...props.modelValue, ...p })
}

/**
 * Der Schlüssel wird lokal gepuffert und erst bei Blur/Enter übernommen.
 * Grund: eine Schlüssel-Änderung zieht ALLE Referenzen nach (Phasen, Bedingungen,
 * Automationen). Bei jedem Tastendruck zu benennen hätte Zwischenstände wie
 * „emai" als eigenständige Umbenennung behandelt und fremde Felder mitgerissen.
 */
const keyDraft = ref(props.modelValue.key)
watch(() => props.modelValue.key, (v) => { keyDraft.value = v })

function commitKey() {
  const next = keyDraft.value.trim()
  if (next !== props.modelValue.key) patch({ key: next })
  else keyDraft.value = props.modelValue.key
}

function setWidget(w: Widget) {
  const next: FieldDef = { ...props.modelValue, widget: w }
  // Unterfelder und „Nur anhängen" gibt es ausschließlich bei Wiederholgruppen –
  // der Server lehnt sie sonst ab.
  if (w !== 'collection') {
    next.item = []
    if (next.mode === 'append_only') next.mode = null
  }
  // Ein vom System vergebener Wert braucht die Vergabe-Angaben (Server-Regel);
  // bei jedem anderen Feldtyp wären sie wirkungslos.
  if (w === 'server_generated') {
    next.assign = next.assign ?? blankAssign()
    open.value.assign = true
  } else if (next.assign) {
    next.assign = null
  }
  emit('update:modelValue', next)
}

function setAssign(p: Partial<AssignSpec>) {
  patch({ assign: { ...(props.modelValue.assign ?? blankAssign()), ...p } })
}

const toStr = (v: string): string | null => (v.trim() === '' ? null : v)
const toNum = (v: string): number | null =>
  v.trim() === '' || Number.isNaN(Number(v)) ? null : Number(v)

function setC(p: Partial<FieldConstraints>) {
  const cur: FieldConstraints = props.modelValue.constraints ?? blankConstraints()
  const next: FieldConstraints = { ...cur, ...p }
  const empty = next.pattern === null && next.minLength === null && next.maxLength === null
    && next.min === null && next.max === null && next.minDate === null && next.maxDate === null
  patch({ constraints: empty ? null : next })
}

function setVis(p: Partial<FieldVisibility>) {
  const next: FieldVisibility = { ...vis.value, ...p }
  patch({ visibility: !next.confidential && next.visibleToGroups.length === 0 ? null : next })
}

function setComputedFrom(v: string) {
  // Ohne Quelle ergibt „überschreibbar" keinen Sinn und wird mit zurückgesetzt.
  patch({ computed: v ? { from: v } : null, overridable: v ? props.modelValue.overridable : false })
}

function setAppendOnly(on: boolean) {
  patch({ mode: on ? 'append_only' : null })
}

// ── Anzeige-Logik ─────────────────────────────────────────────────────────────

/** Auch bei „unpassendem" Widget zeigen, wenn Daten da sind – sonst wären sie unsichtbar. */
const showOptions = computed(() =>
  OPTION_WIDGETS.includes(props.modelValue.widget)
  || opts.value.length > 0 || props.modelValue.optionsSource !== null)
const optionsMismatch = computed(() =>
  !OPTION_WIDGETS.includes(props.modelValue.widget) && showOptions.value)

const showSub = computed(() => props.modelValue.widget === 'collection' || items.value.length > 0)
const subMismatch = computed(() => props.modelValue.widget !== 'collection' && items.value.length > 0)

// ── Nummernvergabe (widget=server_generated) ──────────────────────────────────

const isGenerated = computed(() => props.modelValue.widget === 'server_generated')
const showAssign = computed(() => isGenerated.value || props.modelValue.assign !== null)
const assignMismatch = computed(() => !isGenerated.value && props.modelValue.assign !== null)
const assignMissing = computed(() => isGenerated.value && props.modelValue.assign === null)
const counterUnknown = computed(() => {
  const c = props.modelValue.assign?.counter
  return !!c && !SEQUENCE_COUNTERS.includes(c)
})
/** Kandidaten für das Firmen-Feld. Der Katalog kommt hier nur als Schlüsselliste
 *  an, deshalb keine Filterung auf den Feldtyp – der Hinweistext sagt es. */
const companyKeys = computed(() => [...new Set(allKeys.value.filter(Boolean))])

const hasTextRules = computed(() => TEXT_WIDGETS.includes(props.modelValue.widget))
const hasNumberRules = computed(() => props.modelValue.widget === 'number')
const hasDateRules = computed(() => props.modelValue.widget === 'date')
const showRules = computed(() =>
  hasTextRules.value || hasNumberRules.value || hasDateRules.value || cons.value !== null)
const rulesMismatch = computed(() =>
  !hasTextRules.value && !hasNumberRules.value && !hasDateRules.value && cons.value !== null)

const keyError = computed(() => {
  const k = props.modelValue.key ?? ''
  if (!k.trim()) return 'Feld braucht einen Schlüssel.'
  if (!isValidFieldKey(k)) return 'Erlaubt sind Buchstaben, Ziffern, „_" und Punkte als Trennung.'
  if (allKeys.value.filter((x) => x === k).length > 1) return `Schlüssel „${k}" wird mehrfach verwendet.`
  return null
})

const widgetUnknown = computed(() => !WIDGETS_TOP.includes(props.modelValue.widget))

const patternError = computed(() => {
  const p = cons.value?.pattern
  if (!p) return false
  try {
    new RegExp(p)
    return false
  } catch {
    return true
  }
})
const lengthError = computed(() => {
  const c = cons.value
  return !!c && c.minLength !== null && c.maxLength !== null && c.minLength > c.maxLength
})
const rangeError = computed(() => {
  const c = cons.value
  return !!c && c.min !== null && c.max !== null && c.min > c.max
})
const dateError = computed(() => {
  const c = cons.value
  return !!c && !!c.minDate && !!c.maxDate && c.minDate > c.maxDate
})

const confidentialError = computed(() =>
  vis.value.confidential && vis.value.visibleToGroups.length === 0)

/** Kandidaten für „berechnet aus" – das Feld selbst wäre ein Ringschluss. */
const sourceKeys = computed(() =>
  [...new Set(allKeys.value.filter((k) => !!k && k !== props.modelValue.key))])
const computedUnknown = computed(() => {
  const from = props.modelValue.computed?.from
  return !!from && !allKeys.value.includes(from)
})

// ── Kurzfassungen für die zugeklappten Abschnitte ─────────────────────────────

const optionsSummary = computed(() => {
  const src = props.modelValue.optionsSource
  const parts: string[] = [src ? SOURCE_LABEL[src] : 'keine Quelle']
  if (opts.value.length) parts.push(`${opts.value.length} Optionen`)
  if (props.modelValue.allowOther) parts.push('Freitext erlaubt')
  return parts.join(' · ')
})
const subSummary = computed(() =>
  items.value.length ? `${items.value.length} Unterfelder` : 'keine Unterfelder')
const rulesSummary = computed(() => (cons.value ? 'eingeschränkt' : 'keine'))
const visibilitySummary = computed(() => {
  if (!props.modelValue.visibility) return 'für alle sichtbar'
  const n = vis.value.visibleToGroups.length
  return `${vis.value.confidential ? 'vertraulich' : 'eingeschränkt'} · ${n} Fachabteilungen`
})
const computedSummary = computed(() =>
  props.modelValue.computed ? `aus ${props.modelValue.computed.from}` : 'nicht berechnet')
</script>

<template>
  <div class="space-y-3">
    <!-- ── Grunddaten ─────────────────────────────────────────────────────── -->
    <div class="grid md:grid-cols-2 gap-3">
      <div>
        <label class="lbl">Schlüssel</label>
        <input v-model="keyDraft" @change="commitKey" @blur="commitKey"
               @keydown.enter.prevent="($event.target as HTMLInputElement).blur()"
               placeholder="z. B. person.vorname" class="pfi font-mono"
               :class="keyError ? 'border-red-400 bg-red-50 dark:bg-red-900/20' : ''" />
        <p v-if="keyError" class="text-xs text-red-500 mt-1">{{ keyError }}</p>
        <p v-else class="text-xs text-gray-400 mt-1">
          Technischer Name. Phasen und Bedingungen verweisen darauf.
        </p>
      </div>
      <div>
        <label class="lbl">Bezeichnung <span class="text-gray-400 font-normal">(optional)</span></label>
        <input :value="modelValue.label ?? ''"
               @input="patch({ label: toStr(($event.target as HTMLInputElement).value) })"
               placeholder="z. B. Vorname" class="pfi" />
      </div>
      <div>
        <label class="lbl">Feldtyp</label>
        <select :value="modelValue.widget"
                @change="setWidget(($event.target as HTMLSelectElement).value as Widget)"
                class="pfi" :class="widgetUnknown ? 'border-red-400 bg-red-50 dark:bg-red-900/20' : ''">
          <option v-for="w in WIDGETS_TOP" :key="w" :value="w">{{ WIDGET_LABEL[w] }}</option>
          <option v-if="widgetUnknown" :value="modelValue.widget" class="text-red-600">
            Nicht verfügbar: {{ modelValue.widget }}
          </option>
        </select>
      </div>
      <div>
        <label class="lbl">Platzhalter <span class="text-gray-400 font-normal">(optional)</span></label>
        <input :value="modelValue.placeholder ?? ''"
               @input="patch({ placeholder: toStr(($event.target as HTMLInputElement).value) })"
               placeholder="Graue Vorschau im leeren Feld" class="pfi" />
      </div>
      <div class="md:col-span-2">
        <label class="lbl">Hilfetext <span class="text-gray-400 font-normal">(optional)</span></label>
        <textarea :value="modelValue.help ?? ''"
                  @input="patch({ help: toStr(($event.target as HTMLTextAreaElement).value) })"
                  rows="2" placeholder="Erklärung unter dem Feld im Formular"
                  class="pfi resize-none"></textarea>
      </div>
    </div>

    <!-- ── Auswahl ────────────────────────────────────────────────────────── -->
    <div v-if="showOptions" class="rounded-xl border border-gray-200 dark:border-white/10">
      <button type="button" @click="toggle('options')"
              class="w-full flex items-center gap-2 px-3 py-2 text-left rounded-xl
                     hover:bg-gray-50 dark:hover:bg-[#263040] transition">
        <span class="w-3 text-xs text-gray-400">{{ open.options ? '▾' : '▸' }}</span>
        <span class="text-sm font-semibold text-gray-700 dark:text-gray-300">Auswahl</span>
        <span class="text-xs text-gray-400 truncate">{{ optionsSummary }}</span>
      </button>
      <div v-if="open.options"
           class="px-3 pb-3 pt-3 space-y-3 border-t border-gray-200 dark:border-white/10">
        <div v-if="optionsMismatch"
             class="rounded-xl border border-amber-200 dark:border-amber-500/30 bg-amber-50
                    dark:bg-amber-900/20 px-4 py-3 text-sm text-amber-800 dark:text-amber-200">
          Der gewählte Feldtyp wertet keine Auswahl aus. Die Angaben bleiben gespeichert, wirken
          sich aber nicht aus.
        </div>

        <div class="grid md:grid-cols-2 gap-3">
          <div>
            <label class="lbl">Herkunft der Optionen</label>
            <select :value="modelValue.optionsSource ?? ''"
                    @change="patch({ optionsSource:
                      (($event.target as HTMLSelectElement).value || null) as OptionsSource | null })"
                    class="pfi">
              <option value="">— nicht festgelegt —</option>
              <option v-for="s in OPTIONS_SOURCES" :key="s" :value="s">{{ SOURCE_LABEL[s] }}</option>
            </select>
          </div>
          <label class="flex items-center gap-2.5 text-sm text-gray-600 dark:text-gray-300
                        cursor-pointer select-none md:mt-6 w-fit">
            <input type="checkbox" :checked="modelValue.allowOther"
                   @change="patch({ allowOther: ($event.target as HTMLInputElement).checked })"
                   class="h-4 w-4 rounded border-gray-300 dark:border-white/20 text-[#3EAAB8]
                          focus:ring-[#3EAAB8]/30 cursor-pointer" />
            <span>Freie Eingabe zusätzlich erlauben</span>
          </label>
        </div>

        <div v-if="modelValue.optionsSource === null || modelValue.optionsSource === 'static'
                   || opts.length > 0">
          <p class="lbl">Feste Optionen</p>
          <OptionListEditor :model-value="opts"
                            @update:model-value="patch({ options: $event })" />
        </div>
      </div>
    </div>

    <!-- ── Unterfelder ────────────────────────────────────────────────────── -->
    <div v-if="showSub" class="rounded-xl border border-gray-200 dark:border-white/10">
      <button type="button" @click="toggle('sub')"
              class="w-full flex items-center gap-2 px-3 py-2 text-left rounded-xl
                     hover:bg-gray-50 dark:hover:bg-[#263040] transition">
        <span class="w-3 text-xs text-gray-400">{{ open.sub ? '▾' : '▸' }}</span>
        <span class="text-sm font-semibold text-gray-700 dark:text-gray-300">Unterfelder</span>
        <span class="text-xs text-gray-400 truncate">{{ subSummary }}</span>
      </button>
      <div v-if="open.sub"
           class="px-3 pb-3 pt-3 space-y-3 border-t border-gray-200 dark:border-white/10">
        <div v-if="subMismatch"
             class="rounded-xl border border-amber-200 dark:border-amber-500/30 bg-amber-50
                    dark:bg-amber-900/20 px-4 py-3 text-sm text-amber-800 dark:text-amber-200">
          Unterfelder sind nur bei einer Wiederholgruppe erlaubt. Bitte entfernen oder den Feldtyp
          auf „{{ WIDGET_LABEL.collection }}" stellen.
        </div>

        <SubFieldEditor :model-value="items" @update:model-value="patch({ item: $event })" />

        <label class="flex items-start gap-2.5 text-sm text-gray-600 dark:text-gray-300
                      cursor-pointer select-none">
          <input type="checkbox" :checked="modelValue.mode === 'append_only'"
                 @change="setAppendOnly(($event.target as HTMLInputElement).checked)"
                 class="mt-0.5 h-4 w-4 rounded border-gray-300 dark:border-white/20 text-[#3EAAB8]
                        focus:ring-[#3EAAB8]/30 cursor-pointer" />
          <span>
            Nur anhängen
            <span class="block text-xs text-gray-500 dark:text-gray-400">
              Vorhandene Einträge lassen sich danach nie mehr ändern oder löschen – es kommen
              ausschließlich neue hinzu.
            </span>
          </span>
        </label>
      </div>
    </div>

    <!-- ── Nummernvergabe ─────────────────────────────────────────────────── -->
    <div v-if="showAssign" class="rounded-xl border border-gray-200 dark:border-white/10">
      <button type="button" @click="toggle('assign')"
              class="w-full flex items-center gap-2 px-3 py-2 text-left rounded-xl
                     hover:bg-gray-50 dark:hover:bg-[#263040] transition">
        <span class="w-3 text-xs text-gray-400">{{ open.assign ? '▾' : '▸' }}</span>
        <span class="text-sm font-semibold text-gray-700 dark:text-gray-300">Nummernvergabe</span>
        <span class="text-xs truncate" :class="assignMissing ? 'text-red-500' : 'text-gray-400'">
          {{ assignMissing ? 'noch nicht eingerichtet'
            : (modelValue.assign?.counter || 'kein Nummernkreis') }}
        </span>
      </button>
      <div v-if="open.assign"
           class="px-3 pb-3 pt-3 space-y-3 border-t border-gray-200 dark:border-white/10">
        <div v-if="assignMismatch"
             class="rounded-xl border border-amber-200 dark:border-amber-500/30 bg-amber-50
                    dark:bg-amber-900/20 px-4 py-3 text-sm text-amber-800 dark:text-amber-200">
          Eine Nummer vergibt der Server nur beim Feldtyp
          „{{ WIDGET_LABEL.server_generated }}". Hier bleiben die Angaben wirkungslos.
        </div>
        <div v-else
             class="rounded-xl border border-blue-200 dark:border-blue-500/30 bg-blue-50
                    dark:bg-blue-900/20 px-4 py-3 text-sm text-blue-800 dark:text-blue-200">
          Die Nummer vergibt der Server beim Abschluss der <b>ersten Phase</b>, die dieses
          Feld führt. Niemand kann sie eingeben oder ändern – das Feld ist in jeder Phase
          nur lesend.
        </div>

        <div v-if="assignMissing">
          <button type="button" class="btn-secondary text-xs py-1"
                  @click="patch({ assign: blankAssign() })">Nummernvergabe einrichten</button>
        </div>

        <div v-if="modelValue.assign" class="grid md:grid-cols-2 gap-3">
          <div>
            <label class="lbl">Nummernkreis</label>
            <select :value="modelValue.assign.counter ?? ''"
                    @change="setAssign({ counter: toStr(($event.target as HTMLSelectElement).value) })"
                    class="pfi"
                    :class="!modelValue.assign.counter ? 'border-red-400 bg-red-50 dark:bg-red-900/20' : ''">
              <option value="">— bitte wählen —</option>
              <option v-for="c in SEQUENCE_COUNTERS" :key="c" :value="c">
                {{ COUNTER_LABEL[c] ?? c }}
              </option>
              <option v-if="counterUnknown" :value="modelValue.assign.counter" class="text-red-600">
                Unbekannt: {{ modelValue.assign.counter }}
              </option>
            </select>
            <p v-if="!modelValue.assign.counter" class="text-xs text-red-500 mt-1">
              Ohne Nummernkreis lässt sich das Feld nicht speichern.
            </p>
            <p v-else-if="counterUnknown" class="text-xs text-amber-600 dark:text-amber-400 mt-1">
              Diesen Nummernkreis kennt die Laufzeit nicht – die Vergabe bricht später ab.
            </p>
          </div>
          <div>
            <label class="lbl">Firma steht in</label>
            <select :value="modelValue.assign.companyRef ?? ''"
                    @change="setAssign({ companyRef: toStr(($event.target as HTMLSelectElement).value) })"
                    class="pfi">
              <option value="">— nicht festgelegt —</option>
              <option v-for="k in companyKeys" :key="k" :value="k">{{ k }}</option>
            </select>
            <p class="text-xs mt-1"
               :class="modelValue.assign.companyRef ? 'text-gray-400'
                 : 'text-amber-600 dark:text-amber-400'">
              Die Nummernkreise sind je Firma gepflegt. Ohne ein Feld vom Typ
              „{{ WIDGET_LABEL.company }}" bricht die Vergabe beim Phasenabschluss ab.
            </p>
          </div>
        </div>
      </div>
    </div>

    <!-- ── Regeln ─────────────────────────────────────────────────────────── -->
    <div v-if="showRules" class="rounded-xl border border-gray-200 dark:border-white/10">
      <button type="button" @click="toggle('rules')"
              class="w-full flex items-center gap-2 px-3 py-2 text-left rounded-xl
                     hover:bg-gray-50 dark:hover:bg-[#263040] transition">
        <span class="w-3 text-xs text-gray-400">{{ open.rules ? '▾' : '▸' }}</span>
        <span class="text-sm font-semibold text-gray-700 dark:text-gray-300">Regeln</span>
        <span class="text-xs text-gray-400 truncate">{{ rulesSummary }}</span>
      </button>
      <div v-if="open.rules"
           class="px-3 pb-3 pt-3 space-y-3 border-t border-gray-200 dark:border-white/10">
        <div v-if="rulesMismatch"
             class="rounded-xl border border-amber-200 dark:border-amber-500/30 bg-amber-50
                    dark:bg-amber-900/20 px-4 py-3 text-sm text-amber-800 dark:text-amber-200">
          Für diesen Feldtyp gibt es keine Regeln. Die gespeicherten Angaben wirken sich nicht aus.
        </div>

        <div v-if="hasTextRules" class="space-y-3">
          <div>
            <label class="lbl">Muster <span class="text-gray-400 font-normal">(regulärer Ausdruck)</span></label>
            <input :value="cons?.pattern ?? ''"
                   @input="setC({ pattern: toStr(($event.target as HTMLInputElement).value) })"
                   placeholder="z. B. ^[A-Z]{2}-\d{4}$" class="pfi font-mono"
                   :class="patternError ? 'border-red-400 bg-red-50 dark:bg-red-900/20' : ''" />
            <p v-if="patternError" class="text-xs text-red-500 mt-1">
              Ungültiges Muster – bitte einen gültigen regulären Ausdruck angeben.
            </p>
          </div>
          <div class="grid md:grid-cols-2 gap-3">
            <div>
              <label class="lbl">Mindestlänge</label>
              <input :value="cons?.minLength ?? ''" type="number" inputmode="numeric" min="0"
                     @input="setC({ minLength: toNum(($event.target as HTMLInputElement).value) })"
                     class="pfi" />
            </div>
            <div>
              <label class="lbl">Maximallänge</label>
              <input :value="cons?.maxLength ?? ''" type="number" inputmode="numeric" min="0"
                     @input="setC({ maxLength: toNum(($event.target as HTMLInputElement).value) })"
                     class="pfi" />
            </div>
          </div>
          <p v-if="lengthError" class="text-xs text-red-500">
            Die Mindestlänge ist größer als die Maximallänge.
          </p>
        </div>

        <div v-if="hasNumberRules" class="space-y-3">
          <div class="grid md:grid-cols-2 gap-3">
            <div>
              <label class="lbl">Kleinster Wert</label>
              <input :value="cons?.min ?? ''" type="number"
                     @input="setC({ min: toNum(($event.target as HTMLInputElement).value) })"
                     class="pfi" />
            </div>
            <div>
              <label class="lbl">Größter Wert</label>
              <input :value="cons?.max ?? ''" type="number"
                     @input="setC({ max: toNum(($event.target as HTMLInputElement).value) })"
                     class="pfi" />
            </div>
          </div>
          <p v-if="rangeError" class="text-xs text-red-500">
            Der kleinste Wert ist größer als der größte Wert.
          </p>
        </div>

        <div v-if="hasDateRules" class="space-y-3">
          <div class="grid md:grid-cols-2 gap-3">
            <div>
              <label class="lbl">Frühestes Datum</label>
              <input :value="cons?.minDate ?? ''" type="date"
                     @input="setC({ minDate: toStr(($event.target as HTMLInputElement).value) })"
                     class="pfi" />
            </div>
            <div>
              <label class="lbl">Spätestes Datum</label>
              <input :value="cons?.maxDate ?? ''" type="date"
                     @input="setC({ maxDate: toStr(($event.target as HTMLInputElement).value) })"
                     class="pfi" />
            </div>
          </div>
          <p v-if="dateError" class="text-xs text-red-500">
            Das früheste Datum liegt nach dem spätesten Datum.
          </p>
        </div>
      </div>
    </div>

    <!-- ── Sichtbarkeit ───────────────────────────────────────────────────── -->
    <div class="rounded-xl border border-gray-200 dark:border-white/10">
      <button type="button" @click="toggle('visibility')"
              class="w-full flex items-center gap-2 px-3 py-2 text-left rounded-xl
                     hover:bg-gray-50 dark:hover:bg-[#263040] transition">
        <span class="w-3 text-xs text-gray-400">{{ open.visibility ? '▾' : '▸' }}</span>
        <span class="text-sm font-semibold text-gray-700 dark:text-gray-300">Sichtbarkeit</span>
        <span class="text-xs truncate"
              :class="vis.confidential ? 'text-red-500' : 'text-gray-400'">{{ visibilitySummary }}</span>
      </button>
      <div v-if="open.visibility"
           class="px-3 pb-3 pt-3 space-y-3 border-t border-gray-200 dark:border-white/10">
        <div class="rounded-xl border border-blue-200 dark:border-blue-500/30 bg-blue-50
                    dark:bg-blue-900/20 px-4 py-3 text-sm text-blue-800 dark:text-blue-200">
          <p><strong>Vertraulich:</strong> Das Feld sehen ausschließlich Mitglieder der gewählten
            Fachabteilungen. Eine Vollsicht auf den Vorgang genügt dafür nicht.</p>
          <p class="mt-1"><strong>Nicht vertraulich, aber mit Fachabteilungen:</strong> Zusätzlich
            zu den gewählten Fachabteilungen sehen alle Personen mit Vollsicht das Feld.</p>
          <p class="mt-1">Ohne Fachabteilungen und ohne Vertraulichkeit ist das Feld für alle
            Beteiligten sichtbar.</p>
        </div>

        <label class="flex items-center gap-2.5 text-sm text-gray-600 dark:text-gray-300
                      cursor-pointer select-none w-fit">
          <input type="checkbox" :checked="vis.confidential"
                 @change="setVis({ confidential: ($event.target as HTMLInputElement).checked })"
                 class="h-4 w-4 rounded border-gray-300 dark:border-white/20 text-[#3EAAB8]
                        focus:ring-[#3EAAB8]/30 cursor-pointer" />
          <span>Vertraulich</span>
        </label>

        <div>
          <p class="lbl">Berechtigte Fachabteilungen</p>
          <GroupMultiPicker :model-value="vis.visibleToGroups" :groups="groups"
                            @update:model-value="setVis({ visibleToGroups: $event })" />
          <p v-if="confidentialError" class="text-xs text-red-500 mt-1">
            Vertrauliche Felder brauchen mindestens eine berechtigte Fachabteilung.
          </p>
        </div>
      </div>
    </div>

    <!-- ── Berechnet ──────────────────────────────────────────────────────── -->
    <div class="rounded-xl border border-gray-200 dark:border-white/10">
      <button type="button" @click="toggle('computed')"
              class="w-full flex items-center gap-2 px-3 py-2 text-left rounded-xl
                     hover:bg-gray-50 dark:hover:bg-[#263040] transition">
        <span class="w-3 text-xs text-gray-400">{{ open.computed ? '▾' : '▸' }}</span>
        <span class="text-sm font-semibold text-gray-700 dark:text-gray-300">Berechnet</span>
        <span class="text-xs text-gray-400 truncate">{{ computedSummary }}</span>
      </button>
      <div v-if="open.computed"
           class="px-3 pb-3 pt-3 space-y-3 border-t border-gray-200 dark:border-white/10">
        <div class="grid md:grid-cols-2 gap-3">
          <div>
            <label class="lbl">Wert übernehmen aus</label>
            <select :value="modelValue.computed?.from ?? ''"
                    @change="setComputedFrom(($event.target as HTMLSelectElement).value)"
                    class="pfi"
                    :class="computedUnknown ? 'border-red-400 bg-red-50 dark:bg-red-900/20' : ''">
              <option value="">— nicht berechnet —</option>
              <option v-for="k in sourceKeys" :key="k" :value="k">{{ k }}</option>
              <option v-if="computedUnknown" :value="modelValue.computed?.from" class="text-red-600">
                Unbekannt: {{ modelValue.computed?.from }}
              </option>
            </select>
            <p v-if="computedUnknown" class="text-xs text-red-500 mt-1">
              Dieses Feld gibt es im Katalog nicht (mehr).
            </p>
          </div>
          <label v-if="modelValue.computed"
                 class="flex items-center gap-2.5 text-sm text-gray-600 dark:text-gray-300
                        cursor-pointer select-none md:mt-6 w-fit">
            <input type="checkbox" :checked="modelValue.overridable"
                   @change="patch({ overridable: ($event.target as HTMLInputElement).checked })"
                   class="h-4 w-4 rounded border-gray-300 dark:border-white/20 text-[#3EAAB8]
                          focus:ring-[#3EAAB8]/30 cursor-pointer" />
            <span>Überschreibbar</span>
          </label>
        </div>
        <p class="text-xs text-gray-500 dark:text-gray-400">
          Ein berechnetes Feld ohne „Überschreibbar" darf in keiner Phase bearbeitbar sein –
          dort ist nur „Nur lesen" oder „Ausgeblendet" möglich.
        </p>
      </div>
    </div>

    <div class="flex justify-end pt-1">
      <button type="button" @click="emit('remove')"
              class="text-sm text-red-500 hover:text-red-600 hover:underline">Feld entfernen</button>
    </div>
  </div>
</template>

<style scoped>
@reference "../../../style.css";
.pfi {
  @apply w-full rounded-xl border border-gray-200 dark:border-white/10
         bg-white dark:bg-[#263040] text-gray-900 dark:text-gray-100
         px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-[#3EAAB8]/30 transition;
}
</style>
