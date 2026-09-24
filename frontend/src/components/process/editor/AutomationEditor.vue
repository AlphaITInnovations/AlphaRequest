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
  Action, ActionType, Automation, DirectusOperation, DirectusWriteBinding, DirectusWriteSpec,
  HttpHeader, HttpMethod, HttpRequestSpec, Trigger, TriggerType,
} from '@/types/process'
import {
  ACTION_LABEL, AUTOMATION_ACTION_TYPES, COUNTER_LABEL, ENTER_STATUS, PRIORITIES, RECIPIENTS,
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
const DIRECTUS_ONERROR: { value: 'continue' | 'block'; label: string }[] = [
  { value: 'continue', label: 'Weiterlaufen + melden (Standard)' },
  { value: 'block', label: 'Blockieren – Abschluss verhindern, bis es klappt' },
]
const HTTP_METHODS: HttpMethod[] = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE']
const HTTP_ONERROR: { value: 'continue' | 'block'; label: string }[] = [
  { value: 'continue', label: 'Weiterlaufen + melden (Standard)' },
  { value: 'block', label: 'Blockieren – Abschluss verhindern, bis es klappt' },
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
  type: 'notify', to: 'responsible', recipients: null, template: null, field: null,
  value: null, counter: null, directus: null, http: null, email: null, emailBody: null,
})
// Platzhalter mit {{…}} als gebundener String – im Template-Attribut würde Vue die
// Mustaches sonst als (verbotene) Attribut-Interpolation deuten.
const bodyPlaceholder = 'Freitext an die Empfänger:innen. Platzhalter: {{feld.key}}, {{title}}, {{id}}.'
const bodyExample = '{{base.mitarbeiter_nachname}}'
const blankDirectus = (): DirectusWriteSpec => ({
  operation: 'create', collection: '', fieldMap: [], idField: '',
  onError: 'continue', matchField: null,
})
const blankHttp = (): HttpRequestSpec => ({
  method: 'POST', url: '', headers: [], body: null, contentType: null,
  timeoutSeconds: 10, onError: 'continue',
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
function setDwOperation(op: DirectusOperation) {
  // matchField (get-or-create) gibt es nur bei create – beim Wechsel weg davon
  // aufräumen, sonst bliebe ein nicht mehr bedienbarer Validierungsfehler stehen.
  patchDirectus(op === 'create' ? { operation: op } : { operation: op, matchField: null })
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
function patchDwMap(i: number, next: (b: DirectusWriteBinding) => DirectusWriteBinding) {
  const cur = a.value.action.directus ?? blankDirectus()
  patchDirectus({ fieldMap: cur.fieldMap.map((b, j) => (j === i ? next(b) : b)) })
}
/** Bedingung (when) unverändert übernehmen – aber NUR, wenn eine existiert.
 *  Kein `when: null` schreiben: die Normalisierung lässt den Schlüssel dann weg,
 *  ein explizites null würde den Dirty-Vergleich fälschlich auslösen. */
function keepWhen(base: DirectusWriteBinding, prev: DirectusWriteBinding): DirectusWriteBinding {
  return prev.when ? { ...base, when: prev.when } : base
}
/** Quelle einer Zuordnung umstellen: Prozess-Feld ODER fester Wert. Beim Wechsel
 *  die jeweils andere Seite (+ resolve) verwerfen, damit genau eines gesetzt ist.
 *  Die Bedingung (when) bleibt erhalten – sie gilt unabhängig von der Quelle. */
function setDwSourceKind(i: number, kind: string) {
  patchDwMap(i, (b): DirectusWriteBinding => keepWhen(kind === 'const'
    ? { target: b.target, source: null, value: b.value ?? '' }
    : { target: b.target, source: b.source ?? '' }, b))
}
function setDwConst(i: number, value: string) {
  patchDwMap(i, (b): DirectusWriteBinding => keepWhen({ target: b.target, source: null, value }, b))
}
// ── Fester Wert: Typ (Text / Ja-Nein / Zahl) ─────────────────────────────────
function dwConstKind(b: DirectusWriteBinding): 'text' | 'bool' | 'num' {
  if (typeof b.value === 'boolean') return 'bool'
  if (typeof b.value === 'number') return 'num'
  return 'text'
}
function setDwConstKind(i: number, kind: string) {
  const value = kind === 'bool' ? true : kind === 'num' ? 0 : ''
  patchDwMap(i, (b): DirectusWriteBinding => keepWhen({ target: b.target, source: null, value }, b))
}
function setDwConstBool(i: number, value: boolean) {
  patchDwMap(i, (b): DirectusWriteBinding => keepWhen({ target: b.target, source: null, value }, b))
}
function setDwConstNum(i: number, raw: string) {
  const n = Number(raw)
  patchDwMap(i, (b): DirectusWriteBinding =>
    keepWhen({ target: b.target, source: null, value: Number.isFinite(n) ? n : 0 }, b))
}
// ── Bedingung (when): Zuordnung nur schreiben, wenn ein Feld == Wert ──────────
function setDwWhenEnabled(i: number, on: boolean) {
  patchDwMap(i, (b): DirectusWriteBinding => {
    if (on) return { ...b, when: b.when ?? { field: '', equals: '' } }
    const rest = { ...b }             // Bedingung ganz entfernen (kein `when: null`)
    delete rest.when
    return rest
  })
}
function setDwWhen(i: number, part: 'field' | 'equals', value: string) {
  patchDwMap(i, (b): DirectusWriteBinding => ({
    ...b,
    when: { field: b.when?.field ?? '', equals: b.when?.equals ?? '', [part]: value },
  }))
}

// ── API-Aufruf (http_request) ────────────────────────────────────────────────
function patchHttp(p: Partial<HttpRequestSpec>) {
  patchAction({ http: { ...(a.value.action.http ?? blankHttp()), ...p } })
}
function addHeader() {
  const cur = a.value.action.http ?? blankHttp()
  patchHttp({ headers: [...cur.headers, { name: '', value: '' }] })
}
function removeHeader(i: number) {
  const cur = a.value.action.http ?? blankHttp()
  patchHttp({ headers: cur.headers.filter((_, j) => j !== i) })
}
function setHeader(i: number, part: keyof HttpHeader, value: string) {
  const cur = a.value.action.http ?? blankHttp()
  patchHttp({ headers: cur.headers.map((h, j) => (j === i ? { ...h, [part]: value } : h)) })
}
/** Zeitlimit robust setzen (leer/ungültig → Standard 10). */
function setHttpTimeout(raw: string) {
  const n = Math.floor(Number(raw))
  patchHttp({ timeoutSeconds: Number.isFinite(n) && n > 0 ? n : 10 })
}
/** Kurzer Platzhalter-Spick: die wichtigsten verfügbaren {{…}}-Tokens. */
const placeholderHint = computed(() => {
  const fields = keys.value.slice(0, 6).map((k) => `{{${k}}}`)
  return ['{{title}}', '{{id}}', ...fields].join('  ')
})

function onActionType(t: ActionType) {
  const cur = a.value.action
  // recipients IMMER mitführen (null-Default wie normAction) – sonst fehlt der Key
  // nach einem Typwechsel und der Dirty-Vergleich schlägt dauerhaft an.
  const next: Action = {
    type: t, to: null, recipients: null, template: null, field: null,
    value: null, counter: null, directus: null, http: null, email: null, emailBody: null,
  }
  if (t === 'directus_write') {
    next.directus = cur.directus ?? blankDirectus()
  }
  if (t === 'http_request') {
    next.http = cur.http ?? blankHttp()
  }
  if (t === 'notify' || t === 'escalate') {
    next.to = cur.to ?? 'responsible'
    next.recipients = cur.recipients ?? null
    next.template = cur.template
    next.emailBody = cur.emailBody ?? null
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
/** Belegte Directus-Zielfelder – Auswahl für den Geschäftsschlüssel (get-or-create). */
const dwTargets = computed(() =>
  (a.value.action.directus?.fieldMap ?? []).map((b) => b.target).filter(Boolean))
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
        <option v-for="t in AUTOMATION_ACTION_TYPES" :key="t" :value="t">{{ ACTION_LABEL[t] ?? t }}</option>
      </select>

      <!-- Benachrichtigen / Eskalieren -->
      <template v-if="a.action.type === 'notify' || a.action.type === 'escalate'">
        <div>
          <label class="lbl">Empfänger:in</label>
          <select class="afi w-full" :value="a.action.to ?? ''" @change="patchAction({ to: val($event) || null })">
            <option value="">Empfänger:in wählen…</option>
            <option v-for="r in recipients" :key="r.value" :value="r.value">{{ r.label }}</option>
            <option
              v-if="a.action.to && !recipients.some((r) => r.value === a.action.to)"
              :value="a.action.to"
            >{{ a.action.to }} (unbekannt)</option>
          </select>
        </div>
        <div>
          <label class="lbl">Betreff-Zusatz <span class="text-gray-400 font-normal">(optional)</span></label>
          <input
            type="text"
            class="afi w-full"
            placeholder="z. B. Sofort-Sperrung – erscheint im Betreff"
            :value="a.action.template ?? ''"
            @input="patchAction({ template: val($event) || null })"
          />
          <p class="mt-1 text-xs text-gray-400">
            Betreff der Mail: „[AlphaRequest] &lt;Zusatz&gt;: &lt;Auftragstitel&gt;".
            Ohne Angabe „Erinnerung" bzw. „Eskalation".
          </p>
        </div>
        <div>
          <label class="lbl">Nachricht <span class="text-gray-400 font-normal">(optional)</span></label>
          <textarea
            rows="4"
            class="afi w-full resize-y"
            :placeholder="bodyPlaceholder"
            :value="a.action.emailBody ?? ''"
            @input="patchAction({ emailBody: val($event) || null })"
          />
          <p class="mt-1 text-xs text-gray-400">
            Erscheint als Fließtext in der Mail. Platzhalter wie <code>{{ bodyExample }}</code>
            werden mit den Auftragswerten gefüllt (wie in der Freigabe-Mail).
          </p>
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
                    @change="setDwOperation(val($event) as DirectusOperation)">
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

        <div>
          <label class="lbl">Bei Fehler</label>
          <select class="afi w-full" :value="a.action.directus?.onError ?? 'continue'"
                  @change="patchDirectus({ onError: val($event) as 'continue' | 'block' })">
            <option v-for="o in DIRECTUS_ONERROR" :key="o.value" :value="o.value">{{ o.label }}</option>
          </select>
          <p class="text-xs text-gray-400 mt-1">
            <template v-if="(a.action.directus?.onError ?? 'continue') === 'block'">
              Schlägt das Schreiben fehl, wird die auslösende Aktion (z. B. „Fachabteilung
              abschließen“) abgebrochen – gilt erst als erledigt, wenn es wirklich klappt.
            </template>
            <template v-else>
              Schlägt das Schreiben fehl, läuft der Auftrag weiter; der Fehler landet im
              Verlauf und als Mail an die Fehler-Empfänger:in.
            </template>
          </p>
        </div>

        <div v-if="(a.action.directus?.operation ?? 'create') === 'create'">
          <label class="lbl">Doppelanlage-Schutz per Feld <span class="text-gray-400 font-normal">(optional)</span></label>
          <select class="afi w-full" :value="a.action.directus?.matchField ?? ''"
                  @change="patchDirectus({ matchField: val($event) || null })">
            <option value="">— kein Geschäftsschlüssel —</option>
            <option v-for="t in dwTargets" :key="t" :value="t">{{ t }}</option>
            <option v-if="a.action.directus?.matchField && !dwTargets.includes(a.action.directus.matchField)"
                    :value="a.action.directus.matchField">{{ a.action.directus.matchField }} (kein Ziel)</option>
          </select>
          <p class="text-xs text-gray-400 mt-1">
            Vor dem Anlegen wird per diesem Directus-Feld gesucht (z. B. „personalnummer“);
            existiert der Datensatz schon, wird dessen id übernommen statt ein Duplikat
            anzulegen. Muss ein oben zugeordnetes Directus-Zielfeld sein.
          </p>
        </div>

        <div v-if="(a.action.directus?.operation ?? 'create') !== 'delete'">
          <div class="flex items-center justify-between">
            <label class="lbl mb-0">Feld-Zuordnung (Prozess → Directus)</label>
            <button type="button" @click="addDwMap" class="text-xs text-[#3EAAB8] hover:underline">+ Zuordnung</button>
          </div>
          <div v-for="(b, i) in (a.action.directus?.fieldMap ?? [])" :key="i" class="mt-2">
            <div class="flex items-center gap-2">
              <!-- Quelle: Prozess-Feld ODER fester Wert. -->
              <select class="afi w-28 shrink-0" :value="b.value != null ? 'const' : 'field'"
                      @change="setDwSourceKind(i, val($event))">
                <option value="field">Prozess-Feld</option>
                <option value="const">Fester Wert</option>
              </select>
              <div v-if="b.value != null" class="flex-1 flex items-center gap-1 min-w-0">
                <select class="afi w-20 shrink-0" :value="dwConstKind(b)"
                        @change="setDwConstKind(i, val($event))">
                  <option value="text">Text</option>
                  <option value="bool">Ja/Nein</option>
                  <option value="num">Zahl</option>
                </select>
                <select v-if="dwConstKind(b) === 'bool'" class="afi flex-1 min-w-0"
                        :value="String(b.value)"
                        @change="setDwConstBool(i, val($event) === 'true')">
                  <option value="true">Ja (true)</option>
                  <option value="false">Nein (false)</option>
                </select>
                <input v-else-if="dwConstKind(b) === 'num'" type="number" class="afi flex-1 min-w-0"
                       :value="b.value as number" @input="setDwConstNum(i, val($event))" />
                <input v-else class="afi flex-1 min-w-0" :value="b.value as string"
                       placeholder="Fester Wert, z. B. AlphaRequest"
                       @input="setDwConst(i, val($event))" />
              </div>
              <select v-else class="afi flex-1" :value="b.source"
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
            <label v-if="b.value == null && (fieldWidgets?.[b.source ?? ''] === 'company' || b.resolve === 'company_directus_id')"
                   class="mt-1 ml-1 flex items-center gap-2 text-xs text-gray-600 dark:text-gray-300">
              <input type="checkbox" :checked="b.resolve === 'company_directus_id'"
                     class="h-3.5 w-3.5 rounded border-gray-300 dark:border-white/20 text-[#3EAAB8]"
                     @change="setDwResolve(i, ($event.target as HTMLInputElement).checked)" />
              Als alphacore-Firmen-ID auflösen (statt Firmenname)
              <span v-if="fieldWidgets?.[b.source ?? ''] !== 'company'" class="text-amber-600 dark:text-amber-400">
                – nur für ein Firmen-Feld gültig
              </span>
            </label>

            <!-- Bedingung (optional): Zuordnung nur schreiben, wenn ein Feld == Wert
                 (z. B. has_car nur bei fuhrpark.car = „Ja"). -->
            <label class="mt-1 ml-1 flex items-center gap-2 text-xs text-gray-600 dark:text-gray-300">
              <input type="checkbox" :checked="!!b.when"
                     class="h-3.5 w-3.5 rounded border-gray-300 dark:border-white/20 text-[#3EAAB8]"
                     @change="setDwWhenEnabled(i, ($event.target as HTMLInputElement).checked)" />
              Nur schreiben, wenn …
            </label>
            <div v-if="b.when" class="mt-1 ml-1 flex items-center gap-2">
              <select class="afi flex-1 text-sm min-w-0" :value="b.when.field"
                      @change="setDwWhen(i, 'field', val($event))">
                <option value="">Feld wählen…</option>
                <option v-for="k in keys" :key="k" :value="k">{{ fieldText(k) }}</option>
                <option v-if="b.when.field && !keys.includes(b.when.field)" :value="b.when.field">
                  {{ b.when.field }} (unbekannt)
                </option>
              </select>
              <span class="text-gray-400 text-sm shrink-0">=</span>
              <input class="afi flex-1 text-sm min-w-0" :value="String(b.when.equals ?? '')"
                     placeholder="Wert, z. B. Ja" @input="setDwWhen(i, 'equals', val($event))" />
            </div>
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
          Auftrag nicht – sie landen im Verlauf und als Mail an die Fehler-Empfänger:in.
        </p>
      </template>

      <!-- API-Aufruf (http_request) -->
      <template v-else-if="a.action.type === 'http_request'">
        <div class="grid grid-cols-1 sm:grid-cols-[7rem_minmax(0,1fr)] gap-3">
          <div>
            <label class="lbl">Methode</label>
            <select class="afi w-full" :value="a.action.http?.method ?? 'POST'"
                    @change="patchHttp({ method: val($event) as HttpMethod })">
              <option v-for="m in HTTP_METHODS" :key="m" :value="m">{{ m }}</option>
            </select>
          </div>
          <div>
            <label class="lbl">Adresse (URL)</label>
            <input class="afi w-full font-mono text-xs"
                   placeholder="https://api.example.org/hooks/{{base.pn}}"
                   :value="a.action.http?.url ?? ''"
                   @input="patchHttp({ url: val($event) })" />
          </div>
        </div>

        <div>
          <div class="flex items-center justify-between">
            <label class="lbl mb-0">Header <span class="text-gray-400 font-normal">(optional)</span></label>
            <button type="button" @click="addHeader" class="text-xs text-[#3EAAB8] hover:underline">+ Header</button>
          </div>
          <div v-for="(hd, i) in (a.action.http?.headers ?? [])" :key="i" class="mt-2 flex items-center gap-2">
            <input class="afi w-40 shrink-0 font-mono text-xs" placeholder="Name, z. B. Authorization"
                   :value="hd.name" @input="setHeader(i, 'name', val($event))" />
            <span class="text-gray-400 text-sm">:</span>
            <input class="afi flex-1 font-mono text-xs" placeholder="Wert (darf {{…}} enthalten)"
                   :value="hd.value" @input="setHeader(i, 'value', val($event))" />
            <button type="button" @click="removeHeader(i)"
                    class="text-gray-400 hover:text-red-500 text-lg leading-none">×</button>
          </div>
        </div>

        <div>
          <label class="lbl">Body <span class="text-gray-400 font-normal">(optional)</span></label>
          <textarea rows="4" class="afi w-full resize-y font-mono text-xs"
                    placeholder='{ "personalnummer": "{{base.pn}}", "name": "{{base.first_name}}" }'
                    :value="a.action.http?.body ?? ''"
                    @input="patchHttp({ body: val($event) || null })" />
        </div>

        <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div>
            <label class="lbl">Content-Type <span class="text-gray-400 font-normal">(optional)</span></label>
            <input class="afi w-full font-mono text-xs"
                   placeholder="application/json (Standard bei Body)"
                   :value="a.action.http?.contentType ?? ''"
                   @input="patchHttp({ contentType: val($event) || null })" />
          </div>
          <div>
            <label class="lbl">Zeitlimit (Sekunden)</label>
            <input type="number" min="1" max="60" class="afi w-full"
                   :value="a.action.http?.timeoutSeconds ?? 10"
                   @input="setHttpTimeout(val($event))" />
          </div>
        </div>

        <div>
          <label class="lbl">Bei Fehler</label>
          <select class="afi w-full" :value="a.action.http?.onError ?? 'continue'"
                  @change="patchHttp({ onError: val($event) as 'continue' | 'block' })">
            <option v-for="o in HTTP_ONERROR" :key="o.value" :value="o.value">{{ o.label }}</option>
          </select>
          <p class="text-xs text-gray-400 mt-1">
            <template v-if="(a.action.http?.onError ?? 'continue') === 'block'">
              Schlägt der Aufruf fehl, wird die auslösende Aktion (z. B. „Fachabteilung
              abschließen“) abgebrochen – wirkt nur beim Auslöser „Fachabteilung abgeschlossen“.
            </template>
            <template v-else>
              Schlägt der Aufruf fehl, läuft der Auftrag weiter; der Fehler landet im
              Verlauf und als Mail an die Fehler-Empfänger:in.
            </template>
          </p>
        </div>

        <div class="rounded-lg bg-gray-50 dark:bg-white/[0.04] px-3 py-2">
          <p class="text-xs text-gray-500 dark:text-gray-400">
            In Adresse, Header-Werten und Body kannst du Platzhalter aus den Auftragsfeldern
            nutzen: <code class="text-[11px]">{{ placeholderHint }}</code> … In der URL werden
            die Werte automatisch URL-sicher kodiert.
          </p>
        </div>
      </template>
    </div>
  </div>
</template>

