<script setup lang="ts">
/**
 * Auftrag aus einem veröffentlichten Prozess anlegen.
 * Das Formular wird vollständig aus der Prozess-Definition gerendert.
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppLayout from '@/components/AppLayout.vue'
import { useToast } from '@/composables/useToast'
import type { OptionSources, ProcessDefinition, ProcessOut } from '@/types/process'
import type { SimFieldError } from '@/lib/processSim'
import { validatePhaseCompletion, validateValues } from '@/lib/processSim'
import { normalizeDefinition } from '@/lib/processNormalize'
import { errorMessage, issuesFromError } from '@/lib/processErrors'
import { PRIORITIES } from '@/lib/processSchema'
import { emptySources, loadOptionSources } from '@/lib/processSources'
import { applyComputed } from '@/lib/conditionDsl'
import * as processesApi from '@/api/processes'
import { createTicket } from '@/api/processTickets'
import SchemaForm from '@/components/process/form/SchemaForm.vue'

const route = useRoute()
const router = useRouter()
const { showToast } = useToast()

const loading = ref(true)
const submitting = ref(false)
const catalog = ref<ProcessOut[]>([])
const selectedKey = ref<string>(String(route.params.key || ''))
const definition = ref<ProcessDefinition | null>(null)
const values = ref<Record<string, unknown>>({})
const title = ref('')
const priority = ref('normal')
const errors = ref<SimFieldError[]>([])
const sources = ref<OptionSources>(emptySources())

/** Aus Sicht der erstellenden Person: Owner ⇒ Vollsicht. */
const viewer = { fullView: true, isAdmin: false, groupIds: [] }

const startPhase = computed(() => definition.value?.phases?.[0] ?? null)

async function loadProcess(key: string) {
  if (!key) { definition.value = null; return }
  try {
    const row = await processesApi.getPublished(key)
    definition.value = normalizeDefinition(row.definition)
    title.value = row.name
    values.value = {}
    errors.value = []
  } catch (e) {
    definition.value = null
    showToast(errorMessage(e, 'Prozess konnte nicht geladen werden'), false)
  }
}

/** Abgeleitete Felder wie auf dem Server nachziehen (sonst blieben sie leer und
 *  ein berechnetes Pflichtfeld wäre nie erfüllbar). */
function onValues(next: Record<string, unknown>) {
  values.value = definition.value ? applyComputed(definition.value.fields, next) : next
}

/** Fehler ohne Feldbezug (Phasen-Regeln, Server-Meldungen) – die zeigt das
 *  Formular selbst nicht an, sie brauchen eine eigene Liste. */
const generalErrors = computed(() => {
  const fieldKeys = new Set(definition.value?.fields.map((f) => f.key) ?? [])
  return errors.value.filter((e) => !fieldKeys.has(e.path))
})

async function submit() {
  if (!definition.value || !startPhase.value) return
  // Client-Vorprüfung (der Server prüft erneut und ist maßgeblich)
  const shapeErrors = validateValues(definition.value, values.value)
  const requiredErrors = validatePhaseCompletion(definition.value, startPhase.value, values.value)
  errors.value = [...shapeErrors, ...requiredErrors]
  if (errors.value.length) {
    showToast('Bitte die markierten Felder prüfen', false)
    return
  }
  submitting.value = true
  try {
    const t = await createTicket({
      processKey: definition.value.key,
      title: title.value || null,
      priority: priority.value,
      values: values.value,
    })
    showToast('Auftrag angelegt')
    router.push(`/prozess-auftraege/${t.id}`)
  } catch (e) {
    const issues = issuesFromError(e)
    errors.value = issues.map((i) => ({ path: i.path, code: i.code, message: i.message }))
    showToast(errorMessage(e, 'Anlegen fehlgeschlagen'), false)
  } finally {
    submitting.value = false
  }
}

onMounted(async () => {
  sources.value = await loadOptionSources(true)
  try {
    catalog.value = await processesApi.listProcesses()
  } catch { /* Katalog optional, wenn der Key aus der Route kommt */ }
  if (selectedKey.value) await loadProcess(selectedKey.value)
  loading.value = false
})
</script>

<template>
  <AppLayout>
    <div class="max-w-4xl mx-auto px-4 py-6">
      <h1 class="text-xl font-semibold text-gray-800 dark:text-gray-100 mb-4">Neuer Auftrag</h1>

      <div v-if="loading" class="flex items-center justify-center py-16">
        <div class="w-7 h-7 rounded-full border-2 border-[#3EAAB8] border-t-transparent animate-spin" />
      </div>

      <template v-else>
        <!-- Prozess-Auswahl -->
        <section class="card-section mb-4">
          <label class="block text-xs text-gray-500 dark:text-gray-400 mb-1">Prozess</label>
          <select v-model="selectedKey" class="afi w-full" @change="loadProcess(selectedKey)">
            <option value="">– bitte wählen –</option>
            <!-- Kein Symbol: Listen-Routen liefern `definition` grundsätzlich als null. -->
            <option v-for="p in catalog" :key="p.key" :value="p.key">{{ p.name }}</option>
          </select>
          <p v-if="!catalog.length" class="text-xs text-gray-400 mt-2">
            Es ist noch kein Prozess veröffentlicht.
          </p>
        </section>

        <template v-if="definition && startPhase">
          <section class="card-section mb-4">
            <div class="grid md:grid-cols-3 gap-3">
              <div class="md:col-span-2">
                <label class="block text-xs text-gray-500 dark:text-gray-400 mb-1">Titel</label>
                <input v-model="title" class="afi w-full" maxlength="255" />
              </div>
              <div>
                <label class="block text-xs text-gray-500 dark:text-gray-400 mb-1">Priorität</label>
                <select v-model="priority" class="afi w-full">
                  <option v-for="p in PRIORITIES" :key="p" :value="p">{{ p }}</option>
                </select>
              </div>
            </div>
          </section>

          <SchemaForm :definition="definition" :phase="startPhase" :model-value="values"
                      :viewer="viewer" :errors="errors" :sources="sources"
                      @update:model-value="onValues($event)" />

          <div v-if="generalErrors.length"
               class="rounded-xl border border-red-200 dark:border-red-500/30 bg-red-50 dark:bg-red-900/20
                      px-4 py-3 text-sm text-red-800 dark:text-red-200 mt-3">
            <div class="font-medium mb-1">Auftrag kann nicht angelegt werden:</div>
            <ul class="list-disc list-inside">
              <li v-for="(e, i) in generalErrors" :key="i">
                <span v-if="e.path !== 'body'" class="font-mono text-xs opacity-70">{{ e.path }} — </span>{{ e.message }}
              </li>
            </ul>
          </div>

          <div class="flex justify-end gap-2 mt-4">
            <button @click="router.back()" class="btn-secondary text-sm">Abbrechen</button>
            <button @click="submit" :disabled="submitting"
                    class="px-4 py-2 rounded-xl text-sm text-white bg-[#3EAAB8] hover:bg-[#369aa7]
                           disabled:opacity-40 transition">
              {{ submitting ? 'Wird angelegt…' : 'Auftrag anlegen' }}
            </button>
          </div>
        </template>
      </template>
    </div>
  </AppLayout>
</template>
