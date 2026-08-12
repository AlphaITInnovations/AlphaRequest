<script setup lang="ts">
/** Detail-Editor der ausgewählten Phase: Stammdaten, Zuständigkeit, Felder,
 *  Regeln und Automationen. */
import { computed } from 'vue'
import type {
  ApprovalSpec, Condition, FieldDef, FieldMode, PhaseConstraint, PhaseDef, PhaseKind, PhaseView,
} from '@/types/process'
import {
  ENTER_STATUS, FIELD_MODES, FIELD_MODE_LABEL, PHASE_KINDS, PHASE_KIND_LABEL,
  PHASE_VIEWS, PHASE_VIEW_LABEL, STATUS_LABEL, blankApproval, blankFieldRef,
  isValidPhaseKey, phaseKindPatch,
} from '@/lib/processSchema'
import ApprovalEditor from './ApprovalEditor.vue'
import ResponsibilityEditor from './ResponsibilityEditor.vue'
import ConditionEditor from './ConditionEditor.vue'
import ConditionSummary from './ConditionSummary.vue'
import AutomationList from './AutomationList.vue'
import LayoutEditor from './LayoutEditor.vue'

const props = defineProps<{
  modelValue: PhaseDef
  index: number
  catalog: FieldDef[]
  groups: { id: string; name: string }[]
  users: { id: string; displayName: string }[]
  fieldKeys: string[]
  fieldLabels?: Record<string, string>
  takenIds?: string[]
  /** Alle Phasen des Prozesses – für den Rücksprung einer Freigabe nötig. */
  phases?: { key: string; label: string | null }[]
  readonly?: boolean
}>()

const emit = defineEmits<{ 'update:modelValue': [value: PhaseDef] }>()

function patch(part: Partial<PhaseDef>) {
  emit('update:modelValue', { ...props.modelValue, ...part })
}

const keyValid = computed(() => !props.modelValue.key || isValidPhaseKey(props.modelValue.key))

/** Phasen-Art umstellen – Freigabe-Block und Ansicht ziehen mit (Server-Regel). */
function setKind(kind: PhaseKind) {
  if (kind === props.modelValue.kind) return
  patch(phaseKindPatch(props.modelValue, kind))
}

/** Nur Phasen VOR dieser taugen als Rücksprung-Ziel. */
const earlierPhases = computed(() => (props.phases ?? []).slice(0, props.index))

/** Katalog-Felder, die in dieser Phase noch nicht eingebunden sind. */
const available = computed(() => {
  const used = new Set(props.modelValue.fields.map((f) => f.ref))
  return props.catalog.filter((f) => !used.has(f.key))
})

function addFieldRef(ref: string) {
  if (!ref) return
  patch({ fields: [...props.modelValue.fields, blankFieldRef(ref)] })
}
function patchFieldRef(i: number, part: Record<string, unknown>) {
  patch({ fields: props.modelValue.fields.map((f, j) => (j === i ? { ...f, ...part } : f)) })
}
function removeFieldRef(i: number) {
  patch({ fields: props.modelValue.fields.filter((_, j) => j !== i) })
}
function moveFieldRef(i: number, delta: number) {
  const t = i + delta
  if (t < 0 || t >= props.modelValue.fields.length) return
  const next = [...props.modelValue.fields]
  const [item] = next.splice(i, 1)
  next.splice(t, 0, item)
  patch({ fields: next })
}

function addConstraint() {
  patch({ constraints: [...props.modelValue.constraints, { when: { truthy: '' }, message: '' }] })
}
function patchConstraint(i: number, part: Partial<PhaseConstraint>) {
  patch({ constraints: props.modelValue.constraints.map((c, j) => (j === i ? { ...c, ...part } : c)) })
}
function removeConstraint(i: number) {
  patch({ constraints: props.modelValue.constraints.filter((_, j) => j !== i) })
}

function labelFor(ref: string) {
  return props.fieldLabels?.[ref] || ref
}
</script>

<template>
  <div class="space-y-5">
    <!-- Stammdaten -->
    <section class="card-section">
      <h3 class="section-title">Phase</h3>
      <div class="grid md:grid-cols-2 gap-3">
        <div>
          <label class="block text-xs text-gray-500 dark:text-gray-400 mb-1">Bezeichnung</label>
          <input :value="modelValue.label ?? ''" :disabled="readonly" class="afi w-full"
                 placeholder="z. B. Prüfung durch IT"
                 @input="patch({ label: ($event.target as HTMLInputElement).value || null })" />
        </div>
        <div>
          <label class="block text-xs text-gray-500 dark:text-gray-400 mb-1">Schlüssel</label>
          <input :value="modelValue.key" :disabled="readonly" class="afi w-full font-mono text-sm"
                 :class="keyValid ? '' : 'ring-1 ring-red-400'"
                 @input="patch({ key: ($event.target as HTMLInputElement).value })" />
          <p v-if="!keyValid" class="text-xs text-red-500 mt-1">
            Nur Kleinbuchstaben, Ziffern und Unterstrich.
          </p>
        </div>
        <div>
          <label class="block text-xs text-gray-500 dark:text-gray-400 mb-1">Art</label>
          <select :value="modelValue.kind" :disabled="readonly" class="afi w-full"
                  @change="setKind(($event.target as HTMLSelectElement).value as PhaseKind)">
            <option v-for="k in PHASE_KINDS" :key="k" :value="k">{{ PHASE_KIND_LABEL[k] }}</option>
          </select>
        </div>
        <div>
          <label class="block text-xs text-gray-500 dark:text-gray-400 mb-1">Ansicht</label>
          <select :value="modelValue.view" :disabled="readonly" class="afi w-full"
                  @change="patch({ view: ($event.target as HTMLSelectElement).value as PhaseView })">
            <!-- „Freigabe" passt nur zur gleichnamigen Phasen-Art (Server-Regel). -->
            <option v-for="v in PHASE_VIEWS" :key="v" :value="v"
                    :disabled="v === 'approval' && modelValue.kind !== 'approval'">
              {{ PHASE_VIEW_LABEL[v] }}
            </option>
          </select>
        </div>
        <div>
          <label class="block text-xs text-gray-500 dark:text-gray-400 mb-1">
            Status beim Betreten
          </label>
          <select :value="modelValue.enterStatus ?? ''" :disabled="readonly" class="afi w-full"
                  @change="patch({ enterStatus: ($event.target as HTMLSelectElement).value || null })">
            <option value="">Automatisch</option>
            <option v-for="s in ENTER_STATUS" :key="s" :value="s">{{ STATUS_LABEL[s] }}</option>
          </select>
          <p class="text-[11px] text-gray-400 mt-1">
            Automatisch: „In Prüfung" bei Fachabteilungen, sonst „In Bearbeitung".
          </p>
        </div>
        <div class="flex items-start pt-5">
          <label class="flex items-start gap-2 text-sm text-gray-700 dark:text-gray-200">
            <input type="checkbox" :checked="modelValue.grantsFullView" :disabled="readonly"
                   class="mt-0.5 h-4 w-4 rounded border-gray-300 dark:border-white/20 text-[#3EAAB8]"
                   @change="patch({ grantsFullView: ($event.target as HTMLInputElement).checked })" />
            <span>
              Volle Sicht für Bearbeitende
              <span class="block text-[11px] text-gray-400">
                Wer diese Phase bearbeitet, sieht alle nicht-vertraulichen Felder.
              </span>
            </span>
          </label>
        </div>
      </div>
    </section>

    <!-- Freigabe (nur bei der Phasen-Art „Freigabe") -->
    <section v-if="modelValue.kind === 'approval'" class="card-section">
      <h3 class="section-title">Freigabe</h3>
      <p class="text-sm text-gray-500 dark:text-gray-400 mb-3">
        Eine Frage, zwei Antworten. Wer entscheidet, steht unten unter „Wer bearbeitet".
      </p>
      <ApprovalEditor v-if="modelValue.approval" :model-value="modelValue.approval"
                      :earlier-phases="earlierPhases" :field-keys="fieldKeys"
                      :field-labels="fieldLabels" :readonly="readonly"
                      @update:model-value="patch({ approval: $event as ApprovalSpec })" />
      <div v-else class="rounded-xl border border-red-200 dark:border-red-500/30 bg-red-50
                         dark:bg-red-900/20 px-4 py-3 text-sm text-red-800 dark:text-red-200
                         flex items-center justify-between gap-3">
        <span>Diese Freigabe-Phase hat noch keine Frage – so lässt sie sich nicht speichern.</span>
        <button v-if="!readonly" class="btn-secondary text-xs py-1 shrink-0"
                @click="patch({ approval: blankApproval() })">Freigabe einrichten</button>
      </div>
    </section>

    <!-- Zuständigkeit -->
    <section class="card-section">
      <h3 class="section-title">Wer bearbeitet</h3>
      <ResponsibilityEditor :model-value="modelValue.responsibility" :groups="groups" :users="users"
                            :catalog="catalog"
                            :field-keys="fieldKeys" :field-labels="fieldLabels" :readonly="readonly"
                            @update:model-value="patch({ responsibility: $event })" />
    </section>

    <!-- Felder -->
    <section class="card-section">
      <div class="flex items-center justify-between mb-2">
        <h3 class="section-title mb-0">Felder in dieser Phase</h3>
        <select v-if="!readonly && available.length" class="afi text-sm" :value="''"
                @change="addFieldRef(($event.target as HTMLSelectElement).value); ($event.target as HTMLSelectElement).value = ''">
          <option value="">+ Feld hinzufügen…</option>
          <option v-for="f in available" :key="f.key" :value="f.key">{{ f.label || f.key }}</option>
        </select>
      </div>
      <p v-if="!modelValue.fields.length" class="text-sm text-gray-400 italic">
        Keine Felder – in dieser Phase wird nichts ausgefüllt.
      </p>

      <div v-for="(fr, i) in modelValue.fields" :key="i" :id="`pe-phase-${index}-field-${i}`"
           class="rounded-xl border border-gray-200 dark:border-white/10 p-3 mb-2 space-y-2">
        <div class="flex items-center gap-2 flex-wrap">
          <span class="font-medium text-sm text-gray-800 dark:text-gray-100">{{ labelFor(fr.ref) }}</span>
          <span class="text-[11px] font-mono text-gray-400">{{ fr.ref }}</span>
          <span v-if="!fieldKeys.includes(fr.ref)"
                class="text-[11px] px-1.5 py-0.5 rounded bg-red-100 text-red-700">nicht im Katalog</span>
          <div class="ml-auto flex items-center gap-1">
            <button v-if="!readonly" @click="moveFieldRef(i, -1)" :disabled="i === 0"
                    aria-label="Nach oben" class="px-1 text-gray-400 hover:text-gray-700 disabled:opacity-30">▲</button>
            <button v-if="!readonly" @click="moveFieldRef(i, 1)" :disabled="i === modelValue.fields.length - 1"
                    aria-label="Nach unten" class="px-1 text-gray-400 hover:text-gray-700 disabled:opacity-30">▼</button>
            <button v-if="!readonly" @click="removeFieldRef(i)" aria-label="Feld entfernen"
                    class="px-1 text-gray-400 hover:text-red-500">✕</button>
          </div>
        </div>

        <div class="grid md:grid-cols-2 gap-2">
          <div>
            <label class="block text-[11px] text-gray-500 mb-1">Bearbeitbarkeit</label>
            <select :value="fr.mode" :disabled="readonly" class="afi w-full text-sm"
                    @change="patchFieldRef(i, { mode: ($event.target as HTMLSelectElement).value as FieldMode })">
              <option v-for="m in FIELD_MODES" :key="m" :value="m">{{ FIELD_MODE_LABEL[m] }}</option>
            </select>
          </div>
          <div class="flex items-end pb-2">
            <label class="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-200">
              <input type="checkbox" :checked="fr.required" :disabled="readonly"
                     class="h-4 w-4 rounded border-gray-300 dark:border-white/20 text-[#3EAAB8]"
                     @change="patchFieldRef(i, { required: ($event.target as HTMLInputElement).checked })" />
              Pflichtfeld
            </label>
          </div>
        </div>

        <details class="text-sm">
          <summary class="cursor-pointer text-xs text-gray-500 dark:text-gray-400 select-none">
            Bedingungen · sichtbar wenn:
            <ConditionSummary :condition="fr.visibleWhen" :field-labels="fieldLabels" />
            · pflicht wenn: <ConditionSummary :condition="fr.requiredWhen" :field-labels="fieldLabels" />
          </summary>
          <div class="mt-2 space-y-3 pl-1">
            <div>
              <div class="text-[11px] text-gray-500 mb-1">Nur anzeigen, wenn</div>
              <ConditionEditor :model-value="fr.visibleWhen" :field-keys="fieldKeys"
                               @update:model-value="patchFieldRef(i, { visibleWhen: $event as Condition | null })" />
            </div>
            <div>
              <div class="text-[11px] text-gray-500 mb-1">Nur Pflicht, wenn</div>
              <ConditionEditor :model-value="fr.requiredWhen" :field-keys="fieldKeys"
                               @update:model-value="patchFieldRef(i, { requiredWhen: $event as Condition | null })" />
            </div>
          </div>
        </details>
      </div>
    </section>

    <!-- Darstellung -->
    <section class="card-section">
      <h3 class="section-title">Darstellung des Formulars</h3>
      <p class="text-sm text-gray-500 dark:text-gray-400 mb-3">
        Abschnitte, Breiten und Design-Elemente. Das steuert nur, <b>wie</b> das
        Formular aussieht – <b>was</b> ein Feld tut (Pflicht, Bedingungen), steht oben
        bei den Feldern.
      </p>
      <LayoutEditor :model-value="modelValue.layout" :fields="modelValue.fields"
                    :field-labels="fieldLabels" :readonly="readonly"
                    @update:model-value="patch({ layout: $event })" />
    </section>

    <!-- Regeln -->
    <section class="card-section">
      <div class="flex items-center justify-between mb-2">
        <h3 class="section-title mb-0">Regeln zum Abschluss</h3>
        <button v-if="!readonly" @click="addConstraint" class="btn-secondary text-xs py-1">+ Regel</button>
      </div>
      <p v-if="!modelValue.constraints.length" class="text-sm text-gray-400 italic">
        Keine zusätzlichen Regeln. (Feldübergreifend, z. B. „mindestens eine Auswahl".)
      </p>
      <div v-for="(c, i) in modelValue.constraints" :key="i"
           class="rounded-xl border border-gray-200 dark:border-white/10 p-3 mb-2 space-y-2">
        <div class="flex items-center gap-2">
          <input :value="c.message" :disabled="readonly" class="afi flex-1"
                 placeholder="Meldung, wenn die Regel nicht erfüllt ist"
                 @input="patchConstraint(i, { message: ($event.target as HTMLInputElement).value })" />
          <button v-if="!readonly" @click="removeConstraint(i)" class="text-gray-400 hover:text-red-500 px-1"
                  aria-label="Regel entfernen">✕</button>
        </div>
        <div class="text-[11px] text-gray-500">Abschluss nur möglich, wenn:</div>
        <ConditionEditor :model-value="c.when" :field-keys="fieldKeys"
                         @update:model-value="patchConstraint(i, { when: ($event ?? {}) as Condition })" />
      </div>
    </section>

    <!-- Automationen -->
    <section class="card-section">
      <AutomationList :model-value="modelValue.automations" :field-keys="fieldKeys"
                      :field-labels="fieldLabels" :groups="groups" title="Automationen dieser Phase"
                      :taken-ids="takenIds" :readonly="readonly"
                      @update:model-value="patch({ automations: $event })" />
    </section>
  </div>
</template>
