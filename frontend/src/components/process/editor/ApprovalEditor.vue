<script setup lang="ts">
/**
 * Freigabe-Block einer Phase (`kind=approval`): eine Frage, zwei Antworten.
 *
 * Erscheint ausschließlich bei der Phasen-Art „Freigabe" – der Server lehnt den
 * Block bei jeder anderen Art ab. Umgekehrt ist er dort Pflicht: ohne Frage
 * wüsste die Laufzeit nicht, worüber entschieden wird.
 *
 * Es wird immer eine VOLLSTÄNDIGE ApprovalSpec nach oben gemeldet (Spread +
 * Änderung), damit der Dirty-Vergleich des Elternteils verlässlich bleibt.
 */
import { computed } from 'vue'
import type { ApprovalOnReject, ApprovalSpec } from '@/types/process'
import { backToTarget } from '@/lib/processSchema'
import { isValidDuration } from '@/lib/isoDuration'
import DurationInput from './DurationInput.vue'

const props = defineProps<{
  modelValue: ApprovalSpec
  /** Phasen VOR dieser – nur dorthin darf zurückgesprungen werden. */
  earlierPhases: { key: string; label: string | null }[]
  fieldKeys: string[]
  fieldLabels?: Record<string, string>
  readonly?: boolean
}>()

const emit = defineEmits<{ 'update:modelValue': [value: ApprovalSpec] }>()

function patch(part: Partial<ApprovalSpec>) {
  emit('update:modelValue', { ...props.modelValue, ...part })
}

const val = (e: Event) => (e.target as HTMLInputElement | HTMLSelectElement).value
const checked = (e: Event) => (e.target as HTMLInputElement).checked
const toStr = (v: string): string | null => (v.trim() === '' ? null : v)

function fieldText(k: string): string {
  const l = props.fieldLabels?.[k]
  return l ? `${l} · ${k}` : k
}

// ── Verhalten bei „Nein" ──────────────────────────────────────────────────────

/** Rücksprung-Ziele: nur frühere Phasen (ein Sprung nach vorn überspringt Arbeit). */
const rejectChoices = computed(() => [
  { value: 'reject', label: 'Auftrag ablehnen (Ende)' },
  ...props.earlierPhases.map((p) => ({
    value: `back_to:${p.key}`,
    label: `Zurück zur Nachbesserung an „${p.label || p.key}"`,
  })),
])

/** Ein Ziel, das es nicht (mehr) gibt oder das NACH dieser Phase liegt. */
const rejectUnknown = computed(() =>
  !rejectChoices.value.some((c) => c.value === props.modelValue.onReject))
const rejectTarget = computed(() => backToTarget(props.modelValue.onReject))

const ageInvalid = computed(() => !isValidDuration(props.modelValue.linkMaxAge))
const questionMissing = computed(() => !props.modelValue.question?.trim())

const unknownField = (k: string | null) => !!k && !props.fieldKeys.includes(k)
</script>

<template>
  <div class="space-y-3">
    <div>
      <label class="block text-xs text-gray-500 dark:text-gray-400 mb-1">
        Frage an die entscheidende Person
      </label>
      <textarea :value="modelValue.question" :disabled="readonly" rows="2"
                class="afi w-full resize-none"
                :class="questionMissing ? 'ring-1 ring-red-400' : ''"
                placeholder="z. B. Soll die Einstellung von Max Mustermann freigegeben werden?"
                @input="patch({ question: (($event.target as HTMLTextAreaElement).value) })" />
      <p v-if="questionMissing" class="text-xs text-red-500 mt-1">
        Ohne Frage weiß niemand, worüber er entscheidet.
      </p>
    </div>

    <div class="grid md:grid-cols-2 gap-3">
      <div>
        <label class="block text-xs text-gray-500 dark:text-gray-400 mb-1">Beschriftung „Ja"</label>
        <input :value="modelValue.approveLabel" :disabled="readonly" class="afi w-full"
               placeholder="Freigeben" @input="patch({ approveLabel: val($event) })" />
      </div>
      <div>
        <label class="block text-xs text-gray-500 dark:text-gray-400 mb-1">Beschriftung „Nein"</label>
        <input :value="modelValue.rejectLabel" :disabled="readonly" class="afi w-full"
               placeholder="Ablehnen" @input="patch({ rejectLabel: val($event) })" />
      </div>
    </div>

    <!-- ── Entscheidung per Mail-Link ── -->
    <div class="rounded-xl border border-gray-200 dark:border-white/10 p-3 space-y-3">
      <label class="flex items-start gap-2 text-sm text-gray-700 dark:text-gray-200">
        <input type="checkbox" :checked="modelValue.externalLink" :disabled="readonly"
               class="mt-0.5 h-4 w-4 rounded border-gray-300 dark:border-white/20 text-[#3EAAB8]"
               @change="patch({ externalLink: checked($event) })" />
        <span>
          Entscheidung per Mail-Link ermöglichen
          <span class="block text-[11px] text-gray-400">
            Die Mail enthält beide Antworten. Der Link führt auf eine Bestätigungsseite –
            entschieden wird erst dort. Ohne diese Option läuft die Freigabe nur in der App.
          </span>
        </span>
      </label>

      <!-- Bewusst auch ohne Mail-Link sichtbar: der Server prüft die Dauer
           immer, ein ausgeblendetes Feld wäre ein unbehebbarer Fehler. -->
      <div>
        <label class="block text-xs text-gray-500 dark:text-gray-400 mb-1">
          Link gültig für
          <span v-if="!modelValue.externalLink" class="text-gray-400">
            (wirkt erst mit Mail-Link)
          </span>
        </label>
        <DurationInput :model-value="modelValue.linkMaxAge"
                       @update:model-value="patch({ linkMaxAge: $event ?? '' })" />
        <p v-if="ageInvalid" class="text-xs text-red-500 mt-1">
          Bitte eine gültige Dauer größer als null angeben (z.&nbsp;B. P7D).
        </p>
      </div>
    </div>

    <!-- ── Begründung ── -->
    <label class="flex items-start gap-2 text-sm text-gray-700 dark:text-gray-200">
      <input type="checkbox" :checked="modelValue.requireReason" :disabled="readonly"
             class="mt-0.5 h-4 w-4 rounded border-gray-300 dark:border-white/20 text-[#3EAAB8]"
             @change="patch({ requireReason: checked($event) })" />
      <span>
        Begründung bei „Nein" verlangen
        <span class="block text-[11px] text-gray-400">
          Ohne Begründungs-Feld (siehe unten) landet der Text im Verlauf – den sieht
          jede Person mit Leserecht. Mit Feld gilt dessen Sichtbarkeit.
        </span>
      </span>
    </label>

    <!-- ── Ergebnis in Felder schreiben ── -->
    <div class="grid md:grid-cols-2 gap-3">
      <div>
        <label class="block text-xs text-gray-500 dark:text-gray-400 mb-1">
          Entscheidung schreiben nach <span class="text-gray-400">(optional)</span>
        </label>
        <select :value="modelValue.decisionField ?? ''" :disabled="readonly" class="afi w-full"
                @change="patch({ decisionField: toStr(val($event)) })">
          <option value="">— nicht speichern —</option>
          <option v-for="k in fieldKeys" :key="k" :value="k">{{ fieldText(k) }}</option>
          <option v-if="unknownField(modelValue.decisionField)"
                  :value="modelValue.decisionField" class="text-red-600">
            {{ modelValue.decisionField }} (unbekannt)
          </option>
        </select>
        <p class="text-[11px] text-gray-400 mt-1">
          Gespeichert wird „approve" bzw. „reject" – nicht die Beschriftung.
        </p>
      </div>
      <div>
        <label class="block text-xs text-gray-500 dark:text-gray-400 mb-1">
          Begründung schreiben nach <span class="text-gray-400">(optional)</span>
        </label>
        <select :value="modelValue.reasonField ?? ''" :disabled="readonly" class="afi w-full"
                @change="patch({ reasonField: toStr(val($event)) })">
          <option value="">— nicht speichern —</option>
          <option v-for="k in fieldKeys" :key="k" :value="k">{{ fieldText(k) }}</option>
          <option v-if="unknownField(modelValue.reasonField)"
                  :value="modelValue.reasonField" class="text-red-600">
            {{ modelValue.reasonField }} (unbekannt)
          </option>
        </select>
      </div>
    </div>

    <!-- ── Verhalten bei „Nein" ── -->
    <div>
      <label class="block text-xs text-gray-500 dark:text-gray-400 mb-1">Bei „Nein" passiert</label>
      <select :value="modelValue.onReject" :disabled="readonly" class="afi w-full"
              :class="rejectUnknown ? 'ring-1 ring-red-400' : ''"
              @change="patch({ onReject: val($event) as ApprovalOnReject })">
        <option v-for="c in rejectChoices" :key="c.value" :value="c.value">{{ c.label }}</option>
        <option v-if="rejectUnknown" :value="modelValue.onReject" class="text-red-600">
          Nicht möglich: {{ modelValue.onReject }}
        </option>
      </select>
      <p v-if="rejectUnknown" class="text-xs text-red-500 mt-1">
        <template v-if="rejectTarget">
          „{{ rejectTarget }}" gibt es nicht oder die Phase liegt nicht VOR dieser –
          ein Rücksprung nach vorn würde Arbeit überspringen.
        </template>
        <template v-else>Unbekanntes Verhalten „{{ modelValue.onReject }}".</template>
      </p>
      <p v-else-if="!earlierPhases.length" class="text-[11px] text-gray-400 mt-1">
        Ein Rücksprung zur Nachbesserung ist erst möglich, wenn es Phasen VOR dieser gibt.
      </p>
    </div>
  </div>
</template>

