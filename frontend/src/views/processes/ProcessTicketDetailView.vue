<script setup lang="ts">
/**
 * Auftrag eines dynamischen Prozesses: aktuelle Phase bearbeiten, abschließen,
 * ablehnen. Formular und Sichtbarkeit kommen aus der GEPINNTEN Definition.
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppLayout from '@/components/AppLayout.vue'
import { useToast } from '@/composables/useToast'
import type { OptionSources, ProcessDefinition, ProcessTicketOut } from '@/types/process'
import type { SimFieldError, SimViewer } from '@/lib/processSim'
import { validatePhaseCompletion, validateValues } from '@/lib/processSim'
import { normalizeDefinition } from '@/lib/processNormalize'
import { errorMessage, issuesFromError } from '@/lib/processErrors'
import { STATUS_LABEL } from '@/lib/processSchema'
import { emptySources, loadOptionSources } from '@/lib/processSources'
import { applyComputed } from '@/lib/conditionDsl'
import * as processesApi from '@/api/processes'
import * as ticketsApi from '@/api/processTickets'
import { reopenTicket } from '@/api/processEvents'
import { useAuthStore } from '@/stores/authStore'
import SchemaForm from '@/components/process/form/SchemaForm.vue'
import SchemaReadonlyView from '@/components/process/form/SchemaReadonlyView.vue'
import ProcessTimeline from '@/components/process/ProcessTimeline.vue'
import ProcessWatchers from '@/components/process/ProcessWatchers.vue'
import ProcessAttachments from '@/components/process/ProcessAttachments.vue'

const route = useRoute()
const router = useRouter()
const { showToast } = useToast()
const auth = useAuthStore()

const id = computed(() => Number(route.params.id))
const loading = ref(true)
const busy = ref(false)
const ticket = ref<ProcessTicketOut | null>(null)
const definition = ref<ProcessDefinition | null>(null)
const values = ref<Record<string, unknown>>({})
const errors = ref<SimFieldError[]>([])
const sources = ref<OptionSources>(emptySources())
const loadError = ref<string | null>(null)

/**
 * Sichtbarkeits-Kontext für die ANZEIGE.
 *
 * Verbindlich filtert der Server: `ticket.values` enthält nur freigegebene
 * Felder, und Schreibzugriffe auf gesperrte Felder verwirft er.
 *
 * OFFEN: Das Frontend kennt die Gruppen-Mitgliedschaft nicht (`/auth/me` liefert
 * sie nicht mit), deshalb steht hier noch `fullView`. Folge: das Formular kann
 * ein Eingabefeld für ein Feld zeigen, das diese Person nicht sehen darf – es
 * käme leer an und der Server verwürfe die Eingabe. Sauber wird das, wenn die
 * Antwort die sichtbaren/editierbaren Feld-Schlüssel mitliefert (wie `abilities`).
 */
const viewer = computed<SimViewer>(() => ({ fullView: true, isAdmin: true, groupIds: [] }))

const phase = computed(() => {
  if (!definition.value || !ticket.value) return null
  const i = ticket.value.runtime?.current_index ?? 0
  return definition.value.phases[i] ?? null
})

/**
 * Erlaubte Aktionen kommen vom Server (`abilities`). Fehlt das Feld (alte
 * Antwort), wird konservativ NICHTS angeboten – lieber eine fehlende
 * Schaltfläche als eine, die mit 403 endet.
 */
const abilities = computed(() => ticket.value?.abilities ?? {
  edit: false, internal_comment: false, manage_watchers: false, reopen: false,
})

/** Beschriftungen für den Verlauf (Feld-/Phasen-Schlüssel sind nicht lesbar). */
const fieldLabels = computed<Record<string, string>>(() => {
  const out: Record<string, string> = {}
  for (const f of definition.value?.fields ?? []) out[f.key] = f.label || f.key
  return out
})
const phaseLabels = computed<Record<string, string>>(() => {
  const out: Record<string, string> = {}
  for (const p of definition.value?.phases ?? []) out[p.key] = p.label || p.key
  return out
})

/** Verlauf nach jeder Aktion neu laden (Referenz auf die Komponente). */
const timeline = ref<{ reload: () => void } | null>(null)

const dirty = computed(() =>
  JSON.stringify(values.value) !== JSON.stringify(ticket.value?.values ?? {}))

/** Abgeleitete Felder wie auf dem Server nachziehen. */
function onValues(next: Record<string, unknown>) {
  values.value = definition.value ? applyComputed(definition.value.fields, next) : next
}

/** Fehler ohne Feldbezug (Phasen-Regeln, Server-Meldungen). */
const generalErrors = computed(() => {
  const fieldKeys = new Set(definition.value?.fields.map((f) => f.key) ?? [])
  return errors.value.filter((e) => !fieldKeys.has(e.path))
})

async function load() {
  loading.value = true
  loadError.value = null
  try {
    const t = await ticketsApi.getTicket(id.value)
    ticket.value = t
    values.value = { ...(t.values || {}) }
    // Immer die GEPINNTE Version laden – nicht die aktuell veröffentlichte.
    const row = await processesApi.getVersion(t.process_key, t.process_version)
    definition.value = normalizeDefinition(row.definition)
  } catch (e) {
    loadError.value = errorMessage(e, 'Auftrag konnte nicht geladen werden')
  } finally {
    loading.value = false
  }
}

async function saveValues() {
  if (!definition.value) return
  const shape = validateValues(definition.value, values.value)
  if (shape.length) { errors.value = shape; showToast('Bitte Eingaben prüfen', false); return }
  busy.value = true
  try {
    ticket.value = await ticketsApi.patchTicket(id.value, { values: values.value })
    values.value = { ...(ticket.value.values || {}) }
    errors.value = []
    showToast('Gespeichert')
    timeline.value?.reload()
  } catch (e) {
    errors.value = issuesFromError(e).map((i) => ({ path: i.path, code: i.code, message: i.message }))
    showToast(errorMessage(e, 'Speichern fehlgeschlagen'), false)
  } finally { busy.value = false }
}

async function advance() {
  if (!definition.value || !phase.value) return
  if (dirty.value) { showToast('Bitte zuerst speichern', false); return }
  const req = validatePhaseCompletion(definition.value, phase.value, values.value)
  if (req.length) { errors.value = req; showToast('Pflichtangaben fehlen', false); return }
  if (!confirm('Diese Phase abschließen?')) return
  busy.value = true
  try {
    ticket.value = await ticketsApi.advanceTicket(id.value)
    values.value = { ...(ticket.value.values || {}) }
    errors.value = []
    showToast('Phase abgeschlossen')
    timeline.value?.reload()
  } catch (e) {
    errors.value = issuesFromError(e).map((i) => ({ path: i.path, code: i.code, message: i.message }))
    showToast(errorMessage(e, 'Weiterschalten fehlgeschlagen'), false)
  } finally { busy.value = false }
}

async function reject() {
  if (!confirm('Auftrag ablehnen? Ein Admin kann ihn danach wieder aufnehmen.')) return
  busy.value = true
  try {
    ticket.value = await ticketsApi.rejectTicket(id.value)
    showToast('Auftrag abgelehnt')
    timeline.value?.reload()
  } catch (e) {
    showToast(errorMessage(e, 'Ablehnen fehlgeschlagen'), false)
  } finally { busy.value = false }
}

/** Wiederaufnahme: nur Admin, nur bei fertigem Auftrag, Grund ist Pflicht. */
async function reopen() {
  const reason = prompt('Warum wird der Auftrag wieder aufgenommen? '
    + '(steht anschließend im Verlauf)')
  if (reason === null) return
  if (!reason.trim()) { showToast('Ohne Grund keine Wiederaufnahme', false); return }
  busy.value = true
  try {
    ticket.value = await reopenTicket(id.value, reason.trim())
    values.value = { ...(ticket.value.values || {}) }
    showToast('Auftrag wieder aufgenommen')
    timeline.value?.reload()
  } catch (e) {
    showToast(errorMessage(e, 'Wiederaufnahme fehlgeschlagen'), false)
  } finally { busy.value = false }
}

const groupName = (gid: string) => sources.value.groups.find((g) => g.id === gid)?.name || gid

onMounted(async () => { sources.value = await loadOptionSources(true); await load() })
</script>

<template>
  <AppLayout>
    <div class="max-w-5xl mx-auto px-4 py-6">
      <div v-if="loading" class="flex items-center justify-center py-20">
        <div class="w-7 h-7 rounded-full border-2 border-[#3EAAB8] border-t-transparent animate-spin" />
      </div>

      <div v-else-if="loadError" class="text-sm text-red-600">{{ loadError }}</div>

      <template v-else-if="ticket && definition">
        <!-- Kopf -->
        <div class="flex items-start justify-between gap-4 flex-wrap mb-4">
          <div class="min-w-0">
            <button @click="router.push('/prozess-auftraege')"
                    class="text-xs text-gray-400 hover:text-[#3EAAB8] mb-1">← Aufträge</button>
            <h1 class="text-xl font-semibold text-gray-800 dark:text-gray-100 truncate">
              {{ ticket.title }}
            </h1>
            <div class="text-xs text-gray-400 flex items-center gap-2 flex-wrap">
              <span>#{{ ticket.id }}</span><span>·</span>
              <span class="font-mono">{{ ticket.process_key }} v{{ ticket.process_version }}</span>
              <span>·</span>
              <span>{{ STATUS_LABEL[ticket.status] || ticket.status }}</span>
              <span v-if="ticket.current_phase_label">· Phase: {{ ticket.current_phase_label }}</span>
            </div>
          </div>
          <div class="flex items-center gap-2">
            <button v-if="abilities.edit" @click="saveValues" :disabled="busy || !dirty"
                    class="btn-secondary text-sm">Speichern</button>
            <button v-if="abilities.edit" @click="advance" :disabled="busy"
                    class="px-4 py-2 rounded-xl text-sm text-white bg-[#3EAAB8] hover:bg-[#369aa7]
                           disabled:opacity-40 transition">Phase abschließen</button>
            <button v-if="abilities.edit" @click="reject" :disabled="busy"
                    class="px-3 py-2 rounded-xl text-sm border border-red-300 text-red-600
                           hover:bg-red-50 dark:hover:bg-red-900/20 disabled:opacity-40 transition">
              Ablehnen
            </button>
            <button v-if="abilities.reopen" @click="reopen" :disabled="busy"
                    class="px-3 py-2 rounded-xl text-sm border border-amber-300 text-amber-700
                           dark:text-amber-300 hover:bg-amber-50 dark:hover:bg-amber-900/20
                           disabled:opacity-40 transition">
              Wieder aufnehmen
            </button>
          </div>
        </div>

        <!-- Phasenfortschritt -->
        <div class="card-section mb-4">
          <ol class="flex items-center gap-2 flex-wrap">
            <li v-for="(p, i) in definition.phases" :key="p.key" class="flex items-center gap-2">
              <span class="px-2.5 py-1 rounded-full text-xs"
                    :class="i < (ticket.runtime?.current_index ?? 0)
                      ? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300'
                      : i === (ticket.runtime?.current_index ?? 0)
                        ? 'bg-[#3EAAB8]/15 text-[#3EAAB8]'
                        : 'bg-gray-100 text-gray-400 dark:bg-white/10'">
                {{ p.label || p.key }}
              </span>
              <span v-if="i < definition.phases.length - 1" class="text-gray-300">→</span>
            </li>
          </ol>
          <div v-if="ticket.responsibility" class="text-xs text-gray-400 mt-2">
            Zuständig:
            <template v-if="ticket.responsibility.kind === 'departments'">
              {{ ticket.responsibility.departments.map(d => groupName(d.group)).join(', ') || '—' }}
            </template>
            <template v-else-if="ticket.responsibility.kind === 'group'">
              {{ groupName(ticket.responsibility.group) }}
            </template>
            <template v-else-if="ticket.responsibility.kind === 'owner'">
              {{ ticket.owner_name || 'Ersteller:in' }}
            </template>
            <template v-else>—</template>
          </div>
        </div>

        <!-- Formular der aktuellen Phase (nur für die zuständige Stelle) -->
        <template v-if="abilities.edit && phase">
          <SchemaForm :definition="definition" :phase="phase" :model-value="values"
                      :viewer="viewer" :errors="errors" :sources="sources"
                      @update:model-value="onValues($event)" />
          <!-- Nur Fehler OHNE Feldbezug: feldbezogene zeigt das Formular selbst an. -->
          <div v-if="generalErrors.length"
               class="rounded-xl border border-red-200 dark:border-red-500/30 bg-red-50 dark:bg-red-900/20
                      px-4 py-3 text-sm text-red-800 dark:text-red-200 mt-3">
            <ul class="list-disc list-inside">
              <li v-for="(e, i) in generalErrors" :key="i">
                <span v-if="e.path !== 'body'" class="font-mono text-xs opacity-70">{{ e.path }} — </span>{{ e.message }}
              </li>
            </ul>
          </div>
        </template>

        <!-- Gesamtansicht -->
        <div class="card-section mt-4">
          <h3 class="section-title">Alle Angaben</h3>
          <SchemaReadonlyView :definition="definition" :values="ticket.values" :viewer="viewer"
                              :sources="sources" />
        </div>

        <!-- Allgemeine Anhänge des Auftrags (Feld-Anhänge stehen im Formular) -->
        <div class="mt-4">
          <ProcessAttachments :ticket-id="ticket.id" :can-edit="abilities.edit" />
        </div>

        <div class="grid gap-4 mt-4 lg:grid-cols-[2fr_1fr] items-start">
          <ProcessTimeline ref="timeline" :ticket-id="ticket.id"
                           :field-labels="fieldLabels" :phase-labels="phaseLabels"
                           :group-name="groupName"
                           :can-be-internal="abilities.internal_comment" />
          <ProcessWatchers :ticket-id="ticket.id" :current-user-id="auth.user?.id ?? null"
                           :can-manage="abilities.manage_watchers"
                           :users="sources.users" />
        </div>
      </template>
    </div>
  </AppLayout>
</template>
