<script setup lang="ts">
/** Zuständigkeit einer Phase: wer bearbeitet sie? */
import type { Condition, DepartmentRule, Responsibility, ResponsibilityKind } from '@/types/process'
import {
  RESPONSIBILITY_KINDS, RESPONSIBILITY_LABEL, blankDepartmentRule, responsibilityKindPatch,
} from '@/lib/processSchema'
import { computed } from 'vue'
import GroupPicker from './GroupPicker.vue'
import ConditionEditor from './ConditionEditor.vue'
import ConditionSummary from './ConditionSummary.vue'

const props = defineProps<{
  modelValue: Responsibility
  groups: { id: string; name: string }[]
  users: { id: string; displayName: string }[]
  fieldKeys: string[]
  /**
   * Feld-Katalog: gebraucht, um die Quellfelder anzubieten – Personen-Felder für
   * kind=assignable, Fachabteilungs-Felder für kind=group_from_field.
   */
  catalog?: { key: string; widget: string }[]
  fieldLabels?: Record<string, string>
  readonly?: boolean
}>()

const emit = defineEmits<{ 'update:modelValue': [value: Responsibility] }>()

/** Nur Personen-Felder taugen als Quelle für „Person aus einem Feld". */
const userFieldKeys = computed(() =>
  (props.catalog ?? []).filter((f) => f.widget === 'user').map((f) => f.key))
/** Nur Fachabteilungs-Felder taugen als Quelle für „Fachabteilung aus einem Feld". */
const groupFieldKeys = computed(() =>
  (props.catalog ?? []).filter((f) => f.widget === 'group').map((f) => f.key))

function patch(part: Partial<Responsibility>) {
  emit('update:modelValue', { ...props.modelValue, ...part })
}

function setKind(kind: ResponsibilityKind) {
  // Nicht mehr passende Angaben fliegen raus – der Server prüft sie streng.
  emit('update:modelValue', responsibilityKindPatch(props.modelValue, kind))
}

function patchRule(i: number, part: Partial<DepartmentRule>) {
  const rule = props.modelValue.rule.map((r, j) => (j === i ? { ...r, ...part } : r))
  patch({ rule })
}
function addRule() { patch({ rule: [...props.modelValue.rule, blankDepartmentRule()] }) }
function removeRule(i: number) { patch({ rule: props.modelValue.rule.filter((_, j) => j !== i) }) }
</script>

<template>
  <div class="space-y-3">
    <div>
      <label class="block text-xs text-gray-500 dark:text-gray-400 mb-1">Zuständigkeit</label>
      <select :value="modelValue.kind" :disabled="readonly" class="afi w-full"
              @change="setKind(($event.target as HTMLSelectElement).value as ResponsibilityKind)">
        <option v-for="k in RESPONSIBILITY_KINDS" :key="k" :value="k">
          {{ RESPONSIBILITY_LABEL[k] }}
        </option>
      </select>
    </div>

    <div v-if="modelValue.kind === 'group'">
      <label class="block text-xs text-gray-500 dark:text-gray-400 mb-1">Fachabteilung</label>
      <GroupPicker :model-value="modelValue.group" :groups="groups"
                   @update:model-value="patch({ group: $event })" />
    </div>

    <div v-else-if="modelValue.kind === 'assignable'">
      <label class="block text-xs text-gray-500 dark:text-gray-400 mb-1">
        Personen-Feld, das die Zuständigkeit trägt
      </label>
      <select :value="modelValue.fromField ?? ''" :disabled="readonly" class="afi w-full"
              @change="patch({ fromField: ($event.target as HTMLSelectElement).value || null })">
        <option value="">– bitte wählen –</option>
        <option v-for="k in userFieldKeys" :key="k" :value="k">
          {{ fieldLabels?.[k] || k }}
        </option>
      </select>
      <p v-if="!userFieldKeys.length" class="text-xs text-amber-600 dark:text-amber-400 mt-1">
        Es gibt noch kein Feld vom Typ „Person" – bitte zuerst im Feld-Katalog anlegen.
      </p>
      <p v-else class="text-[11px] text-gray-400 mt-1">
        Zuständig ist, wer in diesem Feld eingetragen ist – so wie im Alt-System die
        bei der Erstellung ausgewählte Person.
      </p>
    </div>

    <div v-else-if="modelValue.kind === 'group_from_field'">
      <label class="block text-xs text-gray-500 dark:text-gray-400 mb-1">
        Fachabteilungs-Feld, das die Zuständigkeit trägt
      </label>
      <select :value="modelValue.fromField ?? ''" :disabled="readonly" class="afi w-full"
              @change="patch({ fromField: ($event.target as HTMLSelectElement).value || null })">
        <option value="">– bitte wählen –</option>
        <option v-for="k in groupFieldKeys" :key="k" :value="k">
          {{ fieldLabels?.[k] || k }}
        </option>
      </select>
      <p v-if="!groupFieldKeys.length" class="text-xs text-amber-600 dark:text-amber-400 mt-1">
        Es gibt noch kein Feld vom Typ „Fachabteilung" – bitte zuerst im Feld-Katalog anlegen.
      </p>
      <p v-else class="text-[11px] text-gray-400 mt-1">
        Zuständig ist die Fachabteilung, die in diesem Feld steht – die erstellende
        Person wählt sie also selbst aus (Muster des Basis-Tickets).
      </p>
    </div>

    <div v-else-if="modelValue.kind === 'user'">
      <label class="block text-xs text-gray-500 dark:text-gray-400 mb-1">Person</label>
      <select :value="modelValue.user ?? ''" :disabled="readonly" class="afi w-full"
              @change="patch({ user: ($event.target as HTMLSelectElement).value || null })">
        <option value="">– bitte wählen –</option>
        <option v-for="u in users" :key="u.id" :value="u.id">{{ u.displayName }}</option>
      </select>
    </div>

    <div v-else-if="modelValue.kind === 'departments'" class="space-y-2">
      <div class="flex items-center justify-between">
        <span class="text-xs text-gray-500 dark:text-gray-400">Beteiligte Fachabteilungen</span>
        <button v-if="!readonly" @click="addRule" class="btn-secondary text-xs py-1">+ Abteilung</button>
      </div>
      <p v-if="!modelValue.rule.length" class="text-xs text-gray-400 italic">
        Noch keine Fachabteilung – die Phase hätte niemanden, der sie bearbeitet.
      </p>
      <div v-for="(r, i) in modelValue.rule" :key="i"
           class="rounded-xl border border-gray-200 dark:border-white/10 p-3 space-y-2">
        <div class="flex items-center gap-2">
          <GroupPicker class="flex-1" :model-value="r.group" :groups="groups"
                       @update:model-value="patchRule(i, { group: $event ?? '' })" />
          <label class="flex items-center gap-1 text-xs text-gray-600 dark:text-gray-300 whitespace-nowrap">
            <input type="checkbox" :checked="r.required" :disabled="readonly"
                   class="h-4 w-4 rounded border-gray-300 dark:border-white/20 text-[#3EAAB8]"
                   @change="patchRule(i, { required: ($event.target as HTMLInputElement).checked })" />
            Pflicht
          </label>
          <button v-if="!readonly" @click="removeRule(i)" class="text-gray-400 hover:text-red-500 px-1"
                  aria-label="Abteilung entfernen">✕</button>
        </div>
        <div>
          <div class="text-[11px] text-gray-400 mb-1">
            Nur beteiligt, wenn: <ConditionSummary :condition="r.when" :field-labels="fieldLabels" />
          </div>
          <ConditionEditor v-if="!readonly" :model-value="r.when" :field-keys="fieldKeys"
                           @update:model-value="patchRule(i, { when: $event as Condition | null })" />
        </div>
      </div>
    </div>

    <p v-else-if="modelValue.kind === 'owner'" class="text-xs text-gray-400">
      Die Person, die den Auftrag angelegt hat, bearbeitet diese Phase.
    </p>

    <!-- Gilt für jede Zuständigkeits-Art, daher NACH der Kette (nicht darin). -->
    <label class="flex items-start gap-2 text-sm text-gray-700 dark:text-gray-200 pt-3
                  border-t border-gray-100 dark:border-white/[0.06]">
      <input type="checkbox" :checked="modelValue.notifyOnEnter" :disabled="readonly"
             class="mt-0.5 h-4 w-4 rounded border-gray-300 dark:border-white/20 text-[#3EAAB8]"
             @change="patch({ notifyOnEnter: ($event.target as HTMLInputElement).checked })" />
      <span>
        Beim Betreten benachrichtigen
        <span class="block text-[11px] text-gray-400">
          Die zuständige Stelle bekommt automatisch eine Mail. Ohne das erfährt
          niemand, dass Arbeit ansteht. (Bei „Ersteller:in" entfällt die Mail –
          die Person hat gerade selbst gehandelt.)
        </span>
      </span>
    </label>
  </div>
</template>
