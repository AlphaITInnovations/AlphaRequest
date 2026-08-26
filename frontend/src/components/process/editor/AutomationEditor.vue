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
import { computed, ref, watch } from 'vue'
import type {
  Action, ActionType, Automation, DirectusOperation, DirectusWriteSpec, Trigger, TriggerType,
} from '@/types/process'
import {
  ACTION_LABEL, ACTION_TYPES, COUNTER_LABEL, ENTER_STATUS, PRIORITIES, RECIPIENTS,
  RECIPIENT_LABEL, SEQUENCE_COUNTERS, STATUS_LABEL, TRIGGER_LABEL, TRIGGER_TYPES,
} from '@/lib/processSchema'
import { listCollections, listFields } from '@/api/directus'
import type { DirectusCollection, DirectusField } from '@/api/directus'
import ConditionEditor from './ConditionEditor.vue'
import DurationInput from './DurationInput.vue'

const props = defineProps<{
  modelValue: Automation
  fieldKeys: string[]
  fieldLabels?: Record<string, string>
  /** Feld-Key → Widget; nötig, um „als Firmen-ID auflösen“ nur bei company-Feldern
   *  anzubieten. */
  fieldWidgets?: Record<string, string>
  groups?: { id: string; name: string }[]
  /** Fachabteilungen DIESER Phase (für den Trigger „Fachabteilung abgeschlossen“).
   *  Fehlt sie, wird auf alle `groups` ausgewichen. */
  departmentGroups?: { id: string; name: string }[]
}>()

const DIRECTUS_OPS: { value: DirectusOperation; label: string }[] = [
  { value: 'create', label: 'Anlegen' },
  { value: 'update', label: 'Ändern' },
  { value: 'delete', label: 'Löschen' },
]
const deptGroups = computed(() =>
  (props.departmentGroups?.length ? props.departmentGroups : props.groups) ?? [])

const emit = defineEmits<{
  'update:modelValue': [value: Automation]
  remove: []
}>()

const PRIORITY_LABEL: Record<string, string> = {
  low: 'Niedrig', normal: 'Normal', high: 'Hoch', urgent: 'Dringend',
}

// ── Robuste Sicht auf den Wert (die Definition kann unvollständig sein) ───────

const blankTrigger = (): Trigger => ({ type: 'on_enter', after: null, repeat: null, field: null, group: null })
const blankAction = (): Action => ({
  type: 'notify', to: 'responsible', template: null, field: null,
  value: null, counter: null, directus: null,
})
const blankDirectus = (): DirectusWriteSpec => ({
  operation: 'create', collection: '', fieldMap: [], idField: '',
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
    group: t === 'on_department_done'
      ? (a.value.trigger.group ?? (deptGroups.value[0]?.id ?? null)) : null,
  })
}

// ── Directus-Schreiben ──────────────────────────────────────────────────────
function patchDirectus(p: Partial<DirectusWriteSpec>) {
  patchAction({ directus: { ...(a.value.action.directus ?? blankDirectus()), ...p } })
}
function addDwMap() {
  const cur = a.value.action.directus ?? blankDirectus()
  patchDirectus({ fieldMap: [...cur.fieldMap, { source: '', target: '' }] })
}
function removeDwMap(i: number) {
  const cur = a.value.action.directus ?? blankDirectus()
  patchDirectus({ fieldMap: cur.fieldMap.filter((_, j) => j !== i) })
}
function setDwMap(i: number, part: 'source' | 'target', value: string) {
  const cur = a.value.action.directus ?? blankDirectus()
  patchDirectus({ fieldMap: cur.fieldMap.map((b, j) => {
    if (j !== i) return b
    const next: any = { ...b, [part]: value }
    // resolve ist nur für ein Firmen-Feld gültig – bei Quellwechsel weg damit,
    // sonst lehnt der Server die Definition ab.
    if (part === 'source' && props.fieldWidgets?.[value] !== 'company') delete next.resolve
    return next
  }) })
}
function setDwResolve(i: number, on: boolean) {
  const cur = a.value.action.directus ?? blankDirectus()
  patchDirectus({ fieldMap: cur.fieldMap.map((b, j) => {
    if (j !== i) return b
    const next: any = { ...b }
    if (on) next.resolve = 'company_directus_id'
    else delete next.resolve
    return next
  }) })
}

function onActionType(t: ActionType) {
  const cur = a.value.action
  const next: Action = {
    type: t, to: null, template: null, field: null, value: null, counter: null, directus: null,
  }
  if (t === 'directus_write') {
    next.directus = cur.directus ?? blankDirectus()
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

// ── Directus-Introspektion: Dropdowns für Collection + Zielfelder ─────────────
// Nur laden, wenn die Aktion „In Directus schreiben“ aktiv ist. Fail-soft: ist
// Directus nicht erreichbar, bleibt der gespeicherte Wert als (unbekannt)-Option
// erhalten, damit die Automation weiter bearbeitbar bleibt (+ „neu laden“).
const isDirectusWrite = computed(() => a.value.action.type === 'directus_write')
const dwCollection = computed(() => a.value.action.directus?.collection ?? '')

const collections = ref<DirectusCollection[]>([])
const collectionsError = ref<string | null>(null)
const collectionsLoading = ref(false)
const fields = ref<DirectusField[]>([])
const fieldsError = ref<string | null>(null)
const fieldsLoading = ref(false)
const fieldsFor = ref('')

async function loadCollections() {
  collectionsLoading.value = true
  collectionsError.value = null
  try {
    collections.value = await listCollections()
  } catch {
    collectionsError.value = 'Directus nicht erreichbar – Collections nicht geladen'
    collections.value = []
  } finally {
    collectionsLoading.value = false
  }
}

async function loadFields(collection: string) {
  fieldsFor.value = collection
  fieldsError.value = null
  if (!collection) { fields.value = []; fieldsLoading.value = false; return }
  fieldsLoading.value = true
  try {
    const res = await listFields(collection)
    if (fieldsFor.value === collection) fields.value = res       // Rennen vermeiden
  } catch {
    if (fieldsFor.value === collection) {
      fieldsError.value = 'Felder nicht geladen'
      fields.value = []
    }
  } finally {
    if (fieldsFor.value === collection) fieldsLoading.value = false
  }
}

watch(isDirectusWrite, (on) => {
  if (on && !collections.value.length && !collectionsLoading.value) loadCollections()
}, { immediate: true })

watch(dwCollection, (c) => {
  if (isDirectusWrite.value) loadFields(c)
}, { immediate: true })
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

      <div v-else-if="a.trigger.type === 'on_department_done'">
        <label class="lbl">Fachabteilung</label>
        <select class="afi w-full" :value="a.trigger.group ?? ''"
                @change="patchTrigger({ group: val($event) || null })">
          <option value="">Fachabteilung wählen…</option>
          <option v-for="g in deptGroups" :key="g.id" :value="g.id">{{ g.name }}</option>
          <option v-if="a.trigger.group && !deptGroups.some((g) => g.id === a.trigger.group)"
                  :value="a.trigger.group">{{ a.trigger.group }} (unbekannt)</option>
        </select>
        <p class="text-xs text-gray-400 mt-1">
          Feuert, sobald diese Fachabteilung ihren Teil abgeschlossen hat (nur in einer
          Fachabteilungs-Phase).
        </p>
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

      <!-- In Directus schreiben -->
      <template v-else-if="a.action.type === 'directus_write'">
        <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div>
            <label class="lbl">Operation</label>
            <select class="afi w-full" :value="a.action.directus?.operation ?? 'create'"
                    @change="patchDirectus({ operation: val($event) as DirectusOperation })">
              <option v-for="o in DIRECTUS_OPS" :key="o.value" :value="o.value">{{ o.label }}</option>
            </select>
          </div>
          <div>
            <label class="lbl">Collection</label>
            <select class="afi w-full" :value="a.action.directus?.collection ?? ''"
                    @change="patchDirectus({ collection: val($event) })">
              <option value="">{{ collectionsLoading ? 'lädt…' : 'Collection wählen…' }}</option>
              <option v-for="c in collections" :key="c.collection" :value="c.collection">{{ c.collection }}</option>
              <option v-if="dwCollection && !collections.some((c) => c.collection === dwCollection)"
                      :value="dwCollection">{{ dwCollection }} (unbekannt)</option>
            </select>
            <p v-if="collectionsError" class="text-xs text-amber-600 dark:text-amber-400 mt-1">
              {{ collectionsError }} ·
              <button type="button" class="underline" @click="loadCollections">neu laden</button>
            </p>
          </div>
        </div>

        <div>
          <label class="lbl">Directus-id speichern in / lesen aus</label>
          <select class="afi w-full" :value="a.action.directus?.idField ?? ''"
                  @change="patchDirectus({ idField: val($event) })">
            <option value="">Feld wählen…</option>
            <option v-for="k in keys" :key="k" :value="k">{{ fieldText(k) }}</option>
            <option v-if="a.action.directus?.idField && !keys.includes(a.action.directus.idField)"
                    :value="a.action.directus.idField">{{ a.action.directus.idField }} (unbekannt)</option>
          </select>
          <p class="text-xs text-gray-400 mt-1">
            Beim Anlegen wird die neue Directus-id hierhin geschrieben (und schützt vor
            Doppelanlage); bei Ändern/Löschen wird sie von hier gelesen.
          </p>
        </div>

        <div v-if="(a.action.directus?.operation ?? 'create') !== 'delete'">
          <div class="flex items-center justify-between">
            <label class="lbl mb-0">Feld-Zuordnung (Prozess → Directus)</label>
            <button type="button" @click="addDwMap" class="text-xs text-[#3EAAB8] hover:underline">+ Zuordnung</button>
          </div>
          <div v-for="(b, i) in (a.action.directus?.fieldMap ?? [])" :key="i" class="mt-2">
            <div class="flex items-center gap-2">
              <select class="afi flex-1" :value="b.source"
                      @change="setDwMap(i, 'source', val($event))">
                <option value="">Prozess-Feld…</option>
                <option v-for="k in keys" :key="k" :value="k">{{ fieldText(k) }}</option>
                <option v-if="b.source && !keys.includes(b.source)" :value="b.source">{{ b.source }} (unbekannt)</option>
              </select>
              <span class="text-gray-400 text-sm">→</span>
              <select class="afi flex-1" :value="b.target" @change="setDwMap(i, 'target', val($event))">
                <option value="">{{ fieldsLoading ? 'lädt…' : 'Directus-Feld…' }}</option>
                <option v-for="f in fields" :key="f.field" :value="f.field">{{ f.field }}</option>
                <option v-if="b.target && !fields.some((f) => f.field === b.target)"
                        :value="b.target">{{ b.target }} (unbekannt)</option>
              </select>
              <button type="button" @click="removeDwMap(i)"
                      class="text-gray-400 hover:text-red-500 text-lg leading-none">×</button>
            </div>
            <label v-if="fieldWidgets?.[b.source] === 'company' || b.resolve === 'company_directus_id'"
                   class="mt-1 ml-1 flex items-center gap-2 text-xs text-gray-600 dark:text-gray-300">
              <input type="checkbox" :checked="b.resolve === 'company_directus_id'"
                     class="h-3.5 w-3.5 rounded border-gray-300 dark:border-white/20 text-[#3EAAB8]"
                     @change="setDwResolve(i, ($event.target as HTMLInputElement).checked)" />
              Als alphacore-Firmen-ID auflösen (statt Firmenname)
              <span v-if="fieldWidgets?.[b.source] !== 'company'" class="text-amber-600 dark:text-amber-400">
                – nur für ein Firmen-Feld gültig
              </span>
            </label>
          </div>
          <p v-if="!dwCollection" class="text-xs text-gray-400 mt-2">
            Zuerst oben eine Collection wählen – dann stehen die Directus-Felder zur Auswahl.
          </p>
          <p v-else-if="fieldsError" class="text-xs text-amber-600 dark:text-amber-400 mt-2">
            {{ fieldsError }} ·
            <button type="button" class="underline" @click="loadFields(dwCollection)">neu laden</button>
          </p>
          <p v-else-if="!(a.action.directus?.fieldMap ?? []).length" class="text-xs text-gray-400 mt-2">
            Noch keine Zuordnung – mindestens eine ist nötig.
          </p>
        </div>

        <p class="text-xs text-gray-400">
          Schreibt live nach Directus. Das braucht einen Directus-Token mit Schreibrechten
          (env DIRECTUS_WRITE_TOKEN oder Schreibrecht des Lese-Tokens). Fehler blockieren den
          Auftrag nicht – sie landen im Verlauf und als Mail an den Fehler-Empfänger.
        </p>
      </template>
    </div>
  </div>
</template>

