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
import SchemaForm from '@/components/process/form/SchemaForm.vue'
import SchemaReadonlyView from '@/components/process/form/SchemaReadonlyView.vue'

const route = useRoute()
const router = useRouter()
const { showToast } = useToast()

const id = computed(() => Number(route.params.id))
const loading = ref(true)
const busy = ref(false)
const ticket = ref<ProcessTicketOut | null>(null)
const definition = ref<ProcessDefinition | null>(null)
const values = ref<Record<string, unknown>>({})
const errors = ref<SimFieldError[]>([])
const sources = ref<OptionSources>(emptySources())
const loadError = ref<string | null>(null)

/** Endpunkte sind derzeit admin-only – daher volle Sicht. Sobald der Zugriff für
 *  Beteiligte geöffnet wird, liefert der Server bereits gefilterte Werte; die
 *  Anzeige filtert zusätzlich clientseitig identisch. */
const viewer = computed<SimViewer>(() => ({ fullView: true, isAdmin: true, groupIds: [] }))

const phase = computed(() => {
  if (!definition.value || !ticket.value) return null
  const i = ticket.value.runtime?.current_index ?? 0
  return definition.value.phases[i] ?? null
})

const terminal = computed(() =>
  !!ticket.value && ['archived', 'rejected'].includes(ticket.value.status))

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
  } catch (e) {
    errors.value = issuesFromError(e).map((i) => ({ path: i.path, code: i.code, message: i.message }))
    showToast(errorMessage(e, 'Weiterschalten fehlgeschlagen'), false)
  } finally { busy.value = false }
}

async function reject() {
  if (!confirm('Auftrag ablehnen? Das lässt sich derzeit nicht rückgängig machen.')) return
  busy.value = true
  try {
    ticket.value = await ticketsApi.rejectTicket(id.value)
    showToast('Auftrag abgelehnt')
  } catch (e) {
    showToast(errorMessage(e, 'Ablehnen fehlgeschlagen'), false)
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
            <button v-if="!terminal" @click="saveValues" :disabled="busy || !dirty"
                    class="btn-secondary text-sm">Speichern</button>
            <button v-if="!terminal" @click="advance" :disabled="busy"
                    class="px-4 py-2 rounded-xl text-sm text-white bg-[#3EAAB8] hover:bg-[#369aa7]
                           disabled:opacity-40 transition">Phase abschließen</button>
            <button v-if="!terminal" @click="reject" :disabled="busy"
                    class="px-3 py-2 rounded-xl text-sm border border-red-300 text-red-600
                           hover:bg-red-50 dark:hover:bg-red-900/20 disabled:opacity-40 transition">
              Ablehnen
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

        <!-- Formular der aktuellen Phase -->
        <template v-if="!terminal && phase">
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
      </template>
    </div>
  </AppLayout>
</template>
