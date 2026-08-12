<script setup lang="ts">
/**
 * Editor für EINE Automation (Auslöser → Bedingung → Aktion).
 *
 * Grundsatz: Es wird immer ein VOLLSTÄNDIGES Automation-Objekt emittiert
 * (Spread über den alten Wert), damit der Elternteil nie teilweise gefüllte
 * Objekte in die Definition schreibt.
 *
 * Wichtig für das Backend: Zeitangaben (after/repeat) sind nur bei
 * trigger.type='timer' erlaubt, `field` nur bei 'on_field_change' – beim
 * Umschalten werden sie deshalb aktiv auf null zurückgesetzt. Ebenso werden
 * beim Aktionswechsel die nicht mehr passenden Action-Felder geleert, sonst
 * lehnt der Server die Definition ab.
 */
import { computed } from 'vue'
import type { Action, ActionType, Automation, Trigger, TriggerType } from '@/types/process'
import {
  ACTION_LABEL, ACTION_TYPES, COUNTER_LABEL, ENTER_STATUS, PRIORITIES, RECIPIENTS,
  RECIPIENT_LABEL, SEQUENCE_COUNTERS, STATUS_LABEL, TRIGGER_LABEL, TRIGGER_TYPES,
} from '@/lib/processSchema'
import ConditionEditor from './ConditionEditor.vue'
import DurationInput from './DurationInput.vue'

const props = defineProps<{
  modelValue: Automation
  fieldKeys: string[]
  fieldLabels?: Record<string, string>
  groups?: { id: string; name: string }[]
}>()

const emit = defineEmits<{
  'update:modelValue': [value: Automation]
  remove: []
}>()

const PRIORITY_LABEL: Record<string, string> = {
  low: 'Niedrig', normal: 'Normal', high: 'Hoch', urgent: 'Dringend',
}

// ── Robuste Sicht auf den Wert (die Definition kann unvollständig sein) ───────

const blankTrigger = (): Trigger => ({ type: 'on_enter', after: null, repeat: null, field: null })
const blankAction = (): Action => ({
  type: 'notify', to: 'responsible', template: null, field: null,
  value: null, counter: null,
})

const a = computed<Automation>(() => {
  const m = props.modelValue
  return {
    id: m?.id ?? '',
    trigger: m?.trigger ? { ...blankTrigger(), ...m.trigger } : blankTrigger(),
    guard: m?.guard ?? null,
    action: m?.action ? { ...blankAction(), ...m.action } : blankAction(),
  }
})

const keys = computed<string[]>(() => props.fieldKeys ?? [])

/** Feld-Schlüssel bleibt sichtbar – Labels sind nur eine Lesehilfe. */
function fieldText(k: string): string {
  const l = props.fieldLabels?.[k]
  return l ? `${l} · ${k}` : k
}

/** Feste Ziele plus je Fachabteilung ein 'group:<id>'-Eintrag. */
const recipients = computed(() => [
  ...RECIPIENTS.map((r) => ({ value: r, label: RECIPIENT_LABEL[r] ?? r })),
  ...(props.groups ?? []).map((g) => ({ value: `group:${g.id}`, label: `Fachabteilung: ${g.name}` })),
])

// ── Schreiben ─────────────────────────────────────────────────────────────────

const val = (e: Event) => (e.target as HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement).value

function patch(p: Partial<Automation>) {
  emit('update:modelValue', { ...a.value, ...p })
}
function patchTrigger(p: Partial<Trigger>) {
  patch({ trigger: { ...a.value.trigger, ...p } })
}
function patchAction(p: Partial<Action>) {
  patch({ action: { ...a.value.action, ...p } })
}

function onTriggerType(t: TriggerType) {
  patchTrigger({
    type: t,
    // Vorbelegung nur beim Timer, sonst wären after/repeat serverseitig ungültig.
    after: t === 'timer' ? (a.value.trigger.after ?? 'P1D') : null,
    repeat: t === 'timer' ? a.value.trigger.repeat : null,
    field: t === 'on_field_change' ? a.value.trigger.field : null,
  })
}

function onActionType(t: ActionType) {
  const cur = a.value.action
  const next: Action = {
    type: t, to: null, template: null, field: null, value: null, counter: null,
  }
  if (t === 'notify' || t === 'escalate') {
    next.to = cur.to ?? 'responsible'
    next.template = cur.template
  } else if (t === 'set_field') {
    next.field = cur.field
    next.value = cur.value ?? ''
  } else if (t === 'set_priority') {
    next.value = PRIORITIES.includes(String(cur.value)) ? cur.value : 'normal'
  } else if (t === 'set_status') {
    next.value = ENTER_STATUS.includes(String(cur.value)) ? cur.value : ENTER_STATUS[0]
  } else if (t === 'assign_sequence') {
    // Beides ist serverseitig Pflicht: woher die Nummer kommt und wohin sie geht.
    next.counter = cur.counter ?? SEQUENCE_COUNTERS[0]
    next.field = cur.field
  }
  patch({ action: next })
}

const counterUnknown = computed(() => {
  const c = a.value.action.counter
  return !!c && !SEQUENCE_COUNTERS.includes(c)
})

const actionValueText = computed(() => {
  const v = a.value.action.value
  return v === null || v === undefined ? '' : String(v)
})
</script>

<template>
  <div class="space-y-4">
    <!-- Kopf: ID + Entfernen -->
    <div class="flex items-end gap-3">
      <div class="flex-1 min-w-0">
        <label class="lbl">Kennung</label>
        <input
          class="afi w-full"
          placeholder="z. B. auto-1"
          :value="a.id"
          @input="patch({ id: val($event) })"
        />
      </div>
      <button
        type="button"
        class="text-sm text-red-500 hover:text-red-600 hover:underline pb-2.5 whitespace-nowrap"
        @click="emit('remove')"
      >Entfernen</button>
    </div>

    <!-- ── Auslöser ── -->
    <div class="rounded-xl border border-gray-200 dark:border-white/10 p-3 space-y-3">
      <p class="text-xs font-semibold uppercase tracking-wider text-gray-400">Auslöser</p>

      <select class="afi w-full" :value="a.trigger.type" @change="onTriggerType(val($event) as TriggerType)">
        <option v-for="t in TRIGGER_TYPES" :key="t" :value="t">{{ TRIGGER_LABEL[t] ?? t }}</option>
      </select>

      <template v-if="a.trigger.type === 'timer'">
        <div>
          <label class="lbl">Nach</label>
          <DurationInput
            :model-value="a.trigger.after"
            @update:model-value="(v) => patchTrigger({ after: v })"
          />
        </div>
        <div>
          <label class="lbl">Wiederholen alle <span class="text-gray-400 font-normal">(optional)</span></label>
          <DurationInput
            :model-value="a.trigger.repeat"
            placeholder="keine Wiederholung"
            @update:model-value="(v) => patchTrigger({ repeat: v })"
          />
        </div>
      </template>

      <div v-else-if="a.trigger.type === 'on_field_change'">
        <label class="lbl">Feld</label>
        <select
          class="afi w-full"
          :value="a.trigger.field ?? ''"
          @change="patchTrigger({ field: val($event) || null })"
        >
          <option value="">Feld wählen…</option>
          <option v-for="k in keys" :key="k" :value="k">{{ fieldText(k) }}</option>
          <option v-if="a.trigger.field && !keys.includes(a.trigger.field)" :value="a.trigger.field">
            {{ a.trigger.field }} (unbekannt)
          </option>
        </select>
      </div>
    </div>

    <!-- ── Bedingung ── -->
    <div class="rounded-xl border border-gray-200 dark:border-white/10 p-3 space-y-3">
      <p class="text-xs font-semibold uppercase tracking-wider text-gray-400">
        Bedingung <span class="normal-case tracking-normal font-normal">(optional)</span>
      </p>
      <ConditionEditor
        :model-value="a.guard"
        :field-keys="keys"
        @update:model-value="(v) => patch({ guard: v })"
      />
    </div>

    <!-- ── Aktion ── -->
    <div class="rounded-xl border border-gray-200 dark:border-white/10 p-3 space-y-3">
      <p class="text-xs font-semibold uppercase tracking-wider text-gray-400">Aktion</p>

      <select class="afi w-full" :value="a.action.type" @change="onActionType(val($event) as ActionType)">
        <option v-for="t in ACTION_TYPES" :key="t" :value="t">{{ ACTION_LABEL[t] ?? t }}</option>
      </select>

      <!-- Benachrichtigen / Eskalieren -->
      <template v-if="a.action.type === 'notify' || a.action.type === 'escalate'">
        <div>
          <label class="lbl">Empfänger</label>
          <select class="afi w-full" :value="a.action.to ?? ''" @change="patchAction({ to: val($event) || null })">
            <option value="">Empfänger wählen…</option>
            <option v-for="r in recipients" :key="r.value" :value="r.value">{{ r.label }}</option>
            <option
              v-if="a.action.to && !recipients.some((r) => r.value === a.action.to)"
              :value="a.action.to"
            >{{ a.action.to }} (unbekannt)</option>
          </select>
        </div>
        <div>
          <label class="lbl">Text <span class="text-gray-400 font-normal">(optional)</span></label>
          <textarea
            rows="3"
            class="afi w-full resize-none"
            placeholder="Kurzer Hinweis für die Empfänger…"
            :value="a.action.template ?? ''"
            @input="patchAction({ template: val($event) || null })"
          />
        </div>
      </template>

      <!-- Feld setzen -->
      <template v-else-if="a.action.type === 'set_field'">
        <div>
          <label class="lbl">Feld</label>
          <select
            class="afi w-full"
            :value="a.action.field ?? ''"
            @change="patchAction({ field: val($event) || null })"
          >
            <option value="">Feld wählen…</option>
            <option v-for="k in keys" :key="k" :value="k">{{ fieldText(k) }}</option>
            <option v-if="a.action.field && !keys.includes(a.action.field)" :value="a.action.field">
              {{ a.action.field }} (unbekannt)
            </option>
          </select>
        </div>
        <div>
          <label class="lbl">Wert</label>
          <input
            class="afi w-full"
            placeholder="Wert, der gesetzt wird"
            :value="actionValueText"
            @input="patchAction({ value: val($event) })"
          />
        </div>
      </template>

      <!-- Priorität setzen -->
      <div v-else-if="a.action.type === 'set_priority'">
        <label class="lbl">Priorität</label>
        <select class="afi w-full" :value="actionValueText" @change="patchAction({ value: val($event) })">
          <option v-for="p in PRIORITIES" :key="p" :value="p">{{ PRIORITY_LABEL[p] ?? p }}</option>
        </select>
      </div>

      <!-- Status setzen -->
      <div v-else-if="a.action.type === 'set_status'">
        <label class="lbl">Status</label>
        <select class="afi w-full" :value="actionValueText" @change="patchAction({ value: val($event) })">
          <option v-for="s in ENTER_STATUS" :key="s" :value="s">{{ STATUS_LABEL[s] ?? s }}</option>
        </select>
      </div>

      <!-- Nummer aus einem Nummernkreis vergeben -->
      <template v-else-if="a.action.type === 'assign_sequence'">
        <div>
          <label class="lbl">Nummernkreis</label>
          <select class="afi w-full" :value="a.action.counter ?? ''"
                  @change="patchAction({ counter: val($event) || null })">
            <option value="">Nummernkreis wählen…</option>
            <option v-for="c in SEQUENCE_COUNTERS" :key="c" :value="c">
              {{ COUNTER_LABEL[c] ?? c }}
            </option>
            <option v-if="counterUnknown" :value="a.action.counter">
              {{ a.action.counter }} (unbekannt)
            </option>
          </select>
          <p v-if="counterUnknown" class="text-xs text-amber-600 dark:text-amber-400 mt-1">
            Diesen Nummernkreis kennt die Laufzeit nicht – die Vergabe bricht später ab.
          </p>
        </div>
        <div>
          <label class="lbl">Nummer schreiben nach</label>
          <select
            class="afi w-full"
            :value="a.action.field ?? ''"
            @change="patchAction({ field: val($event) || null })"
          >
            <option value="">Feld wählen…</option>
            <option v-for="k in keys" :key="k" :value="k">{{ fieldText(k) }}</option>
            <option v-if="a.action.field && !keys.includes(a.action.field)" :value="a.action.field">
              {{ a.action.field }} (unbekannt)
            </option>
          </select>
        </div>
      </template>

      <!-- Automatisch weiterschalten -->
      <p
        v-else-if="a.action.type === 'auto_advance'"
        class="rounded-xl border border-blue-200 dark:border-blue-500/30 bg-blue-50 dark:bg-blue-900/20
               px-4 py-3 text-sm text-blue-800 dark:text-blue-200"
      >
        Die Phase wird automatisch abgeschlossen, sobald der Auslöser greift und alle
        Pflichtangaben vorliegen. Es sind keine weiteren Angaben nötig.
      </p>
    </div>
  </div>
</template>

<style scoped>
@reference "../../../style.css";
.afi {
  @apply rounded-xl border border-gray-200 dark:border-white/10
         bg-white dark:bg-[#263040] text-gray-900 dark:text-gray-100
         px-3.5 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#3EAAB8]/30 transition;
}
</style>
