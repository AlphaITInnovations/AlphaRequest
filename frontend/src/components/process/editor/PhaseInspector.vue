<script setup lang="ts">
/** Detail-Editor der EINSTELLUNGEN einer Phase: Stammdaten, Freigabe,
 *  Zuständigkeit, Regeln und Automationen. Die Felder samt Darstellung baut
 *  der Formular-Baukasten (FormBuilder.vue) – hier bewusst NICHT nochmal. */
import { computed } from 'vue'
import type {
  ApprovalSpec, Condition, DocumentSpec, FieldDef, PhaseConstraint,
  PhaseDef, PhaseKind, PhaseView,
} from '@/types/process'
import {
  ENTER_STATUS, PHASE_KINDS, PHASE_KIND_LABEL,
  PHASE_VIEWS, PHASE_VIEW_LABEL, STATUS_LABEL, blankApproval, blankDocument, blankEscalation,
  isValidPhaseKey, phaseKindPatch,
} from '@/lib/processSchema'
import { deleteDocumentTemplate } from '@/api/processes'
import ApprovalEditor from './ApprovalEditor.vue'
import ResponsibilityEditor from './ResponsibilityEditor.vue'
import ConditionEditor from './ConditionEditor.vue'
import AutomationList from './AutomationList.vue'
import EscalationEditor from './EscalationEditor.vue'
import DocumentTemplateEditor from './DocumentTemplateEditor.vue'
import EditorSection from './EditorSection.vue'

const props = defineProps<{
  modelValue: PhaseDef
  index: number
  catalog: FieldDef[]
  groups: { id: string; name: string }[]
  users: { id: string; displayName: string }[]
  fieldKeys: string[]
  fieldLabels?: Record<string, string>
  fieldWidgets?: Record<string, string>
  takenIds?: string[]
  /** Alle Phasen des Prozesses – für den Rücksprung einer Freigabe nötig. */
  phases?: { key: string; label: string | null }[]
  /** Prozess-Schlüssel – nötig, um die .docx-Vorlage hoch-/runterzuladen. */
  processKey?: string
  /** Prozess-Name – nur kosmetisch für die Automations-Testmail. */
  processName?: string | null
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

/** Ansicht umstellen – bei view=document mindestens ein Dokument anlegen,
 *  beim Wechsel weg alle Dokumente entfernen (Server-Regel: view ⇔ documents). */
function setView(view: PhaseView) {
  const part: Partial<PhaseDef> = { view }
  if (view === 'document') {
    if (!props.modelValue.documents?.length) part.documents = [blankDocument('dokument')]
  } else if (props.modelValue.documents?.length) {
    part.documents = []
  }
  patch(part)
}

// ── Dokumente (nur bei view=document) ─────────────────────────────────────────
// Mehrere je Phase möglich; jedes bearbeitet <DocumentTemplateEditor>
// (Titel/Dateiname/Vorlage-Upload/Bindings). Die Vorlage-DATEI liegt als Blob am
// Server (je Prozess/Phase/Dokument), die {{marker}}-ZUORDNUNG ist Definition.
function patchDocumentAt(i: number, part: Partial<DocumentSpec>) {
  patch({ documents: (props.modelValue.documents ?? []).map((d, j) => (j === i ? { ...d, ...part } : d)) })
}

/** Eindeutiger Dokument-Key (Slug) für ein weiteres Dokument. */
function freshDocumentKey(): string {
  const used = new Set((props.modelValue.documents ?? []).map((d) => d.key))
  if (!used.has('dokument')) return 'dokument'
  let i = 2
  while (used.has(`dokument_${i}`)) i += 1
  return `dokument_${i}`
}

function addDocument() {
  patch({ documents: [...(props.modelValue.documents ?? []), blankDocument(freshDocumentKey())] })
}

async function removeDocument(i: number) {
  const docs = props.modelValue.documents ?? []
  const doc = docs[i]
  // Hochgeladene Vorlage best-effort mitlöschen, sonst verwaist der Blob am Server.
  if (doc && props.processKey && props.modelValue.key) {
    try { await deleteDocumentTemplate(props.processKey, props.modelValue.key, doc.key) } catch { /* egal */ }
  }
  patch({ documents: docs.filter((_, j) => j !== i) })
}

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
  <div class="space-y-4">
    <!-- Stammdaten -->
    <EditorSection title="Phase" icon="⚙️">
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
        <div>
          <label class="block text-xs text-gray-500 dark:text-gray-400 mb-1">
            „Weitergeben"-Button
          </label>
          <input :value="modelValue.advanceLabel ?? ''" :disabled="readonly" class="afi w-full"
                 placeholder="z. B. Weitergeben an Vorgesetzten"
                 @input="patch({ advanceLabel: ($event.target as HTMLInputElement).value || null })" />
          <p class="text-[11px] text-gray-400 mt-1">
            Leer → Standard („Weitergeben", in der letzten Phase „Abschließen").
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
    </EditorSection>

    <!-- Freigabe (nur bei der Phasen-Art „Freigabe") -->
    <EditorSection v-if="modelValue.kind === 'approval'" title="Freigabe" icon="✅">
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
    </EditorSection>

    <!-- Dokumente (nur bei der Ansicht „Dokument") -->
    <EditorSection v-if="modelValue.view === 'document'" title="Dokumente" icon="📄"
                   :badge="modelValue.documents?.length || null">
      <p class="text-sm text-gray-500 dark:text-gray-400 mb-3">
        Eine oder mehrere Vorlagen (Word <span class="font-mono text-xs">.docx</span> oder
        PDF-Formular) hochladen und die Platzhalter (Marker in doppelten geschweiften
        Klammern) darin einzelnen Ticket-Feldern zuordnen. Beim Export bleibt alles andere
        unverändert; nicht zugeordnete Platzhalter werden als Lücke ausgegeben.
      </p>
      <div class="space-y-4">
        <DocumentTemplateEditor
          v-for="(doc, i) in modelValue.documents" :key="doc.key"
          :process-key="processKey ?? null" :phase-key="modelValue.key" :index="index"
          :doc="doc" :catalog="catalog" :readonly="readonly"
          :can-remove="modelValue.documents.length > 1"
          @update="patchDocumentAt(i, $event)" @remove="removeDocument(i)" />
      </div>
      <button v-if="!readonly" class="btn-secondary text-xs mt-3" @click="addDocument">
        + Dokument
      </button>
    </EditorSection>

    <!-- Zuständigkeit -->
    <EditorSection title="Wer bearbeitet" icon="👤">
      <ResponsibilityEditor :model-value="modelValue.responsibility" :groups="groups" :users="users"
                            :catalog="catalog"
                            :field-keys="fieldKeys" :field-labels="fieldLabels" :readonly="readonly"
                            @update:model-value="patch({ responsibility: $event })" />
    </EditorSection>

    <!-- Trenner: alles darunter sind seltener genutzte Feineinstellungen -->
    <p class="text-[11px] font-semibold uppercase tracking-wider text-gray-400 pt-2 pl-1">
      Erweitert
    </p>

    <!-- Regeln -->
    <EditorSection title="Regeln zum Abschluss" icon="📏"
                   :badge="modelValue.constraints.length || null" :default-open="false">
      <p v-if="!modelValue.constraints.length" class="text-sm text-gray-400 italic mb-2">
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
      <button v-if="!readonly" @click="addConstraint" class="btn-secondary text-xs py-1">+ Regel</button>
    </EditorSection>

    <!-- Erinnerungen / Eskalation (nicht in einer Abschluss-Phase) -->
    <EditorSection v-if="modelValue.kind !== 'end'" title="Erinnerungen / Eskalation" icon="⏰"
                   :badge="modelValue.escalation ? 'aktiv' : null" :default-open="false">
      <p class="text-sm text-gray-500 dark:text-gray-400 mb-3">
        Liegt der Auftrag zu lange in dieser Phase, geht eine Erinnerungsmail an die
        gewählten Empfänger – gestaffelt (z. B. nach 7 Tagen, dann alle 7 Tage).
      </p>
      <EscalationEditor v-if="modelValue.escalation" :model-value="modelValue.escalation"
                        :groups="groups" :users="users" :readonly="readonly"
                        :phase-label="modelValue.label || modelValue.key"
                        @update:model-value="patch({ escalation: $event })" />
      <button v-else-if="!readonly" class="btn-secondary text-xs py-1"
              @click="patch({ escalation: blankEscalation() })">
        Erinnerungen einrichten
      </button>
      <div v-if="!readonly && modelValue.escalation" class="mt-3">
        <button @click="patch({ escalation: null })"
                class="text-gray-400 hover:text-red-500 text-xs">Erinnerungen entfernen</button>
      </div>
    </EditorSection>

    <!-- Automationen -->
    <EditorSection title="Automationen dieser Phase" icon="⚡"
                   :badge="modelValue.automations.length || null" :default-open="false">
      <AutomationList :model-value="modelValue.automations" :field-keys="fieldKeys"
                      :field-labels="fieldLabels" :field-widgets="fieldWidgets"
                      :groups="groups"
                      :process-name="processName" :phase-label="modelValue.label || modelValue.key"
                      :taken-ids="takenIds" :readonly="readonly"
                      @update:model-value="patch({ automations: $event })" />
    </EditorSection>
  </div>
</template>
