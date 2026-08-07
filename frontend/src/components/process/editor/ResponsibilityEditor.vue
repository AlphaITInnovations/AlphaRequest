<script setup lang="ts">
/** Zuständigkeit einer Phase: wer bearbeitet sie? */
import type { Condition, DepartmentRule, Responsibility, ResponsibilityKind } from '@/types/process'
import {
  RESPONSIBILITY_KINDS, RESPONSIBILITY_LABEL, blankDepartmentRule,
} from '@/lib/processSchema'
import GroupPicker from './GroupPicker.vue'
import ConditionEditor from './ConditionEditor.vue'
import ConditionSummary from './ConditionSummary.vue'

const props = defineProps<{
  modelValue: Responsibility
  groups: { id: string; name: string }[]
  users: { id: string; displayName: string }[]
  fieldKeys: string[]
  fieldLabels?: Record<string, string>
  readonly?: boolean
}>()

const emit = defineEmits<{ 'update:modelValue': [value: Responsibility] }>()

function patch(part: Partial<Responsibility>) {
  emit('update:modelValue', { ...props.modelValue, ...part })
}

function setKind(kind: ResponsibilityKind) {
  // Nicht mehr passende Felder zurücksetzen – der Server prüft sie streng.
  patch({
    kind,
    group: kind === 'group' ? props.modelValue.group : null,
    user: kind === 'user' ? props.modelValue.user : null,
    rule: kind === 'departments'
      ? (props.modelValue.rule.length ? props.modelValue.rule : [blankDepartmentRule()])
      : [],
  })
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
    <p v-else-if="modelValue.kind === 'originator'" class="text-xs text-gray-400">
      Die auslösende Person eines Folgeprozesses. (Nur sinnvoll bei verknüpften Prozessen.)
    </p>
  </div>
</template>
