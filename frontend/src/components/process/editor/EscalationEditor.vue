<script setup lang="ts">
/**
 * Erinnerungen/Eskalation einer Phase: ein An/Aus-Schalter und eine Liste von
 * Stufen (Frist in Tagen → optional Wiederholung → Empfänger → Nachricht →
 * Priorität). Beim Speichern expandiert der Server jede Stufe in eine
 * Timer-Automation (notify bzw. escalate); die bewährte Timer-/Mail-Lauffläche
 * feuert sie unverändert.
 */
import type { EscalationSpec, EscalationStage } from '@/types/process'
import { blankEscalationStage, ESCALATION_MAX_DAYS } from '@/lib/processSchema'
import RecipientPicker from './RecipientPicker.vue'

const props = defineProps<{
  modelValue: EscalationSpec
  groups: { id: string; name: string }[]
  users: { id: string; displayName: string }[]
  readonly?: boolean
}>()

const emit = defineEmits<{ 'update:modelValue': [value: EscalationSpec] }>()

function patch(part: Partial<EscalationSpec>) {
  emit('update:modelValue', { ...props.modelValue, ...part })
}
function setStage(i: number, part: Partial<EscalationStage>) {
  patch({ stages: props.modelValue.stages.map((s, j) => (j === i ? { ...s, ...part } : s)) })
}
function addStage() {
  patch({ stages: [...props.modelValue.stages, blankEscalationStage()] })
}
function removeStage(i: number) {
  patch({ stages: props.modelValue.stages.filter((_, j) => j !== i) })
}

/** Zahl aus einem Eingabefeld (leer/ungültig → 0 bzw. null bei Wiederholung). */
function toInt(v: string): number {
  const n = parseInt(v, 10)
  return Number.isFinite(n) ? n : 0
}
function setRepeatEnabled(i: number, on: boolean) {
  setStage(i, { repeatDays: on ? (props.modelValue.stages[i].repeatDays ?? 7) : null })
}
</script>

<template>
  <div class="space-y-3">
    <!-- Schalter -->
    <label class="flex items-center gap-2.5 text-sm text-gray-700 dark:text-gray-200 select-none">
      <input type="checkbox" :checked="modelValue.enabled" :disabled="readonly"
             class="h-4 w-4 rounded border-gray-300 dark:border-white/20 text-[#3EAAB8] focus:ring-[#3EAAB8]/30"
             @change="patch({ enabled: ($event.target as HTMLInputElement).checked })" />
      Erinnerungen aktiv
    </label>

    <div v-if="modelValue.enabled" class="space-y-3">
      <p v-if="!modelValue.stages.length" class="text-sm text-gray-400 italic">
        Noch keine Stufe – bitte mindestens eine hinzufügen.
      </p>

      <div v-for="(st, i) in modelValue.stages" :key="i"
           class="rounded-xl border border-gray-200 dark:border-white/10 p-3 space-y-3">
        <div class="flex items-center justify-between">
          <span class="text-xs font-semibold text-gray-500 dark:text-gray-400">Stufe {{ i + 1 }}</span>
          <button v-if="!readonly" type="button" @click="removeStage(i)"
                  class="text-gray-400 hover:text-red-500 px-1" aria-label="Stufe entfernen">✕</button>
        </div>

        <!-- Frist + Wiederholung -->
        <div class="flex flex-wrap items-center gap-x-2 gap-y-2 text-sm text-gray-700 dark:text-gray-200">
          <span>Erste Erinnerung nach</span>
          <input type="number" min="1" :max="ESCALATION_MAX_DAYS" :value="st.afterDays" :disabled="readonly"
                 class="afi w-20 text-sm text-center"
                 @input="setStage(i, { afterDays: toInt(($event.target as HTMLInputElement).value) })" />
          <span>Tagen.</span>
          <label class="flex items-center gap-2 ml-1">
            <input type="checkbox" :checked="st.repeatDays !== null" :disabled="readonly"
                   class="h-4 w-4 rounded border-gray-300 dark:border-white/20 text-[#3EAAB8] focus:ring-[#3EAAB8]/30"
                   @change="setRepeatEnabled(i, ($event.target as HTMLInputElement).checked)" />
            danach wiederholen
          </label>
          <template v-if="st.repeatDays !== null">
            <span>alle</span>
            <input type="number" min="1" :max="ESCALATION_MAX_DAYS" :value="st.repeatDays" :disabled="readonly"
                   class="afi w-20 text-sm text-center"
                   @input="setStage(i, { repeatDays: toInt(($event.target as HTMLInputElement).value) })" />
            <span>Tage.</span>
          </template>
        </div>

        <!-- Empfänger -->
        <div>
          <label class="block text-xs text-gray-500 dark:text-gray-400 mb-1.5">Empfänger</label>
          <RecipientPicker :model-value="st.recipients" :groups="groups" :users="users" :readonly="readonly"
                           @update:model-value="setStage(i, { recipients: $event })" />
        </div>

        <!-- Nachricht -->
        <div>
          <label class="block text-xs text-gray-500 dark:text-gray-400 mb-1">Nachricht (optional)</label>
          <input :value="st.message ?? ''" :disabled="readonly" class="afi w-full text-sm"
                 placeholder="z. B. Bitte zeitnah bearbeiten – Frist überschritten."
                 @input="setStage(i, { message: ($event.target as HTMLInputElement).value || null })" />
        </div>

        <!-- Priorität -->
        <label class="flex items-center gap-2.5 text-sm text-gray-600 dark:text-gray-300 select-none">
          <input type="checkbox" :checked="st.raisePriority" :disabled="readonly"
                 class="h-4 w-4 rounded border-gray-300 dark:border-white/20 text-[#3EAAB8] focus:ring-[#3EAAB8]/30"
                 @change="setStage(i, { raisePriority: ($event.target as HTMLInputElement).checked })" />
          Ticket-Priorität dabei auf „hoch" setzen
        </label>
      </div>

      <button v-if="!readonly" type="button" @click="addStage" class="btn-secondary text-xs py-1">
        + Stufe
      </button>
    </div>
  </div>
</template>
