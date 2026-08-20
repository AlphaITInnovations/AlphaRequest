<script setup lang="ts">
/** Detail-Editor der EINSTELLUNGEN einer Phase: Stammdaten, Freigabe,
 *  Zuständigkeit, Regeln und Automationen. Die Felder samt Darstellung baut
 *  der Formular-Baukasten (FormBuilder.vue) – hier bewusst NICHT nochmal. */
import { computed, onMounted, ref, watch } from 'vue'
import type {
  ApprovalSpec, Condition, DocumentSpec, FieldDef, PhaseConstraint, PhaseDef, PhaseKind, PhaseView,
} from '@/types/process'
import {
  ENTER_STATUS, PHASE_KINDS, PHASE_KIND_LABEL,
  PHASE_VIEWS, PHASE_VIEW_LABEL, STATUS_LABEL, blankApproval, blankDocument,
  isValidPhaseKey, phaseKindPatch,
} from '@/lib/processSchema'
import {
  deleteDocumentTemplate, getDocumentTemplate, uploadDocumentTemplate,
  type DocumentTemplateInfo,
} from '@/api/processes'
import { errorMessage } from '@/lib/processErrors'
import { useToast } from '@/composables/useToast'
import ApprovalEditor from './ApprovalEditor.vue'
import ResponsibilityEditor from './ResponsibilityEditor.vue'
import ConditionEditor from './ConditionEditor.vue'
import AutomationList from './AutomationList.vue'

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
  /** Prozess-Schlüssel – nötig, um die .docx-Vorlage hoch-/runterzuladen. */
  processKey?: string
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

/** Ansicht umstellen – die Dokument-Vorlage gehört zu view=document (Server-Regel):
 *  beim Wechsel dorthin ein Start-Template anlegen, beim Wechsel weg entfernen. */
function setView(view: PhaseView) {
  const part: Partial<PhaseDef> = { view }
  if (view === 'document') { if (!props.modelValue.document) part.document = blankDocument() }
  else if (props.modelValue.document) { part.document = null }
  patch(part)
}

function patchDocument(part: Partial<DocumentSpec>) {
  if (!props.modelValue.document) return
  patch({ document: { ...props.modelValue.document, ...part } })
}

// ── .docx-Vorlage (nur bei view=document) ────────────────────────────────────
// Anders als der Rest des Entwurfs liegt die Vorlage-DATEI NICHT in der
// Definition, sondern als Blob am Prozess (Installationsdatei). Deshalb hier
// direkte API-Aufrufe statt patch(); die {{marker}}-ZUORDNUNG dagegen ist
// Definition (document.bindings) und wandert über patchDocument in den Entwurf.
const { showToast } = useToast()
const template = ref<DocumentTemplateInfo | null>(null)
const tplLoading = ref(false)
const tplBusy = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)

const placeholders = computed(() => template.value?.placeholders ?? [])

async function loadTemplate() {
  if (!props.processKey || props.modelValue.view !== 'document') { template.value = null; return }
  tplLoading.value = true
  try {
    template.value = await getDocumentTemplate(props.processKey)
  } catch {
    template.value = null       // Kein Vorlage-Endpunkt / kein Zugriff: still degradieren.
  } finally {
    tplLoading.value = false
  }
}
onMounted(loadTemplate)
watch(() => [props.processKey, props.index, props.modelValue.view], loadTemplate)

function pickFile() { fileInput.value?.click() }

async function onFilePicked(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''              // dieselbe Datei erneut wählbar machen
  if (!file || !props.processKey) return
  if (!file.name.toLowerCase().endsWith('.docx')) {
    showToast('Bitte eine .docx-Datei wählen.', false); return
  }
  tplBusy.value = true
  try {
    template.value = await uploadDocumentTemplate(props.processKey, file)
    pruneBindings()             // Zuordnungen auf die neuen Marker eindampfen
    showToast('Vorlage hochgeladen.')
  } catch (err) {
    showToast(errorMessage(err, 'Upload fehlgeschlagen.'), false)
  } finally {
    tplBusy.value = false
  }
}

async function removeTemplate() {
  if (!props.processKey) return
  tplBusy.value = true
  try {
    await deleteDocumentTemplate(props.processKey)
    template.value = { exists: false }
  } catch (err) {
    showToast(errorMessage(err, 'Löschen fehlgeschlagen.'), false)
  } finally {
    tplBusy.value = false
  }
}

function bindingFor(marker: string): string {
  return props.modelValue.document?.bindings?.[marker] ?? ''
}
function setBinding(marker: string, fieldKey: string) {
  const next = { ...(props.modelValue.document?.bindings ?? {}) }
  if (fieldKey) next[marker] = fieldKey
  else delete next[marker]
  patchDocument({ bindings: next })
}
/** Zuordnungen zu nicht mehr vorhandenen Markern verwerfen (nach Neu-Upload). */
function pruneBindings() {
  const cur = props.modelValue.document?.bindings ?? {}
  const known = new Set(placeholders.value)
  const next: Record<string, string> = {}
  for (const [k, v] of Object.entries(cur)) if (known.has(k)) next[k] = v
  if (Object.keys(next).length !== Object.keys(cur).length) patchDocument({ bindings: next })
}

/** Auswählbare Ticket-Felder für die Zuordnung (mit Label). */
const bindableFields = computed(() =>
  (props.fieldKeys ?? []).map((k) => ({ key: k, label: props.fieldLabels?.[k] || k })))

// Doppelte geschweifte Klammern gehören NICHT direkt ins <template> (der Vue-
// Compiler liest sie als Interpolation) – darum als Script-Konstanten/Helfer.
const PH_HINT = '{{…}}'
function markerLabel(m: string): string { return '{{' + m + '}}' }

/** Fertig zugeordnete Marker (für die Fortschritts-Anzeige). */
const mappedCount = computed(() =>
  placeholders.value.filter((m) => !!bindingFor(m)).length)

/** Nur Anzeige: kürzt einen langen Datumsstring auf Datum. */
const uploadedAtLabel = computed(() => {
  const raw = template.value?.uploaded_at
  return raw ? raw.replace('T', ' ').slice(0, 16) : null
})

/** Nur Phasen VOR dieser taugen als Rücksprung-Ziel. */
const earlierPhases = computed(() => (props.phases ?? []).slice(0, props.index))

function addConstraint() {
  patch({ constraints: [...props.modelValue.constraints, { when: { truthy: '' }, message: '' }] })
}
function patchConstraint(i: number, part: Partial<PhaseConstraint>) {
  patch({ constraints: props.modelValue.constraints.map((c, j) => (j === i ? { ...c, ...part } : c)) })
}
function removeConstraint(i: number) {
  patch({ constraints: props.modelValue.constraints.filter((_, j) => j !== i) })
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
                  @change="setView(($event.target as HTMLSelectElement).value as PhaseView)">
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

    <!-- Dokument-Vorlage (nur bei der Ansicht „Dokument") -->
    <section v-if="modelValue.view === 'document' && modelValue.document" class="card-section">
      <h3 class="section-title">Dokument-Vorlage (.docx)</h3>
      <p class="text-sm text-gray-500 dark:text-gray-400 mb-3">
        Word-Vorlage (z. B. Arbeitsvertrag) hochladen und die
        <span class="font-mono text-xs">{{ PH_HINT }}</span>-Platzhalter darin
        einzelnen Ticket-Feldern zuordnen. Beim Export bleibt alles andere im
        Dokument unverändert; nicht zugeordnete Platzhalter werden als Lücke
        (Pünktchen) ausgegeben – zum Nachfüllen in Word.
      </p>

      <div class="grid md:grid-cols-2 gap-3 mb-3">
        <div>
          <label class="block text-xs text-gray-500 dark:text-gray-400 mb-1">Titel (Überschrift)</label>
          <input :value="modelValue.document.title" :disabled="readonly" class="afi w-full"
                 placeholder="z. B. Arbeitsvertrag"
                 @input="patchDocument({ title: ($event.target as HTMLInputElement).value })" />
        </div>
        <div>
          <label class="block text-xs text-gray-500 dark:text-gray-400 mb-1">Dateiname (Export)</label>
          <input :value="modelValue.document.filename" :disabled="readonly" class="afi w-full font-mono text-sm"
                 placeholder="z. B. Arbeitsvertrag_Nachname"
                 @input="patchDocument({ filename: ($event.target as HTMLInputElement).value })" />
        </div>
      </div>

      <p v-if="!processKey" class="text-sm text-amber-600 dark:text-amber-400">
        Bitte den Prozess zuerst speichern – danach lässt sich die Vorlage hochladen.
      </p>

      <template v-else>
        <input ref="fileInput" type="file" accept=".docx" class="hidden" @change="onFilePicked" />

        <p v-if="tplLoading" class="text-sm text-gray-400 italic">Vorlage wird geladen …</p>

        <!-- Noch keine Vorlage -->
        <div v-else-if="!template?.exists"
             class="rounded-xl border border-dashed border-gray-300 dark:border-white/15 px-4 py-6 text-center">
          <p class="text-sm text-gray-500 dark:text-gray-400 mb-3">Noch keine Vorlage hinterlegt.</p>
          <button v-if="!readonly" class="btn-primary text-sm" :disabled="tplBusy" @click="pickFile">
            {{ tplBusy ? 'Lädt hoch …' : '.docx-Vorlage hochladen' }}
          </button>
        </div>

        <!-- Vorlage vorhanden -->
        <div v-else class="space-y-3">
          <div class="flex items-center justify-between gap-3 rounded-xl border border-gray-200
                      dark:border-white/10 px-4 py-3">
            <div class="min-w-0">
              <p class="text-sm font-medium text-gray-800 dark:text-gray-100 truncate">
                {{ template.filename }}
              </p>
              <p class="text-[11px] text-gray-400">
                {{ placeholders.length }} Platzhalter · {{ mappedCount }} zugeordnet
                <span v-if="uploadedAtLabel"> · {{ uploadedAtLabel }}</span>
                <span v-if="template.uploaded_by"> · {{ template.uploaded_by }}</span>
              </p>
            </div>
            <div v-if="!readonly" class="flex items-center gap-2 shrink-0">
              <button class="btn-secondary text-xs py-1" :disabled="tplBusy" @click="pickFile">Ersetzen</button>
              <button class="text-gray-400 hover:text-red-500 px-1" :disabled="tplBusy"
                      title="Vorlage entfernen" @click="removeTemplate">✕</button>
            </div>
          </div>

          <!-- Zuordnung je Platzhalter -->
          <div v-if="placeholders.length" class="space-y-2">
            <label class="block text-xs text-gray-500 dark:text-gray-400">Platzhalter zuordnen</label>
            <div v-for="m in placeholders" :key="m"
                 class="grid grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)] items-center gap-2">
              <span class="font-mono text-xs text-gray-700 dark:text-gray-200 truncate"
                    :title="m">{{ markerLabel(m) }}</span>
              <select :value="bindingFor(m)" :disabled="readonly" class="afi w-full text-sm"
                      @change="setBinding(m, ($event.target as HTMLSelectElement).value)">
                <option value="">— manuell (in Word nachfüllen) —</option>
                <option v-for="f in bindableFields" :key="f.key" :value="f.key">{{ f.label }}</option>
              </select>
            </div>
          </div>
          <p v-else class="text-sm text-gray-400 italic">
            In dieser Vorlage wurden keine {{ PH_HINT }}-Platzhalter gefunden.
          </p>
        </div>
      </template>
    </section>

    <!-- Zuständigkeit -->
    <section class="card-section">
      <h3 class="section-title">Wer bearbeitet</h3>
      <ResponsibilityEditor :model-value="modelValue.responsibility" :groups="groups" :users="users"
                            :catalog="catalog"
                            :field-keys="fieldKeys" :field-labels="fieldLabels" :readonly="readonly"
                            @update:model-value="patch({ responsibility: $event })" />
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
